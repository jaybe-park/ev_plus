# 게임 엔진 / 웹 게임 흐름 — 현재 사양

> 최종 갱신: 2026-09-26 · 관련 결정: [0024](../decisions/0024-hj-position-naming.md), [0025](../decisions/0025-ports-and-https.md)

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
- 헤즈업(2인)은 딜러가 `BTN/SB` 겸임, 상대가 `BB`다. 프리플랍은 `BTN/SB`가 선행동,
  포스트플랍은 `BB`가 선행동한다(6인 이상과 반대) — 강제 장치:
  `tests/test_poker_full.py::test_6_1_headsup_blind_posting`,
  `::test_6_2_headsup_preflop_btnSB_acts_first`, `::test_6_3_headsup_postflop_bb_acts_first`
- 프리플랍 행동 순서는 UTG부터(딜러+3), SB는 블라인드 포스팅으로 이미 액션한 것으로
  처리되고 BB만 옵션(체크/레이즈)을 보유한다. 포스트플랍은 SB(딜러+1)부터 — 강제 장치:
  `tests/test_poker_full.py::test_2_5_preflop_betting_order_3players`,
  `::test_2_7_postflop_sb_acts_first`, `::test_2_1_bb_option_check`
- 레이즈·올인이 나오면 그 전에 이미 액션했던 활성 플레이어 전원이 다시 기회를 얻는다
  (본인만 남기고 acted 집합 초기화) — 강제 장치: `tests/test_poker_full.py::test_2_3_raise_reopens_action`
- 최소 레이즈: 요청 금액이 `현재 베팅 + 직전 레이즈 크기` 미만이면 그 값으로 자동 보정한다
  (레이즈 불가 최소치 아래로는 못 감) — 강제 장치: `tests/test_poker_full.py::test_4_6_minimum_raise_rule`,
  `::test_5_5_raise_amount_enforced`
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
  스트리트를 전환하며, 상대 전원이 올인이고 콜할 베팅이 없으면 사람 차례도 자동으로
  체크 처리한다(런아웃) — 강제 장치: 장치 없음(런아웃 자동 체크 자체를 겨냥한 테스트 없음.
  관련: `tests/test_poker_full.py::test_5_1_fold_then_bots_complete`)
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
- 프론트 `useEventQueue`는 `events[]`를 소비해 지연 재생한다. `action` 이벤트만
  "생각 중"(THINKING_RATIO 구간) → 배지 표시 2단계이고, 나머지 이벤트는 단일 지연 후
  즉시 다음으로 넘어간다. `chips_after`가 실린 이벤트(`action`/`blind`/`winner`)만
  표시 칩을 갱신한다 — 원본: `web/src/hooks/useEventQueue.ts`
- 이벤트 → 배지 텍스트/좌석 커밋 레이블 판단은 순수 함수로 분리돼 있다
  (`web/src/hooks/eventQueueLogic.ts`: `formatBadge`, `makeCommitLabel`, `commitEffectFor`).
  타이머 스케줄링(`useEventQueue.ts`)은 이 함수들의 결과를 언제 반영할지만 맡는다 —
  이벤트 순서·텍스트 회귀는 vitest로 검증 — 강제 장치:
  `web/src/hooks/__tests__/eventQueueLogic.test.ts`
- `isReplaying`은 별도 state가 아니라 `queue.length > 0`으로 매 렌더 파생한다(전에는
  `enqueue`/effect 두 곳에서 따로 동기화해 set-state-in-effect 린트 위반의 원인이었다).
  큐가 이벤트 있음↔없음으로 전환될 때의 하이라이트 리셋(activePlayer/isThinking/badge/
  bettingPlayer)도 `useEffect`가 아니라 렌더 중 조정 패턴(prevQueueEmpty 비교)으로 처리—
  근거: 2026-09-26 리뷰 W9
- API 오류: FastAPI 422의 `detail`은 배열이라 그대로 `Error`에 넘기면 배너에
  "[object Object]"가 뜬다 — `web/src/api.ts::formatApiError`가 `loc`/`msg`를 사람이 읽는
  한 줄 문장으로 평탄화한다 — 강제 장치: `web/src/__tests__/api.test.ts`
- `GtoRange.raise_size`는 `number | null`이다(서버 `raise_size: Optional[float]`,
  bb 단위 실측값). 패널은 값이 있을 때만 "(N bb)"로 표시 — 원본: `web/src/types.ts`,
  `web/src/components/GtoPanel.tsx`

## 화면·경로·데이터

| 모듈 | 역할 |
|---|---|
| `core/game.py` | 게임 엔진 본체(`TexasHoldem`) — 베팅 라운드, 팟 분배, 포지션, 프리플랍 시퀀스 |
| `core/{card,deck,player,evaluator}.py` | 카드·덱·플레이어·핸드 평가 |
| `server/session.py` | `WebGameSession` — 스텝 방식 진행, 이벤트 큐, 에퀴티/평가/GTO 연결, 사이드팟 승자 계산 |
| `server/main.py` | FastAPI 라우터(게임 엔드포인트 + GTO 관리 API) |
| `server/schemas.py` | 응답/이벤트 Pydantic 모델 |
| `web/src/hooks/useEventQueue.ts` | 이벤트 큐 리플레이(지연·배지·칩 애니메이션, 타이머 스케줄링) |
| `web/src/hooks/eventQueueLogic.ts` | 이벤트 → 배지/커밋 레이블 판단(순수 함수, vitest 대상) |
| `web/src/api.ts` | fetch 래퍼 + 422 detail 배열 평탄화(`formatApiError`) |
| `db/recorder.py` | 핸드/액션 RL 기록(세션과 별개 관심사, 실패해도 게임 진행에 영향 없음) |

엔드포인트(이름·용도 한 줄. 필드 원본: `server/schemas.py`, `https://localhost:8765/docs`):

| 엔드포인트 | 용도 |
|---|---|
| `POST /game/start` | 세션 생성, 첫 핸드 시작 후 사람 차례까지 자동 진행 |
| `GET /game/{id}/state` | 현재 `GameState` 조회 |
| `POST /game/{id}/action` | 사람 액션 제출 → 봇 자동 처리 → 다음 상태 |
| `POST /game/{id}/next-hand` | `hand_over=true`일 때 다음 핸드 시작 |
| `GET /session/{id}/review` | 세션 누적 플레이 평가 요약 |

GTO 관리 API(`/gto/preflop/*`)는 이 문서 담당이 아니다 — 규칙은 [`docs/spec/gto-preflop.md`](gto-preflop.md).

포트·프로토콜: 백엔드 `https://localhost:8765`(HTTPS 필수), 프론트 `http://localhost:5766` —
근거: [0025](../decisions/0025-ports-and-https.md)

## 알려진 한계

- 사이드팟별 승자 표시는 서버 계산(`_calculate_side_pots`)까지만 되어 있고, 프론트
  `HandResult` UI에는 아직 팟별 분해가 노출되지 않는다(팟은 합산 지급되어 결과는 맞지만
  화면에 계층이 안 보임).
- 런잇트와이스는 미구현.
- 이벤트 순서·카드 공개 규칙은 코드 동작으로만 보장되고(위 규칙들), 이벤트 스키마
  전체에 대한 전수 불변식 테스트는 없다.
- `GameState.gto_hint`/`gto_key`는 서로 다른 판정 경로(advisor vs `action_log` 문자열
  매칭)를 쓴다 — GTO 도메인 사안이라 `docs/spec/gto-preflop.md`의 한계로 다룬다.
