# 웹 게임 흐름·API — 현재 사양

> 최종 갱신: 2026-10-01 · 관련 결정: [0025](../decisions/0025-ports-and-https.md), [0038](../decisions/0038-action-validation-and-real-amounts.md), [0043](../decisions/0043-restore-session-on-reload.md), [0047](../decisions/0047-rules-live-in-core.md)
> 룰(행동 순서·재오픈·사이드팟·버튼)은 [game-rules.md](game-rules.md)가 주인이다. 여기는 그 룰을 HTTP 요청·이벤트·화면으로 옮기는 규칙만 둔다.

## 무엇을 하는가

`server/`가 core 엔진([game-rules.md](game-rules.md))을 HTTP 요청 단위로 감싸 웹 세션(`WebGameSession`)을 운영한다: 사람이 액션 1회를
보내면 서버가 봇 전원을 자동 처리해 다음 사람 차례(또는 핸드 종료)까지 진행한 뒤 `GameState`
하나로 응답한다. 응답에 함께 실리는 `events[]`가 프론트 `useEventQueue`의 단계별 리플레이 애니메이션
소스다.

## 규칙 (지금 유효한 것만)

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
  끝난 것으로 본다(core `round_over`, 사람·봇 공통). 남은 스트리트는 액션 이벤트 없이
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
- **재생 표시 상태는 하나다**: 응답이 오면 서버 최종 상태를 바로 그리지 않는다. 재생
  중에는 "요청 직전 상태 + 지금까지 소비한 이벤트"로 만든 표시 상태(`DisplayState`)만 테이블에
  그린다 — 팟·스트리트 라벨·보드 카드 수·로그 줄 수·좌석 칩/베팅/폴드/올인/받은 카드 수가 모두
  순수 리듀서 `eventQueueLogic.applyEvent`에서 나오고 `projectState(next, display)`로 GameState
  하나가 된다. 그래서 폴드 후 봇들이 진행하는 동안 팟·스트리트·베팅액이 애니메이션과 같은 시점에
  바뀐다. 새 핸드의 시작점은 블라인드 전(칩 = 직전 핸드 종료 칩, 팟 0, 카드 0장), 이어지는
  액션의 시작점은 요청 직전 상태다. 스킵은 남은 이벤트를 한 번에 소비한다(최종 상태와 같음).
  로그는 서버가 끝 30줄(`action_log[-30:]`)만 보내므로 **끝 기준으로** 자른다: 아직 소비하지 않은
  이벤트의 로그 줄 수(`logPending`)만큼 `next.action_log` 끝에서 숨겨, 30줄이 넘는 핸드에서도 매
  시점 마지막 줄 = 마지막으로 소비한 이벤트의 로그다 —
  강제 장치: `web/src/hooks/__tests__/replayDisplay.test.ts`(실제 세션 응답 픽스처, 생성 `tests/make_replay_fixture.py`
  `fixtures/replay_session.json`: 시작 화면 = 직전 상태, 팟 = 이벤트 `pot_after`, 스트리트·보드는
  해당 이벤트에서만, 봇 베팅은 그 봇 액션부터, 전부 소비 = 서버 최종 상태, 스킵 동일, 새 핸드,
  "재생 중 로그는 끝 기준으로 자른다")
- 구조화 로그 `log_entries`: 게임 상태는 `action_log`(문자열, 끝 30줄)와 함께 같은 창의
  `log_entries: [{text, street, board, hero_cards}]`를 싣는다 — `action_log`와 1:1(같은 길이, `text` = 같은 위치
  문자열), `street`·`board`(그 줄이 생긴 시점까지 깔린 커뮤니티 카드)·`hero_cards`(사람 홀카드)는 그 줄을 쓸
  때의 값이다. 스트리트 헤더 줄("── 플랍 ──")은 카드를 깐 뒤 기록하므로 새 보드를, 승리 줄은 최종 보드를 싣는다.
  세션은 로그를 `_append_log` 한 곳에서만 쌓는다 — 원본: `server/session.py::_append_log`, `server/schemas.py::LogEntry`
  · 강제 장치: `tests/test_poker_full.py::test_8_32_log_entries_carry_board_and_hero_cards`,
  `::test_8_33_log_entries_window_matches_action_log_tail`
