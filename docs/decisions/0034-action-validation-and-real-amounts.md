# 0034. 액션 판정은 core 한 곳 — 사람 불법 액션은 거절, 봇은 안전 폴백, 금액은 실제 칩 이동

- 상태: 유효
- 날짜: 2026-09-26 · 결정자: 에이전트(T-020·T-021 구현, 2026-09-26 리뷰 RC1 후속)

## 맥락
엔진 `apply_action`이 불법 체크에 `False`만 돌려주고 세션이 이를 무시해, 불법 체크가 "체크"로
기록·방송·RL 기록·평가됐다. 이벤트·로그 금액은 엔진 결과가 아니라 세션 입력값(요청 레이즈 금액,
올인 전 콜 금액, 고정 블라인드)으로 조립돼 퍼징에서 1,327건이 실제 칩 이동과 달랐다. 이 로그가
봇 판단·GTO 키·RL 데이터의 입력이다. 재오픈 판정도 세션과 core에 따로 있었다.

## 결정
- 판정은 core `TexasHoldem.normalize_action`(검증·정규화, 무상태) / `execute_action`(적용 후
  `ActionResult`: 실제 액션·이동 칩·도달 베팅·재오픈) 한 곳에서 한다. 웹 세션과 core 베팅 루프가
  같이 쓴다(T-024 단일화의 첫 단계).
- 정규화(불법 아님): 콜할 금액이 없는 CALL → CHECK. 최소 레이즈-투 미만 RAISE → 최소 레이즈-투로
  보정(기존 규칙 유지). 보정 후 스택 이상인 RAISE → ALL_IN.
- 불법: 벳을 마주한 CHECK, 불완전 올인으로 액션이 닫힌 사람의 레이즈(콜 이하 올인은 허용),
  폴드·올인한 사람의 액션.
- 사람의 불법 액션은 상태를 바꾸기 전에 거절한다(`IllegalActionError` → API 400). 기록·이벤트·평가 없음.
- 봇(및 CLI 콜백·아레나의 사람 좌석 드라이버)의 불법 액션은 경고 로그를 남기고 `fallback_action`으로
  대체한다: 막힌 RAISE/ALL_IN → CALL(콜할 금액이 없으면 CHECK), 불법 CHECK → FOLD. 공격 의도는
  가장 가까운 합법 액션으로, 수동 의도는 칩을 더 넣지 않는 쪽으로 옮긴다.
- 로그·이벤트·RL 기록의 금액은 `ActionResult`에서 만든다: 콜 = 이동액, 레이즈/올인 = 도달 베팅
  (`to_amount` = 이전 베팅 + 이동액), 폴드/체크 = 0, 블라인드 = 실제로 낸 칩.

## 버린 대안
- 봇 불법 액션도 예외로 올려 게임을 멈춤 — 봇 버그 하나로 사람 게임이 멈춘다.
- 모든 불법 액션을 "체크 가능하면 체크, 아니면 폴드"로 — 불완전 올인에 막힌 봇의 올인(강한 패)이
  폴드로 바뀌어 판단이 크게 왜곡된다.
- 콜할 금액 없는 CALL을 불법으로 거절 — UI·테스트·아레나가 "call 0"을 체크로 써 와서 이득 없이 깨진다.
- 레이즈 이벤트 금액을 이동액으로 — 프론트 배지와 로그("레이즈 → X")가 도달 베팅 의미로 굳어 있다.

## 결과
- 영향받는 spec: `docs/spec/game.md`
- 강제 장치: `tests/test_poker_full.py::test_8_10_illegal_check_rejected_not_recorded`,
  `::test_8_11_bot_illegal_action_falls_back`, `::test_8_12_session_fuzz_event_amounts_and_conservation`,
  `::test_8_7_incomplete_raise_allin_call_or_fold_only`
