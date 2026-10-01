# 에퀴티 엔진·패널 — 현재 사양

> 최종 갱신: 2026-10-01 · 관련 결정: [0034](../decisions/0034-abolish-equity-cache.md), [0045](../decisions/0045-equity-precision-1pp-adaptive-mc.md), [0018](../decisions/0018-equity-fast-paths.md)(고속 평가기), [0014](../decisions/0014-difficulty-is-mc-resolution.md), [0022](../decisions/0022-equity-cache-rebuildable-vsrandom-ui.md)(vs_random UI 부분)
> 봇이 equity를 어떻게 쓰는지: [bot.md](bot.md) · DB: [db.md](db.md)

## 무엇을 하는가

`ai/equity.py`가 "내 홀카드 + 보드 vs 상대 N명" 승률을 매번 계산한다. 결과를 어디에도 저장하지 않는다(캐시·워커 없음).
봇의 포스트플랍 판단과 사람에게 보여주는 에퀴티 패널이 이 값을 쓴다.

## 규칙 (지금 유효한 것만)

### 계산 경로 (`smart_equity` / `equity_detail`, vs 랜덤 핸드)
- **프리플랍(상대 1~5명)**: 상수 테이블 `ai/preflop_equity_table.py`(169핸드 × 상대 1~5명 = 845값, 값마다 100만 샘플)를 그대로 쓴다. 샘플 수 인자와 무관하다. 테이블은 `scripts/gen_preflop_table.py`로 현재 엔진에서 다시 만들 수 있다(전체 1~2시간, `--dry-run`은 소수 값만 기존 테이블과 3σ 비교) — 근거: [0034](../decisions/0034-abolish-equity-cache.md) · 강제 장치: `tests/test_equity_verify.py` V-1(공개 기준값 23개 ±0.3%p), `tests/test_equity.py::test_preflop_table`(경로·845값·표기, 테이블 = 현재 MC 3σ+0.40%p 이내)
- **리버 상대 1명**: 전수조사(990조합, 약 3ms). 모든 난이도에서 쓴다(샘플 수를 고정해도 전수) — 근거: [0034](../decisions/0034-abolish-equity-cache.md) · 강제 장치: `tests/test_equity.py::test_equity_paths`, `::test_exact_river`, `tests/test_equity_verify.py` V-2(독립 전수 20스팟과 동일)
- **그 밖(플랍·턴, 리버 멀티웨이)**: 실시간 몬테카를로.
  - 샘플 수를 주지 않으면 **적응형 MC**다(정밀도 목표 1σ ≤ 1%p). 250샘플씩 돌며 500샘플(`MC_MIN_SAMPLES`) 이후 표준오차 `sqrt(표본분산/n)`이 1%p(`TARGET_SE`) 이하가 되면 멈추고, 최대 2,500샘플(`MC_MAX_SAMPLES`)에서 끝낸다.
    - 상한 근거: 샘플 1개의 지분 분산은 최대 0.25(p=0.5, 동률 없음)라 0.25 / 0.01² = 2,500이면 어떤 스팟도 목표를 만족한다(상한 자체가 보장).
    - 시작 500 근거: 표본분산 추정의 상대오차가 약 1/√(2n) ≈ 3%라 조기 종료 판정이 믿을 만하고, 에퀴티가 극단적인 스팟(p=0.95 → 필요 약 475)도 여기서 끝난다.
    - 실측 평균 샘플: 플랍 vs1 약 2,100, vs2 약 1,850, vs5 약 1,200 — 근거: [0045](../decisions/0045-equity-precision-1pp-adaptive-mc.md) · 강제 장치: `tests/test_equity.py::test_mc_precision`(턴 1:1 반복 30회 표준편차 ≤ 1.4%p이고 평균이 전수값과 일치, 플랍 vs2 반복 20회 표준편차 ≤ 1.5%p), `tests/test_equity_verify.py` V-4(고정 시드 턴 1:1 10스팟 × 10회, 전수 대비 rmse ≤ 1.3%p, ±2%p 안 ≥ 93%)
  - 샘플 수를 주면 그 수만큼만 고정 MC다. easy 봇(40)이 해상도를 일부러 낮출 때 쓴다 — 근거: [0014](../decisions/0014-difficulty-is-mc-resolution.md) · 강제 장치: `tests/test_equity.py::test_mc_precision`(easy 40샘플 표준편차 > 3%p), `::test_equity_paths`
