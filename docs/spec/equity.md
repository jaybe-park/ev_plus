# 에퀴티 엔진·패널 — 현재 사양

> 최종 갱신: 2026-09-26 · 관련 결정: [0034](../decisions/0034-abolish-equity-cache.md), [0038](../decisions/0038-adaptive-mc-for-precision-target.md), [0018](../decisions/0018-equity-fast-paths.md)(고속 평가기·보드 테이블), [0014](../decisions/0014-difficulty-is-mc-resolution.md), [0022](../decisions/0022-equity-cache-rebuildable-vsrandom-ui.md)(vs_random UI 부분)
> 봇이 equity를 어떻게 쓰는지: [bot.md](bot.md) · DB: [db.md](db.md)

## 무엇을 하는가

`ai/equity.py`가 "내 홀카드 + 보드 vs 상대 N명" 승률을 매번 계산한다. 결과를 어디에도 저장하지 않는다(캐시·워커 없음).
봇의 포스트플랍 판단과 사람에게 보여주는 에퀴티 패널이 이 값을 쓴다.

## 규칙 (지금 유효한 것만)

### 계산 경로 (`smart_equity` / `equity_detail`, vs 랜덤 핸드)
- **프리플랍(상대 1~5명)**: 상수 테이블 `ai/preflop_equity_table.py`(169핸드 × 상대 1~5명 = 845값, 값마다 100만 샘플)를 그대로 쓴다. 샘플 수 인자와 무관하다 — 근거: [0034](../decisions/0034-abolish-equity-cache.md) · 강제 장치: `tests/test_equity.py::test_preflop_table`(AA vs1 85.2%, AKs 67.0%, 72o 34.6%, AA vs5 49.2%를 ±0.2%p로 대조, 테이블 = 현재 MC 3σ 이내)
- **리버 상대 1명**: 전수조사(990조합, 약 3ms). 모든 난이도에서 쓴다(샘플 수를 고정해도 전수) — 근거: [0034](../decisions/0034-abolish-equity-cache.md) · 강제 장치: `tests/test_equity.py::test_equity_paths`, `::test_exact_river`
- **그 밖(플랍·턴, 리버 멀티웨이)**: 실시간 몬테카를로.
  - 샘플 수를 주지 않으면 **적응형 MC**다. 500샘플씩 돌며 1,000샘플 이후 표준오차 `sqrt(표본분산/n)`이 0.5%p(`TARGET_SE`) 이하가 되면 멈추고, 최대 10,000샘플(`MC_MAX_SAMPLES`)에서 끝낸다. 샘플 1개의 지분 분산은 최대 0.25(p=0.5, 동률 없음)라 10,000이면 어떤 스팟도 1σ ≤ 0.5%p를 만족한다. 실측 평균 샘플: 플랍 vs1 약 8,300, vs2 약 6,400, vs5 약 4,800 — 근거: [0034](../decisions/0034-abolish-equity-cache.md) · 강제 장치: `tests/test_equity.py::test_mc_precision`(턴 1:1 반복 30회 표준편차 ≤ 0.7%p이고 평균이 전수값과 일치, 플랍 vs2 반복 20회 표준편차 ≤ 0.75%p)
  - 샘플 수를 주면 그 수만큼만 고정 MC다. easy 봇(40)이 해상도를 일부러 낮출 때 쓴다 — 근거: [0014](../decisions/0014-difficulty-is-mc-resolution.md) · 강제 장치: `tests/test_equity.py::test_mc_precision`(easy 40샘플 표준편차 > 1.5%p), `::test_equity_paths`
