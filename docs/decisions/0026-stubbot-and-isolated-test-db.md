# 0026. 로직 테스트는 StubBot + 테스트별 임시 DB로 격리

- 상태: 유효
- 날짜: 2026-07-08 · 결정자: jaybe-park

## 맥락
`test_poker_full.py`가 실제 `PokerBot`(equity 계산 + GTO DB 조회)과 공유 SQLite DB를
그대로 쓰자 테스트가 30초 넘게 걸렸다. 원인은 두 가지: (1) 매 봇 결정마다 실제 AI
판단(비결정적이고 느림)이 들어감, (2) `WebGameSession`마다 `GameRecorder`가 커넥션을
열고 닫지 않아, 테스트가 DB 파일 하나를 공유하면 쓰기 락 경합이 누적돼 결국
busy_timeout(30초)까지 블로킹됨.

## 결정
`test_poker_full.py`는 모듈 임포트 시점에 `PokerBot.decide_action`을 "콜 금액 있으면
콜, 없으면 체크"의 스텁으로 전역 패치한다 — 이 파일은 게임 **로직**(핸드 평가/베팅/팟
분배/흐름)만 검증하고 봇 실력은 검증하지 않는다. 특정 시퀀스가 필요하면
`StubBot(player, scripted_actions=[...])`로 행동을 주입한다. 또한 `run()` 헬퍼가 테스트
함수 실행 직전마다 `EV_PLUS_DB` 환경변수를 새 임시 파일로 갱신해 테스트끼리 DB 커넥션이
충돌하지 않게 한다. 총 실행 시간이 `TIME_BUDGET_SEC`(30초)를 넘으면 실패시키지 않고
경고만 낸다(성능 회귀 조기 감지). 실제 AI 판단력 검증은 `test_equity.py`/
`scripts/ai_regression.py`가 별도로 담당한다.

## 버린 대안
- 실제 `PokerBot`으로 로직 테스트 — 느리고 비결정적이라 게임 흐름 검증에 부적합하다.
- 시간 버짓 초과 시 테스트 실패 처리 — 로직 자체는 맞으므로 경고로 충분하다고 판단.

## 결과
- 영향받는 spec: `docs/spec/testing.md`
- 강제 장치: `tests/test_poker_full.py`의 `PokerBot.decide_action = _stub_decide_action`
  전역 패치, 모듈 상단 `EV_PLUS_DB` 임시 파일 지정, `TIME_BUDGET_SEC`(경고만, 실패 아님)
