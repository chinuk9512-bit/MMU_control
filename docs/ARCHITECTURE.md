# Architecture

## 개요

MMU Control은 Windows PC에서 실행되는 Python/PySide6 데스크톱 GUI입니다. 사용자는 GUI에서 Linux Server로 SSH 접속한 뒤, 해당 서버를 작업 허브로 사용하여 MMU/Board의 Shell, Serial(minicom), SFTP, 전원 제어 업무를 수행합니다.

기본 흐름은 다음과 같습니다.

```text
Windows PC GUI
  -> Paramiko SSH
  -> Linux Server
  -> Board/MMU Shell, minicom, SFTP, Power Supply command
```

## 기술 스택

- Python 3.12 이상
- PySide6: GUI, Signal/Slot, QThreadPool 기반 백그라운드 실행
- Paramiko: SSH 접속, 명령 실행, Shell channel, 로컬 PC -> Linux Server 파일 업로드
- JSON: 설정, 명령 세트, 전원 공급기 명령 템플릿 저장
- PyInstaller: Windows 실행 파일 패키징
- pytest: 단위/GUI 로직 테스트

## 소스 구조

```text
src/mmu_control/
  app.py                         # QApplication 생성, MainWindow 실행, 로깅 초기화/종료
  core/                          # SSH/SFTP/minicom/전원/설정/로깅/터미널 시퀀스 등 비즈니스 로직
  models/                        # JSON 직렬화 가능한 dataclass 모델
  storage/                       # 명령 세트와 연결 프로필 JSON 저장소
  ui/                            # PySide6 위젯, 메인 윈도우, 터미널 위젯, 백그라운드 작업 실행기
  resources/                     # 패키지에 포함되는 기본 JSON 리소스
```

## 주요 모듈과 책임

### Entry Point

- `mmu_control.app.main`
  - 로깅을 설정하고 `QApplication`과 `MainWindow`를 생성합니다.
  - 애플리케이션 종료 시 로깅 핸들러를 정리합니다.

### UI Layer

- `MainWindow`
  - SSH 연결 정보, 전원 공급기 정보, Board/MMU 정보 입력 영역을 구성합니다.
  - Workspace 탭으로 Terminal, Commands, SFTP 기능을 제공합니다.
  - Board 콘솔 탭으로 Serial Console(minicom)과 SSH Console을 분리합니다.
  - 설정 로드/저장, 버튼 상태 전환, Shell polling, SFTP 파일 목록 갱신 등 화면 상태를 조율합니다.
- `TerminalWidget`
  - 출력과 현재 입력 프롬프트를 한 위젯 안에서 관리합니다.
  - 일반 line-editing 모드와 `minicom`, `htop`, `vi` 등 즉시 키 입력이 필요한 interactive 모드를 지원합니다.
- `CommandEditorDialog`
  - 이름, 설명, 여러 줄 명령으로 구성된 명령 세트를 편집합니다.
- `ThreadPoolTaskRunner`
  - GUI thread를 막지 않도록 연결, 업로드, 원격 명령 실행 같은 blocking 작업을 Qt global thread pool에서 실행합니다.

### Core Layer

- `SSHManager`
  - Linux Server SSH 연결 수명주기를 관리합니다.
  - 연결/해제/재연결, interactive shell 생성, 비대화형 명령 실행, 로컬 PC 파일 업로드, USB serial port 검색을 담당합니다.
- `InteractiveShell`
  - Paramiko shell channel의 얇은 래퍼입니다.
  - 즉시 읽기 가능한 출력만 읽고, 명령/원시 입력을 전송합니다.
- `SFTPManager`
  - Linux Server 안에서 실행되는 `sftp` CLI 명령을 구성하고 제어합니다.
  - Board IP, 사용자, 포트, IPv6 zone/interface, password prompt, authenticity prompt, upload/download/close 명령을 처리합니다.
- `MinicomManager`
  - `/dev/ttyUSB*`, `/dev/ttyACM*` 형식만 허용하여 안전한 `minicom -o -c off -D ...` 명령을 만듭니다.
  - 종료 시 Ctrl-A, X, Enter 시퀀스를 보냅니다.
- `PowerSupplyManager`
  - `resources/power_supply_commands.json`에 정의된 전원 공급기 command template을 로드합니다.
  - IP/전압/전류 입력값을 검증하고 `on`, `off`, `status`, `all_status`, `set` 명령을 생성합니다.
- `ConfigManager`
  - `%APPDATA%/MMUControl/settings.json`에 애플리케이션 설정을 원자적으로 저장합니다.
  - 기존 JSON과의 하위 호환을 위해 누락 필드는 기본값으로 채웁니다.
- `TerminalStreamFilter`
  - ANSI/VT escape sequence와 제어 문자를 제거하면서 출력 chunk 사이의 상태를 유지합니다.
- `run_with_retry`
  - 재연결 등 일시 실패 가능 작업에 사용할 retry/backoff helper입니다.
