# Coding Rules

## 기본 원칙

- Python 3.12 이상을 기준으로 작성한다.
- type hint를 유지한다.
- public class/function/method에는 docstring을 작성한다.
- UI 코드와 business logic을 분리한다.
- GUI thread에서 SSH, SFTP, 파일 I/O, 장시간 명령 실행 같은 blocking 작업을 직접 수행하지 않는다.
- import 주변에 `try/except`를 두지 않는다.
- 하나의 변경은 가능한 한 하나의 목적에 집중한다.

## UI 규칙

- PySide6 위젯 생성과 layout 구성은 `MainWindow` 또는 전용 dialog/widget에 둔다.
- UI callback은 입력 검증, 상태 갱신, service 호출 조율에 집중한다.
- blocking 작업은 `TaskRunner`/`ThreadPoolTaskRunner`를 통해 실행한다.
- 백그라운드 작업 완료 후 UI 변경은 Qt signal/callback 경로로 수행한다.
- Terminal 출력은 사용자가 어떤 remote context에서 발생한 출력인지 알 수 있도록 적절한 terminal pane에 기록한다.
- SFTP shell과 main terminal shell의 상태를 섞지 않는다.

## Core 규칙

- `core/` 모듈은 가능한 한 PySide6 UI 위젯에 의존하지 않는다.
- shell 명령 인자에는 `shlex.quote` 등 적절한 quoting을 사용한다.
- device path처럼 허용 형식이 명확한 값은 regex나 명시적 검증을 적용한다.
- Paramiko client/channel lifecycle은 명확히 close/disconnect 경로를 제공한다.
- 사용자에게 보여줄 수 있는 예외 메시지는 구체적이고 action-oriented하게 작성한다.

## Model / Storage 규칙

- JSON 직렬화 모델은 `from_dict`와 `to_dict`를 제공한다.
- 새 필드를 추가할 때 `from_dict`는 누락 필드에 기본값을 적용해야 한다.
- 저장 파일 schema는 하위 호환성을 유지한다.
- 설정/명령 세트 저장은 가능하면 temporary file 작성 후 replace하는 방식으로 손상 위험을 줄인다.
- user data 기본 위치는 `%APPDATA%/MMUControl` 정책을 따른다.

## Terminal / Shell 규칙

- line command는 newline을 붙여 전송한다.
- interactive program에서는 raw key input을 즉시 전송한다.
- Ctrl+C, `q`, Backspace 등 특수 입력은 현재 interactive mode와 remote program 종류를 고려한다.
- ANSI/VT sequence 처리는 chunk 경계를 고려하여 stateful parser를 사용한다.

## SFTP 규칙

- SFTP는 Linux Server에서 실행되는 CLI session으로 간주한다.
- SFTP shell은 main Terminal shell과 독립적으로 생성/종료한다.
- Board/MMU 경로는 POSIX path로 처리한다.
- Windows local path와 Linux Server path를 혼동하지 않도록 UI 문구와 문서에서 명확히 구분한다.
- 로컬 PC 파일 drag-and-drop은 먼저 Linux Server로 업로드한 뒤 SFTP `put`으로 Board/MMU에 전달한다.

## 테스트 규칙

- manager/model/storage 로직은 pytest 단위 테스트로 검증한다.
- UI 로직은 가능한 fake manager/runner를 사용해 네트워크 없이 검증한다.
- PyInstaller spec과 package data 변경 시 관련 테스트를 갱신한다.
- 버그 수정 시 회귀 테스트를 우선 추가한다.

## 문서 규칙

- PRD는 사용자 가치와 요구사항 중심으로 작성한다.
- Architecture는 실제 코드 구조와 런타임 흐름 중심으로 작성한다.
- Implementation Plan은 구현 상태와 남은 작업을 구분한다.
- Requirements는 설치/실행/빌드에 필요한 dependency와 입력 파일을 명확히 작성한다.
- TASKS는 Codex/agent가 작업할 때 따라야 하는 절차를 담는다.
