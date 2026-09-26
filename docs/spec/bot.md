# AI 봇 — 현재 사양

> 최종 갱신: 2026-09-26 · 관련 결정: [0014](../decisions/0014-difficulty-is-mc-resolution.md), [0015](../decisions/0015-aggression-margin.md), [0016](../decisions/0016-bot-validation-arena-legacy.md), [0023](../decisions/0023-postflop-range-narrowing.md), [0004](../decisions/0004-raise-size-measured.md), [0005](../decisions/0005-100bb-and-headsup-sb.md), [0007](../decisions/0007-structured-preflop-seq.md)
> 에퀴티 계산·캐시·워커: [equity.md](equity.md) · 프리플랍 GTO 조회 규칙: [gto-preflop.md](gto-preflop.md)

## 무엇을 하는가

`ai/bot.py` `PokerBot.decide_action(game_state)`가 봇 한 명의 액션 `(Action, 금액)`을 정한다.
프리플랍은 GTO 데이터를 확률적으로 따르고, 데이터가 없으면 핸드 강도 휴리스틱. 포스트플랍은 equity(승률) 추정 vs 팟오즈로 판단한다.
같은 코드가 웹 게임 봇, 아레나·튜닝·회귀 도구, 사람 액션 평가(Play Grader)에 쓰인다.

## 규칙 (지금 유효한 것만)

### 난이도·페르소나
- 난이도는 **같은 로직, 다른 해상도**다. 포스트플랍 MC 샘플 수 easy 40 / medium 300 / hard 1200, 프리플랍 GTO 준수율 40% / 70% / 95%. hard만 리버 1:1 전수조사와 상대 레인지 반영을 쓴다. 일부러 틀리는 규칙은 두지 않는다 — 근거: [0014](../decisions/0014-difficulty-is-mc-resolution.md) · 강제 장치: 장치 없음 (수치 원본: `ai/bot.py` `POSTFLOP_PROFILES`, `GTO_COMPLIANCE`)
- 캐시: easy는 캐시 값을 읽지 않지만 MC 결과는 캐시에 기여한다. medium·hard는 정확값/고정밀 캐시가 있으면 그것을 쓴다 — 강제 장치: 장치 없음
- 페르소나는 난이도 프로파일 위에 얹는 가산(콜/레이즈/밸류 기준)·배율(블러프·세미블러프 빈도, 벳 사이즈) 보정이다. 튜닝 오버라이드가 최우선 — 강제 장치: 장치 없음
- 웹 게임은 난이도 하나를 전 봇에 적용하고, 페르소나는 좌석 고정: Alpha=tight, Beta=loose, Gamma=aggressive, Delta=passive, Epsilon=balanced (`server/session.py`) — 강제 장치: 장치 없음

### 프리플랍
- GTO 조회·노드 선택은 advisor가 한다(규칙은 [gto-preflop.md](gto-preflop.md) "게임 중 조회"). 봇은 `random() > 준수율`이면 GTO를 쓰지 않는다 — 강제 장치: 장치 없음
- GTO를 안 쓰거나 결과가 없을 때: 프리플랍 레이즈가 3회 이상이면 강한 패만 올인·나머지 폴드(콜 비용 0이면 체크), 아니면 핸드 강도 휴리스틱 — 강제 장치: 장치 없음
- 레이즈 사이즈는 GTO 실측 `raise_size`(bb)가 우선이고, 없을 때만 폴백 공식(오픈 2.5bb / 오픈 상대 ×3 / 그 이상 ×2.5, 스택 70%↑ 올인)을 쓴다 — 근거: [0004](../decisions/0004-raise-size-measured.md) · 강제 장치: 장치 없음

