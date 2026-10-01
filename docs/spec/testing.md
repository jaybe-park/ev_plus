# 테스트 체계 — 현재 사양

> 최종 갱신: 2026-10-01 · 관련 결정: [0026](../decisions/0026-stubbot-and-isolated-test-db.md), [0001](../decisions/0001-adopt-playbook.md)

## 무엇을 하는가

`tests/run_all.py`가 대표 실행 진입점이다. 여러 테스트 파일을 subprocess로 순차 실행하며
실시간 출력 릴레이 + 통합 요약(파일별 통과/실패, 소요 시간)을 낸다. 하나라도 실패하면
exit code 1.

## 규칙 (지금 유효한 것만)

- `python3 tests/run_all.py`(= `--fast`)는 `FAST_FILES`, `--full`은 `FULL_FILES`를 돈다. 어떤
  파일이 어디에 들어가는지는 원본 `tests/run_all.py`의 두 상수가 정한다. 새 테스트 파일은
  두 상수에 등록해야 대표 명령에 포함된다 — 원본: `tests/run_all.py`
- 실행 시간(2026-10-01, 로컬 맥): `--fast` 약 6초(`test_poker_full.py` 약 5초), `--full` 약 30~37초
  (파이썬 약 30초 — `test_equity.py`·`test_equity_verify.py`가 각 5~9초 — + 프론트 게이트 약 5~7초)
- **`--full`은 파이썬 스위트 뒤에 프론트 품질 게이트도 돈다**: `tests/run_all.py::WEB_STEPS` —
  `npm run build`(tsc -b + vite build) → `npm run lint`(eslint .) → `npm run test`(vitest run,
  `web/src/**/__tests__/*.test.ts`), `web/` 디렉터리에서 순차 실행하고 실패하면 통합 요약에
  ❌로 반영되어 전체 exit code 1이 된다. `npm`이 PATH에 없으면 세 단계를 건너뛰고 경고 한
  줄만 낸다(파이썬 테스트만은 항상 돈다). `web/node_modules`가 없으면(새 워크트리 등) 세 단계가
  실패한다. `--fast`는 프론트 게이트를 돌지 않는다 · 강제 장치: `tests/run_all.py::WEB_STEPS`,
  `web/package.json`의 `build`/`lint`/`test` 스크립트
- 파일 역할: `test_poker_full.py` = 포커 로직(핸드 평가/베팅/팟 분배/게임 흐름/웹 세션/헤즈업·
  사이드팟/프리플랍 GTO 조회·저장/세션 경로 룰) · `test_equity.py` = 에퀴티 엔진 + 봇 의사결정 ·
  `test_grader.py` = 플레이 평가(Play Grader) 판정 엔진 · `test_gto_tree.py` = GTO 트리
  수집기·감사·재시드·큐 정리 스크립트의 순수 로직(브라우저·네트워크 없음) · `test_guards.py` =
  테스트 인프라 가드(운영 DB 스냅샷 비교, DB 크기 임계치, `equity_detail` 중복 카드 입력 검증) ·
  `test_workflow.py` = Claude Code hook(`.claude/hooks/block_dangerous.py`)의 차단 패턴·동시
  실행 금지·등록 여부(1초 이내).
  각 파일의 정확한 항목 수·번호는 여기 쓰지 않는다 — 실제 목록은 각 파일의 `ALL_TESTS`/`def test_*`
  선언을 보거나 `run_all.py` 출력의 통합 요약을 본다.
- **StubBot 방침**: `test_poker_full.py`는 모듈 임포트 시점에 `PokerBot.decide_action`을
  "콜 금액 있으면 콜, 없으면 체크"의 스텁으로 전역 패치한다(equity/GTO DB 조회 없음).
  이 파일의 목적은 게임 엔진 정합성이지 봇 실력이 아니다. 특정 액션 시퀀스가 필요한
  테스트는 `StubBot(player, scripted_actions=[...])`로 행동을 직접 주입한다. 봇의 실제
  판단력(equity 정확도, GTO 준수 등)은 `test_equity.py`/`scripts/ai_regression.py`가
  담당한다 — 근거: [0026](../decisions/0026-stubbot-and-isolated-test-db.md) ·
  강제 장치: `tests/test_poker_full.py` 상단의 `PokerBot.decide_action = _stub_decide_action` 패치
