# 포커 룰 엔진 — 현재 사양

> 최종 갱신: 2026-10-01 · 관련 결정: [0024](../decisions/0024-hj-position-naming.md), [0036](../decisions/0036-moving-button.md), [0038](../decisions/0038-action-validation-and-real-amounts.md), [0047](../decisions/0047-rules-live-in-core.md), [0048](../decisions/0048-cumulative-short-allins-reopen.md)
> 웹 세션·API·화면 규칙은 [web-flow.md](web-flow.md), 봇은 [bot.md](bot.md).

## 무엇을 하는가

`core/`가 6-max(최대) 캐시게임 텍사스 홀덤 엔진을 순수 로직으로 구현한다(외부 의존 없음).
룰(좌석·버튼, 블라인드, 행동 순서, 액션 판정, 라운드 진행, 스트리트 전환, 사이드팟 분배)은
전부 `core/game.py::TexasHoldem` 한 곳에 있고, 웹 세션·CLI(`cli/main.py`)·아레나·테스트는 같은
메서드를 호출만 한다: `seat_for_next_hand()` → `start_hand()` → [`next_to_act()` →
`validate()`/`validate_or_fallback()` → `act()`]* → `advance_street()` → … → `showdown()`
(콜백 방식 CLI는 `play_round()`가 괄호 부분을 돈다) — 근거:
[0047](../decisions/0047-rules-live-in-core.md) · 강제 장치:
`tests/test_poker_full.py::test_4_10_cli_and_web_session_same_behavior`(같은 카드·결정이면 CLI와
웹 세션이 핸드마다 같은 액션·칩), `::test_8_12_session_fuzz_event_amounts_and_conservation`
## 규칙 (지금 유효한 것만)

- 좌석 수 2~7인 지원. 포지션 라벨(딜러 기준 상대 위치)은 `core/game.py::get_positions()`가
  좌석 수별 고정 배열로 정한다 — 근거: [0024](../decisions/0024-hj-position-naming.md)
  · 강제 장치: 장치 없음(배열 전체를 검사하는 테스트는 없음. 헤즈업 라벨은
    `tests/test_poker_full.py::test_2_6_headsup_btn_acts_first_preflop`가 확인)
- 행동 순서는 core `TexasHoldem._betting_order`, 다음 차례는 `next_to_act()`가 정한다(웹 세션
  `_next_to_act`는 위임만). 라운드는 acted(마지막 풀 레이즈 이후 행동한 사람) 빈 집합으로
  시작한다 — 블라인드 포스팅은 행동이 아니다.
- 헤즈업(2인)은 딜러가 `BTN/SB` 겸임, 상대가 `BB`다. 프리플랍은 `BTN/SB`가 선행동하고
  BTN/SB가 림프하면 BB가 체크/레이즈 옵션을 받는다. 포스트플랍은 `BB`가 선행동한다
  (6인 이상과 반대). BTN/SB 첫 결정 시점의 프리플랍 시퀀스는 비어 있어 GTO 힌트가 SB RFI
  노드로 조회된다 — 강제 장치(세션 경로): `tests/test_poker_full.py::test_8_3_headsup_btnsb_first_and_bb_option`,
  `::test_8_4_headsup_human_btnsb_acts_first`, `::test_8_5_headsup_btnsb_first_decision_has_gto_hint`
  · core 헬퍼: `::test_6_1_headsup_blind_posting`, `::test_6_2_headsup_preflop_btnSB_acts_first`,
  `::test_6_3_headsup_postflop_bb_acts_first`
- 3인 이상 프리플랍 행동 순서는 UTG부터(딜러+3)이고, 아무도 레이즈하지 않으면 SB는 콜(완성)/
  레이즈/폴드, BB는 옵션(체크/레이즈)을 갖는다. 포스트플랍은 SB(딜러+1)부터 — 강제 장치:
  `tests/test_poker_full.py::test_8_12_session_fuzz_event_amounts_and_conservation`(세션 경로
  퍼저가 참조 모델로 매 액션의 차례를 대조, 2~6인), core 헬퍼 `::test_2_5_preflop_betting_order_3players`,
  `::test_2_7_postflop_sb_acts_first`