- `equity_detail`은 `(equity, source, samples)`를 돌려준다. `source`는 실제로 탄 경로 `"preflop-table"` / `"exact"` / `"mc:N"`이고, `samples`는 테이블 샘플 수(1,000,000) / 전수 조합 수(990) / MC 샘플 수다 — 강제 장치: `tests/test_equity.py::test_equity_paths`
- `standard_error(EquityResult)`는 그 추정의 표준오차(1σ)다: MC는 sqrt(p(1−p)/N)(지분 분산 상한이라 실제보다 같거나 크다), `exact`·`preflop-table`은 0. Play Grader 경계 구간(ADR 0039)이 쓴다. 세션 패널 정보에 `vs_random_se`로 싣되 응답 스키마 밖이다(화면 비표시) — 강제 장치: `tests/test_grader.py::test_borderline_band`
- 에퀴티 계산은 DB를 열지 않는다. `ai/equity.py`는 DB 모듈을 import하지 않는다 — 근거: [0034](../decisions/0034-abolish-equity-cache.md) · 강제 장치: `tests/test_equity.py::test_no_db_writes`(계산·봇 판단 중 `sqlite3.connect` 0회, 세션 패널을 여러 번 계산한 새 DB에 에퀴티 테이블 없음)
- 동률은 나눈 인원으로 나눈다: 나를 포함해 k명이 팟을 나누면 지분 1/k. 카운트 `(wins, ties, total)`와 `(wins + 0.5·ties)/total`을 그대로 쓰려고 ties에 `2/k`를 더한다(헤즈업은 +1). vs 랜덤·레인지 반영, 고정·적응형 MC 공통 — 강제 장치: `tests/test_equity.py::test_multiway_tie_share`(로열 보드 vs2 = 1/3, vs5 = 1/6, 일부만 동률 = 1/2, `smart_equity` 경로 포함)
- 홀-보드 또는 보드 내부에 중복 카드가 있으면 `ValueError` — 강제 장치: `tests/test_guards.py::test_equity_duplicate_cards`, `tests/test_equity.py::test_equity_paths`
- 계산용 평가는 고속 `evaluate_rank`(랭크 카운트 + 수트 비트마스크), 쇼다운 표시용은 `HandEvaluator` — 근거: [0018](../decisions/0018-equity-fast-paths.md) · 강제 장치: `tests/test_equity.py::test_fast_evaluator`(두 평가기 3,000세트 일치), `tests/test_equity_verify.py` V-2(독립 평가기와 랜덤 7장 5,000핸드 동일)
- `exact_counts_turn`(약 4.6만 조합, 약 0.15초)·`exact_counts_flop`(약 107만 조합, 약 3초)은 런타임 경로가 아니라 정밀도 테스트의 정답(기준값)용이다 — 강제 장치: `tests/test_equity.py::test_mc_precision`, `tests/test_equity_verify.py` V-4(턴 정답)

### 레인지 반영 에퀴티 (`ranged_equity`)
- vs 랜덤과 같은 적응형 MC다(1σ ≤ 1%p, 500~2,500샘플). hard 봇·패널 vs_range·상대별 1:1 모두 샘플 수를 주지 않는다. 샘플 수를 주면 고정 MC(easy가 레인지를 켜면 40) — 근거: [0045](../decisions/0045-equity-precision-1pp-adaptive-mc.md) · 강제 장치: `tests/test_equity.py::test_mc_precision`(리버 레인지 2명 반복 30회 표준편차 ≤ 1.4%p이고 평균이 전수 정답과 일치, 플랍 레인지 1명 반복 20회 ≤ 1.5%p)
- 상대 홀카드는 결합분포 Π wᵢ(hᵢ)·[카드 비중복]에서 뽑는다: 각 레인지에서 내 홀·보드와 겹치는 콤보를 먼저 빼고(남는 게 없으면 그 상대는 랜덤), 레인지 상대 전원을 한 번에 뽑아 서로 겹치면 전체를 다시 뽑는다(결합 거절 샘플링, 200회 연속 실패 시 그 샘플만 순차 방식). 랜덤 상대는 남은 카드에서 균등. 상대 순서와 무관하다 — 강제 장치: `tests/test_equity.py::test_ranged_equity`(리버 JJ vs {AA,55}·{AA,66}: 전수 정답 31.6%와 3σ 이내, 순서 바꿔도 동일), `tests/test_equity_verify.py` V-3(독립 전수 3케이스 — 가중치·블로커 교차·랜덤 상대 혼합, 리버 — 와 3σ 이내)

