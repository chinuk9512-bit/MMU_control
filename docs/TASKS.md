# Codex Workflow

이 문서는 이 저장소에서 Codex/agent가 작업할 때 따라야 할 절차를 정의한다.

## 작업 시작 전

1. `docs/PRD.md`를 읽고 사용자 요구사항을 확인한다.
2. `docs/ARCHITECTURE.md`를 읽고 현재 모듈 구조와 데이터 흐름을 확인한다.
3. `docs/IMPLEMENTATION_PLAN.md`를 읽고 완료된 기능과 남은 작업을 구분한다.
4. `docs/CODING_RULES.md`를 읽고 코드/문서 작성 규칙을 확인한다.
5. 관련 테스트 파일을 먼저 확인한다.

## 구현 원칙

- 한 번에 하나의 명확한 목적만 변경한다.
- GUI thread blocking을 만들지 않는다.
- UI 변경과 core logic 변경을 가능한 한 분리한다.
- JSON schema를 변경할 때는 기존 파일을 읽을 수 있게 한다.
- public API에는 type hint와 docstring을 유지한다.
- SSH, SFTP, minicom, power supply command는 실제 장비 없이 테스트 가능한 부분을 우선 단위 테스트한다.

## 권장 작업 순서

1. 요구사항과 현재 구현 차이를 정리한다.
2. 영향을 받는 source/test/docs 파일을 식별한다.
3. 테스트를 추가하거나 기존 테스트 기대값을 갱신한다.
4. 코드를 수정한다.
5. 문서를 필요한 범위만 갱신한다.
6. `python -m pytest`를 실행한다.
7. 변경 파일과 테스트 결과를 보고한다.

## 완료 보고 형식

완료 보고에는 다음을 포함한다.

- 변경 요약
- 변경된 주요 파일
- 실행한 테스트/검증 명령과 결과
- 남은 제한 사항 또는 후속 작업

## 현재 우선순위 후보

- Connection Profile 전체 UI workflow 구현
- SFTP 전송 진행 상태와 취소 UX 개선
- password/key 저장 방식 보안 검토
- 실제 Power Supply 장비별 command template 확장
- Board/MMU SSH Console 인증 실패/timeout 메시지 개선
