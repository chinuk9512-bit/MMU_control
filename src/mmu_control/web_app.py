"""Streamlit web interface for MMU Control."""

from __future__ import annotations

import os
import posixpath
import shlex
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mmu_control.core.automation_runner import AutomationRunner
from mmu_control.core.config_manager import ConfigError, ConfigManager
from mmu_control.core.interactive_shell import InteractiveShell
from mmu_control.core.logging_config import configure_logging, shutdown_logging
from mmu_control.core.minicom_manager import MinicomError, MinicomManager
from mmu_control.core.power_supply_manager import PowerSupplyCommandError, PowerSupplyManager
from mmu_control.core.sftp_manager import SFTPError, SFTPManager
from mmu_control.core.ssh_manager import SSHConnectionError, SSHManager
from mmu_control.core.ttyd_manager import TtydError, TtydManager
from mmu_control.models.automation import (
    AutomationScenario,
    AutomationStep,
)
from mmu_control.models.command_set import CommandSet
from mmu_control.models.settings import (
    AppSettings,
    BoardSettings,
    PowerSupplySettings,
    SSHSettings,
)
from mmu_control.storage.automation_store import AutomationStore, AutomationStoreError
from mmu_control.storage.command_set_store import CommandSetStore, CommandSetStoreError


@dataclass(frozen=True, slots=True)
class WebSftpEntry:
    """A file entry displayed by the Streamlit SFTP view."""

    is_dir: bool
    name: str
    path: str
    is_link: bool = False
    link_target: str | None = None
    navigate_path: str | None = None


@dataclass(slots=True)
class WebServices:
    """Long-lived services stored in Streamlit session state."""

    ssh_manager: SSHManager
    sftp_manager: SFTPManager
    minicom_manager: MinicomManager
    power_supply_manager: PowerSupplyManager
    ttyd_manager: TtydManager
    config_manager: ConfigManager
    command_set_store: CommandSetStore
    automation_store: AutomationStore


def create_web_services() -> WebServices:
    """Create the default service set for the web UI."""
    return WebServices(
        ssh_manager=SSHManager(),
        sftp_manager=SFTPManager(),
        minicom_manager=MinicomManager(),
        power_supply_manager=PowerSupplyManager(),
        ttyd_manager=TtydManager(),
        config_manager=ConfigManager.create_default(),
        command_set_store=CommandSetStore.create_default(),
        automation_store=AutomationStore.create_default(),
    )


def settings_from_form_values(
    *,
    ssh_host: str,
    ssh_port: int,
    ssh_username: str,
    ssh_password: str,
    board_ip: str,
    board_username: str,
    board_password: str,
    board_interface: str,
    board_usb_port: str,
    board_ssh_port: int,
    power_ip: str,
    power_voltage: str,
    power_current: str,
    active_profile: str = "default",
) -> AppSettings:
    """Build application settings from Streamlit form values."""
    return AppSettings(
        ssh=SSHSettings(
            host=ssh_host.strip(),
            port=int(ssh_port),
            username=ssh_username.strip(),
            password=ssh_password,
        ),
        board=BoardSettings(
            ip_address=board_ip.strip(),
            username=board_username.strip(),
            password=board_password,
            interface=board_interface.strip(),
            usb_port=board_usb_port.strip(),
            ssh_port=int(board_ssh_port),
        ),
        power_supply=PowerSupplySettings(
            ip_address=power_ip.strip(),
            voltage=power_voltage.strip(),
            current=power_current.strip(),
        ),
        active_profile=active_profile.strip() or "default",
    )


def parse_find_listing(output: str) -> list[WebSftpEntry]:
    """Parse a tab-delimited Linux find listing into file entries."""
    entries: list[WebSftpEntry] = []
    for line in output.splitlines():
        if "\t" not in line:
            continue
        kind, path = line.split("\t", 1)
        clean_path = path.strip()
        if clean_path:
            entries.append(WebSftpEntry(kind == "d", posixpath.basename(clean_path.rstrip("/")), clean_path))
    return entries


