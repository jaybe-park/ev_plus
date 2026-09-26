# 게임 엔진 / 웹 게임 흐름 — 현재 사양

> 최종 갱신: 2026-09-27 · 관련 결정: [0024](../decisions/0024-hj-position-naming.md), [0025](../decisions/0025-ports-and-https.md), [0036](../decisions/0036-moving-button.md), [0038](../decisions/0038-action-validation-and-real-amounts.md), [0043](../decisions/0043-restore-session-on-reload.md), [0048](../decisions/0048-cumulative-short-allins-reopen.md), [0047](../decisions/0047-rules-live-in-core.md)

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
`server/`가 이 엔진을 HTTP 요청 단위로 감싸 웹 세션(`WebGameSession`)을 운영한다: 사람이 액션 1회를
보내면 서버가 봇 전원을 자동 처리해 다음 사람 차례(또는 핸드 종료)까지 진행한 뒤 `GameState`
하나로 응답한다. 응답에 함께 실리는 `events[]`가 프론트 `useEventQueue`의 단계별 리플레이 애니메이션
소스다.

## 규칙 (지금 유효한 것만)

### 룰
- 좌석 수 2~7인 지원. 포지션 라벨(딜러 기준 상대 위치)은 `core/game.py::get_positions()`가
  좌석 수별 고정 배열로 정한다 — 근거: [0024](../decisions/0024-hj-position-naming.md)
  · 강제 장치: 장치 없음(그 자체를 검사하는 테스트는 없음. 6인 좌석 순서 사용 예:
    `tests/test_poker_full.py::test_2_5_preflop_betting_order_3players`)
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
  누적 재오픈(TDA 47), 이벤트·로그 금액 = 실제 칩 이동, 봇 불법 요청의 폴백, 사람 화면 값
  (`call_amount`·`can_raise`·`min_raise_to`)과 불법 판정, 칩 보존, 무빙 버튼. T-019~T-023·T-038
  버그 10종을 되살리면 모두 실패함을 확인했다(2026-09-27, 일회성 확인) — 강제 장치: 그 자체,
  퍼저 분포 회귀는 `tests/test_poker_full.py::test_8_28_fuzzer_catches_reverted_cumulative_reopen`
  (T-038을 되돌리면 퍼저가 실패해야 함)
- 사이드팟: core `TexasHoldem.calculate_side_pots`/`showdown()`이 `total_bet_this_round`
  오름차순으로 계층을 나누고, 각 계층은 그 금액을 낸 플레이어(eligible)끼리만 나눈다. **eligible이
  1명뿐인 계층(초과 베팅 반환)은 승자 집계에서 제외**한다. 결과는 `ShowdownResult`(총액·승자·
  계층별 `PotShare`·평가·쇼다운 여부)로 돌려주고 웹 세션·CLI가 그대로 표시한다(CLI는 팟이
  여럿이면 계층별 금액·승자도 출력) — 강제 장치:
  `tests/test_poker_full.py::test_6_5_sidepot_shortstack_wins_mainpot_only`,
  `::test_6_6_sidepot_three_allins`, `::test_6_7_sidepot_folded_player_contribution`,
  `::test_3_5_allin_player_cannot_win_more_than_contributed`(core),
  `::test_4_9_cli_sidepot_and_moving_button`(CLI)
- 칩 보존: 모든 핸드에서 `모든 플레이어 chips 합 + pot == 핸드 시작 시 총합`이 성립한다
  (헤즈업·사이드팟 포함) — 강제 장치: `tests/test_poker_full.py::test_3_1_pot_conservation`,
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

### 웹 게임 흐름
- `POST /game/{id}/action`은 사람 액션을 적용한 뒤 `_run_until_human()`으로 봇을 자동
  처리한다: 각 봇은 `PokerBot.decide_action(game_state)`로 결정하고, 라운드가 끝나면
  스트리트를 전환한다.
