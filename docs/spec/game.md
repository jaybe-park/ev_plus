# 게임 엔진 / 웹 게임 흐름 — 현재 사양

> 최종 갱신: 2026-09-26 · 관련 결정: [0024](../decisions/0024-hj-position-naming.md), [0025](../decisions/0025-ports-and-https.md), [0034](../decisions/0034-action-validation-and-real-amounts.md)

## 무엇을 하는가

`core/`가 6-max(최대) 캐시게임 텍사스 홀덤 엔진을 순수 로직으로 구현한다(외부 의존 없음, CLI·웹 공용).
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
- 행동 순서·라운드 시작 acted는 core 한 곳(`TexasHoldem._betting_order`, `initial_acted`)이
  정하고 웹 세션(`WebGameSession._setup_round`)은 그것을 호출만 한다.
- 헤즈업(2인)은 딜러가 `BTN/SB` 겸임, 상대가 `BB`다. 프리플랍은 `BTN/SB`가 선행동하고
  BTN/SB가 림프하면 BB가 체크/레이즈 옵션을 받는다. 포스트플랍은 `BB`가 선행동한다
  (6인 이상과 반대). BTN/SB 첫 결정 시점의 프리플랍 시퀀스는 비어 있어 GTO 힌트가 SB RFI
  노드로 조회된다 — 강제 장치(세션 경로): `tests/test_poker_full.py::test_8_3_headsup_btnsb_first_and_bb_option`,
  `::test_8_4_headsup_human_btnsb_acts_first`, `::test_8_5_headsup_btnsb_first_decision_has_gto_hint`
  · core 헬퍼: `::test_6_1_headsup_blind_posting`, `::test_6_2_headsup_preflop_btnSB_acts_first`,
  `::test_6_3_headsup_postflop_bb_acts_first`
- 3인 이상 프리플랍 행동 순서는 UTG부터(딜러+3), SB는 블라인드 포스팅으로 이미 액션한 것으로
  처리되고 BB만 옵션(체크/레이즈)을 보유한다. 포스트플랍은 SB(딜러+1)부터 — 강제 장치:
  core 헬퍼만 `tests/test_poker_full.py::test_2_5_preflop_betting_order_3players`,
  `::test_2_7_postflop_sb_acts_first` (세션은 같은 함수를 호출하므로 간접 보장)
- 재오픈(표준 불완전 레이즈 규칙): 레이즈 증가분(새 `current_bet` − 이전 `current_bet`)이
  `min_raise` 이상인 풀 레이즈(올인 포함)만 액션을 다시 연다 — 이미 행동한 사람 전원이 다시
  기회를 얻고 `min_raise`가 그 증가분으로 갱신된다. 증가분이 `min_raise` 미만인 올인은
  `current_bet`만 올리고 재오픈하지 않는다: 이미 행동한 사람은 콜/폴드만 할 수 있고
  (응답 `can_raise=false`, `min_raise_to=0`), 아직 행동하지 않은 사람은 레이즈할 수 있다.
  콜도 못 채우는 올인은 `current_bet`을 바꾸지 않는다. 블라인드 포스팅은 행동이 아니다
  (SB도 자기 차례에 레이즈 가능). 연속된 불완전 올인의 합이 풀 레이즈가 되는 경우도
  재오픈하지 않는다(액션 단위 판정) — 강제 장치(세션 경로):
  `tests/test_poker_full.py::test_8_6_short_allin_under_call_does_not_reopen`,
  `::test_8_7_incomplete_raise_allin_call_or_fold_only`, `::test_8_8_full_allin_updates_min_raise`
  · core: `::test_2_3_raise_reopens_action`
- 최소 레이즈: 요청 금액이 `현재 베팅 + min_raise` 미만이면 그 값으로 자동 보정한다.
  보정 후 금액이 스택(`chips + current_bet`) 이상이면 올인으로 적용한다 — 스택보다 큰 레이즈
  요청이 실제로 걸리지 않은 `current_bet`을 만들지 않는다 — 강제 장치:
  `tests/test_poker_full.py::test_8_9_raise_over_stack_becomes_allin`(세션 경로),
  `::test_4_6_minimum_raise_rule`, `::test_5_5_raise_amount_enforced`(core)
