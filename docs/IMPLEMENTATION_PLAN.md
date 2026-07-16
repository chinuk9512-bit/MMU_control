# Implementation Plan

이 문서는 현재 코드 기준의 구현 완료 상태와 향후 확장 계획을 정리한다. 각 작업은 독립적으로 테스트 가능해야 하며, GUI thread blocking을 만들지 않아야 한다.

## Phase 1. Project Skeleton ✅

- `pyproject.toml` 기반 Python 패키지 구성
- `src/mmu_control` package layout 구성
- `mmu-control` entry point 제공
- pytest 설정 및 기본 테스트 경로 구성

## Phase 2. Main UI / Settings ✅

- `MainWindow` 기반 3영역 레이아웃 구현
  - connection panel
  - workspace tabs(Terminal, Commands, SFTP)
  - Board console tabs(Serial Console, SSH Console)
- SSH, Power Supply, Board/MMU 입력 폼 구현
- status bar 구현
- window size, maximize state, panel expanded state 저장/복원
- `%APPDATA%/MMUControl/settings.json` 기반 설정 로드/저장

## Phase 3. SSH / Interactive Shell ✅

- Paramiko 기반 `SSHManager` 구현
- Connect, Disconnect, Reconnect 구현
- interactive shell channel open 구현
- Terminal 탭 명령 입력/출력 구현
- QTimer 기반 shell polling 구현
- `ThreadPoolTaskRunner`로 blocking 연결 작업을 GUI thread 밖에서 실행

## Phase 4. Terminal UX ✅

- `TerminalWidget` 구현
- prompt와 출력이 같은 pane에서 동작하도록 구현
- line editing, paste, clear, stream append 지원
- immediate raw input mode 구현
- full-screen/interactive 프로그램 감지 및 mode 전환
- terminal escape/control sequence filtering 구현

## Phase 5. USB Detection / Minicom ✅

- Linux Server에서 `/dev/ttyUSB*`, `/dev/ttyACM*` 검색
- USB port combo box 갱신
- 선택 port 검증
- `minicom -o -c off -D <port>` 실행
- Ctrl-A, X, Enter 기반 minicom 종료
- Serial Console 탭 상태와 버튼 상태 갱신

## Phase 6. Command Sets ✅

- `CommandSet`, `CommandSetCollection` 모델 구현
- `CommandSetStore` JSON 저장소 구현
- command editor dialog 구현
- 명령 세트 생성/수정/삭제/실행 구현
- 기존 `commands` key를 읽을 수 있는 하위 호환 처리 구현

## Phase 7. SFTP ✅

- Linux Server에서 Board/MMU로 접속하는 SFTP command builder 구현
- IPv4/IPv6, interface, port, username 처리
- password prompt와 authenticity prompt 처리
- 메인 Terminal과 독립된 SFTP shell 사용
- SFTP open/close/upload/download 구현
- Server/MMU file list 표시
- directory double-click navigation 구현
- symlink 표시와 directory link navigation 처리
- 파일 목록 drag-and-drop transfer 구현
- 로컬 PC 파일 drop -> Linux Server upload -> MMU put workflow 구현

## Phase 8. Board/MMU SSH Console ✅

- Board/MMU SSH 접속 command builder 구현
- Board SSH Console 탭 분리
- SSH port, key path, IPv6 interface 입력값 반영
- connect/disconnect 버튼 상태 관리

## Phase 9. Power Supply ✅

- `PowerSupplySettings` 모델 구현
- `PowerSupplyManager` 구현
- `resources/power_supply_commands.json` template 로드
- ON/OFF/Status/All Status/Set 버튼 구현
- PyInstaller package data에 resource 포함

## Phase 10. Logging / Error Recovery ✅

- rotating file logging 설정 구현
- 앱 종료 시 logging handler 정리
- retry/backoff helper 구현
- 주요 실패 상황을 terminal/status UI에 표시

## Phase 11. Packaging ✅

- PowerShell build script 구현
- `MMUControl.spec` 작성
- package resource 포함 검증 테스트 구현
- `dist/MMUControl.exe` 산출물 경로 정의

## Phase 12. Connection Profile UI ⏳

현재 모델과 저장소는 준비되어 있으나, 전체 UI workflow는 후속 작업이다.

- profile 목록 UI 추가
- 현재 입력값을 profile로 저장
- profile 선택 시 SSH/Board/MMU 입력값 반영
- profile 삭제/이름 변경
- `AppSettings.active_profile`과 `ProfileCollection.active_profile` 동기화

## Phase 13. Hardening / UX 개선 ⏳

- 장시간 SFTP 전송 진행 상태 표시
- 원격 명령 timeout/cancel UX 보강
- password/key 저장 보안 정책 검토
- power supply command template 실제 장비별 preset 확장
- Board/MMU SSH Console의 인증 실패 메시지 개선
- 다국어 UI 문구 정리

## 완료 기준

각 작업은 다음 조건을 만족해야 한다.

- 기존 테스트가 통과한다.
- 새 기능은 가능한 단위 테스트를 포함한다.
- public method에는 type hint와 docstring을 유지한다.
- GUI thread에서 blocking 작업을 수행하지 않는다.
- JSON schema 변경 시 기존 파일을 읽을 수 있어야 한다.
- PyInstaller 빌드에 필요한 resource를 누락하지 않는다.