### 에퀴티 패널 (`server/session.py::_get_equity_info`)
- 사람 차례(`waiting_for_action`)이고 `equity_enabled`일 때만 계산한다(아레나는 끔). 같은 결정 지점(스트리트 + 현재 벳)은 재계산하지 않는다 — 강제 장치: `tests/test_poker_full.py` 5-12(`equity_enabled=False`면 계산 안 함) · 같은 지점 재계산 안 함은 장치 없음
- **패널은 vs_range 한 기준이다**: 큰 숫자·게이지·팟오즈 글자 색·콜 EV·스트리트별 추이(history)가 모두 `vs_range`다. `vs_random`은 응답에는 있지만 화면에 보이지 않는다(Play Grader·기록·레인지 없을 때의 값) — 근거: [0022](../decisions/0022-equity-cache-rebuildable-vsrandom-ui.md)(UI 부분), [0034](../decisions/0034-abolish-equity-cache.md) · 강제 장치: `tests/test_grader.py::test_panel_vs_range_basis`(콜 EV·history = vs_range), `web/src/components/__tests__/equityPanelLogic.test.ts`(게이지·색·추이가 vs_range)
- `vs_random`: 살아 있는 상대 수만큼 랜덤 핸드 상대(`equity_detail`, 샘플 수 미지정 → 위 계산 경로). 표준오차는 `vs_random_se`(Play Grader용, 스키마 밖) — 강제 장치: `tests/test_equity.py::test_multiway_tie_share`(리버 3인), `::test_no_db_writes`
- `vs_range`: 상대별 추정 레인지 반영(`ranged_equity_detail` 적응형). 레인지 정보가 있는 상대가 하나도 없으면(`range_applied=false`) vs_random 계산 결과를 그대로 쓰고, 패널 라벨이 "상대 레인지 모름 → 랜덤 핸드"로 바뀐다. **`source`/`samples`는 vs_range를 실제로 만든 계산**이다: 레인지 반영이면 `mc:N`/N(500~2,500), 아니면 vs_random 경로(`preflop-table`/1,000,000 · `exact`/990 · `mc:N`/N). 화면 표기는 "프리플랍 표 · 샘플 1,000,000 · 상대 5명" 식. 상대별 1:1 브레이크다운은 레인지가 있으면 `ranged_equity`, 없으면 랜덤 1:1(`smart_equity`, 정보 없는 상대끼리 한 번만 계산해 공유) — 강제 장치: `tests/test_grader.py::test_panel_vs_range_basis`(레인지 반영 `mc:N`=샘플 수, 레인지 없음 = vs_random 경로), `::test_session_equity_and_review`, `tests/test_equity.py::test_headsup_range_uses_sb`
- 스트리트별 추이는 그 스트리트 **첫 결정**의 vs_range를 한 번 기록한다(같은 스트리트의 두 번째 결정은 추이를 바꾸지 않는다) — 강제 장치: `tests/test_grader.py::test_panel_vs_range_basis`
- 프리플랍에도 사람 차례마다 패널이 나온다(상수 테이블, 앞선 레이저가 있으면 레인지 반영 MC). 서버가 프리플랍에 에퀴티를 비우는 경로는 없다(폴드·홀카드 없음·사람 차례 아님만 `null`) — 강제 장치: `tests/test_grader.py::test_panel_vs_range_basis`(6인 프리플랍 사람 차례에 에퀴티 존재)
- **에퀴티와 GTO가 어긋나는 것은 정상일 수 있다**(패널 라벨의 ⓘ 툴팁 한 줄). 대표 사례: CO가 UTG 2.5bb 오픈을 받음(팟 4bb, 콜 2.5bb → 팟오즈 38.5%). K9s의 UTG 오픈 레인지(약 17%) 상대 에퀴티는 약 40.5%라 콜 EV가 +로 보이지만 GTO는 폴드한다. 에퀴티는 "지금 패로 쇼다운까지 그대로 간다"는 승률이라 ① 뒤에 남은 BTN·SB·BB의 3벳(스퀴즈) ② 도미네이트된 패가 포스트플랍에서 에퀴티를 다 실현하지 못하는 것 ③ 포지션을 반영하지 않는다. 반대로 A5s처럼 콜 EV가 비슷해도 GTO가 3벳하는 건 상대가 접는 몫(폴드 에퀴티)이 에퀴티에 없어서다. 수치는 `ranged_equity`로 손 계산한 값(2026-09-26) — 강제 장치: 툴팁 문구만 `web/src/components/__tests__/equityPanelLogic.test.ts`
- 팟오즈·콜 EV는 **유효 콜·유효 팟** 기준이다(`core/pot_odds.effective_call_pot`, 봇·Play Grader와 같은 함수). 유효 콜 = min(콜, 내 남은 칩), 유효 팟 = 팟 − 각 상대 기여 중 (내 기여 + 유효 콜)을 넘는 부분(폴드한 사람 포함). 세션은 핸드 전체 기여(`total_bet_this_round`)로 계산한다. 예: 팟 100에 상대 1,000 올인, 내 스택 100 → 콜 100·팟 200, 팟오즈 33% — 강제 장치: `tests/test_grader.py::test_short_stack_effective_call`