- 액션 판정은 core `TexasHoldem.normalize_action`/`execute_action` 한 곳에서 하고
  (`ActionResult`: 실제 액션·이동 칩·도달 베팅·재오픈 여부), 웹 세션과 core 베팅 루프가 같이 쓴다
  — 근거: [0034](../decisions/0034-action-validation-and-real-amounts.md)
- 액션 유효성: 벳을 마주한 체크, 액션이 닫힌 사람의 레이즈, 폴드·올인한 사람의 액션은 불법이다.
  콜할 금액이 없는 콜은 체크로 적용된다. 사람의 불법 액션은 상태를 바꾸기 전에 거절되고
  (API 400) 로그·이벤트·RL 기록·플레이 평가에 남지 않는다. 봇의 불법 액션은 경고 로그
  (`server.session` 로거)를 남기고 안전한 액션으로 대체된다: 막힌 레이즈/올인 → 콜(콜할 금액
  없으면 체크), 불법 체크 → 폴드 — 강제 장치: `tests/test_poker_full.py::test_8_10_illegal_check_rejected_not_recorded`,
  `::test_8_11_bot_illegal_action_falls_back`
- 금액 불변식: 로그·`action`/`blind` 이벤트·RL 기록의 금액은 실제 칩 이동에서 만든다 —
  콜 = 이동액, 레이즈/올인 = 도달 베팅(이전 베팅 + 이동액, 로그 "레이즈 → X"/"올인! (X)"),
  폴드/체크 = 0, 블라인드 = 실제로 낸 칩(숏스택이면 블라인드보다 적음) — 강제 장치:
  `tests/test_poker_full.py::test_8_12_session_fuzz_event_amounts_and_conservation`
  (시드 고정 세션 퍼저 250핸드: 금액 불변식·칩 보존·사람 불법 액션 무변경)
- 사이드팟: `total_bet_this_round` 오름차순으로 계층을 나누고, 각 계층은 그 금액을 낸
  플레이어(eligible)끼리만 나눈다. **eligible이 1명뿐인 계층(초과 베팅 반환)은 승자 집계에서
  제외**한다 — 강제 장치: `tests/test_poker_full.py::test_6_5_sidepot_shortstack_wins_mainpot_only`,
  `::test_6_6_sidepot_three_allins`, `::test_6_7_sidepot_folded_player_contribution`
- 칩 보존: 모든 핸드에서 `모든 플레이어 chips 합 + pot == 핸드 시작 시 총합`이 성립한다
  (헤즈업·사이드팟 포함) — 강제 장치: `tests/test_poker_full.py::test_3_1_pot_conservation`,
  `::test_6_4_headsup_chip_conservation`, `::test_6_8_sidepot_conservation`
- 파산: 칩이 0 이하인 플레이어는 다음 핸드 시작 시(`_start_new_hand`) 좌석에서 제거된다.
  사람이 파산하거나 활성 플레이어가 2명 미만이 되면 `game_over=true` — 강제 장치:
  `tests/test_poker_full.py::test_4_2_bankrupt_player_removed`, `::test_4_5_game_over_when_human_busted`

### 웹 게임 흐름
- `POST /game/{id}/action`은 사람 액션을 적용한 뒤 `_run_until_human()`으로 봇을 자동
  처리한다: 각 봇은 `PokerBot.decide_action(game_state)`로 결정하고, 라운드가 끝나면
  스트리트를 전환한다.
- 런아웃: 행동 가능한(폴드·올인 아닌) 플레이어가 1명뿐이고 그가 콜할 금액이 없으면 라운드가
  끝난 것으로 본다(core `_is_round_over`, 사람·봇 공통). 남은 스트리트는 액션 이벤트 없이
  `street_start`·`community_card`만 나오고 쇼다운으로 간다 — 무의미한 체크·"올인!" 이벤트,
  RL 기록, 봇 MC 계산이 생기지 않는다. 콜할 금액이 있으면(예: 상대가 더 큰 올인) 그 사람에게는
  묻는다 — 강제 장치: `tests/test_poker_full.py::test_8_13_runout_when_one_player_can_act`
