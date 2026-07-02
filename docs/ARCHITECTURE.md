# Architecture

## Technology
- Python 3.12+
- PySide6
- Paramiko
- JSON

## Folder

src/
  ui/
  core/
  models/
  storage/
  resources/

## Core Modules
- SSHManager
- TerminalManager
- MinicomManager
- SFTPManager
- CommandExecutor
- ConfigManager

## Threads
GUI
 |- SSH Worker
 |- Terminal Reader
 |- Command Executor

## Data Flow
GUI -> CommandExecutor -> SSHManager -> Linux Shell -> TerminalManager -> GUI