def parse_sftp_listing(output: str, current_directory: str) -> list[WebSftpEntry]:
    """Parse long-format SFTP `ls -la` output into file entries."""
    entries: list[WebSftpEntry] = []
    for raw_line in output.splitlines():
        line = normalize_sftp_listing_line(raw_line)
        if not line:
            continue
        parts = line.split(maxsplit=8)
        if len(parts) < 9 or not parts[0] or parts[0][0] not in "-dl":
            continue
        raw_name = parts[8]
        is_link = parts[0].startswith("l")
        name, link_target = split_sftp_link_name(raw_name) if is_link else (raw_name, None)
        if name == ".":
            continue
        is_dir = parts[0].startswith("d")
        path = (
            posixpath.dirname(current_directory.rstrip("/")) or "/"
            if name == ".."
            else posixpath.join(current_directory, name)
        )
        navigate_path = sftp_link_navigation_path(path, link_target) if is_link else path
        if is_link:
            is_dir = bool(link_target)
        entries.append(WebSftpEntry(is_dir, name, path, is_link, link_target, navigate_path))
    return entries


def normalize_sftp_listing_line(line: str) -> str:
    """Return a clean long-format SFTP listing row, without prompts or echoes."""
    line = line.strip()
    if not line or line.startswith("Listing MMU files:"):
        return ""
    if line.startswith("sftp>"):
        line = line.removeprefix("sftp>").strip()
    if line.startswith(("ls ", "dir ")):
        return ""
    return line


def split_sftp_link_name(raw_name: str) -> tuple[str, str | None]:
    """Split an SFTP symlink display name into name and target."""
    name, separator, target = raw_name.partition(" -> ")
    if not separator:
        return raw_name, None
    return name, target or None


def sftp_link_navigation_path(link_path: str, link_target: str | None) -> str:
    """Resolve a symlink target as an SFTP navigation path."""
    if not link_target:
        return link_path
    if link_target.startswith("/"):
        return posixpath.normpath(link_target)
    return posixpath.normpath(posixpath.join(posixpath.dirname(link_path), link_target))


def resolve_sftp_path(current: str, target: str) -> str:
    """Resolve an SFTP target path relative to a current directory."""
    if not target:
        return current
    if target.startswith("/"):
        return posixpath.normpath(target)
    return posixpath.normpath(posixpath.join(current, target))


def command_lines(command_set: CommandSet) -> list[str]:
    """Return executable command lines from a command set."""
    return [line.strip() for line in command_set.commands.splitlines() if line.strip()]


def next_command_line(command_set: CommandSet, index: int) -> tuple[str | None, int]:
    """Return the indexed non-empty command and the subsequent index."""
    lines = command_lines(command_set)
    safe_index = max(index, 0)
    if safe_index >= len(lines):
        return None, len(lines)
    return lines[safe_index], safe_index + 1


def main() -> int:
    """Launch the Streamlit server, or render when already inside Streamlit."""
    if _is_streamlit_runtime():
        render_app()
        return 0

    configure_logging()
    try:
        streamlit_script = _streamlit_script_path()
        from streamlit.web import bootstrap

        streamlit_options = {
            "global.developmentMode": False,
            "server.address": "localhost",
        }
        bootstrap.load_config_options(streamlit_options)
        _patch_streamlit_static_dir_for_pyinstaller()
        bootstrap.run(
            str(streamlit_script),
            False,
            [],
            streamlit_options,
        )
        return 0
    finally:
        shutdown_logging()


def _streamlit_script_path() -> Path:
    """Return the source script Streamlit should execute in this environment."""
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        script_path = Path(bundle_dir) / "mmu_control" / "streamlit_app" / "web_app.py"
    else:
        script_path = Path(__file__).resolve()

    if not script_path.is_file():
        raise FileNotFoundError(
            f"Streamlit application script was not found at {script_path}. "
            "The PyInstaller bundle may be missing src/mmu_control/web_app.py "
            "as mmu_control/streamlit_app/web_app.py."
        )
    return script_path