- 한 응답 안의 `events[]`는 그 요청에서 새로 발생한 것만 담고(`get_state()` 호출 시
  큐가 비워짐), 순서는 실제 발생 순서와 같다. 이벤트 종류: `deal_card`(카드 딜, 라운드 1·2) →
  `blind`(SB/BB 포스팅) → `action`(폴드/체크/콜/레이즈/올인) → `street_start`(스트리트 전환) →
  `community_card`(커뮤니티 카드 1장씩) → `showdown`(봇 카드 공개) → `winner`(팟 지급) —
  강제 장치: 장치 없음(순서 불변식 자체를 검증하는 테스트 없음)
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
- 프론트 `useEventQueue`는 `events[]`를 소비해 지연 재생한다. `action` 이벤트만
  "생각 중"(THINKING_RATIO 구간) → 배지 표시 2단계이고, 나머지 이벤트는 단일 지연 후
  즉시 다음으로 넘어간다. `chips_after`가 실린 이벤트(`action`/`blind`/`winner`)만
  표시 칩을 갱신한다 — 원본: `web/src/hooks/useEventQueue.ts`

## 화면·경로·데이터

| 모듈 | 역할 |
|---|---|
| `core/game.py` | 게임 엔진 본체(`TexasHoldem`) — 베팅 라운드, 팟 분배, 포지션, 프리플랍 시퀀스 |
| `core/{card,deck,player,evaluator}.py` | 카드·덱·플레이어·핸드 평가 |
| `server/session.py` | `WebGameSession` — 스텝 방식 진행, 이벤트 큐, 에퀴티/평가/GTO 연결, 사이드팟 승자 계산 |
| `server/main.py` | FastAPI 라우터(게임 엔드포인트 + GTO 관리 API) |
| `server/schemas.py` | 응답/이벤트 Pydantic 모델 |
| `web/src/hooks/useEventQueue.ts` | 이벤트 큐 리플레이(지연·배지·칩 애니메이션) |
| `db/recorder.py` | 핸드/액션 RL 기록(세션과 별개 관심사, 실패해도 게임 진행에 영향 없음) |

엔드포인트(이름·용도 한 줄. 필드 원본: `server/schemas.py`, `https://localhost:8765/docs`):

| 엔드포인트 | 용도 |
|---|---|
| `POST /game/start` | 세션 생성, 첫 핸드 시작 후 사람 차례까지 자동 진행 |
| `GET /game/{id}/state` | 현재 `GameState` 조회 |
| `POST /game/{id}/action` | 사람 액션 제출 → 봇 자동 처리 → 다음 상태. 불법 액션은 400(상태 무변경) |
| `POST /game/{id}/next-hand` | `hand_over=true`일 때 다음 핸드 시작(핸드 중이면 무시하고 현재 상태 반환) |
| `GET /session/{id}/review` | 세션 누적 플레이 평가 요약 |

GTO 관리 API(`/gto/preflop/*`)는 이 문서 담당이 아니다 — 규칙은 [`docs/spec/gto-preflop.md`](gto-preflop.md).

포트·프로토콜: 백엔드 `https://localhost:8765`(HTTPS 필수), 프론트 `http://localhost:5766` —
근거: [0025](../decisions/0025-ports-and-https.md)

## 알려진 한계

- 사이드팟별 승자 표시는 서버 계산(`_calculate_side_pots`)까지만 되어 있고, 프론트
  `HandResult` UI에는 아직 팟별 분해가 노출되지 않는다(팟은 합산 지급되어 결과는 맞지만
  화면에 계층이 안 보임).
- 런잇트와이스는 미구현.
- 불완전 올인으로 액션이 닫힌 사람에게도 프론트 `ActionBar`의 "올인" 버튼은 보인다
  (레이즈 UI는 `min_raise_to=0`으로 꺼짐). 누르면 서버가 400으로 거절하고 오류 배너가 뜬다 —
  버튼을 `can_raise`로 숨기는 것은 UI 변경이라 별도 확인 필요.
- 이벤트 금액·칩 보존은 세션 퍼저(`test_8_12`)가 검사하지만, 이벤트 종류 순서·카드 공개
  규칙 전체에 대한 전수 불변식 테스트는 없다(T-024 퍼저 확장 대상).
- `GameState.gto_hint`/`gto_key`는 서로 다른 판정 경로(advisor vs `action_log` 문자열
  매칭)를 쓴다 — GTO 도메인 사안이라 `docs/spec/gto-preflop.md`의 한계로 다룬다.