- `equity_detail`은 `(equity, source, samples)`를 돌려준다. `source`는 실제로 탄 경로 `"preflop-table"` / `"exact"` / `"mc:N"`이고, `samples`는 테이블 샘플 수(1,000,000) / 전수 조합 수(990) / MC 샘플 수다 — 강제 장치: `tests/test_equity.py::test_equity_paths`
- 에퀴티 계산은 DB를 열지 않는다. `ai/equity.py`는 DB 모듈을 import하지 않는다 — 근거: [0034](../decisions/0034-abolish-equity-cache.md) · 강제 장치: `tests/test_equity.py::test_no_db_writes`(계산·봇 판단 중 `sqlite3.connect` 0회, 세션 패널을 여러 번 계산한 새 DB에 에퀴티 테이블 없음)
- 동률은 나눈 인원으로 나눈다: 나를 포함해 k명이 팟을 나누면 지분 1/k. 카운트 `(wins, ties, total)`와 `(wins + 0.5·ties)/total`을 그대로 쓰려고 ties에 `2/k`를 더한다(헤즈업은 +1). 고정·적응형 MC와 `mc_counts_ranged` 공통 — 강제 장치: `tests/test_equity.py::test_multiway_tie_share`(로열 보드 vs2 = 1/3, vs5 = 1/6, 일부만 동률 = 1/2, `smart_equity` 경로 포함)
- 홀-보드 또는 보드 내부에 중복 카드가 있으면 `ValueError` — 강제 장치: `tests/test_guards.py::test_equity_duplicate_cards`, `tests/test_equity.py::test_equity_paths`
- 계산용 평가는 고속 `evaluate_rank`(랭크 카운트 + 수트 비트마스크), 쇼다운 표시용은 `HandEvaluator` — 근거: [0018](../decisions/0018-equity-fast-paths.md) · 강제 장치: `tests/test_equity.py::test_fast_evaluator`
- 같은 보드의 리버 스팟 여러 개는 `board_rank_table`(보드 밖 2장 조합 1,081개 랭크)을 한 번 만들어 이진탐색 + 블로커 보정으로 계산할 수 있다. 결과는 `exact_counts_river`와 같아야 한다. 지금 런타임 경로는 쓰지 않는다 — 근거: [0018](../decisions/0018-equity-fast-paths.md) · 강제 장치: `tests/test_equity.py::test_board_rank_table`
- `exact_counts_turn`(약 4.5만 조합)·`exact_counts_flop`(약 107만 조합)은 런타임 경로가 아니라 테스트 기준값용이다 — 강제 장치: `tests/test_equity.py::test_mc_precision`(턴 정답)

### 레인지 반영 에퀴티 (`ranged_equity`)
- 고정 샘플 MC다(hard 봇 1,200, 패널 1,000). 적응형·정밀도 목표는 아직 적용하지 않았다(알려진 한계).
- 상대 홀카드는 결합분포 Π wᵢ(hᵢ)·[카드 비중복]에서 뽑는다: 각 레인지에서 내 홀·보드와 겹치는 콤보를 먼저 빼고(남는 게 없으면 그 상대는 랜덤), 레인지 상대 전원을 한 번에 뽑아 서로 겹치면 전체를 다시 뽑는다(결합 거절 샘플링, 200회 연속 실패 시 그 샘플만 순차 방식). 랜덤 상대는 남은 카드에서 균등. 상대 순서와 무관하다 — 강제 장치: `tests/test_equity.py::test_ranged_equity`(리버 JJ vs {AA,55}·{AA,66}: 전수 정답 31.6%와 3σ 이내, 순서 바꿔도 동일)

### 에퀴티 패널 (`server/session.py::_get_equity_info`)
- 사람 차례(`waiting_for_action`)이고 `equity_enabled`일 때만 계산한다(아레나는 끔). 같은 결정 지점(스트리트 + 현재 벳)은 재계산하지 않는다 — 강제 장치: `tests/test_poker_full.py` 5-10, 5-12
- `vs_random`: 살아 있는 상대 수만큼 랜덤 핸드 상대(`equity_detail`, 샘플 수 미지정 → 위 계산 경로). `source`/`samples`는 이 계산의 실제 경로와 샘플 수다 — 강제 장치: `tests/test_equity.py::test_multiway_tie_share`(리버 3인 → `mc:N`), `::test_no_db_writes`(프리플랍 → `preflop-table`)
- `vs_range`: 상대별 추정 레인지 반영(`ranged_equity` 1,000샘플, 레인지 정보가 없으면 vs_random과 같음). 상대별 1:1 브레이크다운은 레인지가 있으면 `ranged_equity`, 없으면 랜덤 1:1(`smart_equity`, 정보 없는 상대끼리 한 번만 계산해 공유) — 강제 장치: `tests/test_grader.py::test_session_equity_and_review`, `tests/test_equity.py::test_headsup_range_uses_sb`
- 팟오즈·콜 EV는 **유효 콜·유효 팟** 기준이다(`core/pot_odds.effective_call_pot`, 봇·Play Grader와 같은 함수). 유효 콜 = min(콜, 내 남은 칩), 유효 팟 = 팟 − 각 상대 기여 중 (내 기여 + 유효 콜)을 넘는 부분(폴드한 사람 포함). 세션은 핸드 전체 기여(`total_bet_this_round`)로 계산한다. 예: 팟 100에 상대 1,000 올인, 내 스택 100 → 콜 100·팟 200, 팟오즈 33% — 강제 장치: `tests/test_grader.py::test_short_stack_effective_call`
- 콜 EV는 vs_random 기준이다. 스트리트별 추이(history)도 vs_random만 기록한다 — D-16
- vs_random은 UI에서 빼고 vs_range만 보이기로 결정됐다(계산은 유지, 봇·플레이 평가가 씀) — 근거: [0022](../decisions/0022-equity-cache-rebuildable-vsrandom-ui.md) · 미구현 T-006