- 동시성: 게임 엔드포인트는 동기 `def`라 FastAPI 스레드풀에서 동시에 돈다. 같은 세션에 대한
  요청(상태 조회·액션·다음 핸드·리뷰)은 세션별 `WebGameSession.lock`(RLock)으로 직렬화한다
  — 탭 두 개·연타로 요청이 겹쳐도 이벤트가 빠지거나 중복되지 않고, "다음 핸드" 동시 요청도
  한 핸드만 넘어간다 — 강제 장치:
  `tests/test_poker_full.py::test_8_18_concurrent_requests_do_not_steal_or_duplicate_events`
- 봇 판단 예외: `decide_action`이 예외를 던지거나 `Action`이 아닌 값을 돌려주면 세션이
  잡아 `server.session` 로거에 오류(트레이스백 포함)를 남기고 core `fallback_action(봇,
  CHECK)`(콜할 금액이 없으면 체크, 있으면 폴드)으로 대신해 게임을 계속한다 — 강제 장치:
  `tests/test_poker_full.py::test_8_19_bot_exception_logged_and_game_continues`
- 자가 복구: 요청 중간의 예상 못 한 오류로 세션이 "핸드 진행 중인데 사람 차례가 아님"에
  멈춰 있으면(`needs_recovery()`), `GET /game/{id}/state`가 `recover()`로 사람 차례·핸드
  종료까지 진행하고 그 이벤트를 싣는다(경고 로그). 정상 세션에서 GET은 상태를 바꾸지 않는다
  (`events=[]`) — 강제 장치: `tests/test_poker_full.py::test_8_20_get_state_recovers_stuck_bot_turn`
- 런아웃: 행동 가능한(폴드·올인 아닌) 플레이어가 1명뿐이고 그가 콜할 금액이 없으면 라운드가
  끝난 것으로 본다(core `_is_round_over`, 사람·봇 공통). 남은 스트리트는 액션 이벤트 없이
  `street_start`·`community_card`만 나오고 쇼다운으로 간다 — 무의미한 체크·"올인!" 이벤트,
  RL 기록, 봇 MC 계산이 생기지 않는다. 콜할 금액이 있으면(예: 상대가 더 큰 올인) 그 사람에게는
  묻는다 — 강제 장치: `tests/test_poker_full.py::test_8_13_runout_when_one_player_can_act`
- 한 응답 안의 `events[]`는 그 요청에서 새로 발생한 것만 담고, 순서는 실제 발생 순서와
  같다. 상태를 바꾸는 세션 메서드(`submit_action`/`next_hand`/`recover`)가 그 호출에서 생긴
  이벤트 목록을 반환하고, 엔드포인트가 그것을 `get_state(events)`에 넘긴다. `get_state()`는
  순수 조회라 이벤트 버퍼를 읽거나 비우지 않는다(첫 핸드 이벤트는 생성자가
  `start_events`에 담아 `POST /game/start`가 싣는다). 중간에 실패한 요청의 이벤트는 다음
  응답에 다시 나오지 않는다 — 강제 장치:
  `tests/test_poker_full.py::test_8_18_concurrent_requests_do_not_steal_or_duplicate_events`,
  `::test_8_12_session_fuzz_event_amounts_and_conservation`(매 조회 `events == []`) ·
  이벤트 종류: `deal_card`(카드 딜, 라운드 1·2) →
  `blind`(SB/BB 포스팅) → `action`(폴드/체크/콜/레이즈/올인) → `street_start`(스트리트 전환) →
  `community_card`(커뮤니티 카드 1장씩) → `showdown`(봇 카드 공개) → `winner`(팟 지급) —
  강제 장치: 장치 없음(순서 불변식 자체를 검증하는 테스트 없음)