def _patch_streamlit_static_dir_for_pyinstaller() -> None:
    """Point Streamlit at bundled frontend assets in one-file PyInstaller builds."""
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if not bundle_dir:
        return
    static_dir = Path(bundle_dir) / "streamlit" / "static"
    if not static_dir.is_dir():
        return

    import streamlit.file_util

    streamlit.file_util.get_static_dir = lambda: str(static_dir)


def render_app() -> None:
    """Render the Streamlit application."""
    import streamlit as st

    st.set_page_config(page_title="MMU Control Web", layout="wide")
    _init_state(st)
    _poll_outputs(st)

    st.title("MMU Control Web")
    _render_sidebar(st)

    terminal_tab, sftp_tab, commands_tab, automation_tab, power_tab = st.tabs(
        ["Terminal", "SFTP", "Commands", "Automation", "Power"]
    )
    with terminal_tab:
        _render_terminal_tab(st)
    with sftp_tab:
        _render_sftp_tab(st)
    with commands_tab:
        _render_commands_tab(st)
    with automation_tab:
        _render_automation_tab(st)
    with power_tab:
        _render_power_tab(st)
    _render_auto_refresh(st)


def _is_streamlit_runtime() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
    except Exception:
        return False
    return get_script_run_ctx() is not None


def _init_state(st: Any) -> None:
    if "web_services" not in st.session_state:
        st.session_state.web_services = create_web_services()
    if "settings" not in st.session_state:
        try:
            st.session_state.settings = st.session_state.web_services.config_manager.load()
        except ConfigError:
            st.session_state.settings = AppSettings()
    defaults = {
        "shell": None,
        "sftp_shell": None,
        "sftp_active": False,
        "minicom_active": False,
        "terminal_output": "",
        "terminal_ttyd_url": "",
        "terminal_ttyd_error": "",
        "sftp_output": "",
        "server_sftp_directory": os.path.expanduser("~"),
        "mmu_sftp_directory": "/tmp",
        "server_entries": [],
        "mmu_entries": [],
        "usb_ports": [],
        "automation_runner": None,
        "automation_output": "",
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _services(st: Any) -> WebServices:
    return st.session_state.web_services


def _settings(st: Any) -> AppSettings:
    return st.session_state.settings


def _is_shell_open(shell: InteractiveShell | None) -> bool:
    """Return whether a shell object exists and can accept input."""
    return shell is not None and shell.is_open


def _append_output(st: Any, key: str, text: str, limit: int = 20000) -> None:
    if not text:
        return
    st.session_state[key] = f"{st.session_state.get(key, '')}{text}"[-limit:]


def _poll_outputs(st: Any) -> None:
    shell = st.session_state.get("shell")
    if shell is not None:
        try:
            if shell.is_open:
                output = shell.read_available()
                _append_output(st, "terminal_output", output)
                runner = st.session_state.get("automation_runner")
                if runner is not None and runner.is_active and output:
                    runner.receive_output(output)
                    _append_output(st, "automation_output", output, limit=AutomationRunner.OUTPUT_LIMIT * 4)
        except Exception as exc:
            _append_output(st, "terminal_output", f"\nShell error: {exc}\n")

    sftp_shell = st.session_state.get("sftp_shell")
    if sftp_shell is not None:
        try:
            if sftp_shell.is_open:
                output = sftp_shell.read_available()
                if output:
                    _handle_sftp_auth_output(st, output)
                    _append_output(st, "sftp_output", output)
        except Exception as exc:
            _append_output(st, "sftp_output", f"\nSFTP shell error: {exc}\n")

    runner = st.session_state.get("automation_runner")
    if runner is not None and runner.is_active:
        needs_file_check = runner.tick()
        if needs_file_check:
            command = runner.file_check_command()
            if command and shell is not None and shell.is_open:
                shell.send_line(command)


def _render_sidebar(st: Any) -> None:
    services = _services(st)
    settings = _settings(st)
    with st.sidebar:
        st.header("Connection")
        with st.form("settings_form"):
            ssh_host = st.text_input("SSH host", settings.ssh.host)
            ssh_port = st.number_input("SSH port", 1, 65535, settings.ssh.port)
            ssh_username = st.text_input("SSH user", settings.ssh.username)
            ssh_password = st.text_input("SSH password", settings.ssh.password, type="password")
            st.divider()
            board_ip = st.text_input("MMU IP", settings.board.ip_address)
            board_username = st.text_input("MMU user", settings.board.username)
            board_password = st.text_input("MMU password", settings.board.password, type="password")
            board_interface = st.text_input("MMU interface", settings.board.interface)
            board_usb_port = st.text_input("USB port", settings.board.usb_port)
            board_ssh_port = st.number_input("MMU SSH/SFTP port", 1, 65535, settings.board.ssh_port)
            st.divider()
            power_ip = st.text_input("Power supply IPv4", settings.power_supply.ip_address)
            power_voltage = st.text_input("Voltage", settings.power_supply.voltage)
            power_current = st.text_input("Current", settings.power_supply.current)
            saved = st.form_submit_button("Save settings")
        if saved:
            st.session_state.settings = settings_from_form_values(
                ssh_host=ssh_host,
                ssh_port=ssh_port,
                ssh_username=ssh_username,
                ssh_password=ssh_password,
                board_ip=board_ip,
                board_username=board_username,
                board_password=board_password,
                board_interface=board_interface,
                board_usb_port=board_usb_port,
                board_ssh_port=board_ssh_port,
                power_ip=power_ip,
                power_voltage=power_voltage,
                power_current=power_current,
                active_profile=settings.active_profile,
            )
            try:
                services.config_manager.save(st.session_state.settings)
                st.success("Settings saved.")
            except ConfigError as exc:
                st.error(str(exc))

        connected = services.ssh_manager.is_connected
        st.caption(f"SSH: {'connected' if connected else 'disconnected'}")
        cols = st.columns(2)
        if cols[0].button("Connect SSH", disabled=connected):
            _connect_ssh(st)
        if cols[1].button("Disconnect", disabled=not connected):
            _disconnect_ssh(st)


def _connect_ssh(st: Any) -> None:
    services = _services(st)
    settings = _settings(st)
    try:
        services.ssh_manager.connect(settings.ssh)
        shell = services.ssh_manager.open_shell()
        ttyd_session = services.ttyd_manager.start_ssh_terminal(settings.ssh)
    except SSHConnectionError as exc:
        st.error(str(exc))
        return
    except TtydError as exc:
        services.ttyd_manager.stop()
        services.ssh_manager.disconnect()
        st.error(str(exc))
        return
    st.session_state.shell = shell
    st.session_state.terminal_ttyd_url = ttyd_session.url
    st.session_state.terminal_ttyd_error = ""
    _append_output(st, "terminal_output", f"Connected to {settings.ssh.host}.\n")


def _disconnect_ssh(st: Any) -> None:
    services = _services(st)
    _close_shell(st.session_state.get("sftp_shell"))
    _close_shell(st.session_state.get("shell"))
    services.ttyd_manager.stop()
    services.ssh_manager.disconnect()
    st.session_state.shell = None
    st.session_state.sftp_shell = None
    st.session_state.sftp_active = False
    st.session_state.minicom_active = False
    st.session_state.terminal_ttyd_url = ""
    st.session_state.terminal_ttyd_error = ""
    st.session_state.automation_runner = None
    _append_output(st, "terminal_output", "Disconnected.\n")


def _close_shell(shell: InteractiveShell | None) -> None:
    if shell is not None:
        try:
            if shell.is_open:
                shell.close()
        except Exception:
            pass


def _render_terminal_tab(st: Any) -> None:
    shell = st.session_state.get("shell")
    ttyd_url = st.session_state.get("terminal_ttyd_url", "")
    if ttyd_url and shell is not None and shell.is_open:
        st.caption("Interactive terminal is provided by ttyd. App actions below still use the managed SSH shell.")
        st.components.v1.iframe(ttyd_url, height=560, scrolling=False)
        st.caption(f"ttyd endpoint: {ttyd_url}")
    else:
        st.info("Connect SSH to open a ttyd browser terminal.")
    if st.button("Clear managed terminal log"):
        st.session_state.terminal_output = ""
    with st.expander("Managed SSH shell log used by automation and app actions"):
        st.text_area("Managed terminal output", st.session_state.terminal_output, height=260)

    usb_cols = st.columns(4)
    if usb_cols[0].button("Refresh USB", disabled=shell is None or not shell.is_open):
        try:
            st.session_state.usb_ports = _services(st).ssh_manager.list_serial_ports()
        except SSHConnectionError as exc:
            st.error(str(exc))
    selected_usb = usb_cols[1].selectbox("USB port", st.session_state.usb_ports or [""])
    if usb_cols[2].button("Open minicom", disabled=shell is None or not shell.is_open):
        _open_minicom(st, selected_usb)
    if usb_cols[3].button("Close minicom", disabled=not st.session_state.minicom_active):
        _close_minicom(st)


def _open_minicom(st: Any, usb_port: str) -> None:
    shell = st.session_state.get("shell")
    if shell is None or not shell.is_open:
        st.warning("Connect SSH first.")
        return
    try:
        command = _services(st).minicom_manager.build_command(usb_port)
        shell.send_line(command)
    except MinicomError as exc:
        st.error(str(exc))
        return
    st.session_state.minicom_active = True
    _append_output(st, "terminal_output", f"$ {command}\n")


def _close_minicom(st: Any) -> None:
    shell = st.session_state.get("shell")
    if shell is not None and shell.is_open:
        _services(st).minicom_manager.close_session(shell)
    st.session_state.minicom_active = False


def _render_sftp_tab(st: Any) -> None:
    services = _services(st)
    active = bool(st.session_state.sftp_active)
    cols = st.columns([1, 1, 2])
    if cols[0].button("Open SFTP", disabled=active or not services.ssh_manager.is_connected):
        _open_sftp(st)
    if cols[1].button("Close SFTP", disabled=not active):
        _close_sftp(st)
    cols[2].caption("SFTP runs in a separate SSH shell from the Terminal tab.")

    server_path = st.text_input("Linux server directory", st.session_state.server_sftp_directory)
    mmu_path = st.text_input("MMU directory", st.session_state.mmu_sftp_directory)
    path_cols = st.columns(4)
    if path_cols[0].button("Set server path"):
        st.session_state.server_sftp_directory = resolve_sftp_path(st.session_state.server_sftp_directory, server_path)
    if path_cols[1].button("Set MMU path", disabled=not active):
        st.session_state.mmu_sftp_directory = resolve_sftp_path(st.session_state.mmu_sftp_directory, mmu_path)
        _send_sftp_line(st, f"cd {shlex.quote(st.session_state.mmu_sftp_directory)}")
    if path_cols[2].button("Refresh server"):
        _refresh_server_entries(st)
    if path_cols[3].button("Refresh MMU", disabled=not active):
        _refresh_mmu_entries(st)

    left, right = st.columns(2)
    with left:
        st.subheader("Linux server files")
        _render_entries_table(st, "server_entries")
    with right:
        st.subheader("MMU files")
        _render_entries_table(st, "mmu_entries")

    st.divider()
    upload = st.file_uploader("Upload local PC file to MMU")
    upload_dest = st.text_input("MMU upload destination", "/tmp/" + upload.name if upload else "/tmp/upload.bin")
    if st.button("Upload to MMU", disabled=upload is None or not active):
        _upload_local_file_to_mmu(st, upload, upload_dest)

    transfer_cols = st.columns(3)
    server_file = transfer_cols[0].text_input("Server file")
    mmu_file = transfer_cols[1].text_input("MMU file")
    if transfer_cols[2].button("Server -> MMU", disabled=not active):
        _sftp_upload(st, server_file, mmu_file)
    if transfer_cols[2].button("MMU -> Server", disabled=not active):
        _sftp_download(st, mmu_file, server_file)
    delete_path = st.text_input("Delete MMU file")
    if st.button("Delete MMU file", disabled=not active):
        _sftp_remove(st, delete_path)
    st.text_area("SFTP output", st.session_state.sftp_output, height=260)


def _render_entries_table(st: Any, key: str) -> None:
    entries: list[WebSftpEntry] = st.session_state.get(key, [])
    st.dataframe(
        [
            {
                "type": "dir" if entry.is_dir else "file",
                "name": entry.name,
                "path": entry.path,
                "link": entry.link_target or "",
            }
            for entry in entries
        ],
        use_container_width=True,
        hide_index=True,
    )


def _open_sftp(st: Any) -> None:
    services = _services(st)
    try:
        shell = services.ssh_manager.open_shell()
        command = services.sftp_manager.open_session(shell, _settings(st).board)
    except (SSHConnectionError, SFTPError) as exc:
        st.error(str(exc))
        return
    st.session_state.sftp_shell = shell
    st.session_state.sftp_active = True
    _append_output(st, "sftp_output", f"Opening SFTP: {command}\n")


def _handle_sftp_auth_output(st: Any, output: str) -> None:
    shell = st.session_state.get("sftp_shell")
    if shell is None or not shell.is_open:
        return
    services = _services(st)
    settings = _settings(st).board
    services.sftp_manager.handle_authenticity_prompt(shell, output)
    services.sftp_manager.handle_password_prompt(shell, output, settings)


def _close_sftp(st: Any) -> None:
    shell = st.session_state.get("sftp_shell")
    if shell is not None and shell.is_open and st.session_state.sftp_active:
        _services(st).sftp_manager.close_session(shell)
    _close_shell(shell)
    st.session_state.sftp_shell = None
    st.session_state.sftp_active = False
    _append_output(st, "sftp_output", "SFTP session closed.\n")


def _send_sftp_line(st: Any, command: str) -> None:
    shell = st.session_state.get("sftp_shell")
    if shell is None or not shell.is_open:
        st.warning("Open SFTP first.")
        return
    shell.send_line(command)
    _append_output(st, "sftp_output", f"sftp> {command}\n")


def _refresh_server_entries(st: Any) -> None:
    services = _services(st)
    directory = st.session_state.server_sftp_directory
    command = (
        f"find {shlex.quote(directory)} -maxdepth 1 "
        r"\( -type d -printf 'd\t%p\n' -o -type f -printf 'f\t%p\n' -o -type l -printf 'l\t%p\n' \)"
    )
    try:
        output = services.ssh_manager.execute_command(command)
    except SSHConnectionError as exc:
        st.error(str(exc))
        return
    st.session_state.server_entries = parse_find_listing(output)


def _refresh_mmu_entries(st: Any) -> None:
    directory = st.session_state.mmu_sftp_directory
    _send_sftp_line(st, f"ls -la {shlex.quote(directory)}")
    _append_output(st, "sftp_output", "Refresh again after output arrives to parse the latest listing.\n")
    st.session_state.mmu_entries = parse_sftp_listing(st.session_state.sftp_output, directory)


def _upload_local_file_to_mmu(st: Any, upload: Any, destination: str) -> None:
    services = _services(st)
    suffix = Path(upload.name).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_file.write(upload.getbuffer())
        local_path = temp_file.name
    server_path = posixpath.join("/tmp/mmu_control_uploads", upload.name)
    try:
        services.ssh_manager.execute_command(f"mkdir -p {shlex.quote(posixpath.dirname(server_path))}")
        services.ssh_manager.upload_file(local_path, server_path)
        _sftp_upload(st, server_path, destination)
    finally:
        try:
            os.unlink(local_path)
        except OSError:
            pass


def _sftp_upload(st: Any, server_path: str, mmu_path: str) -> None:
    shell = st.session_state.get("sftp_shell")
    try:
        command = _services(st).sftp_manager.upload(shell, server_path, mmu_path)
    except (SFTPError, AttributeError) as exc:
        st.error(str(exc))
        return
    _append_output(st, "sftp_output", f"sftp> {command}\n")


def _sftp_download(st: Any, mmu_path: str, server_path: str) -> None:
    shell = st.session_state.get("sftp_shell")
    try:
        command = _services(st).sftp_manager.download(shell, mmu_path, server_path)
    except (SFTPError, AttributeError) as exc:
        st.error(str(exc))
        return
    _append_output(st, "sftp_output", f"sftp> {command}\n")


def _sftp_remove(st: Any, mmu_path: str) -> None:
    shell = st.session_state.get("sftp_shell")
    try:
        command = _services(st).sftp_manager.remove(shell, mmu_path)
    except (SFTPError, AttributeError) as exc:
        st.error(str(exc))
        return
    _append_output(st, "sftp_output", f"sftp> {command}\n")


def _render_commands_tab(st: Any) -> None:
    services = _services(st)
    try:
        collection = services.command_set_store.load()
    except CommandSetStoreError as exc:
        st.error(str(exc))
        return
    names = sorted(collection.command_sets)
    selected = st.selectbox("Command set", names, index=0 if names else None)
    command_set = collection.command_sets.get(selected) if selected else None
    if st.session_state.get("command_line_set") != selected:
        st.session_state["command_line_set"] = selected
        st.session_state["command_line_index"] = 0
    with st.form("command_set_form"):
        name = st.text_input("Name", command_set.name if command_set else "")
        parent_path = st.text_input("Folder path", command_set.parent_path if command_set else "")
        description = st.text_area("Description", command_set.description if command_set else "", height=80)
        commands = st.text_area("Commands", command_set.commands if command_set else "", height=180)
        saved = st.form_submit_button("Save command set")
    if saved:
        try:
            services.command_set_store.upsert(CommandSet(name, description, commands, parent_path))
            st.success("Command set saved.")
        except CommandSetStoreError as exc:
            st.error(str(exc))
    cols = st.columns(3)
    shell = st.session_state.get("shell")
    if cols[0].button("Run command set", disabled=command_set is None or not _is_shell_open(shell)):
        for line in command_lines(command_set):
            shell.send_line(line)
            _append_output(st, "terminal_output", f"$ {line}\n")
    line_index = st.session_state.get("command_line_index", 0)
    lines = command_lines(command_set) if command_set is not None else []
    if cols[1].button(
        "Run next line",
        disabled=command_set is None or not _is_shell_open(shell) or line_index >= len(lines),
        help="Runs the next non-empty stored command by index; this is not based on the text-area caret.",
    ):
        line, next_index = next_command_line(command_set, line_index)
        if line is not None:
            shell.send_line(line)
            _append_output(st, "terminal_output", f"$ {line}\n")
            st.session_state["command_line_index"] = next_index
    st.caption(
        f"Run next line uses a stored non-empty-line index (not the editor caret): "
        f"{min(line_index + 1, len(lines)) if lines else 0} of {len(lines)}."
    )
    if cols[2].button("Delete command set", disabled=command_set is None):
        services.command_set_store.delete(command_set.name)
        st.success("Command set deleted.")


def _render_automation_tab(st: Any) -> None:
    services = _services(st)
    try:
        collection = services.automation_store.load()
    except AutomationStoreError as exc:
        st.error(str(exc))
        return
    names = sorted(collection.scenarios)
    selected = st.selectbox("Scenario", names, index=0 if names else None)
    scenario = collection.scenarios.get(selected) if selected else None
    _render_automation_editor(st, scenario)
    if scenario is not None and st.button("Copy scenario"):
        copied = copy_automation_scenario(scenario, set(collection.scenarios))
        try:
            services.automation_store.upsert(copied)
            st.success(f'Scenario copied as "{copied.name}".')
        except AutomationStoreError as exc:
            st.error(str(exc))
    st.divider()
    if scenario is not None:
        start_options = [f"{index + 1}: {step.name or step.command}" for index, step in enumerate(scenario.steps)]
        start_label = st.selectbox("Start step", start_options, index=0 if start_options else None)
        start_index = start_options.index(start_label) if start_label else 0
    else:
        start_index = 0
    cols = st.columns(2)
    shell = st.session_state.get("shell")
    if cols[0].button("Run scenario", disabled=scenario is None or not _is_shell_open(shell)):
        runner = AutomationRunner(shell.send_line)
        try:
            runner.start(scenario, start_step_index=start_index)
            runner.receive_initial_output(st.session_state.terminal_output[-AutomationRunner.OUTPUT_LIMIT :])
            st.session_state.automation_runner = runner
        except (RuntimeError, ValueError) as exc:
            st.error(str(exc))
    if cols[1].button("Stop", disabled=st.session_state.automation_runner is None):
        st.session_state.automation_runner.cancel()
    runner = st.session_state.get("automation_runner")
    if runner is not None:
        st.info(f"{runner.status.state}: {runner.status.message}")
    st.text_area("Automation output", st.session_state.automation_output, height=260)


def copy_automation_scenario(
    scenario: AutomationScenario,
    existing_names: set[str],
) -> AutomationScenario:
    """Return an independent scenario copy with a non-conflicting name."""
    copied = AutomationScenario.from_dict(scenario.to_dict())
    base_name = f"{scenario.name} (Copy)"
    copied.name = base_name
    copy_number = 2
    while copied.name in existing_names:
        copied.name = f"{base_name} {copy_number}"
        copy_number += 1
    return copied


def _render_automation_editor(st: Any, scenario: AutomationScenario | None) -> None:
    services = _services(st)
    with st.form("automation_form"):
        name = st.text_input("Scenario name", scenario.name if scenario else "")
        description = st.text_area("Scenario description", scenario.description if scenario else "", height=80)
        raw_steps = st.text_area(
            "Steps (one command per line)",
            "\n".join(step.command for step in scenario.steps) if scenario else "",
            height=160,
        )
        saved = st.form_submit_button("Save scenario")
    if saved:
        steps = [AutomationStep(command=line.strip()) for line in raw_steps.splitlines() if line.strip()]
        try:
            services.automation_store.upsert(AutomationScenario(name=name, description=description, steps=steps))
            st.success("Scenario saved.")
        except AutomationStoreError as exc:
            st.error(str(exc))
    if scenario is not None and st.button("Delete scenario"):
        services.automation_store.delete(scenario.name)
        st.success("Scenario deleted.")


def _render_power_tab(st: Any) -> None:
    services = _services(st)
    services.power_supply_manager.update_settings(_settings(st).power_supply)
    cols = st.columns(5)
    shell = st.session_state.get("shell")
    for column, action, label in zip(
        cols,
        ["set", "on", "off", "status", "all_status"],
        ["Set", "ON", "OFF", "Status", "All Status"],
        strict=True,
    ):
        if column.button(label, disabled=not _is_shell_open(shell)):
            try:
                command = services.power_supply_manager.build_command(action)
                shell.send_line(command)
            except (PowerSupplyCommandError, AttributeError) as exc:
                st.error(str(exc))
                continue
            _append_output(st, "terminal_output", f"$ {command}\n")
    st.caption("Power commands are sent through the connected Linux server SSH shell.")


def _render_auto_refresh(st: Any) -> None:
    import streamlit as st_module

    @st_module.fragment(run_every="1s")
    def _heartbeat() -> None:
        _poll_outputs(st_module)

    _heartbeat()


if __name__ == "__main__":
    if _is_streamlit_runtime():
        render_app()
    else:
        raise SystemExit(main())
