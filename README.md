# MMU Control

Windows Python GUI application for connecting to a Linux server over SSH and controlling board workflows such as shell, minicom, and SFTP.

## Recommended Setup

From Command Prompt or PowerShell, run the installer. It selects Python 3.12 or
newer, creates (or reuses) `.venv`, and installs the runtime and development
dependencies. It also builds the desktop executable at `dist\MMUControl.exe`:

```powershell
.\install.bat
```

If the installer fails, use these manual commands for troubleshooting:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m PyInstaller --clean -y "MMUControl.spec"
```

## Run

```powershell
mmu-control
```

## Run Web UI

```powershell
mmu-control-web
```

During development you can also run the Streamlit entry point directly:

```powershell
python -m streamlit run .\src\mmu_control\web_app.py
```

The web UI runs locally and reuses the same settings, command sets, and
automation scenarios stored in `<project>/local_data`. Its Terminal tab embeds
a browser terminal served by `ttyd`, so install `ttyd` and make it available on
`PATH`, or set `MMU_CONTROL_TTYD` to the full `ttyd` executable path before
starting `mmu-control-web`. The embedded terminal runs a normal local `ssh`
client, so the browser terminal may prompt for SSH credentials separately from
the app-managed Paramiko connection used by automation and buttons.

## Board workflows

- SSH connection and board fields are restored when the application restarts.
- `Refresh USB` searches the connected Linux server for `/dev/ttyUSB*` and `/dev/ttyACM*` devices.
- Select a detected device and use `Open Minicom` / `Close Minicom` for the board serial console.
- When the Linux server is disconnected, `SSH Connect` opens a direct SSH session from the local Windows PC to the board. Serial console controls remain unavailable because Windows COM-port support is not implemented yet.
- Full-screen commands such as `htop` use immediate key input, so `q` and `Ctrl+C` are sent without pressing Enter.
- The SFTP tab uses its own SSH terminal and opens an SFTP session from the Linux server to the board. Closing it does not close the main Terminal tab.
- `Server path` is a path on that Linux server, not a path on the Windows PC. `Board path` is the corresponding path on the board.
- You can drag and drop a file into the `Server path` input to fill in a local PC path as an entry aid; use it only when that same path is accessible from the SSH Linux server, otherwise enter the Linux server path manually.
- Use `Upload to Board` for SFTP `put` and `Download to Server` for SFTP `get`.

## Automation scenarios

- Command sets are loaded from and saved to
  `src/mmu_control/user_command/command_sets.json`.
- Automation scenarios are loaded from and saved to
  `src/mmu_control/user_scenario/automation_scenarios.json`.
- In development these paths are relative to the repository/project root. In a
  PyInstaller build they are relative to the executable directory (not its
  temporary extraction directory). For example, `C:\MMUControl\MMUControl.exe`
  stores the files at
  `C:\MMUControl\src\mmu_control\user_command\command_sets.json` and
  `C:\MMUControl\src\mmu_control\user_scenario\automation_scenarios.json`.
- The application must have write permission for the `user_command` and
  `user_scenario` directories. A save failure reports the actual target path.
- These JSON files can be committed so the team can manage the same commands and
  scenarios together. Do not put IDs, passwords, or other secrets in them.
- Shared commands and scenario steps may reference per-user values with the
  `${VARIABLE_NAME}` syntax, for example `ssh ${MMU_USERNAME}@${MMU_HOST}`.
  Literal remote-shell placeholders can be escaped as `$${VARIABLE_NAME}`.
- Each user supplies the actual values in `<project>\local_data\variables.json`:

  ```json
  {
    "schema_version": 1,
    "variables": {
      "MMU_USERNAME": "your-user-name",
      "MMU_PASSWORD": "your-password"
    }
  }
  ```

  This file is outside the repository and is never copied into command or
  scenario JSON. If any referenced variable is missing, the command is not sent.
- The Scenarios tab loads this file when the application starts and refreshes the scenario list after a scenario is saved.

## Test

```powershell
python -m pytest
```

## Build EXE

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1
```

The executable is created at `dist\MMUControl.exe`.

