# 0007. advisor 입력은 구조화 프리플랍 시퀀스(한글 로그 파싱 금지)

- 상태: 유효 (결과 절의 "bot.py 미전환"은 2026-10-01 T-046으로 해소됨)
- 날짜: 2026-07-15 · 결정자: jaybe-park

## 맥락
advisor가 UI 표시용 한글 `action_log`를 문자열 부분매칭으로 재파싱하고 있었다. 이 방식으로는 콜인지 레이즈인지, 액션 순서, 실제 참여 인원을 구조적으로 판별할 수 없었다. 한편 기존 `event_log`는 확장돼 있었지만 아무도 소비하지 않는 상태였다.

## 결정
`core/game.py`의 action 이벤트에 position/street/to_amount를 추가하고, `preflop_action_seq()`가 `[{position, action, amount_bb}]` 형태의 구조화 시퀀스를 반환하게 한다. `_get_game_state()`는 이를 `preflop_seq`로 노출한다. 블라인드는 시퀀스에서 제외한다(GTO Wizard 표기와 동일하게 맞추기 위해). 레이즈 횟수 집계는 기존 quirk를 그대로 유지해 allin은 raise 횟수에서 제외한다(한글 파서가 "레이즈"라는 문구만 세던 동작을 보존).

## 버린 대안
- 한글 파서 유지·보강 — 구조적으로 판별 불가능한 문제라 근본 해결이 안 된다.
- 별도 이벤트 체계 신설 — 기존 `event_log` 확장이 하위 호환이라 그쪽을 택했다.

## 결과
- 영향받는 spec: `docs/spec/gto-preflop.md`, `docs/spec/game.md`
- 강제 장치: `tests/test_poker_full.py::test_6_10_squeeze_seq_includes_call`, `tests/test_poker_full.py::test_6_11_headsup_seq_labels_btnSB`, `tests/test_poker_full.py::test_6_12_vs_open_routing_via_seq`
- `ai/bot.py`(opponent_range_info, `_count_raises`)는 이 결정 이후에도 여전히 한글 로그를 파싱하고 있어 구조화 시퀀스로 아직 전환되지 않았다 — DECISIONS.md 참고.