- `blind` 이벤트는 좌석 순서와 무관하게 항상 SB(헤즈업은 BTN/SB) → BB 순서로 나온다 — core
  `_post_blinds`가 기록한 `blind_posts`(포스팅 순서·실제 금액)를 세션이 그대로 발행 — 강제 장치:
  `tests/test_poker_full.py::test_8_14_blind_events_sb_then_bb_when_human_bb`(사람 BB, 2~6인)
- 카드 공개: 사람 홀카드는 항상 공개. 봇 홀카드는 핸드 진행 중 비공개이고, **쇼다운(2명
  이상 대결)이 실제로 있었을 때만** 공개된다 — 전원 폴드로 1명만 남는 경우는 비공개 유지
  — 강제 장치: `tests/test_poker_full.py::test_5_7_human_cards_always_visible`,
  `::test_5_8_bot_cards_hidden_during_hand`, `::test_5_9_showdown_reveals_bot_cards`
- 게임오버: `game_over=true`가 되면 세션은 더 이상 액션을 받지 않는다
  (`submit_action`/`next_hand`이 조용히 무시) — 강제 장치:
  `tests/test_poker_full.py::test_5_2_action_ignored_when_hand_over`(핸드 종료 시점)
- 다음 핸드: `next_hand`는 `hand_over=true`일 때만 새 핸드를 시작하고, 핸드 진행 중 요청은
  조용히 무시한다(응답은 현재 상태). 연타·중복 요청이 와도 핸드는 하나만 넘어가고 팟 칩이
  사라지지 않는다. 결과 창 "다음 핸드" 버튼은 요청 중(`loading`) 비활성 — 강제 장치:
  `tests/test_poker_full.py::test_8_1_next_hand_double_call_keeps_chips`,
  `::test_8_2_next_hand_during_hand_ignored` (버튼 비활성은 장치 없음 — `HandResult.tsx`)
- **재생 표시 상태는 하나다**(T-029): 응답이 오면 서버 최종 상태를 바로 그리지 않는다. 재생
  중에는 "요청 직전 상태 + 지금까지 소비한 이벤트"로 만든 표시 상태(`DisplayState`)만 테이블에
  그린다 — 팟·스트리트 라벨·보드 카드 수·로그 줄 수·좌석 칩/베팅/폴드/올인/받은 카드 수가 모두
  순수 리듀서 `eventQueueLogic.applyEvent`에서 나오고 `projectState(next, display)`로 GameState
  하나가 된다. 그래서 폴드 후 봇들이 진행하는 동안 팟·스트리트·베팅액이 애니메이션과 같은 시점에
  바뀐다. 새 핸드의 시작점은 블라인드 전(칩 = 직전 핸드 종료 칩, 팟 0, 카드 0장), 이어지는
  액션의 시작점은 요청 직전 상태다. 스킵은 남은 이벤트를 한 번에 소비한다(최종 상태와 같음) —
  강제 장치: `web/src/hooks/__tests__/replayDisplay.test.ts`(실제 세션 응답 픽스처, 생성 `tests/make_replay_fixture.py`
  `fixtures/replay_session.json`: 시작 화면 = 직전 상태, 팟 = 이벤트 `pot_after`, 스트리트·보드는
  해당 이벤트에서만, 봇 베팅은 그 봇 액션부터, 전부 소비 = 서버 최종 상태, 스킵 동일, 새 핸드)
- 이벤트 페이로드: `blind`/`action`은 `pot_after`(이벤트 직후 팟)·`bet_after`(그 플레이어의
  이번 스트리트 베팅), `street_start`는 `pot_after`를 싣는다. `winner` 이후 표시 팟은 0 — 강제
  장치: `tests/test_poker_full.py::test_8_12_session_fuzz_event_amounts_and_conservation`(누적 이동액
  = `pot_after`, 스트리트 누적 = `bet_after`, 사람 차례 팟 = 실제 팟)
