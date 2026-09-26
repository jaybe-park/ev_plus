# 테스트 체계 — 현재 사양

> 최종 갱신: 2026-09-26 · 관련 결정: [0026](../decisions/0026-stubbot-and-isolated-test-db.md)

## 무엇을 하는가

`tests/run_all.py`가 대표 실행 진입점이다. 여러 테스트 파일을 subprocess로 순차 실행하며
실시간 출력 릴레이 + 통합 요약(파일별 통과/실패, 소요 시간)을 낸다. 하나라도 실패하면
exit code 1.

## 규칙 (지금 유효한 것만)

- `python3 tests/run_all.py` 또는 `--fast`: `run_all.py::FAST_FILES` = `test_poker_full.py` +
  `test_gto_tree.py`(로직 검증만, 수 초 이내). `--full`: `FULL_FILES` = 위에 `test_equity.py` +
  `test_grader.py` 추가. 신규 테스트 파일을 대표 명령에 포함하려면 이 두 상수에 등록해야
  한다 — 원본: `tests/run_all.py`
- `test_poker.py`는 `run_all.py`에 등록돼 있지 않다(독립 레거시 스위트, 개별 실행만).
- 파일 역할: `test_poker_full.py` = 포커 로직(핸드 평가/베팅/팟 분배/게임 흐름/웹 세션/헤즈업·
  사이드팟/프리플랍 GTO 트리 라우팅) · `test_equity.py` = 에퀴티 엔진 + 봇 의사결정 ·
  `test_grader.py` = 플레이 평가(Play Grader) 판정 엔진 · `test_gto_tree.py` = GTO 트리
  수집 워커의 순수 로직 · `test_guards.py` = 테스트 인프라 자체의 가드(poker.db 무결성
  검사 로직, DB 크기 임계치 판정 함수, `canonical_key` 입력 검증) · `test_poker.py` = 기본
  핸드 평가 유닛 테스트(레거시).
  각 파일의 정확한 항목 수·번호는 여기 쓰지 않는다 — 실제 목록은 각 파일의 `def test_*`
  (또는 `check(...)`) 선언을 grep하거나 `run_all.py` 출력의 통합 요약을 본다.
- **StubBot 방침**: `test_poker_full.py`는 모듈 임포트 시점에 `PokerBot.decide_action`을
  "콜 금액 있으면 콜, 없으면 체크"의 스텁으로 전역 패치한다(equity/GTO DB 조회 없음).
  이 파일의 목적은 게임 엔진 정합성이지 봇 실력이 아니다. 특정 액션 시퀀스가 필요한
  테스트는 `StubBot(player, scripted_actions=[...])`로 행동을 직접 주입한다. 봇의 실제
  판단력(equity 정확도, GTO 준수 등)은 `test_equity.py`/`scripts/ai_regression.py`가
  담당한다 — 근거: [0026](../decisions/0026-stubbot-and-isolated-test-db.md) ·
  강제 장치: `tests/test_poker_full.py` 상단의 `PokerBot.decide_action = _stub_decide_action` 패치
- **EV_PLUS_DB 격리**: 로직 테스트는 실 DB(그라인드 데이터)와 락 경합·오염을 피하려고
  `run()` 헬퍼가 테스트 함수 실행 직전마다 `EV_PLUS_DB` 환경변수를 새 임시 SQLite 파일로
  갱신한다. `WebGameSession` 생성마다 `GameRecorder`가 커넥션을 열고 닫지 않기 때문에,
  DB 파일을 공유하면 테스트가 누적될수록 쓰기 락 경합이 심해진다 — 근거:
  [0026](../decisions/0026-stubbot-and-isolated-test-db.md) · 강제 장치:
  `tests/test_poker_full.py`의 모듈 상단 `os.environ["EV_PLUS_DB"] = tempfile...`
- **격리는 파일마다 개별 구현**: `run_all.py`는 각 테스트 파일을 별도 subprocess로 실행하므로
  환경변수는 파일 간에 상속되지 않는다. `db.connection.get_connection()`을 인자 없이
  호출하는 모든 경로(`gto/loader.py`, `gto/advisor.py` 등)가 대상이라, 파일마다 모듈
  임포트 시점에 `os.environ["EV_PLUS_DB"] = tempfile...`를 직접 설정해야 한다 —
  `test_poker_full.py`, `test_equity.py`, `test_grader.py`, `test_gto_tree.py`,
  `test_guards.py` 모두 이 패턴을 쓴다. `ai/equity.py`의 `_db()`는 `DB_PATH`가 `None`이면
  `_DEFAULT_DB_PATH`를 직접 넘기지 않고 `get_connection(None)`으로 위임해 이 환경변수
  규칙을 그대로 따른다(과거엔 `_DEFAULT_DB_PATH`를 직접 넘겨 환경변수를 우회했다) —
  강제 장치: `tests/test_equity.py`(전체, DB_PATH 미지정 경로도 실 DB를 타지 않음을 보장)
- **운영 poker.db 무결성 가드**: `tests/run_all.py`가 실행 전후 운영 `poker.db`의
  `(mtime, size)`를 비교해(`poker_db_snapshot`/`poker_db_untouched`) 값이 바뀌면(격리
  누락으로 실제 DB에 썼다는 뜻) 전체를 실패로 처리한다 — 강제 장치: `tests/run_all.py`
  자체 로직(exit code 1) · 함수 단위 테스트: `tests/test_guards.py::test_run_all_db_snapshot_guard`
- **시간 버짓**: `test_poker_full.py`는 총 실행 시간이 `TIME_BUDGET_SEC`(30초)를 넘으면
  테스트를 실패시키지 않고 "⚠️ 시간 버짓 초과" 경고만 낸다(성능 회귀 조기 감지용,
  StubBot 적용 후 정상 실행은 1초 미만) — 강제 장치: 경고만(실패로 격상하지 않음),
  `tests/test_poker_full.py::TIME_BUDGET_SEC`
- **영역 번호 규약**: `test_poker_full.py`는 함수명을 `test_<영역>_<순번>_<설명>` 형식으로
  붙인다(예: `test_6_9_headsup_gto_btnSB_mapped_to_sb_rfi`). 영역 번호는 핸드 평가(1)·
  베팅 라운드(2)·팟 분배(3)·게임 흐름(4)·웹 세션(5)·헤즈업/사이드팟/프리플랍 GTO 트리(6)·
  GTO 저장·조회 가드(7) 순으로 굳어져 있다. **새 원칙 테스트는 해당 영역 번호 안에
  다음 순번으로 추가**한다(예: 게임 흐름 원칙이면 4번대, GTO 조회 가드면 7번대). 새
  영역이 필요하면 다음 정수를 새로 할당하고 이 문단을 갱신한다.

## 알려진 한계

- 이벤트 순서(`docs/spec/game.md`의 웹 게임 흐름 불변식)와 런아웃 자동 체크에는 전용
  테스트가 없다 — 코드 동작으로만 보장된다.
- `test_poker.py`는 `run_all.py`에 포함되지 않아 커밋 전 루틴 실행에서 빠질 수 있다.
