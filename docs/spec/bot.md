# AI 봇 — 현재 사양

> 최종 갱신: 2026-10-02 · 관련 결정: [0049](../decisions/0049-grader-vs-range-symmetric-band.md), [0039](../decisions/0039-grader-uncertainty-band.md), [0014](../decisions/0014-difficulty-is-mc-resolution.md), [0034](../decisions/0034-abolish-equity-cache.md), [0045](../decisions/0045-equity-precision-1pp-adaptive-mc.md), [0015](../decisions/0015-aggression-margin.md), [0016](../decisions/0016-bot-validation-arena-legacy.md), [0023](../decisions/0023-postflop-range-narrowing.md), [0004](../decisions/0004-raise-size-measured.md), [0005](../decisions/0005-100bb-and-headsup-sb.md), [0007](../decisions/0007-structured-preflop-seq.md)
> 에퀴티 계산: [equity.md](equity.md) · 프리플랍 GTO 조회 규칙: [gto-preflop.md](gto-preflop.md)

## 무엇을 하는가

`ai/bot.py` `PokerBot.decide_action(game_state)`가 봇 한 명의 액션 `(Action, 금액)`을 정한다.
프리플랍은 GTO 데이터를 확률적으로 따르고, 데이터가 없으면 핸드 강도 휴리스틱. 포스트플랍은 equity(승률) 추정 vs 팟오즈로 판단한다.
같은 코드가 웹 게임 봇, 아레나·튜닝·회귀 도구, 사람 액션 평가(Play Grader)에 쓰인다.

## 규칙 (지금 유효한 것만)

### 난이도·페르소나
- 난이도는 **같은 로직, 다른 해상도**다. 포스트플랍 equity(vs 랜덤·레인지 반영 공통): easy는 고정 MC 40샘플(1σ 최대 약 8%p로 자연스럽게 실수), medium·hard는 적응형 MC(1σ ≤ 1%p, 500~2,500샘플, [equity.md](equity.md)). 리버 1:1 전수조사는 모든 난이도가 쓴다(`smart_equity`가 결정). hard만 상대 레인지 반영(`ranged_equity`)을 쓴다. 프리플랍 GTO 준수율 40% / 70% / 95%. 일부러 틀리는 규칙은 두지 않는다 — 근거: [0014](../decisions/0014-difficulty-is-mc-resolution.md), [0045](../decisions/0045-equity-precision-1pp-adaptive-mc.md) · 강제 장치: `tests/test_equity.py::test_mc_precision`(easy 40샘플은 목표보다 거칠고 적응형은 목표 이내) (수치 원본: `ai/bot.py` `POSTFLOP_PROFILES`의 `sims`, `GTO_COMPLIANCE`)
- 봇 판단은 DB를 열지 않는다(에퀴티 캐시 폐기) — 근거: [0034](../decisions/0034-abolish-equity-cache.md) · 강제 장치: `tests/test_equity.py::test_no_db_writes`(medium 봇 판단 중 `sqlite3.connect` 0회)
- 페르소나는 난이도 프로파일 위에 얹는 가산(콜/레이즈/밸류 기준)·배율(블러프·세미블러프 빈도, 벳 사이즈) 보정이다. 튜닝 오버라이드가 최우선 — 강제 장치: 장치 없음
- 웹 게임은 난이도 하나를 전 봇에 적용하고, 페르소나는 좌석 고정: Alpha=tight, Beta=loose, Gamma=aggressive, Delta=passive, Epsilon=balanced (`server/session.py`) — 강제 장치: 장치 없음

### 프리플랍
- GTO 조회·노드 선택은 advisor가 한다(규칙은 [gto-preflop.md](gto-preflop.md) "게임 중 조회"). 봇은 `random() > 준수율`이면 GTO를 쓰지 않는다 — 강제 장치: 장치 없음
- GTO를 안 쓰거나 결과가 없을 때: 프리플랍 레이즈가 3회 이상이면 강한 패만 올인·나머지 폴드(콜 비용 0이면 체크), 아니면 핸드 강도 휴리스틱 — 강제 장치: 장치 없음
- 레이즈 사이즈는 GTO 실측 `raise_size`(bb)가 우선이고, 없을 때만 폴백 공식(오픈 2.5bb / 오픈 상대 ×3 / 그 이상 ×2.5, 스택 70%↑ 올인)을 쓴다 — 근거: [0004](../decisions/0004-raise-size-measured.md) · 강제 장치: 장치 없음