- `AutomationRunner`
  - 하나의 SSH 또는 minicom terminal에서 사용자 정의 Step을 순서대로 실행합니다.
  - 콘솔/프롬프트/장비 파일/시간 완료 조건을 판정하며, 실패 Step만 2초 뒤 한 번 재시도합니다.

### Model / Storage Layer

- `AppSettings`
  - SSH, Board/MMU, 전원 공급기, Window 상태, active profile 이름을 포함합니다.
- `SSHSettings`, `BoardSettings`, `PowerSupplySettings`, `WindowSettings`
  - 각 설정 그룹의 직렬화/역직렬화를 담당합니다.
- `CommandSet`, `CommandSetCollection`
  - Commands 탭에서 생성/수정/삭제/실행하는 명령 묶음입니다.
- `AutomationScenario`, `AutomationStep`
  - 명령, 완료 조건, timeout을 가진 순차 장비 자동화 모델입니다.
- `ConnectionProfile`, `ProfileCollection`, `ProfileStore`
  - SSH/Board 연결 설정을 이름별 프로필로 저장하기 위한 모델과 저장소입니다.
  - 현재 UI는 기본 설정 저장을 중심으로 동작하며, 프로필 저장소는 확장 기반으로 준비되어 있습니다.
- `CommandSetStore`
  - `%APPDATA%/MMUControl/command_sets.json`에 명령 세트를 저장합니다.
- `AutomationStore`
  - `%APPDATA%/MMUControl/automation_scenarios.json`에 자동화 시나리오를 저장합니다.

## 런타임 데이터 흐름

### SSH Terminal

```text
MainWindow Connect 버튼
  -> ThreadPoolTaskRunner
  -> SSHManager.connect()
  -> SSHManager.open_shell()
  -> InteractiveShell
  -> QTimer polling
  -> TerminalWidget.write_stream()
```

사용자가 Terminal 탭에서 명령을 입력하면 `InteractiveShell.send_line()`으로 Linux Server shell에 전달됩니다. 즉시 입력 모드에서는 key press가 `InteractiveShell.send()`로 바로 전달됩니다.

### Serial Console(minicom)

```text
Refresh USB
  -> SSHManager.list_serial_ports()
  -> /dev/ttyUSB*, /dev/ttyACM* 목록 표시
Open Minicom
  -> MinicomManager.build_command()
  -> Main terminal shell에서 minicom 실행
  -> TerminalWidget interactive mode 전환
Close Minicom
  -> Ctrl-A, X, Enter 전송
```

### SFTP

```text
Open SFTP
  -> 별도 SSH shell 생성
  -> Linux Server에서 sftp user@board 실행
  -> prompt/auth/password 처리
  -> Server/MMU 파일 목록 표시
Upload/Download/Drag-and-drop
  -> sftp put/get 명령 전송
  -> 파일 목록 재갱신
```

SFTP는 메인 Terminal shell과 독립된 shell을 사용하므로 SFTP 종료가 Terminal 연결을 닫지 않습니다.

### Local PC 파일 Drag-and-drop

```text
Windows local file drop
  -> SSHManager.upload_file()로 Linux Server /tmp/mmu_control_uploads에 업로드
  -> SFTP put 명령으로 Linux Server 파일을 MMU/Board로 전송
```

### Power Supply

```text
Power Supply UI 버튼
  -> PowerSupplyManager.build_command(action)
  -> SSHManager.execute_command(command)
  -> TerminalWidget에 실행 결과 출력
```

## Threading / 비동기 원칙

- GUI thread에서는 blocking SSH, SFTP, 파일 업로드, 원격 명령 실행을 직접 수행하지 않습니다.
- `ThreadPoolTaskRunner`가 백그라운드 작업의 성공/실패 콜백을 UI thread로 되돌립니다.
- Interactive shell 출력은 짧은 주기의 `QTimer` polling으로 읽습니다.
- SFTP startup timeout timer를 두어 remote prompt가 늦거나 실패한 경우 UI 상태가 무기한 대기하지 않도록 합니다.

## 저장 파일

기본 사용자 데이터 위치는 `%APPDATA%/MMUControl`입니다. `APPDATA`가 없으면 홈 디렉터리 아래 `AppData/Roaming/MMUControl`을 사용합니다. 이 위치는 PyInstaller one-file 실행 파일의 임시 추출 경로와 분리되어 있으므로 재실행 후에도 유지됩니다.

- `settings.json`: SSH, Board/MMU, Power Supply, Window 상태
- `command_sets.json`: 사용자 정의 명령 세트
- `automation_scenarios.json`: 자동화 시나리오
- `mmu_control.log`: rotating log file
- `profiles.json`: 연결 프로필 저장소 확장용 파일

## 패키징

- `pyproject.toml`은 패키지 메타데이터, runtime dependency, dev extra, package data를 정의합니다.
- `scripts/build_exe.ps1`은 PyInstaller를 실행하여 `dist/MMUControl.exe`를 생성합니다.
- `MMUControl.spec`은 package resource인 `power_supply_commands.json`을 포함하도록 구성됩니다. 사용자 데이터는 package resource로 포함하지 않습니다.
