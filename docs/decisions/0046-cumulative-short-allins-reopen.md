# 0046. 불완전 올인 여러 개의 합이 풀 레이즈면 재오픈한다 (TDA Rule 47)

- 상태: 유효
- 날짜: 2026-09-26 · 결정자: 에이전트(T-038 구현, 검증 에이전트 발견 후속) — [0038](0038-action-validation-and-real-amounts.md) 보완

## 맥락
0038은 "불완전 올인으로 액션이 닫힌 사람의 레이즈는 불법"이라고만 정했고, 구현은 "마지막 풀 레이즈
이후 행동했는가"(acted 집합)로 닫힘을 판정했다. 그래서 불완전 올인을 액션 하나씩만 보았다:
벳 100 → 콜 → 150 올인(+50) → 220 올인(+70) 뒤 처음 벳한 사람은 +120(최소 레이즈 100 이상)을
마주하는데도 레이즈할 수 없었다. 표준 규칙(TDA Rule 47)은 이미 행동한 사람이 "마지막 행동 이후
적어도 풀 레이즈를 마주하면" 다시 레이즈할 수 있다고 본다.

## 결정
- 레이즈 권한 = 이번 라운드에서 아직 행동하지 않았거나, `current_bet − (그 사람이 마지막으로 행동한
  직후의 current_bet) ≥ min_raise`. 판정은 core `TexasHoldem.raise_allowed(player, bet_seen)` 한 곳.
- 라운드 종료 판정(acted 집합: 마지막 풀 레이즈 이후 행동한 사람)은 그대로 둔다. 레이즈 권한만
  `bet_seen`으로 판정한다.
- `min_raise`는 여전히 풀 레이즈(증가분 ≥ min_raise)일 때만 그 증가분으로 갱신한다. 불완전 올인은
  `current_bet`만 올린다.
- 플레이 평가·RL 기록 등 액션 적용 전에 금액을 쓰는 곳은 요청값이 아니라 core `bet_target`
  (최소 레이즈 보정·스택 한도 반영한 도달 베팅)을 쓴다.

## 버린 대안
- 액션 단위 판정 유지(불완전 올인은 절대 재오픈 안 함) — 흔한 카지노 규칙과 다르고, 숏스택 올인이
  이어지는 멀티웨이 팟에서 공격 기회를 부당하게 빼앗는다.
- 불완전 올인의 증가분을 누적해 `min_raise`를 갱신 — 다음 레이즈 최소치까지 바뀌어 표준과 다르다.

## 결과
- 영향받는 spec: `docs/spec/game.md`
- 강제 장치: `tests/test_poker_full.py::test_8_25_cumulative_short_allins_reopen`,
  `::test_8_26_cumulative_short_allins_below_full_raise_stay_closed`(세션 경로),
  `::test_2_8_core_cumulative_short_allins_reopen`(core 베팅 루프·CLI 경로),
  `::test_8_27_grade_receives_real_raise_amount`(평가 금액)
