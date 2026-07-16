# Device Control Tool - PRD

## 목표

Windows에서 실행되는 Python(PySide6) GUI 애플리케이션으로 Linux Server에 SSH 접속하고, 그 서버를 통해 MMU/Board 개발 업무를 한 화면에서 수행한다.

## 대상 사용자

- Windows PC에서 장비 개발/검증을 수행하는 엔지니어
- Linux Server를 gateway 또는 작업 서버로 사용하여 Board/MMU에 접근하는 사용자
- Serial console, SSH shell, SFTP, 전원 제어를 반복적으로 수행하는 사용자

## Primary Workflow

```text
Windows PC
  -> MMU Control GUI
  -> SSH to Linux Server
  -> Shell / minicom / SFTP / Power Supply command
  -> Board 또는 MMU
```

## 핵심 가치

- SSH 접속 정보와 Board/MMU 정보를 저장하여 반복 입력을 줄인다.
- Terminal, Serial Console, SFTP, Command Set, Power Supply 작업을 하나의 GUI에서 수행한다.
- 장시간 실행되거나 blocking 되는 네트워크 작업이 GUI를 멈추지 않도록 한다.
- 자주 쓰는 여러 줄 shell 명령을 저장하고 재실행한다.
- Linux Server와 Board/MMU 사이의 파일 전송을 GUI 파일 목록과 drag-and-drop으로 보조한다.

## 기능 요구사항

### 1. Linux Server SSH

- Host, Port, Username, Password를 입력할 수 있어야 한다.
- Connect, Disconnect를 지원해야 한다.
- 연결 성공 후 interactive shell을 열어 Terminal 탭에 출력해야 한다.
- 연결 상태를 status bar에 표시해야 한다.
- 원격 명령 실행, shell channel 생성, 로컬 PC 파일 업로드, USB serial port 검색 기능을 제공해야 한다.

### 2. Terminal

- 사용자가 명령을 입력하고 Linux Server shell로 전송할 수 있어야 한다.
- Linux 출력, minicom 출력, SFTP 출력은 각 목적에 맞는 terminal 영역에 표시되어야 한다.
- `htop`, `top`, `vi`, `vim`, `nano`, `less`, `more`, `tail -f`, `minicom`처럼 즉시 키 입력이 필요한 프로그램은 interactive mode로 동작해야 한다.
- `q`, `Ctrl+C`, Backspace 등 raw key 입력을 원격 shell로 즉시 보낼 수 있어야 한다.
- ANSI/VT escape sequence는 필요한 경우 표시용 텍스트에서 제거할 수 있어야 한다.

### 3. Board/MMU Serial Console

- Linux Server에서 `/dev/ttyUSB*`, `/dev/ttyACM*` 장치를 검색할 수 있어야 한다.
- 검색된 USB port를 선택할 수 있어야 한다.
- 선택된 port로 `minicom -o -c off -D <port>`를 실행할 수 있어야 한다.
- minicom 종료 버튼은 Ctrl-A, X, Enter 시퀀스를 전송해야 한다.
- Serial Console은 Board 콘솔 영역에서 SSH Console과 구분되어야 한다.

### 4. Board/MMU SSH Console

- Board/MMU IP, IP version, username, password, SSH port, SSH key path, IPv6 interface 정보를 입력할 수 있어야 한다.
- Linux Server shell에서 Board/MMU로 SSH 접속하는 command를 구성할 수 있어야 한다.
- Board/MMU SSH Console을 Serial Console과 별도 탭으로 제공해야 한다.

### 5. SFTP

- Linux Server에서 `sftp` CLI를 실행하여 Board/MMU에 접속해야 한다.
- Board/MMU IP, username, password, port, IPv6 interface를 사용할 수 있어야 한다.
- Password prompt와 first connection authenticity prompt를 처리해야 한다.
- SFTP session은 메인 Terminal shell과 독립되어야 한다.
- Server 측 현재 경로와 MMU/Board 측 현재 경로를 표시해야 한다.
- Server 파일 목록과 MMU/Board 파일 목록을 표시하고 directory 이동을 지원해야 한다.
- Upload는 Linux Server 파일을 MMU/Board로 `put`해야 한다.
- Download는 MMU/Board 파일을 Linux Server로 `get`해야 한다.
- 로컬 PC 파일 drag-and-drop 시 먼저 Linux Server 임시 업로드 경로로 전송한 뒤 SFTP로 MMU/Board에 업로드해야 한다.

### 6. Command Sets

- 명령 세트는 이름, 설명, 여러 줄 명령으로 구성되어야 한다.
- 사용자는 명령 세트를 생성, 수정, 삭제할 수 있어야 한다.
- 명령 세트는 JSON 파일에 저장되어 앱 재시작 후에도 유지되어야 한다.
- 선택된 명령 세트의 여러 줄 명령을 순서대로 Terminal shell에 전송할 수 있어야 한다.
- 기존 JSON schema와 하위 호환되어야 한다.

### 7. Settings

- SSH 정보, Board/MMU 정보, Power Supply 정보, 선택된 USB port, window 크기/최대화 상태, connection panel 확장 상태를 저장해야 한다.
- 설정 파일이 없으면 기본값으로 시작해야 한다.
- 설정 파일에 새 필드가 없더라도 기본값을 적용하여 로드해야 한다.
- 설정 저장은 임시 파일 후 replace 방식으로 손상 가능성을 줄여야 한다.

### 8. Connection Profiles

- 연결 프로필은 SSH 정보와 Board/MMU 정보를 이름별로 저장할 수 있는 모델/저장소를 제공해야 한다.
- active profile 이름을 유지할 수 있어야 한다.
- 현재 구현은 기본 설정 저장 중심이며, UI에서의 전체 프로필 관리 기능은 후속 확장 범위로 둔다.

### 9. Power Supply

- Power Supply IP, voltage, current를 입력할 수 있어야 한다.
- ON, OFF, Status, All Status, Set 명령을 실행할 수 있어야 한다.
- 명령 템플릿은 패키지 리소스 JSON으로 관리되어야 한다.
- 필수 입력값이 없거나 action이 정의되지 않은 경우 사용자에게 오류를 알려야 한다.

### 10. Logging / Error Recovery

- 애플리케이션 로그를 사용자 설정 디렉터리에 저장해야 한다.
- 로그 파일은 크기 제한과 backup count를 갖는 rotating file 방식이어야 한다.
- 일시 실패 가능 작업은 retry/backoff helper를 사용할 수 있어야 한다.
- 사용자에게는 status bar와 terminal output을 통해 실패 원인을 알기 쉽게 표시해야 한다.

### 11. Packaging

- `mmu-control` console script로 개발 환경에서 실행할 수 있어야 한다.
- PowerShell build script로 Windows executable을 생성할 수 있어야 한다.
- PyInstaller spec은 앱 실행에 필요한 package resource를 포함해야 한다.

## 비기능 요구사항

- GUI thread에서 SSH 연결, 파일 업로드, 원격 명령 실행 같은 blocking 작업을 수행하지 않는다.
- UI와 business logic을 분리한다.
- JSON 저장 형식은 하위 호환성을 유지한다.
- public API에는 type hint와 docstring을 유지한다.
- 사용자가 선택하거나 입력한 shell 경로/명령 인자는 가능한 경우 quoting/검증한다.
- 테스트 가능한 단위로 모듈을 나누고 pytest 테스트를 유지한다.