- 재오픈(TDA Rule 47): 레이즈 증가분(새 `current_bet` − 이전 `current_bet`)이 `min_raise`
  이상인 풀 레이즈(올인 포함)는 `min_raise`를 그 증가분으로 갱신하고 이미 행동한 사람 전원에게
  다시 기회를 준다. 증가분이 `min_raise` 미만인 올인(불완전 레이즈)은 `current_bet`만 올린다.
  레이즈 권한은 core `TexasHoldem.raise_allowed(player, bet_seen)` 한 곳에서 정한다: 이번
  라운드에서 아직 행동하지 않았거나, 마지막으로 행동한 직후의 `current_bet`에서 지금까지 오른
  금액의 합계가 `min_raise` 이상이면 레이즈할 수 있고, 아니면 콜/폴드만 할 수 있다(응답
  `can_raise=false`, `min_raise_to=0`). 그래서 불완전 올인 여러 개의 합이 풀 레이즈 이상이면
  재오픈된다(벳 100 → 콜 → 150 올인 → 220 올인이면 처음 벳한 사람은 +120을 마주해 레이즈 가능,
  190 올인이면 +90이라 콜/폴드만). 콜도 못 채우는 올인은 `current_bet`을 바꾸지 않는다.
  블라인드 포스팅은 행동이 아니다(SB도 자기 차례에 레이즈 가능) — 근거:
  [0048](../decisions/0048-cumulative-short-allins-reopen.md) · 강제 장치(세션 경로):
  `tests/test_poker_full.py::test_8_6_short_allin_under_call_does_not_reopen`,
  `::test_8_7_incomplete_raise_allin_call_or_fold_only`, `::test_8_8_full_allin_updates_min_raise`,
  `::test_8_25_cumulative_short_allins_reopen`, `::test_8_26_cumulative_short_allins_below_full_raise_stay_closed`
  · core 베팅 루프(CLI 경로): `::test_2_8_core_cumulative_short_allins_reopen`, `::test_2_3_raise_reopens_action`
- 콜할 상대가 없으면 레이즈할 수 없다: 나 외에 행동 가능한(폴드·올인 아닌) 플레이어가 없으면
  `raise_allowed`가 거짓이라 레이즈·올인-레이즈는 불법이고 콜·폴드만 된다(응답 `can_raise=false`,
  봇 요청은 콜로 대체). 예: 3인 BTN 폴드 · SB 올인 30 → BB는 콜 30 또는 폴드 — 강제 장치:
  `tests/test_poker_full.py::test_8_29_no_raise_when_no_opponent_can_act`,
  `::test_8_12_session_fuzz_event_amounts_and_conservation`(참조 모델 `may_raise`가 같은 규칙)
- 블라인드: 숏스택 BB가 BB보다 적게 내도 프리플랍 `current_bet`은 BB 전액이라 다른 사람의 콜
  금액은 BB 기준이다(표준 관행) — 강제 장치: `tests/test_poker_full.py::test_8_12_session_fuzz_event_amounts_and_conservation`
  (참조 모델이 블라인드 뒤 `level = BB`로 대조)
- 포스트플랍 최소 벳 = BB: 스트리트가 바뀌면 `current_bet = 0`, `min_raise = BB`로 다시 시작하므로
  첫 벳의 최소 도달 베팅은 BB다 — 강제 장치: `tests/test_poker_full.py::test_4_4_street_bet_reset`
- 오픈 폴드(콜할 금액이 없는데 폴드)는 룰상 합법이라 core가 받는다. 사람 화면은 체크할 수 있으면
  폴드 버튼을 잠그고(`ActionBar`, CLI는 `[f]`를 보이지 않음), 봇은 쓰지 않는다(봇 쪽은
  [`bot.md`](bot.md)) — 강제 장치: 장치 없음(화면 렌더링 테스트 없음)
- 최소 레이즈: 요청 금액이 `현재 베팅 + min_raise` 미만이면 그 값으로 자동 보정한다.
  보정 후 금액이 스택(`chips + current_bet`) 이상이면 올인으로 적용한다 — 스택보다 큰 레이즈
  요청이 실제로 걸리지 않은 `current_bet`을 만들지 않는다 — 강제 장치:
  `tests/test_poker_full.py::test_8_9_raise_over_stack_becomes_allin`(세션 경로),
  `::test_4_6_minimum_raise_rule`, `::test_5_5_raise_amount_enforced`(core)
- 액션 판정은 core `TexasHoldem.validate`(→ `normalize_action`)/`act`(→ `execute_action`) 한 곳에서 하고
  (`ActionResult`: 실제 액션·이동 칩·도달 베팅·재오픈 여부), 웹 세션과 core 베팅 루프가 같이 쓴다
  — 근거: [0038](../decisions/0038-action-validation-and-real-amounts.md)