### 포스트플랍
- equity: hard는 상대 레인지 정보가 하나라도 있으면 `ranged_equity`, 없으면(모두 unknown) `smart_equity`(vs 랜덤). easy·medium은 항상 `smart_equity` — 근거: [0014](../decisions/0014-difficulty-is-mc-resolution.md) · 강제 장치: 장치 없음
- 상대 레인지(hard·에퀴티 패널 공용, `opponent_range_info`)는 core가 넣는 구조화 `preflop_seq`(`[{position, action, amount_bb}]`, 블라인드 제외)만으로 정한다. 한글 `action_log`는 읽지 않으므로 CLI(core `_get_game_state()`)와 웹 세션이 같은 라인에서 같은 레인지를 쓴다. 이름→포지션은 `players[].position` — 근거: [0007](../decisions/0007-structured-preflop-seq.md) · 강제 장치: `tests/test_equity.py::test_range_cli_web_same`(UTG 오픈→HJ 3벳→CO 콜→UTG 콜을 core 상태와 세션 상태로 만들어 상대별 role·레인지·`_count_raises` 동일), `git grep action_log ai/` 0건
  - 레이즈 = `raise`, 또는 그때까지 최고 베팅(시작 1bb)보다 높은 `allin`. 최고 베팅 이하의 올인(콜도 다 못 낸 숏스택)은 콜이다. 프리플랍 레이즈 횟수(`_count_raises`, 3회 이상이면 4벳+ 대응)도 같은 기준으로 올인을 센다
  - 오프너(첫 레이즈) → 그 포지션 RFI 레이즈 레인지. 3벳터(처음 올린 레이즈가 두 번째) → "3벳터 vs 오프너 open" vs_open 노드의 레이즈(+올인) 빈도 레인지(RFI로 대신하지 않는다). 4벳 이상을 처음 올린 사람 → 데이터 없음(랜덤). 오픈 뒤 콜한 사람 → 그 오프너 상대 콜 레인지. 오픈 전 콜(림프)만 한 사람·림프 팟 → 랜덤. 오프너가 3벳에 콜하거나 4벳해도 RFI 레인지다
  - 레인지는 GTO 빈도가 가중치(빈도 ≤ 2%인 핸드 제외). 반환 role은 raiser/caller/unknown이고 **레인지 데이터를 못 찾은 상대는 역할과 무관하게 `unknown`**(패널이 role 문자열을 그대로 보여주므로) — 강제 장치: `tests/test_equity.py::test_three_bettor_range`(격리 DB에 UTG RFI·HJ vs UTG open을 심고 UTG 오픈→HJ 3벳: HJ = raiser·vs_open 레이즈 빈도 가중, 노드 없으면 unknown), `::test_range_from_preflop_seq`(레이즈 번호·림프·올인 셈), `::test_ranged_equity`(샘플러·콤보 수·블로커), `::test_role_unknown_without_range`(데이터 없는 레이저·콜러 = unknown)