- **EV_PLUS_DB 격리**: 테스트는 공유 `poker.db`를 열지 않는다. `db.connection.get_connection()`을
  인자 없이 부르는 모든 경로(`gto/loader.py`, `gto/advisor.py`, 세션 기록기 등)가 `EV_PLUS_DB`를
  따르므로, DB를 여는 테스트 파일은 모듈 임포트 시점에 `os.environ["EV_PLUS_DB"] = tempfile...`를
  설정한다(`test_workflow.py`는 DB를 열지 않아 설정하지 않는다)(`run_all.py`는 파일마다 별도 subprocess라 환경변수가 파일 간에 이어지지 않는다).
  `test_poker_full.py`의 `run()` 헬퍼는 테스트 함수마다 새 임시 DB로 바꿔, 한 테스트가 시딩한
  GTO 노드·미수집 큐 행·핸드 기록이 다음 테스트로 새지 않게 한다. GTO 로더 캐시는 프로세스
  안에 남으므로 GTO 데이터를 쓰는 테스트는 `_seed_situation`(시딩 후 `loader.invalidate()`)이나
  `_fresh_gto_db()`(새 DB + 캐시 비움)로 시작한다. 에퀴티 계산(`ai/equity.py`)은 DB를 전혀
  열지 않는다 — 근거: [0026](../decisions/0026-stubbot-and-isolated-test-db.md) · 강제 장치:
  각 파일 상단의 `EV_PLUS_DB` 설정, `tests/test_equity.py::test_no_db_writes`
- **운영 poker.db 무결성 가드**: `tests/run_all.py`가 실행 전후 그 체크아웃의 `poker.db`
  (`db.connection._DEFAULT_DB_PATH`)의 `(mtime, size)`를 비교해 값이 바뀌면(격리 누락으로 실제
  DB에 썼다는 뜻) 전체를 실패로 처리한다 — 강제 장치: `tests/run_all.py` 자체 로직(exit code 1) ·
  함수 단위 테스트: `tests/test_guards.py::test_run_all_db_snapshot_guard`
- **시간 버짓**: `test_poker_full.py`는 총 실행 시간이 `TIME_BUDGET_SEC`(30초)를 넘으면
  테스트를 실패시키지 않고 "⚠️ 시간 버짓 초과" 경고만 낸다(성능 회귀 조기 감지용) —
  강제 장치: 경고만, `tests/test_poker_full.py::TIME_BUDGET_SEC`
- **영역 번호 규약**: `test_poker_full.py`는 함수명을 `test_<영역>_<순번>_<설명>` 형식으로
  붙인다(예: `test_6_9_headsup_gto_btnSB_mapped_to_sb_rfi`). 영역 번호는 핸드 평가(1)·
  베팅 라운드(2)·팟 분배(3)·게임 흐름(4)·웹 세션(5)·헤즈업/사이드팟/프리플랍 GTO 트리(6)·
  GTO 저장·조회 가드(7)·세션 경로 룰(8) 순으로 굳어져 있다. 영역 8은 게임 룰을
  core 헬퍼가 아니라 `WebGameSession` 공개 API(`submit_action`/`next_hand`/`get_state`의
  `events`)로 검사한다 — 스택·딜러·봇 스크립트를 정한 새 핸드는 `_scripted_session()` 헬퍼로
  만든다. **새 원칙 테스트는 해당 영역 번호 안에 다음 순번으로 추가**하고 파일 끝 `ALL_TESTS`에
  등록한다(등록하지 않으면 돌지 않는다). 새 영역이 필요하면 다음 정수를 새로 할당하고 이 문단을 갱신한다.

## 알려진 한계

- `test_poker_full.py`·`test_gto_tree.py`·`test_workflow.py`·`test_equity.py`·`test_grader.py`·
  `test_equity_verify.py`·`test_guards.py`는 테스트를 함수 목록(`ALL_TESTS` 또는 `__main__` 호출)으로
  직접 돌린다 — 함수를 정의하고 목록에 넣지 않으면 돌지 않는다 · 강제 장치:
  `tests/test_guards.py::test_all_tests_registered`(AST로 모듈 최상위 `def test_*`가 실행 목록에서
  참조되는지 검사, 빠진 함수 이름을 들어 실패)
- 수집기의 브라우저 쪽(DOM 읽기·렌더 대기)과 `tools/gto_extract_and_save.js`에는 테스트가 없다.