- 로그 화면(사이드 "📋 로그" 탭): 줄마다 오른쪽에 그 시점의 내 핸드 | 보드를 작게 보인다(♥♦ 빨강). 재생 중에는
  `projectState`가 `log_entries`도 `action_log`와 같은 개수(`logPending`)만큼 끝에서 숨기고, 줄의 보드는 지금
  화면 보드 장수까지만 보인다(`street_start`가 `community_card`보다 먼저 소비되므로 아직 안 깔린 카드를 로그가
  먼저 보이지 않게). `log_entries`가 없거나 길이·텍스트가 어긋나면 텍스트만 보인다. 로그 영역은 내용만큼
  늘어나고 사이드 패널 높이(좁은 화면은 60vh)를 넘으면 안에서 스크롤한다. 우상단 "복사" 버튼은 로그 텍스트만
  (카드 표시 없이 줄바꿈으로 이어) `navigator.clipboard`에 넣고 잠깐 "복사됨"을 보인다. 클립보드 실패·미지원은
  조용히 무시 — 원본: `web/src/components/actionLogLogic.ts`, `web/src/components/ActionLog.tsx` · 강제 장치:
  `web/src/components/__tests__/actionLogLogic.test.ts`(줄 구성·보드 자르기·복사 문자열·클립보드 실패),
  `web/src/hooks/__tests__/replayDisplay.test.ts`("log_entries … 1:1을 유지한다"), 늘어나는 높이는 장치 없음
- 이벤트 페이로드: `blind`/`action`은 `pot_after`(이벤트 직후 팟)·`bet_after`(그 플레이어의
  이번 스트리트 베팅), `street_start`는 `pot_after`를 싣는다. `winner` 이후 표시 팟은 0 — 강제
  장치: `tests/test_poker_full.py::test_8_12_session_fuzz_event_amounts_and_conservation`(누적 이동액
  = `pot_after`, 스트리트 누적 = `bet_after`, 사람 차례 팟 = 실제 팟)
- 힌트 패널(에퀴티·GTO)과 액션 바는 재생 중 **재생 직전 상태**를 유지한다(`panelState`). 새
  에퀴티(아직 안 깔린 카드 반영)·새 GTO 노드 조회는 재생이 끝난 뒤에만 보인다 — 강제 장치:
  `web/src/hooks/__tests__/replayDisplay.test.ts`("힌트 패널은 재생이 끝날 때까지 이전 값")
- 헤더: 핸드 번호는 `panelState`(재생 직전 상태)에서 읽어 재생이 끝난 뒤 바뀐다. 세션 요약
  "GTO N% · EV 손실 N.Nbb"는 핸드가 끝나고 **그 재생도 끝난 뒤에** `GET /session/{id}/review`로
  받는다(`shouldFetchReview`). 서버 `total_ev_loss_bb`·`ev_loss_bb`는 양수 = 손실 크기라 헤더에 "+"를
  붙이지 않는다 — 원본: `web/src/reviewLogic.ts` · 강제 장치: `web/src/__tests__/reviewLogic.test.ts`,
  `web/src/hooks/__tests__/replayDisplay.test.ts`("헤더 핸드 번호는 재생이 끝난 뒤에 바뀐다")
- 결과 창: 승자 줄("🏆 이름 승리"), 쇼다운 패, 내 칩, 복기 줄. 복기 줄의 손실은 "−N.Nbb"(빨강,
  `evLossText` — 손실 없음·판정 안 함은 표시 없음). `GameState.pots`(팟 계층: `amount`·`eligible`·
  `winners`·`returned`)에 계층이 2개 이상이면 계층별 줄을 보인다 — 첫 일반 계층 "메인 팟 — 금액 —
  승자", 이후 "사이드 팟 k — 금액 — 승자", `returned=true`(아무도 콜하지 않은 초과 베팅)는 "반환 N →
  이름". `pots`가 없거나 null이거나 계층이 하나면 승자 줄만 보인다. 화면의 이름은 봇 접두사 "🤖 "를
  뗀 표시 이름(`format.ts::displayName`) — 원본: `web/src/components/handResultLogic.ts` · 강제 장치:
  `web/src/components/__tests__/handResultLogic.test.ts`, `web/src/__tests__/reviewLogic.test.ts`
  (렌더링 테스트 없음)
- 타이밍(`eventTiming`): 봇 `action`은 "생각 중"(THINKING_RATIO 구간) → 표시 반영 + 배지 →
  다음. **사람 자신의 액션은 "생각 중" 없이 즉시 반영**하고 배지만 `HUMAN_ACTION_MS`(350ms)
  보인다(봇만 연출). `deal_card`는 지연 끝에 반영, 그 밖의 이벤트는 시작하자마자 반영하고 지연 후
  다음으로 — 강제 장치: `web/src/hooks/__tests__/replayDisplay.test.ts`("이벤트 타이밍")
- 이벤트 → 배지 텍스트/좌석 커밋 레이블(`formatBadge`, `makeCommitLabel`)도 같은 모듈의 순수
  함수다. `useEventQueue.ts`는 언제 반영할지(타이머)와 하이라이트 연출(생각 중·배지·칩 날아가기)만
  맡는다 — 강제 장치: `web/src/hooks/__tests__/eventQueueLogic.test.ts`