- 액션 유효성: 벳을 마주한 체크, 액션이 닫힌 사람의 레이즈, 폴드·올인한 사람의 액션은 불법이다.
  콜할 금액이 없는 콜은 체크로 적용된다. 사람의 불법 액션은 상태를 바꾸기 전에 거절되고
  (API 400) 로그·이벤트·RL 기록·플레이 평가에 남지 않는다. 봇의 불법 액션은 경고 로그
  (`server.session` 로거)를 남기고 안전한 액션으로 대체된다: 막힌 레이즈/올인 → 콜(콜할 금액
  없으면 체크), 불법 체크 → 폴드 — 강제 장치: `tests/test_poker_full.py::test_8_10_illegal_check_rejected_not_recorded`,
  `::test_8_11_bot_illegal_action_falls_back`
- 금액 불변식: 로그·`action`/`blind` 이벤트·RL 기록의 금액은 실제 칩 이동에서 만든다 —
  콜 = 이동액, 레이즈/올인 = 도달 베팅(이전 베팅 + 이동액, 로그 "레이즈 → X"/"올인! (X)"),
  폴드/체크 = 0, 블라인드 = 실제로 낸 칩(숏스택이면 블라인드보다 적음). 액션 적용 전에 금액을
  쓰는 플레이 평가(`_grade_human_action`)도 요청값이 아니라 core `bet_target`(최소 레이즈
  보정·스택 한도 반영한 도달 베팅)을 받는다 — 강제 장치:
  `tests/test_poker_full.py::test_8_12_session_fuzz_event_amounts_and_conservation`
  (시드 고정 세션 퍼저 400핸드, 아래 '세션 퍼저' 참고),
  `::test_8_27_grade_receives_real_raise_amount`
- 세션 퍼저: `test_8_12`가 시드 고정(액션·덱 셔플)으로 2~6인·무작위 스택(절반은 1bb 미만씩
  올라가는 숏스택 사다리)·불법 포함 무작위 액션 400핸드를 돌리며, 테스트 쪽에 따로 적은 참조
  모델(`_RefTable`)과 매 이벤트를 대조한다: 행동 순서(헤즈업·BB 옵션·런아웃), 최소 레이즈,
  누적 재오픈(TDA 47), 콜할 상대 없는 레이즈 금지, 이벤트·로그 금액 = 실제 칩 이동, 봇 불법
  요청의 폴백, 사람 화면 값(`call_amount`·`can_raise`·`min_raise_to`)과 불법 판정, 칩 보존,
  무빙 버튼 — 강제 장치: 그 자체, 퍼저 분포 회귀는
  `tests/test_poker_full.py::test_8_28_fuzzer_catches_reverted_cumulative_reopen`
  (누적 재오픈을 되돌리면 퍼저가 실패해야 함)
- 사이드팟: core `TexasHoldem.calculate_side_pots`/`showdown()`이 `total_bet_this_round`
  오름차순으로 계층을 나누고, 각 계층은 그 금액을 낸(폴드 안 한) 플레이어(eligible)끼리만 나눈다.
  아무도 콜하지 않은 초과 베팅(최대 기여 − 두 번째 기여)은 쇼다운에서 본인에게 **반환**하는
  별도 계층(`PotShare.returned=True`, 맨 끝)이고, 반환만 받은 사람은 승자가 아니다. eligible이
  1명이어도 폴드한 사람의 돈이 든 계층은 반환이 아니라 그 사람이 이긴 팟이다. 전원 폴드로 끝난
  핸드는 팟 전액 1계층(반환 아님). 결과는 `ShowdownResult`(총액·승자·계층별 `PotShare`·평가·
  쇼다운 여부)로 돌려준다 — 강제 장치:
  `tests/test_poker_full.py::test_3_6_sidepot_independent_calculator_2000`(코드를 공유하지 않는
  독립 계산기 `tests/test_sidepot_indep.py`와 시드 고정 2,000 시나리오의 칩 증가분·홀수 칩
  수령자·계층·반환 대조), `::test_6_6_sidepot_three_allins`(100/300/600 → 메인·사이드·반환),
  `::test_6_5_sidepot_shortstack_wins_mainpot_only`, `::test_6_7_sidepot_folded_player_contribution`,
  `::test_3_5_allin_player_cannot_win_more_than_contributed`
- 팟 결과 전달: 웹 세션은 핸드가 끝나면 `GameState.pots`(`[{amount, eligible, winners,
  returned}]`, 메인 → 사이드 → 반환 순, 핸드 진행 중 `null`)를 싣는다. `winner` 이벤트의
  `pot`과 로그 "🏆 … 승리 (N)"의 N은 반환분을 뺀 실제 수령 합이고, `winner_chips`에는 반환받은
  사람을 포함해 팟을 받은 전원의 최종 칩이 들어간다. CLI는 팟이 여럿이면 계층별 금액·승자와
  "반환 N → 이름"을 출력한다 — 강제 장치:
  `tests/test_poker_full.py::test_8_30_hand_over_pots_main_side_returned`,
  `::test_8_31_fold_win_pots_single_layer`, `::test_4_9_cli_sidepot_and_moving_button`(CLI 분배)