- 힌트 패널(에퀴티·GTO)과 액션 바는 재생 중 **재생 직전 상태**를 유지한다(`panelState`). 새
  에퀴티(아직 안 깔린 카드 반영)·새 GTO 노드 조회는 재생이 끝난 뒤에만 보인다 — 강제 장치:
  `web/src/hooks/__tests__/replayDisplay.test.ts`("힌트 패널은 재생이 끝날 때까지 이전 값")
- 타이밍(`eventTiming`): 봇 `action`은 "생각 중"(THINKING_RATIO 구간) → 표시 반영 + 배지 →
  다음. **사람 자신의 액션은 "생각 중" 없이 즉시 반영**하고 배지만 `HUMAN_ACTION_MS`(350ms)
  보인다(봇만 연출). `deal_card`는 지연 끝에 반영, 그 밖의 이벤트는 시작하자마자 반영하고 지연 후
  다음으로 — 강제 장치: `web/src/hooks/__tests__/replayDisplay.test.ts`("이벤트 타이밍")
- 이벤트 → 배지 텍스트/좌석 커밋 레이블(`formatBadge`, `makeCommitLabel`)도 같은 모듈의 순수
  함수다. `useEventQueue.ts`는 언제 반영할지(타이머)와 하이라이트 연출(생각 중·배지·칩 날아가기)만
  맡는다 — 강제 장치: `web/src/hooks/__tests__/eventQueueLogic.test.ts`
- `isReplaying`은 `queue.length > 0`으로 매 렌더 파생한다. 큐가 비는 순간의 하이라이트 리셋은
  렌더 중 조정 패턴(prevQueueEmpty 비교)으로 처리 — 근거: 2026-09-26 리뷰 W9
- 세션 수명: 세션은 서버 메모리(`server/main.py::sessions`)에만 있다. 마지막 요청 후
  `SESSION_TTL_SEC`(24시간)이 지나거나 세션 수가 `MAX_SESSIONS`(20)를 넘으면 가장 오래 안 쓴
  세션부터 정리한다(요청마다·새 게임 등록 시 `_prune_sessions`). 정리됐거나 서버가 재시작돼
  없는 세션에 대한 요청은 404다. 서버 재시작 뒤 게임 복구는 하지 않는다 — 근거:
  [0043](../decisions/0043-restore-session-on-reload.md) · 강제 장치:
  `tests/test_poker_full.py::test_8_24_old_sessions_pruned_and_return_404`
- dev 서버 재시작 범위: `dev.sh`의 uvicorn `--reload`는 `--reload-dir server core ai gto db`만
  감시한다(`python3 server/main.py` 직접 실행도 같은 목록). `tests/`·`scripts/`·`docs/`·`web/`을
  고쳐도 서버가 재시작되지 않아 진행 중인 게임이 유지된다 — 강제 장치:
  `tests/test_poker_full.py::test_8_23_dev_server_reload_watches_server_code_only`
- 새로고침 후 이어하기: 프론트는 받은 `session_id`를 `sessionStorage`(`ev_plus_session_id`)에
  보관하고, 페이지를 열 때 보관된 번호가 있으면 `GET /game/{id}/state`로 확인해 살아 있으면
  그 게임을 이어서 보여준다(확인하는 동안 "진행 중인 게임을 불러오는 중…"). 404면 번호를
  지우고 설정 화면에 "세션 만료 — 새 게임 — 이전 게임을 이어갈 수 없습니다." 안내를 띄운다
  — 근거: [0043](../decisions/0043-restore-session-on-reload.md) · 원본: `web/src/sessionStore.ts`,
  `web/src/App.tsx` · 강제 장치: `web/src/__tests__/sessionStore.test.ts`(보관·삭제·저장소 예외·
  404 판정), 화면 흐름은 장치 없음
- 세션 만료 표시: 게임 중 요청이 404를 받으면(`ApiError.status === 404`) 오류 문구 대신
  "세션 만료 — 새 게임: 서버에서 이 게임을 찾을 수 없습니다." 배너와 "새 게임" 버튼을 띄우고,
  액션 바와 결과 창 "다음 핸드" 버튼을 잠근다. 400 등 다른 오류는 기존 오류 배너 — 원본:
  `web/src/App.tsx` · 강제 장치: `web/src/__tests__/sessionStore.test.ts::세션 만료 판정`(판정만)