- 헤즈업 딜러 라벨 `BTN/SB`는 레인지 조회 시 `SB`로 바꾼다(레이저·콜러 본인과 오프너 모두). BTN/SB 오픈 → SB RFI 레인지, BTN/SB 오픈에 BB 콜 → BB vs SB 콜 레인지 — 근거: [0005](../decisions/0005-100bb-and-headsup-sb.md) · 강제 장치: `tests/test_equity.py::test_headsup_range_uses_sb`(순수 함수 + 헤즈업 세션 패널 vs_range)
- 벳을 받으면: equity가 레이즈 기준 이상이면 레이즈(트랩 빈도만큼 콜) → 드로우면 포지션 가중 세미블러프 레이즈 → 아니면 `equity ≥ 팟오즈 + 콜 마진 + 어그레션 마진 × min(벳/팟, 1.2)`이면 콜, 아니면 폴드. 드로우는 마진 −0.04(임플라이드 오즈) — 근거: [0015](../decisions/0015-aggression-margin.md) · 강제 장치: `tests/test_equity.py::test_bot_decisions`(넛 폴드 없음, 트래시 폴드, 좋은 오즈 드로우 폴드 없음)
- 팟오즈(포스트플랍·프리플랍 휴리스틱)는 유효 콜·유효 팟 기준이다(`core/pot_odds.effective_call_pot`, 패널·Play Grader와 같은 함수). game_state에는 이번 스트리트 기여(`players[].current_bet`)만 있어 스트리트 기준으로 넘긴다 — 액션 중인 플레이어는 이전 스트리트를 모두 맞췄으므로 핸드 전체 기준과 같다. 어그레션 마진의 벳/팟은 캡하지 않은 원래 벳 크기(상대 레인지 신호)다 — 강제 장치: `tests/test_equity.py::test_bot_decisions`(스택 100이면 1,000 올인에 콜, 스택 5,000이면 폴드)
- 어그레션 마진의 벳/팟(`facing_bet_ratio`) = 공격자의 이번 스트리트 벳(current_bet) ÷ 공격자가 액션하기 직전 팟(팟 − current_bet만큼 넣은 사람들의 이번 스트리트 벳). 레이즈를 받아도 실제 레이즈 크기로 본다: 팟 100에 내가 50 벳, 상대 150 레이즈 → 1.0. 공격자가 그 스트리트 첫 액션이라고 가정한다(벳-3벳 전쟁에선 약간 과대) — 강제 장치: `tests/test_equity.py::test_bot_decisions`(bet_ratio 4사례 + 팟 크기 레이즈에 A-high 폴드)
- 벳이 없으면: equity ≥ 0.85 → 크게 벳(트랩 빈도만큼 체크) / 밸류 기준 이상 → 30% 체크 믹스, 드라이 보드 33% 팟·웻 보드 66~85% 팟 / 드로우 세미블러프 / equity < 0.30이면 포지션·상대 수로 나눈 순수 블러프(리버 ×1.2) / 나머지 체크 — 강제 장치: `tests/test_equity.py::test_bot_decisions`(트래시 대부분 체크, hard 세미블러프 발생)
- 드로우 = 현재 하이카드(`made_hand_rank` ≤ 1)이고 아웃이 있는 핸드(`has_draw`: 홀+보드 같은 수트 4장 플러시 드로우 / 랭크 비트마스크에 한 장을 더하면 5연속이 되는 OESD·거트샷). 백도어·리버는 드로우가 아니다. 오버카드만으로는 드로우가 아니다(AK on Q72r). 멀티웨이는 상대 1명 추가마다 밸류·레이즈 기준 +4%p — 근거: [0049](../decisions/0049-grader-vs-range-symmetric-band.md) · 강제 장치: `tests/test_equity.py::test_has_draw`(AK on Q72r 아님·98s on 762 OESD·A5 on K43 거트샷·플러시 드로우·백도어 아님, KQ on J72r medium 벳 0), `::test_made_hand_rank`
- 봇은 콜할 금액이 0이면 어떤 경로의 폴드도 체크로 바꾼다(오픈 폴드 금지, `decide_action` 마지막 가드) — 강제 장치: `tests/test_equity.py::test_bot_no_open_fold`
- 포지션 점수 = 살아 있는 사람 중 포스트플랍 액션 순서(0.0 첫 ~ 1.0 마지막, 헤즈업은 BTN/SB가 마지막). 블러프·세미블러프 빈도에 곱한다 — 강제 장치: `tests/test_equity.py::test_bot_decisions`
- 보드 텍스처 `board_wetness` 0~1: 같은 수트 수·4갭 안 3장 연결로 가산, 페어 보드 감산 — 강제 장치: `tests/test_equity.py::test_board_wetness`
- 포스트플랍 베팅에 따른 레인지 좁히기는 아직 없다(어그레션 마진으로 근사). 확장 방향은 2-레이어(랭킹 엔진 / 교체 가능한 컷오프 정책), 플랍 첫 벳/레이즈부터, 고정 컷오프(A안)부터 — 근거: [0023](../decisions/0023-postflop-range-narrowing.md) · TODO E-2

