# 0047. 포커 룰은 core 한 곳에 — 웹 세션·CLI는 호출만, 세션 경로는 참조 모델 퍼저로 지킨다

- 상태: 유효
- 날짜: 2026-09-27 · 결정자: 에이전트(T-024 구현, 2026-09-26 리뷰 RC1 후속) — [0038](0038-action-validation-and-real-amounts.md)의 "단일화 첫 단계" 완결

## 맥락
웹 세션(`server/session.py`)이 베팅 루프·스트리트 전환·사이드팟 분배·버튼 기억을 core와 따로
구현했고 테스트는 주로 core 헬퍼를 봤다. 그래서 헤즈업 순서(T-019), 재오픈(T-020), 금액(T-021),
버튼(T-022), 런아웃(T-023) 버그가 실제 사용 경로에서만 났다. 반대로 CLI(`cli/main.py`)가 쓰는 core
`showdown()`은 사이드팟을 몰라 100 올인한 사람이 1100을 가져갔고, 버튼도 옛 인덱스 방식이었다.

## 결정
- 룰은 `core/game.py::TexasHoldem`에만 둔다: 좌석 정리·무빙 버튼(`seat_for_next_hand`, 버튼 이름
  `button_name`), 핸드 시작(`start_hand` — 프리플랍 라운드 준비까지), 라운드 상태(`order`/`acted`/
  `bet_seen`/`turn_i`)와 `next_to_act`·`round_over`·`can_raise`, 판정(`validate`/
  `validate_or_fallback`), 적용(`act`), 스트리트 전환(`advance_street`), 사이드팟 분배(`showdown` →
  `ShowdownResult`).
- 웹 세션은 요청 단위로 이 메서드들을 부르고 결과를 이벤트·로그·RL 기록·평가로 옮기기만 한다.
  CLI는 콜백 방식 `play_round()`로 같은 경로를 쓴다.
- 세션 경로는 테스트 쪽에 룰을 따로 적은 참조 모델(`_RefTable`)과 대조하는 시드 고정 퍼저로 지킨다
  (core 룰을 잘못 고치면 참조 모델과 어긋나 실패). 퍼저가 옛 버그를 잡는지는 버그를 되살려 확인한다.

## 버린 대안
- 세션 쪽 구현을 남기고 core와 결과만 비교하는 테스트 추가 — 룰이 두 곳에 남아 고칠 때마다 둘 다
  고쳐야 한다.
- CLI 폐기 — 쓰는 사람은 적지만 core 콜백 경로(아레나 드라이버·테스트)가 같이 검증되는 이점이 있다.

## 결과
- 영향받는 spec: `docs/spec/game.md`, `docs/spec/testing.md`
- 강제 장치: `tests/test_poker_full.py::test_4_10_cli_and_web_session_same_behavior`,
  `::test_4_9_cli_sidepot_and_moving_button`, `::test_8_12_session_fuzz_event_amounts_and_conservation`,
  `::test_8_28_fuzzer_catches_reverted_cumulative_reopen`