### 응답 시간 (CPython 3.12, `python3 scripts/bench_equity.py --reps 20`, 2026-09-26 실측, 중앙값 / 최대)
| 호출 | 캐시 폐기 후 | 이전(캐시 사용, 리뷰 R4 실측) |
|---|---|---|
| 프리플랍 (테이블) | < 0.1ms | 캐시 조회 약 1ms |
| 리버 1:1 (전수) | 3ms / 3ms | 3ms(hard) · MC 300(medium) 2ms |
| 플랍·턴 vs1 적응형 MC | 54~68ms / 81ms | 캐시 적중 1ms 또는 MC 300~1,200 2~9ms |
| 플랍·턴·리버 vs2 | 66~82ms / 112ms | MC 300~1,200 4~18ms |
| 플랍·턴 vs5 | 58~86ms / 220ms | — |
| 봇 판단 1회 easy / medium / hard (플랍 vs1) | 0.3 / 71 / 66ms | 0.6 / 2.5 / 9ms |
| 봇 판단 1회 medium·hard (플랍 vs2) | 89~98ms / 147ms | — |
| 패널 1회 상대 1명 플랍·턴 | 60~64ms / 75ms | — |
| 패널 1회 상대 2명 플랍·턴 | 152~160ms / 187ms | 67ms (플랍 2명) |
| 패널 1회 상대 5명 플랍·턴 | 151~174ms / 291ms | — |

## 화면·경로·데이터

| 대상 | 무엇 |
|---|---|
| `ai/equity.py` | 계산·레인지 샘플러 (`smart_equity`, `equity_detail`, `mc_adaptive`, `ranged_equity`) |
| `ai/preflop_equity_table.py` | 프리플랍 845값 상수 (자동 생성, 수동 편집 금지) |
| `scripts/export_preflop_equity.py` | 상수 테이블 생성기 — 옛 DB의 `equity_cache` 프리플랍 행을 읽기 전용(`immutable=1`)으로 읽는다(`--dry-run` 지원) |
| `scripts/bench_equity.py` | 응답 시간 측정 (DB 쓰기 없음, 임시 DB로 격리) |
| `core/pot_odds.py` | 에퀴티 → 결정 변환 공용: 유효 콜·유효 팟, 팟오즈, 콜 EV (세션 패널·Play Grader·봇) |

## 알려진 한계

- 프리플랍 테이블의 상대 2~5명 값은 멀티웨이 동률을 1/2로 세던 시절(T-032 이전)에 계산돼 동률 과대분(+0.05~0.15%p)이 섞여 있다. 정밀도 목표(±0.5%p) 안이라 그대로 쓴다.
- 정밀도 목표 ±0.5%p(1σ)를 지키려면 p≈0.5 스팟에서 1만 샘플이 필요하다. ADR 0034의 "약 1,000~2,000샘플"은 이 목표와 맞지 않는다(1,000샘플이면 1σ ≈ 1.6%p). 그 결과 medium·hard 봇 판단은 판단당 약 60~100ms, 패널은 최대 약 0.3초로 이전보다 느리다. 아레나 처리량도 그만큼 줄었다.
- 레인지 반영 에퀴티(`ranged_equity`, hard 봇 1,200·패널 1,000샘플)는 고정 샘플이라 1σ가 최대 약 1.4~1.6%p다. 정밀도 목표를 레인지 경로에도 적용할지는 정해지지 않았다.
- vs_random은 상대가 아무 핸드나 든다는 가정이라 3벳팟 등에서 과대평가 — 봇은 어그레션 마진으로 보정(ADR 0015), 근본 해결은 E-2