### 포스트플랍
- equity: hard는 상대 레인지 정보가 하나라도 있으면 `ranged_equity`, 없으면(모두 unknown) `smart_equity`(vs 랜덤, 캐시 활용). easy·medium은 항상 `smart_equity` — 근거: [0014](../decisions/0014-difficulty-is-mc-resolution.md) · 강제 장치: 장치 없음
- 상대 레인지(hard·에퀴티 패널 공용, `opponent_range_info`): 프리플랍 레이저 → 그 포지션 RFI 레이즈 레인지, 오프너에게 콜한 사람 → 그 오프너 상대 콜 레인지, 그 외 → 랜덤. 레인지는 GTO 빈도가 가중치(빈도 ≤ 2%인 핸드 제외) — 강제 장치: `tests/test_equity.py::test_ranged_equity`(샘플러·콤보 수·블로커. 역할 판정은 장치 없음)
- 헤즈업 딜러 라벨 `BTN/SB`는 레인지 조회 시 `SB`로 바꾼다(레이저·콜러 본인과 오프너 모두). BTN/SB 오픈 → SB RFI 레인지, BTN/SB 오픈에 BB 콜 → BB vs SB 콜 레인지 — 근거: [0005](../decisions/0005-100bb-and-headsup-sb.md) · 강제 장치: `tests/test_equity.py::test_headsup_range_uses_sb`(순수 함수 + 헤즈업 세션 패널 vs_range)
- 벳을 받으면: equity가 레이즈 기준 이상이면 레이즈(트랩 빈도만큼 콜) → 드로우면 포지션 가중 세미블러프 레이즈 → 아니면 `equity ≥ 팟오즈 + 콜 마진 + 어그레션 마진 × min(벳/팟, 1.2)`이면 콜, 아니면 폴드. 드로우는 마진 −0.04(임플라이드 오즈) — 근거: [0015](../decisions/0015-aggression-margin.md) · 강제 장치: `tests/test_equity.py::test_bot_decisions`(넛 폴드 없음, 트래시 폴드, 좋은 오즈 드로우 폴드 없음)
- 팟오즈(포스트플랍·프리플랍 휴리스틱)는 유효 콜·유효 팟 기준이다(`core/pot_odds.effective_call_pot`, 패널·Play Grader와 같은 함수). game_state에는 이번 스트리트 기여(`players[].current_bet`)만 있어 스트리트 기준으로 넘긴다 — 액션 중인 플레이어는 이전 스트리트를 모두 맞췄으므로 핸드 전체 기준과 같다. 어그레션 마진의 벳/팟은 캡하지 않은 원래 벳 크기(상대 레인지 신호)다 — 강제 장치: `tests/test_equity.py::test_bot_decisions`(스택 100이면 1,000 올인에 콜, 스택 5,000이면 폴드)
- 어그레션 마진의 벳/팟(`facing_bet_ratio`) = 공격자의 이번 스트리트 벳(current_bet) ÷ 공격자가 액션하기 직전 팟(팟 − current_bet만큼 넣은 사람들의 이번 스트리트 벳). 레이즈를 받아도 실제 레이즈 크기로 본다: 팟 100에 내가 50 벳, 상대 150 레이즈 → 1.0. 공격자가 그 스트리트 첫 액션이라고 가정한다(벳-3벳 전쟁에선 약간 과대) — 강제 장치: `tests/test_equity.py::test_bot_decisions`(bet_ratio 4사례 + 팟 크기 레이즈에 A-high 폴드)
- 벳이 없으면: equity ≥ 0.85 → 크게 벳(트랩 빈도만큼 체크) / 밸류 기준 이상 → 30% 체크 믹스, 드라이 보드 33% 팟·웻 보드 66~85% 팟 / 드로우 세미블러프 / equity < 0.30이면 포지션·상대 수로 나눈 순수 블러프(리버 ×1.2) / 나머지 체크 — 강제 장치: `tests/test_equity.py::test_bot_decisions`(트래시 대부분 체크, hard 세미블러프 발생)
- 드로우 = 현재 하이카드인데 equity ≥ 0.30 (리버 제외). 멀티웨이는 상대 1명 추가마다 밸류·레이즈 기준 +4%p — 강제 장치: `tests/test_equity.py::test_made_hand_rank`
- 포지션 점수 = 살아 있는 사람 중 포스트플랍 액션 순서(0.0 첫 ~ 1.0 마지막, 헤즈업은 BTN/SB가 마지막). 블러프·세미블러프 빈도에 곱한다 — 강제 장치: `tests/test_equity.py::test_bot_decisions`
- 보드 텍스처 `board_wetness` 0~1: 같은 수트 수·4갭 안 3장 연결로 가산, 페어 보드 감산 — 강제 장치: `tests/test_equity.py::test_board_wetness`
- 포스트플랍 베팅에 따른 레인지 좁히기는 아직 없다(어그레션 마진으로 근사). 확장 방향은 2-레이어(랭킹 엔진 / 교체 가능한 컷오프 정책), 플랍 첫 벳/레이즈부터, 고정 컷오프(A안)부터 — 근거: [0023](../decisions/0023-postflop-range-narrowing.md) · TODO E-2