## Build Web EXE

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_web_exe.ps1
```

The web executable is created at `dist\MMUControlWeb.exe` and starts the local
Streamlit browser UI.

## Multiple clients in one desktop window

The desktop app opens a client tab bar above the existing Terminal/SFTP workspace.
Click **+** to add a client and drag tabs to reorder them. Set **Device name**
in the Client connection panel or double-click a tab to edit the same name.
The tab uses the device name, then the Client IP, then its default `Client N`
label. Clearing the device name restores automatic IP labeling. The label stays
visible after disconnect; the connection status changes separately. Hover over
a tab to see its device name, Client IP, gateway SSH server and connection states. Each tab has its own server and board connection, terminal history,
SFTP session, power settings, and automation run. Switching tabs keeps background
connections and scenarios running. The window title and tab label identify the
client and its connection state.

Closing a connected tab asks before stopping its work; other clients keep running.
Connection and file operations must finish before their tab or the app can close.
Closing the last tab opens a fresh disconnected client. On restart the app restores
the tab names, order, active tab, and each client's saved fields, without connecting
to devices automatically.

The first client reuses `<project>/local_data/settings.json`. Added clients store
connection settings in `<project>/local_data/clients/<client-id>/settings.json`.
All tabs read the same `<project>/local_data/variables.json` for user-defined
command variables, rereading it for each command/scenario run. Tab
layout is saved in `client_tabs.json`; closing a tab retains its settings files.
Command and scenario definitions remain shared across clients and refresh when
switching to an idle client tab. An active scenario keeps its current definition
until it finishes. This tab workflow applies to the desktop app; the web UI is
unchanged.

### Per-client VLAN and MAC variables

Set **VLAN**, **DU MAC**, and **MMU MAC** on the same row in each desktop Client panel. The values are saved
with that client's connection settings and restored on restart. Shared Commands
and automation scenarios can use these placeholders:

```bash
configure --vlan ${MMU_VLAN} --du-mac ${DU_MAC} --mmu-mac ${MMU_MAC}
```

VLAN input must be decimal 1–255. `${MMU_VLAN}` is substituted as exactly two
lowercase hexadecimal digits without `0x` (1 → `01`, 10 → `0a`, 100 → `64`,
255 → `ff`). Add `0x` in a command if required: `0x${MMU_VLAN}`. DU MAC and MMU MAC accept six hexadecimal pairs separated consistently
by colons or hyphens, and are substituted as uppercase colon-separated pairs.
Only referenced inputs are required. A missing or invalid referenced value blocks
the whole command group or scenario before any command is sent. A running scenario
keeps the values captured when it started; edits apply to subsequent runs.
These three variable names use the current Client input fields, overriding values
with the same names in `variables.json`. Other variables continue to use that file.
Literal remote-shell placeholders can still be escaped as `$${MMU_VLAN}`.

### Shared variable lookup

For `${MMU_PW_2}` (and other user-defined variables), every desktop tab loads
only `<project>/local_data/variables.json`. Client-specific `variables.json`
files are no longer read or created; existing files are left untouched. Move any
variables you still need from those files into the common file yourself. Names are case-sensitive; use `MMU_PW_2` as the JSON key and
`${MMU_PW_2}` in the command. Client VLAN/MAC fields still own `${MMU_VLAN}`,
`${DU_MAC}`, and `${MMU_MAC}` as described above.

### Split MAC variables

Each Client MAC input also supplies a first-four-digit `_HEAD` and a
last-eight-digit `_TAIL` variable, with separators removed:

| Input | Full variable | HEAD | TAIL |
| --- | --- | --- | --- |
| DU MAC `12:34:56:78:90:12` | `${DU_MAC}` | `${DU_MAC_HEAD}` = `1234` | `${DU_MAC_TAIL}` = `56789012` |
| MMU MAC `00:01:00:02:0A:BC` | `${MMU_MAC}` | `${MMU_MAC_HEAD}` = `0001` | `${MMU_MAC_TAIL}` = `00020ABC` |

For example, `configure --high 0x${DU_MAC_HEAD} --low 0x${DU_MAC_TAIL}`.
Hexadecimal letters are uppercase and leading zeros are retained. The variables
do not include `0x`; add it in the command where needed. Referencing either part
validates the corresponding Client MAC input. Parts follow the same Client input
precedence and scenario-start snapshot rules as the full MAC variables.

Hover over a DU MAC or MMU MAC input (or its label) to see the exact full/HEAD/TAIL
variable names. Clicking or tabbing into either input also displays its tooltip, without adding
an extra help area or changing the panel height.

### Variable catalog

Click **Variables** at the top of a Client workspace to open a searchable list of
all common `variables.json` names and built-in Client input/full MAC/HEAD/TAIL
variables. The dialog identifies the selected Client and shows only variable
names and masked values, including variables whose inputs are not configured yet.
Click a row or use **Copy variable** to copy `${NAME}` syntax, never its value.

Values are hidden by default; **Show values** explicitly reveals them, including
any passwords in the common file. Search matches only variable names. **Refresh**
reloads the common file and current Client inputs and hides values again. Opening the dialog also reads the latest file contents.

VLAN also shows `${MMU_VLAN}` in a tooltip when hovered, clicked or selected with
Tab, matching the DU MAC and MMU MAC inputs.

Use **Add variable** to register a new common variable: enter its name without
`${}` and then its value in the masked prompt. Duplicate names and Client-owned
VLAN/MAC names cannot be added. Select a common variable and choose **Remove
variable** to delete it after confirmation; Client-owned variables cannot be
removed here. Changes save immediately to the common `variables.json` for all
clients and apply to subsequent commands/scenario runs. The list refreshes with
values hidden after a successful change. Fix unreadable/invalid JSON files and
refresh before making changes; existing files are not overwritten on load errors.

### Private runtime data location

Settings, client tabs, common variables, client-specific settings and logs use
`<project>/local_data/`, which is excluded from Git by `/local_data/`.
Development uses the installed source checkout regardless of the working directory.
An EXE in a project's `dist` directory uses that project's `local_data/`; a
standalone EXE without a source tree uses `local_data/` beside the EXE, never
PyInstaller's temporary extraction folder. The location must be writable.

No existing AppData files are automatically copied, moved or deleted, and no
sample data/templates are generated. Copy any existing settings you wish to keep
manually into this directory before starting the program. Existing behavior when
settings are absent is unchanged. Shared command/scenario JSON locations are
unchanged. Exclude `local_data/` when sharing a ZIP of the project.

### Nested variable names

Commands and scenario steps can build a variable name from another variable.
With `MMU_A` set to `1` and `CC_1` set to `selected-command`, this template:

```bash
configure ${CC_${MMU_A}}
```

runs as `configure selected-command`: the inner expression selects `CC_1`, then
its value is inserted. Multiple selectors and nested selectors are supported,
including Client inputs such as `${CC_${MMU_VLAN}}` (decimal VLAN 100 selects
`CC_64`, not `CC_100`). Missing inner or selected
variables block the whole group/scenario before commands are sent. Scenarios keep
the variable snapshot taken at startup.

Variable values themselves are inserted literally, not recursively expanded.
`$${NAME}` still sends a literal `${NAME}`; `$${CC_${MMU_A}}` sends the entire
nested expression literally. Invalid computed names and nesting beyond 32 levels
are rejected before execution.

### Connection defaults

Click **Save defaults** in a Client workspace to save its currently entered
**SSH server**, **Power supply**, and/or **Client** fields. Choose the groups to
include; saving replaces the defaults with only those checked groups. Defaults
are stored in Git-ignored `local_data/default_settings.json`, including credentials
if their group is selected. Window state and common command variables are not
included.

New Client tabs automatically populate the saved groups. The first workspace of
a new window also uses defaults if it has no saved Client settings. Reopening
existing tabs restores their own settings, regardless of changes to the defaults.
Use **Load defaults** to apply saved groups to an existing disconnected tab after
confirmation; unchecked/unsaved groups are left unchanged. Busy or connected tabs
must finish/disconnect before loading defaults. Applying defaults only fills
inputs: it never connects, runs a scenario, or sends a power command.

In the scenario editor, the Start/Completion condition selectors and timeout
inputs do not change values with the mouse wheel, even while focused. Wheel
motion over these controls scrolls the details pane instead. Change settings
explicitly with clicks, keyboard selection, typing or the timeout arrow buttons.

The Commands editor's **Parent folder** selector also ignores mouse-wheel changes,
including while focused. Select a folder explicitly by clicking or using the keyboard.

Terminal history stores command text without trailing CR/LF. Empty Enter presses
are still sent to the shell but are not added to history. Up/Down skip old blank
entries and remove old trailing line endings when recalling commands; recall does
not execute anything. Interior line breaks and spaces are preserved, and pressing
Enter explicitly submits the recalled command with the shell's normal newline.

`clear` (and local `cls`) clears visible and queued terminal output without deleting
command history. Up/Down can still recall earlier commands afterward; the screen
clear does not execute or resend any recalled command.
