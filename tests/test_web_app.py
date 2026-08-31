"""Tests for the Streamlit web interface helpers."""

from __future__ import annotations

from pathlib import Path

from mmu_control.core.ttyd_manager import TtydError, TtydManager
from mmu_control.models.automation import AutomationScenario, AutomationStep, CompletionType
from mmu_control.models.command_set import CommandSet
from mmu_control.web_app import (
    _is_shell_open,
    _patch_streamlit_static_dir_for_pyinstaller,
    _streamlit_script_path,
    command_lines,
    copy_automation_scenario,
    create_web_services,
    parse_find_listing,
    parse_sftp_listing,
    resolve_sftp_path,
    settings_from_form_values,
    next_command_line,
)


def test_streamlit_script_path_uses_module_file_without_pyinstaller(monkeypatch) -> None:
    monkeypatch.delattr("sys._MEIPASS", raising=False)

    assert _streamlit_script_path() == Path("src/mmu_control/web_app.py").resolve()


def test_streamlit_script_path_uses_bundled_data_file(monkeypatch, tmp_path) -> None:
    bundled_script = tmp_path / "mmu_control" / "streamlit_app" / "web_app.py"
    bundled_script.parent.mkdir(parents=True)
    bundled_script.write_text("# bundled Streamlit script\n", encoding="utf-8")
    monkeypatch.setattr("sys._MEIPASS", str(tmp_path), raising=False)

    assert _streamlit_script_path() == bundled_script