- `isReplaying`은 `queue.length > 0`으로 매 렌더 파생한다. 큐가 비는 순간의 하이라이트 리셋은
  렌더 중 조정 패턴(prevQueueEmpty 비교)으로 처리
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
- 새 게임: "새 게임"을 누르면 이전 게임의 세션 요약(헤더 GTO%·EV 손실), 오류·만료 표시, 보관된
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
- 레이즈할 수 없는 사람(`GameState.can_raise=false` — 불완전 올인으로 액션이 닫힘, 콜할 상대
  없음, 또는 스택이 콜 이하)에게 `ActionBar`는 레이즈·올인 버튼을 보이지 않는다(눌러도 400이라). 스택이 콜 이하면
  콜 버튼이 "콜 N (올인)"으로 남은 칩 전부를 낸다 — 강제 장치: 서버 `can_raise`는
  `tests/test_poker_full.py::test_8_7_incomplete_raise_allin_call_or_fold_only`, 버튼 판단은
  `web/src/components/__tests__/actionBarLogic.test.ts`(렌더링 테스트 없음)
- API 오류: FastAPI 422의 `detail`은 배열이라 그대로 `Error`에 넘기면 배너에
  "[object Object]"가 뜬다 — `web/src/api.ts::formatApiError`가 `loc`/`msg`를 사람이 읽는
  한 줄 문장으로 평탄화한다 — 강제 장치: `web/src/__tests__/api.test.ts`
- `GtoRange.raise_size`는 `number | null`이다(서버 `raise_size: Optional[float]`,
  bb 단위 실측값). 힌트 패널 상황 라벨은 값이 있을 때만 "(Nbb)"를 붙인다 — 원본: `web/src/types.ts`,
  `web/src/components/hintPanelLogic.ts::situationText`
- 힌트 패널(사이드 "💡 힌트" 탭)은 위에서부터 ① 상황 라벨(예 "HJ vs UTG open (7.5bb)", 근사면
  "(근사)") ② GTO 빈도(노드 전체 레인지 `summary` 막대, 올인·레이즈·콜·폴드 순, 0.1% 미만 제외)
  ③ 내 패 액션 %(advisor 추천 `frequencies` = 그리드에서 내 패 칸의 값, 예 "레이즈 65.0% · 콜 35.0%",
  없으면 레인지의 그 핸드) ④ 에퀴티(큰 숫자·게이지·팟오즈·콜 EV) 순서로만 보인다. 그 밖의 것은
  접힌 "자세히"로 뒤에 둔다 — "에퀴티 자세히"(상대별 1:1·스트리트 추이·출처), "GTO 자세히"(레이즈 비교 한
  줄·13×13 레인지 그리드, 데이터 없음이면 GTO Wizard 수집 링크). GTO 데이터 없음은 ① "포지션 — GTO 데이터
  없음" + ④, 포스트플랍·사람 차례 아님은 ④만, 레인지 로딩·조회 실패는 ②③ 자리에 안내 한 줄. 없는 액션을
  폴드로 채우지 않는다(ADR 0002) — 원본: `web/src/components/hintPanelLogic.ts::hintLayout`,
  `web/src/components/HintPanel.tsx` · 강제 장치: `web/src/components/__tests__/hintPanelLogic.test.ts`
  (순서·문자열. 렌더링 테스트 없음)
- 화면 높이: 넓은 화면(`lg`, 1024px 이상)에서 페이지 전체가 뷰포트 높이(`lg:h-screen`)에 고정되고 페이지
  스크롤이 없다. 액션 바는 메인 열 아래 `shrink-0`이라 항상 보이고, 사이드 패널(로그·힌트)과 테이블 영역은
  넘치면 각자 안에서 스크롤한다 — vs_3bet처럼 액션 갈래가 많은 노드에서도 1080px 높이 화면에서 액션 버튼이
  밀려나지 않는다 — 원본: `web/src/App.tsx` · 강제 장치: 장치 없음(레이아웃 렌더링 테스트 없음)

## 화면·경로·데이터

| 모듈 | 역할 |
|---|---|
| `server/session.py` | `WebGameSession` — core 호출을 HTTP 요청 단위로 나눠 진행(봇 자동 처리), core 결과를 이벤트·로그·RL 기록으로 변환, 에퀴티/평가/GTO 연결 |
| `server/main.py` | FastAPI 라우터(게임 엔드포인트 + GTO 관리 API) |
| `server/schemas.py` | 응답/이벤트 Pydantic 모델 |
| `web/src/hooks/useEventQueue.ts` | 이벤트 큐 재생 타이머·하이라이트 연출 |
| `web/src/hooks/eventQueueLogic.ts` | 재생 표시 상태 리듀서·투영, 패널 상태, 타이밍, 배지/레이블(순수 함수, vitest 대상) |
| `web/src/components/HintPanel.tsx` · `hintPanelLogic.ts` | 힌트 탭 구성(① 상황 ② GTO 빈도 ③ 내 패 ④ 에퀴티 + 접힌 자세히), 순서·문자열은 순수 함수 |
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

- `get_state()`는 게임 상태·이벤트를 바꾸지 않지만, 에퀴티 패널 계산 결과를 결정 지점 단위
  캐시(`_equity_cache`)와 스트리트별 history에 한 번 기록한다(같은 결정 지점 재조회는 같은
  값).