- 칩 보존: 모든 핸드에서 `모든 플레이어 chips 합 + pot == 핸드 시작 시 총합`이 성립한다
  (헤즈업·사이드팟 포함) — 강제 장치: `tests/test_poker_full.py::test_3_1_pot_conservation`
  (시드 고정 100핸드, 사람·봇 레이즈·올인 포함, 레이즈·올인·사이드팟 발생까지 확인),
  `::test_6_4_headsup_chip_conservation`, `::test_6_8_sidepot_conservation`
- 홀수 칩: 스플릿 팟(사이드팟 계층 포함)을 나누고 남는 칩은 버튼 왼쪽(SB 자리)부터 시계
  방향으로 돌아 처음 만나는 승자가 받는다(헤즈업은 BB, core `order_from_button_left`) — 강제 장치:
  `tests/test_poker_full.py::test_8_17_odd_chip_to_first_winner_left_of_button`(세션 경로),
  `::test_3_3_split_pot_odd_remainder`(core, 수령자까지 검사)
- 파산: 칩이 0 이하인 플레이어는 다음 핸드 시작 시(`_start_new_hand` → core
  `seat_for_next_hand`) 좌석에서 제거된다. 사람이 파산하거나 활성 플레이어가 2명 미만이 되면
  `game_over=true` — 강제 장치: `tests/test_poker_full.py::test_4_2_bankrupt_player_removed`,
  `::test_4_5_game_over_when_human_busted`
- 버튼(무빙 버튼): 버튼은 매 핸드 "고정 좌석 순서(`TexasHoldem.seat_names`)에서 직전 버튼
  보유자 다음의 살아 있는 사람"으로 옮기고, SB·BB는 그 뒤 두 명이다(헤즈업은 버튼 = SB).
  core가 버튼 보유자를 인덱스가 아니라 이름(`TexasHoldem.button_name`, `start_hand`가 기록)으로
  기억하므로 버튼 앞 좌석이 파산해 빠져도 버튼이 한 칸 더 건너뛰지 않는다. 웹 세션과 CLI 모두
  핸드 시작 전에 `seat_for_next_hand()`를 부른다. 드물게 블라인드를 연속으로
  내거나 건너뛰는 사람이 생길 수 있다(규칙상 일관된 동작) — 근거:
  [0036](../decisions/0036-moving-button.md) · 강제 장치:
  `tests/test_poker_full.py::test_8_15_moving_button_on_bust`(파산 전환·헤즈업 전환),
  `::test_4_1_dealer_rotation`(파산 없을 때 정확히 한 칸, SB·BB 추종),
  `::test_8_12_session_fuzz_event_amounts_and_conservation`(무작위 파산 전환 버튼 불변식),
  `::test_4_9_cli_sidepot_and_moving_button`(CLI 파산 전환)
- 딜러 이동 시점: 다음 핸드 시작 시(`_start_new_hand`)에만 이동한다. 그래서 핸드 종료
  응답(`hand_over=true`)의 포지션 라벨·RL 기록의 포지션은 방금 친 핸드 기준이다 — 강제 장치:
  `tests/test_poker_full.py::test_8_16_hand_over_positions_are_played_hand`

## 화면·경로·데이터

| 모듈 | 역할 |
|---|---|
| `core/game.py` | 룰 엔진 본체(`TexasHoldem`) — 좌석·버튼, 베팅 라운드 진행·액션 판정, 스트리트 전환, 사이드팟 분배(`ShowdownResult`), 포지션, 프리플랍 시퀀스 |
| `core/{card,deck,player,evaluator}.py` | 카드·덱·플레이어·핸드 평가 |
| `cli/main.py` | 터미널 플레이(`GameController`) — core `play_round()` 콜백 방식, 룰은 웹과 동일 |

## 알려진 한계

- 런잇트와이스는 미구현.
- 세션 퍼저(`test_8_12`)는 룰·금액·버튼을 검사하지만, 이벤트 종류 순서·카드 공개 규칙 전체에
  대한 전수 불변식 테스트는 없다.
- CLI의 액션 출력 줄은 봇·사람이 요청한 액션 기준이라, 불법 요청이 폴백으로 바뀐 경우(예:
  닫힌 액션의 봇 레이즈 → 콜) 화면 줄과 실제 적용이 다를 수 있다(칩·팟은 core 기준으로 정확).
