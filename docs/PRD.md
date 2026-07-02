# Device Control Tool - PRD

## Goal
Windows에서 실행되는 Python(PySide6) GUI 애플리케이션으로 Linux Server에 SSH 접속하여 장비 개발 업무를 자동화한다.

## Primary Workflow
Windows -> SSH -> Linux Server -> (minicom / SFTP / Shell) -> Board

## Functional Requirements
1. SSH
- Host/Port/User/Password
- Interactive Shell
- Connect/Disconnect/Reconnect

2. Terminal
- 사용자 입력
- 프로그램 실행 명령
- Linux 출력
- minicom 출력
- SFTP 출력

3. Minicom
- ls /dev/ttyUSB* 자동 검색
- USB Port 선택
- minicom -D /dev/ttyUSBx 실행

4. SFTP
- Linux Server에서 sftp username@[board_ip%interface]
- Board IP, Username, Password, Interface 수정 가능
- Password Prompt 자동 처리

5. Command Sets
- JSON 저장
- 이름/설명/여러 줄 명령
- 생성/수정/삭제

6. Settings
- SSH 정보
- Board 정보
- USB Port
- Window 상태
- Connection Profile

## Non-functional
- GUI Non-blocking
- QThread 사용
- 모듈화
- SOLID 지향
- 로그 저장