### 플레이 평가 (Play Grader, `gto/grader.py` + `server/session.py`)
- 사람 액션만, 액션 적용 **전**의 팟·베팅으로 평가한다. 아레나처럼 `equity_enabled=False`인 세션은 평가·패널 계산을 건너뛴다 — 강제 장치: `tests/test_grader.py::test_session_equity_and_review`
- 프리플랍: GTO 최빈 액션 = ✅, 선택 빈도 > 25% 🟡, 5~25% 🟠, < 5% 🔴, 데이터 없음 ⬜ — 강제 장치: `tests/test_grader.py::test_preflop_grading`, `tests/test_equity.py::test_grader`
- 포스트플랍 입력은 **패널과 같은 vs_range**다: 세션이 `range_applied`이면 `ranged_equity_detail`의 값과 표준오차를 grader에 넘기고, 레인지를 아는 상대가 없으면 vs_random(그때의 vs_range)을 넘기며 사유에 "상대 레인지 모름(랜덤 기준)"이 붙는다. 복기 항목·액션 기록의 `equity`는 판정에 쓴 값이다 — 근거: [0049](../decisions/0049-grader-vs-range-symmetric-band.md) · 강제 장치: `tests/test_grader.py::test_grader_uses_vs_range`(QQ on 742 vs {AA,KK} 콜: 복기 equity = 패널 vs_range·🔴, 레인지 없으면 vs_random·✅·문구)
- 콜·폴드는 **대칭**이다(고정 마진 없음): 경계 밖에서 콜은 `EV = equity×(유효 팟+유효 콜) − 유효 콜`이 음수면 🔴 + 손실 bb, 폴드는 equity > 유효 팟오즈면 🔴 "놓친 EV". 벳/레이즈/체크는 폴드 에퀴티를 모르므로 제한 판정(equity > 0.7 체크 ⚠️, < 0.3 레이즈 🟡 블러프, 그 외 ⬜) — 근거: [0049](../decisions/0049-grader-vs-range-symmetric-band.md) · 강제 장치: `tests/test_grader.py::test_postflop_call_grading`, `::test_postflop_fold_grading`(팟오즈 33.3%에 0.36/0.34/0.30 폴드 = 🔴/⬜/✅, 콜은 거울상), `::test_postflop_bet_grading`, `::test_grader_symmetry_stats`(정규분포 σ=1%p 시뮬 2,000회: −3%p 콜 🔴 84%, +3%p를 버린 폴드 🔴 84%, 본전 ⬜ 95%)
- 콜·폴드 판정의 팟·콜은 유효값이다: 세션이 `stack=(내 남은 칩, 내 핸드 기여, 다른 모두의 핸드 기여)`를 넘기고 grader가 `core/pot_odds.effective_call_pot`으로 캡한다. 예: 팟 100, 상대 1,000 올인, 내 스택 100, 에퀴티 40% → 콜 EV +20 ✅ — 강제 장치: `tests/test_grader.py::test_short_stack_effective_call`(순수 함수 + 세션 `_get_equity_info`/`_grade_human_action` 경로)
- **경계 구간**: 콜·폴드 모두 |에퀴티 − 유효 팟오즈| < **max(2×표준오차, 1%p)**면 ✅/🔴 대신 ⬜ "경계 — 거의 본전"이다(`gto/grader.py::band_width`). 표준오차는 세션이 vs_range를 만든 계산(`EquityResult`)으로 `ai.equity.standard_error`를 구해 넘긴다(`vs_range_se`): MC는 sqrt(p(1−p)/N)(약 1%p → 경계 ±2%p), 전수(리버 1:1)·프리플랍 테이블은 0이라 최소 경계 1%p만 적용된다. 콜·폴드 사유에는 항상 "에퀴티 x% · 팟오즈 y% · 표본 오차 ±z%p · 경계 ±w%p"(전수는 "표본 오차 0(전수)")가 붙는다. 2σ 구간이라 정확히 손익분기인 스팟도 약 5%는 경계 밖(✅/🔴)으로 나온다 — 근거: [0039](../decisions/0039-grader-uncertainty-band.md)(경계 구간), [0049](../decisions/0049-grader-vs-range-symmetric-band.md)(최소 1%p) · 강제 장치: `tests/test_grader.py::test_borderline_band`(순수 함수 경계 안/밖, 전수 0.3%p·0.7%p = ⬜·2.3%p = 🔴, 턴 1:1 손익분기 콜·폴드 40회 반복 ⬜ ≥ 36, 8%p 나쁜 콜 10회 전부 🔴, 세션 `_grade_human_action` 경로 사유 문구)

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
| `players_state`/액션 기록의 `equity` | 봇은 직전 포스트플랍 결정 equity(프리플랍 None), 사람은 평가에 쓴 vs_range(레인지 없으면 vs_random과 같음) | `db/recorder.py` |
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
좌석 문법: `프로파일[:persona=X][:키=값+키=값]`, 프로파일은 easy/medium/hard/legacy. 튜닝은 그라인드와 동시에 돌리지 않는다(CPU·DB 경합, hook이 에이전트 실행분을 막는다).

## 알려진 한계

- 상대 레인지는 프리플랍 첫 레이즈 노드의 근사다: 림프 뒤 오픈도 RFI(ADR 0046의 vs_limp 노드 아님), 콜러가 낀 3벳(스퀴즈)도 콜러 없는 vs_open 노드, 3벳에 콜한 오프너도 RFI, 3벳에 콜드콜한 사람도 오프너 상대 콜 레인지 — E-2(레인지 출발점)
- medium 봇 포스트플랍 EV는 vs_random 기준이다(3벳팟에서 과대, 어그레션 마진으로 근사). 패널·Play Grader는 vs_range다 — T-005(아레나 측정 뒤)
- 복기 경계의 최소 1%p는 레인지 추정의 모델 오차를 대신하는 고정값이다(실측값 아님)
- 포스트플랍 베팅 기반 레인지 좁히기 없음 — E-2
- medium·hard의 포스트플랍 판단 1회가 약 15~23ms(적응형 MC, 이전 캐시·MC 300~1,200 시절 2.5~9ms)라 아레나 처리량이 그만큼 줄었다 — 측정 `scripts/bench_equity.py`, 수치는 [equity.md](equity.md)
- 벳/레이즈 평가는 제한 판정뿐(폴드 에퀴티 모름)