- 새 게임: "새 게임"을 누르면 이전 게임의 세션 요약(헤더 GTO%·EV), 오류·만료 표시, 보관된
  세션 번호, 핸드 번호 비교 기준을 모두 초기화한다 — 원본: `web/src/App.tsx::handleNewGame`
  (장치 없음)
- 게임 설정 검증(`POST /game/start`, `server/schemas.py::StartGameRequest`): 빅 블라인드
  2 이상 짝수(SB = BB/2), 시작 칩 1~10,000,000 이면서 BB×10 이상, AI 봇 1~5명, 난이도
  easy/medium/hard, 플레이어 이름 1~20자(앞뒤 공백 제거)이고 봇 이름 접두사 "🤖"로 시작
  불가(이름이 좌석·버튼 식별자라 겹치면 안 됨). 위반은 422이고 `detail[].msg`는 이유가 적힌
  한국어 문장(`PydanticCustomError`, 접두사 없음)이다. 세션은 첫 상태 계산까지 성공한 뒤에만
  등록되므로 생성 중 오류가 나도 목록에 남지 않는다. 설정 화면(`SetupForm`)은 거절 이유를
  시작 버튼 위에 "게임을 만들 수 없습니다 — <이유>"로 보여주고, 요청 중엔 버튼을 잠근다.
  `ActionRequest`는 `action` ∈ fold/check/call/raise/allin, `amount ≥ 0`(위반 422) — 강제 장치:
  `tests/test_poker_full.py::test_8_21_start_game_rejects_invalid_settings`,
  `::test_8_22_session_registered_only_after_successful_start`, 설정 화면 문구는
  `web/src/__tests__/api.test.ts`(422 평탄화)까지만(렌더링 테스트 없음)
- 레이즈할 수 없는 사람(`GameState.can_raise=false` — 불완전 올인으로 액션이 닫힘, 또는 스택이
  콜 이하)에게 `ActionBar`는 레이즈·올인 버튼을 보이지 않는다(눌러도 400이라). 스택이 콜 이하면
  콜 버튼이 "콜 N (올인)"으로 남은 칩 전부를 낸다 — 강제 장치: 서버 `can_raise`는
  `tests/test_poker_full.py::test_8_7_incomplete_raise_allin_call_or_fold_only`, 버튼 판단은
  `web/src/components/__tests__/actionBarLogic.test.ts`(렌더링 테스트 없음)
- API 오류: FastAPI 422의 `detail`은 배열이라 그대로 `Error`에 넘기면 배너에
  "[object Object]"가 뜬다 — `web/src/api.ts::formatApiError`가 `loc`/`msg`를 사람이 읽는
  한 줄 문장으로 평탄화한다 — 강제 장치: `web/src/__tests__/api.test.ts`
- `GtoRange.raise_size`는 `number | null`이다(서버 `raise_size: Optional[float]`,
  bb 단위 실측값). 패널은 값이 있을 때만 "(N bb)"로 표시 — 원본: `web/src/types.ts`,
  `web/src/components/GtoPanel.tsx`

## 화면·경로·데이터