def test_streamlit_script_path_explains_missing_bundle_data(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("sys._MEIPASS", str(tmp_path), raising=False)

    try:
        _streamlit_script_path()
    except FileNotFoundError as exc:
        assert "mmu_control/streamlit_app/web_app.py" in str(exc)
    else:
        raise AssertionError("Missing bundled Streamlit script did not raise")


def test_main_launches_streamlit_with_production_static_assets() -> None:
    source = Path("src/mmu_control/web_app.py").read_text(encoding="utf-8")

    assert '"global.developmentMode": False' in source
    assert "bootstrap.load_config_options(streamlit_options)" in source


def test_streamlit_static_dir_patch_uses_pyinstaller_bundle(monkeypatch) -> None:
    import streamlit.file_util

    tmp_path = Path("build") / "test_streamlit_bundle"
    bundle_static = tmp_path / "streamlit" / "static"
    bundle_static.mkdir(parents=True, exist_ok=True)
    original_get_static_dir = streamlit.file_util.get_static_dir
    monkeypatch.setattr("sys._MEIPASS", str(tmp_path), raising=False)

    try:
        _patch_streamlit_static_dir_for_pyinstaller()

        assert streamlit.file_util.get_static_dir() == str(bundle_static)
    finally:
        streamlit.file_util.get_static_dir = original_get_static_dir


class FakeShell:
    def __init__(self, is_open: bool) -> None:
        self.is_open = is_open


def test_create_web_services_uses_default_managers() -> None:
    services = create_web_services()

    assert services.ssh_manager is not None
    assert services.sftp_manager is not None
    assert services.minicom_manager is not None
    assert services.power_supply_manager is not None
    assert services.ttyd_manager is not None
    assert services.config_manager is not None
    assert services.command_set_store is not None
    assert services.automation_store is not None


class FakeTtydProcess:
    def __init__(self, command: list[str], **_kwargs: object) -> None:
        self.command = command
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return None if not self.terminated and not self.killed else 0

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        self.killed = True


def test_ttyd_manager_builds_ssh_terminal_command(tmp_path) -> None:
    executable = tmp_path / "ttyd"
    executable.write_text("", encoding="utf-8")
    manager = TtydManager(executable=str(executable), process_factory=FakeTtydProcess)
    settings = settings_from_form_values(
        ssh_host="server.local",
        ssh_port=2222,
        ssh_username="user",
        ssh_password="secret",
        board_ip="",
        board_username="",
        board_password="",
        board_interface="",
        board_usb_port="",
        board_ssh_port=22,
        power_ip="",
        power_voltage="",
        power_current="",
    )

    session = manager.start_ssh_terminal(settings.ssh)

    assert session.url.startswith("http://127.0.0.1:")
    assert manager.session == session
    assert manager._process.command[:5] == [str(executable), "--interface", "127.0.0.1", "--port", str(session.port)]
    assert manager._process.command[5:] == [
        "ssh",
        "-p",
        "2222",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "user@server.local",
    ]
    manager.stop()
    assert not manager.is_running


def test_ttyd_manager_reports_missing_executable(monkeypatch) -> None:
    monkeypatch.setenv("MMU_CONTROL_TTYD", "missing-ttyd")
    manager = TtydManager()
    settings = settings_from_form_values(
        ssh_host="server.local",
        ssh_port=22,
        ssh_username="user",
        ssh_password="",
        board_ip="",
        board_username="",
        board_password="",
        board_interface="",
        board_usb_port="",
        board_ssh_port=22,
        power_ip="",
        power_voltage="",
        power_current="",
    )

    try:
        manager.start_ssh_terminal(settings.ssh)
    except TtydError as exc:
        assert "Configured ttyd executable was not found" in str(exc)
    else:
        raise AssertionError("Missing ttyd executable did not raise")


def test_settings_from_form_values_builds_app_settings() -> None:
    settings = settings_from_form_values(
        ssh_host=" server.local ",
        ssh_port=2222,
        ssh_username=" user ",
        ssh_password="secret",
        board_ip=" fe80::1 ",
        board_username="root",
        board_password="mmu",
        board_interface=" eth0 ",
        board_usb_port="/dev/ttyUSB0",
        board_ssh_port=2200,
        power_ip="192.168.0.5",
        power_voltage="12",
        power_current="1.5",
    )

    assert settings.ssh.host == "server.local"
    assert settings.ssh.port == 2222
    assert settings.board.ip_address == "fe80::1"
    assert settings.board.interface == "eth0"
    assert settings.power_supply.current == "1.5"


def test_command_lines_preserves_blank_physical_lines() -> None:
    command_set = CommandSet("Boot", commands="\n echo one \n\nreboot\n")

    assert command_lines(command_set) == ["", "echo one", "", "reboot"]


def test_next_command_line_advances_physical_line_index_safely() -> None:
    """The Streamlit index policy sends blanks and stays at the physical end."""
    command_set = CommandSet("Boot", commands=" first \n\nsecond\n")

    first, index = next_command_line(command_set, 0)
    blank, index = next_command_line(command_set, index)
    second, index = next_command_line(command_set, index)
    finished, final_index = next_command_line(command_set, index)

    assert (first, second) == ("first", "second")
    assert blank == ""
    assert (finished, final_index) == (None, 3)


def test_is_shell_open_requires_live_shell() -> None:
    assert not _is_shell_open(None)
    assert not _is_shell_open(FakeShell(False))
    assert _is_shell_open(FakeShell(True))


def test_copy_automation_scenario_preserves_data_as_an_independent_copy() -> None:
    original = AutomationScenario(
        name="Boot",
        description="Boot the board",
        steps=[
            AutomationStep(
                name="Wait",
                command="boot",
                completion_type=CompletionType.OUTPUT_CONTAINS,
                completion_value="ready",
            )
        ],
        parent_path="Regression/Nightly",
    )

    copied = copy_automation_scenario(original, {"Boot", "Boot (Copy)"})

    assert copied == AutomationScenario(
        name="Boot (Copy) 2",
        description=original.description,
        steps=[AutomationStep.from_dict(original.steps[0].to_dict())],
        parent_path=original.parent_path,
    )
    assert copied.steps[0] is not original.steps[0]


def test_copy_automation_scenario_uses_the_default_copy_name_when_available() -> None:
    copied = copy_automation_scenario(AutomationScenario(name="Boot"), {"Boot"})

    assert copied.name == "Boot (Copy)"


def test_parse_find_listing_matches_file_kinds() -> None:
    entries = parse_find_listing("d\t/tmp\nf\t/tmp/a.bin\nl\t/tmp/latest\nignored\n")

    assert [(entry.is_dir, entry.name, entry.path) for entry in entries] == [
        (True, "tmp", "/tmp"),
        (False, "a.bin", "/tmp/a.bin"),
        (False, "latest", "/tmp/latest"),
    ]


def test_parse_sftp_listing_handles_parent_and_symlink() -> None:
    output = """
sftp> ls -la /tmp
drwxr-xr-x    2 root root 4096 Jul 01 00:00 .
drwxr-xr-x    5 root root 4096 Jul 01 00:00 ..
-rw-r--r--    1 root root    4 Jul 01 00:00 data.bin
lrwxrwxrwx    1 root root    8 Jul 01 00:00 logs -> /var/log
"""

    entries = parse_sftp_listing(output, "/tmp")

    assert [(entry.name, entry.path, entry.is_dir) for entry in entries] == [
        ("..", "/", True),
        ("data.bin", "/tmp/data.bin", False),
        ("logs", "/tmp/logs", True),
    ]
    assert entries[-1].link_target == "/var/log"
    assert entries[-1].navigate_path == "/var/log"


def test_resolve_sftp_path() -> None:
    assert resolve_sftp_path("/tmp", "firmware") == "/tmp/firmware"
    assert resolve_sftp_path("/tmp/work", "..") == "/tmp"
    assert resolve_sftp_path("/tmp", "/var/log") == "/var/log"


def test_web_pyinstaller_spec_bundles_power_supply_commands_only_as_static_data() -> None:
    spec_text = Path("MMUControlWeb.spec").read_text(encoding="utf-8")

    assert r"src\\mmu_control\\resources\\power_supply_commands.json" in spec_text
    assert "mmu_control/resources" in spec_text
    assert "command_sets.json" not in spec_text
    assert "automation_scenarios.json" not in spec_text


def test_web_pyinstaller_spec_bundles_streamlit_script_as_data() -> None:
    spec_text = Path("MMUControlWeb.spec").read_text(encoding="utf-8")

    assert r"src\\mmu_control\\web_app.py" in spec_text
    assert "mmu_control/streamlit_app" in spec_text


def test_web_pyinstaller_spec_bundles_streamlit_metadata() -> None:
    spec_text = Path("MMUControlWeb.spec").read_text(encoding="utf-8")

    assert "copy_metadata" in spec_text
    assert "copy_metadata('streamlit')" in spec_text


def test_web_pyinstaller_spec_uses_ascii_runtime_temp_directory() -> None:
    spec_text = Path("MMUControlWeb.spec").read_text(encoding="utf-8")

    assert "runtime_tmpdir='C:\\\\Users\\\\Public\\\\MMUControlTemp'" in spec_text