### 응답 시간
- medium·hard 봇 판단 1회 약 15~23ms, 패널 1회 최대 약 70ms(레인지 정보 없음, 상대 5명 플랍). 측정은 `python3 scripts/bench_equity.py`(경로별 전체 표 출력).
- 상한 회귀: 패널 1회(상대 2명 플랍) 중앙값 < 150ms, hard 봇 판단(플랍 vs2) 중앙값 < 60ms — 근거: [0045](../decisions/0045-equity-precision-1pp-adaptive-mc.md) · 강제 장치: `tests/test_equity_verify.py` V-5

### 확률 검증 장치 (`tests/test_equity_verify.py`, `--full` 전용, 약 5초)
- 외부 기준과 독립 구현으로 숫자를 대조한다. 독립 구현은 `tests/indep_eval.py`(브루트포스 평가기·리버 전수·레인지 결합 전수)이며 프로젝트 코드를 import하지 않는다(같은 버그를 공유하지 않게).
- V-1 공개 프리플랍 기준값 23개(vs1 페어 13개·AKs·AKo·AQs·AQo·AJs·KQs·72o·32o, AA vs2·vs5) ±0.3%p · V-2 평가기·리버 전수 동일성 · V-3 레인지 샘플러 3σ · V-4 적응형 MC 정밀도 회귀 · V-5 응답 시간 상한 — 강제 장치: `tests/run_all.py` `FULL_FILES` 등록

## 화면·경로·데이터

| 대상 | 무엇 |
|---|---|
| `ai/equity.py` | 계산·레인지 샘플러 (`smart_equity`, `equity_detail`, `standard_error`, `mc_adaptive`, `ranged_equity`, `ranged_equity_detail`, `mc_adaptive_ranged`) |
| `ai/preflop_equity_table.py` | 프리플랍 845값 상수 (자동 생성, 수동 편집 금지) |
| `scripts/gen_preflop_table.py` | 상수 테이블 재생성기 — 현재 엔진 `mc_counts`(동률 1/k)로 845값 × 100만 샘플(멀티프로세스, DB 미사용). `--dry-run`은 소수 값만 기존 테이블과 3σ 비교 출력 |
| `tests/indep_eval.py` | 독립 평가기·전수 계산 (프로젝트 import 없음, 검증 장치 전용) |
| `scripts/bench_equity.py` | 응답 시간 측정 (DB 쓰기 없음, 임시 DB로 격리) |
| `core/pot_odds.py` | 에퀴티 → 결정 변환 공용: 유효 콜·유효 팟, 팟오즈, 콜 EV (세션 패널·Play Grader·봇) |

## 알려진 한계

- 프리플랍 테이블의 상대 2~5명 값은 멀티웨이 동률을 1/2로 센 계산이라 현재 엔진(1/k)보다 평균 +0.13%p, 최대 +0.40%p(52o vs2) 높다(독립 MC 30값 × 20만 샘플 실측, vs1은 일치). 정밀도 목표(±1%p) 안이라 그대로 쓴다. 원천 DB가 없어 이 값 그대로는 재현할 수 없고, `scripts/gen_preflop_table.py`를 돌리면(사람이 실행) 편향 없는 값으로 바뀐다.
- 적응형 MC의 조기 종료는 추정한 표준오차로 판정하므로, 실제 1σ가 목표를 약간 넘는 스팟이 드물게 있을 수 있다(상한 2,500에서 끝나면 항상 목표 이내).
- 패널(vs_range, 콜 EV 포함)과 Play Grader 판정(vs_random)은 아직 기준이 다르다 — T-005
- vs_random은 상대가 아무 핸드나 든다는 가정이라 3벳팟 등에서 과대평가 — 봇은 어그레션 마진으로 보정(ADR 0015), 근본 해결은 E-2