### 플레이 평가 (Play Grader, `gto/grader.py` + `server/session.py`)
- 사람 액션만, 액션 적용 **전**의 팟·베팅으로 평가한다. 아레나처럼 `equity_enabled=False`인 세션은 평가·패널 계산을 건너뛴다 — 강제 장치: `tests/test_grader.py::test_session_equity_and_review`
- 프리플랍: GTO 최빈 액션 = ✅, 선택 빈도 > 25% 🟡, 5~25% 🟠, < 5% 🔴, 데이터 없음 ⬜ — 강제 장치: `tests/test_grader.py::test_preflop_grading`, `tests/test_equity.py::test_grader`
- 포스트플랍(vs_random equity 기준): 콜은 `EV = equity×(팟+콜) − 콜`이 음수면 🔴 + 손실 bb, 폴드는 equity > 팟오즈 + 0.05면 🔴 "놓친 EV", 벳/레이즈/체크는 폴드 에퀴티를 모르므로 제한 판정(equity > 0.7 체크 ⚠️, < 0.3 레이즈 🟡 블러프, 그 외 ⬜) — 강제 장치: `tests/test_grader.py::test_postflop_call_grading`, `::test_postflop_fold_grading`, `::test_postflop_bet_grading`
- 콜·폴드 판정의 팟·콜은 유효값이다: 세션이 `stack=(내 남은 칩, 내 핸드 기여, 다른 모두의 핸드 기여)`를 넘기고 grader가 `core/pot_odds.effective_call_pot`으로 캡한다. 예: 팟 100, 상대 1,000 올인, 내 스택 100, 에퀴티 40% → 콜 EV +20 ✅ — 강제 장치: `tests/test_grader.py::test_short_stack_effective_call`(순수 함수 + 세션 `_get_equity_info`/`_grade_human_action` 경로)
- 콜 판정 경계(콜 마진 0 vs 폴드 마진 0.05, MC 오차)는 D-29 대기

### 검증·튜닝
- 봇 로직을 바꾸면 `scripts/ai_regression.py`로 legacy(개선 전 휴리스틱 봇) 대비 후퇴가 없는지 확인한다. ±10~20 bb/100은 노이즈 — 근거: [0016](../decisions/0016-bot-validation-arena-legacy.md) · 강제 장치: `scripts/ai_regression.py`(수동, exit 1) — `tests/run_all.py`에 없음
- 튜닝 결과는 `tuning_results.json`에만 쌓이고 봇 코드는 사람이 확인 후 고친다 — 근거: [0016](../decisions/0016-bot-validation-arena-legacy.md) · 강제 장치: 장치 없음
- 아레나는 매 핸드 칩 총량 보존을 검사하고 위반 시 `chip_violations.log`에 재현 정보를 남기고 멈춘다 — 강제 장치: `scripts/bot_arena.py` 내부 assert
- 채택 기준: 3,000핸드 × 시드 3, 개선 전후 차이 ≥ 표준오차 × 2(애매하면 핸드 수 늘려 재측정) — 근거: [0041](../decisions/0041-bot-adoption-criterion.md) · 강제 장치: 없음(측정 절차)

## 화면·경로·데이터

| 대상 | 무엇 | 비고 |
|---|---|---|
| `ai/bot.py` | `PokerBot`, `POSTFLOP_PROFILES`, `PERSONAS`, `opponent_range_info` | 수치 원본 |
| `gto/grader.py` | 평가 순수 함수 | 호출: `server/session.py::_grade_human_action` |
| `core/pot_odds.py` | 유효 콜·유효 팟·팟오즈·콜 EV | 봇·grader·패널 공용 |
| 게임 상태 `hand_review` / `/session/review` | 핸드·세션 평가 결과 | 필드는 FastAPI `/docs` |
| `players_state`/액션 기록의 `equity` | 봇은 직전 포스트플랍 결정 equity(프리플랍 None), 사람은 평가 시 vs_random | `db/recorder.py` |
| `tuning_results.json` | 튜닝 이력(누적, gitignore) | 루트 |
| `chip_violations.log` | 아레나 칩 보존 위반 기록 | 루트 |

### 운영 방법
```bash
python3 scripts/bot_arena.py --hands 600 --seats hard,medium,legacy --seed 99
python3 scripts/bot_arena.py --seats "hard:persona=aggressive,hard:aggression_margin=0.12+bluff_freq=0.3,legacy"
python3 scripts/ai_regression.py [--hands 1000]          # 고정 좌석·시드 99/777, legacy보다 약하면 exit 1
python3 scripts/tune_bot.py --profile hard --param aggression_margin --values 0.04,0.08,0.12 --hands 2000 --seeds 3
python3 scripts/tune_bot.py --profile hard --param semibluff_freq --evolve --start 0.55 --step 0.1 --rounds 5
```
좌석 문법: `프로파일[:persona=X][:키=값+키=값]`, 프로파일은 easy/medium/hard/legacy. 튜닝은 그라인드와 동시에 돌리지 않는다([equity.md](equity.md)).

## 알려진 한계

- 상대 레인지 추정(`opponent_range_info`)과 3벳+ 판정(`_count_raises`)은 아직 한글 `action_log`를 문자열·이름 부분매칭으로 파싱한다(ADR 0007 원칙 미적용). 3벳한 상대도 RFI 레인지로, 올인은 레이저로 취급하고, `_count_raises`는 올인을 세지 않는다 — TODO E-2(레인지 출발점)
- medium 봇과 Play Grader 포스트플랍 EV는 vs_random 기준이다(3벳팟에서 과대) — T-005
- 포스트플랍 베팅 기반 레인지 좁히기 없음 — E-2
- 벳/레이즈 평가는 제한 판정뿐(폴드 에퀴티 모름)