| 모듈 | 역할 |
|---|---|
| `core/game.py` | 룰 엔진 본체(`TexasHoldem`) — 좌석·버튼, 베팅 라운드 진행·액션 판정, 스트리트 전환, 사이드팟 분배(`ShowdownResult`), 포지션, 프리플랍 시퀀스 |
| `core/{card,deck,player,evaluator}.py` | 카드·덱·플레이어·핸드 평가 |
| `server/session.py` | `WebGameSession` — core 호출을 HTTP 요청 단위로 나눠 진행(봇 자동 처리), core 결과를 이벤트·로그·RL 기록으로 변환, 에퀴티/평가/GTO 연결 |
| `cli/main.py` | 터미널 플레이(`GameController`) — core `play_round()` 콜백 방식, 룰은 웹과 동일 |
| `server/main.py` | FastAPI 라우터(게임 엔드포인트 + GTO 관리 API) |
| `server/schemas.py` | 응답/이벤트 Pydantic 모델 |
| `web/src/hooks/useEventQueue.ts` | 이벤트 큐 재생 타이머·하이라이트 연출 |
| `web/src/hooks/eventQueueLogic.ts` | 재생 표시 상태 리듀서·투영, 패널 상태, 타이밍, 배지/레이블(순수 함수, vitest 대상) |
| `web/src/api.ts` | fetch 래퍼 + 422 detail 배열 평탄화(`formatApiError`) + 상태 코드 실은 `ApiError` |
| `web/src/sessionStore.ts` | 세션 번호 `sessionStorage` 보관(새로고침 후 이어하기)·404 만료 판정 |
| `db/recorder.py` | 핸드/액션 RL 기록(세션과 별개 관심사, 실패해도 게임 진행에 영향 없음) |

엔드포인트(이름·용도 한 줄. 필드 원본: `server/schemas.py`, `https://localhost:8765/docs`):

| 엔드포인트 | 용도 |
|---|---|
| `POST /game/start` | 세션 생성, 첫 핸드 시작 후 사람 차례까지 자동 진행. 잘못된 설정은 422(한국어 이유) |
| `GET /game/{id}/state` | 현재 `GameState` 조회(봇 차례에 멈춘 세션이면 복구 진행) |
| `POST /game/{id}/action` | 사람 액션 제출 → 봇 자동 처리 → 다음 상태. 불법 액션은 400(상태 무변경) |
| `POST /game/{id}/next-hand` | `hand_over=true`일 때 다음 핸드 시작(핸드 중이면 무시하고 현재 상태 반환) |
| `GET /session/{id}/review` | 세션 누적 플레이 평가 요약 |

GTO 관리 API(`/gto/preflop/*`)는 이 문서 담당이 아니다 — 규칙은 [`docs/spec/gto-preflop.md`](gto-preflop.md).

포트·프로토콜: 백엔드 `https://localhost:8765`(HTTPS 필수), 프론트 `http://localhost:5766` —
근거: [0025](../decisions/0025-ports-and-https.md)

## 알려진 한계

- 사이드팟별 승자 표시는 core 계산(`ShowdownResult.pots`)까지만 되어 있고, 프론트
  `HandResult` UI에는 아직 팟별 분해가 노출되지 않는다(팟은 합산 지급되어 결과는 맞지만
  화면에 계층이 안 보임).
- 런잇트와이스는 미구현.
- 세션 퍼저(`test_8_12`)는 룰·금액·버튼을 검사하지만, 이벤트 종류 순서·카드 공개 규칙 전체에
  대한 전수 불변식 테스트는 없다.
- `get_state()`는 게임 상태·이벤트를 바꾸지 않지만, 에퀴티 패널 계산 결과를 결정 지점 단위
  캐시(`_equity_cache`)와 스트리트별 history에 한 번 기록한다(같은 결정 지점 재조회는 같은
  값). 에퀴티 모듈의 전역 캐시 기여 버퍼는 세션 락 밖이라 세션 간 동시 접근에 무락이다 —
  에퀴티 캐시 폐기(T-036)에서 버퍼 자체가 사라질 예정이라 여기서 따로 잠그지 않았다.
- CLI의 액션 출력 줄은 봇·사람이 요청한 액션 기준이라, 불법 요청이 폴백으로 바뀐 경우(예:
  닫힌 액션의 봇 레이즈 → 콜) 화면 줄과 실제 적용이 다를 수 있다(칩·팟은 core 기준으로 정확).
