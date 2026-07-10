# AI 봇

`ai/bot.py` — `PokerBot` 클래스, `ai/equity.py` — 에퀴티 엔진.

---

## 의사결정 흐름

```
decide_action(game_state)
  │
  ├─ [프리플랍] GTO 레인지 조회 (gto/advisor.py)
  │     ├─ 데이터 있음 → gto_compliance 확률로 GTO 액션
  │     ├─ 4벳+ → _four_bet_plus_response (강한 패 올인 / 폴드)
  │     └─ 데이터 없음 → _preflop_fallback (핸드 강도 휴리스틱)
  │
  └─ [포스트플랍] equity 기반 의사결정
        equity = smart_equity(홀, 보드, 상대수, 샘플수)
        ├─ 벳 직면: 밸류레이즈 / 세미블러프 레이즈 / equity vs 팟오즈 콜/폴드
        └─ 벳 없음: 밸류벳(사이징 믹스) / 세미블러프 / 순수 블러프 / 체크
```

---

## 에퀴티 엔진 (ai/equity.py)

세 가지 계산 경로:

| 경로 | 사용 시점 | 정확도 |
|---|---|---|
| Monte Carlo 샘플링 | 기본 (실시간) | 샘플 수 ∝ 정확도 (300개 = ±3%) |
| 전수조사 (exact) | 리버 1:1 (hard 봇), 워커 | 정확값 |
| equity_cache DB | 정확값/고정밀 누적값 존재 시 | 캐시 기준 |

- **스팟 자동 축적**: 봇이 계산한 MC 결과는 `equity_cache`에 누적된다.
  처음 만난 스팟은 자동으로 워커 큐에 등록되는 효과.
- **수트 정규화**: A♥K♥와 A♠K♠는 같은 키로 취급 (24개 수트 치환 중 최소 키).
- **고속 7카드 평가기**: `evaluate_rank()` — 부분집합 브루트포스 대신 랭크 카운트
  + 수트 비트마스크로 직접 판정. 기존 대비 **14.8배** (20만 세트 등가성 검증).
  표시용(쇼다운 best_cards)은 기존 `HandEvaluator.evaluate()` 유지.
- **스트리트 분해 DP**: turn = 리버 자식 46개의 합, flop = 턴 자식 47개의 합.
  equity_cache가 메모 테이블 — 자식이 캐시에 있으면 재사용, 없으면 계산 후 저장.
  플랍 1개를 계산하면 부산물로 턴/리버 정확값 ~2,200행이 캐시에 남는다.
- **전수조사 비용** (고속화 후): 리버 3ms / 턴 0.14초(웜 2ms) / 플랍 6.5초(웜 수 ms).
  프리플랍은 21억 조합이라 전수 불가 → 고정밀 샘플링 누적 (169핸드 × 상대 1~5명).
- **보드 중심 리버 계산** (`board_rank_table` / `equity_via_board_table`): 같은 보드를
  공유하는 리버 스팟들은 상대 990조합의 "보드+상대2장" 랭크가 동일하게 반복 계산된다.
  `board_rank_table(board)`가 보드와 겹치지 않는 47장의 모든 2장 조합(C(47,2)=1081개)
  랭크를 한 번만 계산해 정렬 리스트(bisect용) + 카드별 부분 리스트(블로커 보정용)로
  캐시한다. `equity_via_board_table(hole, board, table)`은 이진탐색으로 "나보다
  약한/타이인 조합 수"를 구한 뒤, 내 홀카드 2장을 포함하는 91개 조합
  (46+46-1, inclusion-exclusion)을 블로커로 제외해 정확한 990조합 기준값을 만든다.
  `exact_counts_river`와 **동일한 반환 형식·값**(랜덤 보드 100 × 홀 5 = 500케이스
  완전 일치, E-12). 같은 보드에서 홀카드 N개를 계산할 때 테이블 1회 + N번 lookup이
  `exact_counts_river` N번 직접 호출보다 **N=10에서 약 6.3배, N=50에서 약 28배**
  빠르다 (실측, 2026-07).

### 워커 배치 인출/저장 (2026-07)

계산이 빨라질수록(위 항목들) 스팟당 SQL round-trip 비용이 상대적으로 커진다.
`scripts/equity_worker.py`는 "1건 조회 → 1건 계산 → 1건 UPDATE"를 반복하는 대신
**pending id를 최대 500개(플랍은 20개) 배치로 인출**해 메모리에서 소진하고,
결과는 최대 100건 단위로 모아 `executemany`로 커밋한다.

- **리버 배치**: 조사 결과, 이미 캐시에 쌓인 exact 리버 스팟 20만 건 샘플에서
  canonical key를 디코딩한 실제 보드 기준 그룹 크기 분포는 **평균 ~2, 최대 7**
  (10.2만 개 distinct board / 20만 spot) — 완전 랜덤 실제 딜이라면 리버 보드
  공간(약 24억)이 워커 처리량 대비 압도적으로 커서 자연 중복은 거의 없지만,
  스윕/DP가 만들어내는 canonical key 특성상 유의미한 재사용이 관측됐다.
  → `process_river_batch()`가 배치로 뽑은 스팟들을 **디코딩한 실제 보드로
  그룹화**해 `board_rank_table`을 그룹당 1회만 구축하고 그룹 내 각 홀에
  `equity_via_board_table`을 적용한 뒤, 결과를 executemany로 일괄 UPDATE한다.
  (실측 시점에 실제 pending 리버 큐가 0이라 라이브 데이터로 그룹 크기를 다시
  재현하진 못했지만, 위 샘플과 합성 테스트(30개 실제 보드 × 무작위 홀, 77건 중
  72그룹으로 축소, `exact_counts_river`와 완전 일치)로 로직 정합성은 확인했다.)
- **턴/플랍 배치**: `exact_turn_dp`/`exact_flop_dp`는 매 자식마다 보드가 달라
  `board_rank_table` 재사용 여지가 없다 (스트리트 분해 DP 내부 조사 결과 —
  47×46개 리버 자식은 모두 다른 5장 보드이므로 그룹화 불가, **적용 스킵**).
  대신 "다음 작업 조회" SQL 왕복만 배치 인출로 없애고, 계산 자체는 건별 DP를
  유지한 채 최종 결과만 100건 단위 executemany로 모아 커밋한다.
- **MC 배치** (`next_mc_batch`/`process_mc_batch`): 프리플랍/멀티웨이 샘플
  누적도 동일하게 배치 인출 + `wins=wins+?` 형태의 누적 UPDATE를 executemany로
  모아 커밋한다.
- **멱등성**: 모든 저장 경로가 `WHERE id=? AND exact=0`을 사용 — 그라인드
  (`scripts/grind.py`)가 동시에 같은 스팟을 먼저 끝냈으면 rowcount=0으로
  조용히 skip된다. `scripts/bot_arena.py`를 워커와 동시에 돌려 확인(에러 없음).
- 실측(2026-07-09, 같은 머신, 큐 구성이 실행마다 달라 완전 통제 비교는 아님):
  1분 실행 완료 작업 수 — 배치 전(원본 `next_exact_job` 1건씩) **11개**
  (대부분 플랍) → 배치 후 **20개** (약 1.8배). PyPy에서도 커서 close 패턴이
  유지되어 에러 없이 동일하게 동작 확인.

### 워커 멀티프로세싱 (2026-07-10)

그라인드/워커 실행 중 CPU 사용률이 낮았던 원인은 워커가 단일 프로세스·단일
스레드(GIL)로 계산해 멀티코어 대부분이 유휴 상태였기 때문. SQLite는 동시
쓰기가 근본 제약이므로 **"쓰기(DB 캐시 조회/저장)는 메인 프로세스 1개, 계산
(순수 CPU 작업)은 워커 프로세스 N개"**로 분리해 `multiprocessing.Pool`을
도입했다.

- **리버** (`exact_counts_river`/`equity_via_board_table`): 원래 DB 접근이
  없는 순수 함수라 그대로 병렬화. `process_river_batch_parallel()`이 배치를
  실제 보드로 그룹화(기존 최적화 유지)한 뒤 그룹 단위로 `pool.map`에 분배.
- **턴/플랍**: `exact_turn_dp`/`exact_flop_dp`는 자식 스팟을
  `_lookup_exact`/`_upsert_exact`로 DB에 직접 읽고 쓰기 때문에 원본 함수를
  그대로 워커 프로세스에 넘길 수 없다. "캐시 접근은 메인에서만, 순수 계산만
  Pool로" 원칙으로 재구성:
  - `exact_turn_dp_parallel()`: 46개 리버 자식의 spot_key를 먼저 계산해
    `_batch_lookup_exact()`로 **한 번에** 캐시 조회 → 캐시 미적중 자식만
    모아 `pool.map(_river_calc_job, ...)`로 `exact_counts_river`(순수 함수)를
    병렬 계산 → 결과를 `_batch_upsert_exact()`로 일괄 저장 + 합산.
  - `exact_flop_dp_parallel()`: 47개 턴 자식은 기존처럼 캐시 조회 후 없으면
    `exact_turn_dp_parallel()`을 호출 — 그 내부의 46개 리버가 Pool로
    병렬화된다. 47개 턴 자체를 동시에 병렬화하는 것은 과설계로 보고 생략
    (리버 단위 병렬화만으로 충분한 스케일링을 확인, 아래 실측 참고).
  - 기존 `exact_turn_dp`/`exact_flop_dp`(순차, `--workers 1` 경로)는 그대로
    유지.
- **MC 배치** (`mc_counts`): 순수 함수이므로 `pool.map(_mc_job, ...)`로 그대로
  병렬화, 저장은 기존처럼 `wins=wins+?` 누적 executemany.
- 메인 루프 우선순위(리버→턴→플랍→preflop/mc→스윕)는 그대로 유지, 각 단계가
  `pool`이 있으면 병렬 함수를, 없으면(`--workers 1`) 기존 순차 함수를 호출.

**정합성 검증**: 리버 5 + 턴 3 + 플랍 1 스팟을 `--workers 1`과 `--workers 4`
각각(별도 DB)로 처리해 `(wins, ties, total)`이 완전히 동일함을 확인
(9스팟 전부 일치, 캐시 없는 상태부터 처리 시간 7.33s → 2.34s).

**성능 스케일링 실측** (2026-07-10, 12코어 맥, 신선한 DB/캐시 없음 상태):

| workers | 턴 40스팟 | speedup | 플랍 2스팟 | speedup |
|---|---|---|---|---|
| 1  | 5.68s | x1.00 | 13.6s | x1.00 |
| 2  | 3.36s | x1.69 | -     | -     |
| 4  | 1.82s | x3.13 | 4.2s  | x3.25 |
| 10 (기본) | 1.33s | x4.28 | 2.9s | x4.71 |

코어 수 대비 완전한 선형 스케일링은 아니지만(풀 생성/IPC 오버헤드, 배치당
작업 수가 워커 수보다 작을 때 유휴 워커 발생) 뚜렷한 이득이 확인된다.
기본 워커 수는 `max(1, cpu_count()-2)`로 그라인드(`scripts/grind.py`)의
아레나 프로세스 몫을 배려한다.

**PyPy 호환**: `pypy3 scripts/equity_worker.py --workers 2 --minutes 0.3`
에러 없이 정상 동작 확인 — `multiprocessing.Pool`은 PyPy에서도 지원된다.

```bash
python3 scripts/equity_worker.py               # 무한 실행 (Ctrl+C 안전)
python3 scripts/equity_worker.py --minutes 30       # 시간 제한
python3 scripts/equity_worker.py --workers 1        # 순차 처리 (회귀 안전/디버깅용)
python3 scripts/equity_worker.py --workers 4        # 병렬 워커 수 직접 지정
python3 scripts/equity_worker.py --preflop-first    # 프리플랍 845스팟부터 (순수 워커용)
python3 scripts/equity_worker.py --status           # 현황
```

배치(최대 100건) 단위로 커밋하므로 중단 시 최대 손실은 그 배치 분량뿐이고
재실행 시 이어서 계산한다.

우선순위: 리버 → 턴 → 플랍 전수조사 (게임에서 만난 스팟 우선)
→ 프리플랍/멀티웨이 샘플 누적 → **체계적 플랍 스윕**.
멀티웨이 샘플 누적 내부에서는 `num_opponents ASC, total ASC` 정렬로 vs2/vs3부터
채우고 vs4/vs5는 후순위로 미룬다 (2026-07).

스윕은 큐가 비었을 때 전체 플랍 스팟 공간(~130만)을 AA부터 정해진 순서로
등록·전수조사하는 무한 작업 저장고다. 진행 커서는 `worker_meta`에 저장되어
재시작해도 이어진다. 게임에서 새 스팟을 만나면 스윕보다 항상 먼저 처리된다.

**장시간 워커는 `pypy3` 권장** (약 3.7배, 플랍 전수조사 스팟 기준 실측):

```bash
pypy3 scripts/equity_worker.py --minutes 60   # CPython과 동일하게 사용
```

- 측정(2026-07-09, 동일 머신): 플랍 전수조사 1스팟(캐시적중 1) 평균
  CPython 6.4s → PyPy 1.7s (약 3.7배). 분당 완료 작업 수는 큐 구성(리버/턴 등
  값싼 작업 소진 여부)에 따라 달라져 직접 비교는 부정확하므로, 같은 종류의
  작업 소요 시간으로 비교했다.
- PyPy의 `sqlite3`는 CPython보다 엄격해 `conn.execute(...)`가 반환한 커서를
  소비/close하지 않고 `conn.commit()`을 호출하면
  `cannot commit transaction - SQL statements in progress` 에러가 난다.
  `scripts/equity_worker.py`, `db/connection.py`, `db/recorder.py`,
  `ai/equity.py`는 이 문제를 피하도록 커서를 명시적으로 닫아 두어 CPython/PyPy
  양쪽에서 동일하게 동작한다.
- `pyarrow` 등 워커가 안 쓰는 C 확장은 무관. `sqlite3`는 표준 라이브러리라
  PyPy에도 포함되어 별도 설치 없이 동작한다 (`brew install pypy3`).

### `--status` 증분 통계 테이블 전환 (2026-07-10)

`--status`의 카테고리별 진행률 쿼리가 equity_cache(9,600만 행+) 전체를 `GROUP BY`로
풀스캔해 **59초** 걸리던 문제를 `equity_cache_stats` 요약 테이블(스키마 v9,
`docs/db-schema.md` 참고)로 해결했다. equity_cache에 쓰는 모든 경로
(`ai/equity.py`의 MC 기여/exact 기여, `scripts/equity_worker.py`의 신규 스팟
등록/exact 승격/MC 배치)가 같은 트랜잭션 안에서 `bump_equity_stats`로 델타를
증분 반영한다. `--status`는 이제 이 작은 테이블만 읽어 **행 수와 무관하게 즉시
응답**(실측 0.09초, 656배 개선).

검증(2026-07-10, 동일 DB):
- `--rebuild-stats` 백필 직후 `equity_cache_stats` 합계가 실제 `equity_cache`
  풀스캔 `GROUP BY` 집계와 완전 일치(20개 카테고리 전부, COUNT/SUM 모두 일치).
- 워커 2분 실행(`--workers 2`) 후 재대조에서 드리프트 발견 — `_batch_upsert_exact`가
  같은 배치 안에 캐노니컬 키가 중복될 때(수트 정규화로 다른 실제 카드가 같은
  키로 겹치는 경우, `exact_turn_dp_parallel`의 46개 리버 자식 배치에서 흔함)
  델타를 중복 반영했음. 배치 내 마지막 값 기준으로만 델타를 계산하도록 수정 후
  재검증 → 이후 두 차례 추가 워커 실행 + 실시간 봇 MC/exact 기여 경로 직접 실행
  모두 드리프트 없음 확인.
- `tests/run_all.py --full` 통과(31/31, 총 15.99s).

`--rebuild-stats`는 1회성 백필/복구용 서브커맨드로, 이후로는 증분 갱신만으로
정합성이 유지된다.

---

## 난이도 프로파일

난이도의 핵심 축은 **MC 샘플 수 = 판단 해상도**다.
easy는 ±8% 오차로 판단하므로 "일부러 바보처럼 코딩"하지 않아도 자연스럽게 실수한다.

| 파라미터 | easy | medium | hard |
|---|---|---|---|
| GTO 준수율 (프리플랍) | 40% | 70% | 95% |
| MC 샘플 수 | 40 (±8%) | 300 (±3%) | 1,200 (±1.4%) |
| 리버 전수조사 | ✗ | ✗ | ✅ (정확값) |
| 캐시 사용 | ✗ | ✅ | ✅ |
| 레인지 반영 equity | ✗ | ✗ | ✅ |
| 콜 마진 | -0.06 (콜링스테이션) | 0 | +0.02 (타이트) |
| 어그레션 마진 | 0 | 0.06 | 0.08 |
| 세미블러프 빈도 | 10% | 40% | 55% |
| 순수 블러프 빈도 | 4% | 13% | 22% |
| 트랩(슬로우플레이) | 5% | 10% | 14% |

### 상대 레인지 반영 (B단계, hard 전용)

프리플랍 액션 로그를 파싱해 상대 핸드 분포를 좁힌다:
- **레이저** → 그 포지션의 GTO RFI 레이즈 레인지 (빈도 가중)
- **콜러** → 오프너에 대한 GTO 콜 레인지
- **정보 없음** (블라인드 체크 등) → 랜덤 핸드

레인지 정보가 있으면 `ranged_equity()`(레인지 조건부 MC)를 사용하고,
없으면 `smart_equity()`(캐시 활용 랜덤 equity)로 폴백.
조건부 분포라 equity_cache에는 저장하지 않는다.

### 어그레션 마진

상대가 벳/레이즈했다는 것 자체가 레인지를 강하게 만든다.
"equity vs 랜덤"은 이 상황에서 과대평가되므로, 벳 크기에 비례해 콜 기준을 올린다:

```
margin += aggression_margin × min(벳/팟, 1.2)
```

이 보정이 없으면 타이트한 상대의 밸류벳에 원페어로 계속 지불하는 leak이 생긴다
(아레나 검증에서 -39 → +19 bb/100 역전의 핵심 요인).

### 페르소나 (D단계)

난이도 프로파일 위에 성향 보정을 얹는다. 웹 게임 기본 배정:

| 봇 | 페르소나 | 특징 |
|---|---|---|
| Alpha | tight | 콜 기준 +5%p, 블러프 0.7배 |
| Beta | loose | 콜 기준 -5%p, 밸류벳 범위 넓음 |
| Gamma | aggressive | 블러프 1.6배, 세미블러프 1.5배, 사이즈 1.25배 |
| Delta | passive | 블러프 0.5배, 레이즈 기준 +5%p, 사이즈 0.85배 |
| Epsilon | balanced | 보정 없음 |

---

## 포스트플랍 판단 요소

- **equity vs 팟 오즈**: `equity ≥ call/(pot+call) + margin` → 콜.
  드로우는 임플라이드 오즈 보정(-0.04)으로 콜 범위 확대.
- **드로우 판별**: made rank ≤ 하이카드인데 equity ≥ 0.30 (리버 제외)
  → 세미블러프 후보 (벳/레이즈로 폴드 에퀴티 + 드로우 아웃츠 두 경로).
- **포지션 점수**: 살아있는 플레이어 중 액션 순서를 0.0(첫)~1.0(마지막)으로 등급화.
  블러프/세미블러프 빈도에 곱해진다.
- **보드 텍스처** (`board_wetness` 0~1): 플러시/스트레이트 코디네이션 판정.
  - 드라이 보드 밸류벳: 33% 팟 (스몰벳)
  - 웻 보드 밸류벳: 66~85% 팟 (드로우에 값 청구)
  - 넛급(equity ≥ 0.85): 75~110% 팟
- **멀티웨이 보정**: 상대 1명 추가마다 밸류 기준 +4%p, 블러프 빈도 1/n.
- **체크 믹스**: 밸류 핸드도 30% 체크(팟 컨트롤), 넛은 trap_freq만큼 슬로우플레이.

---

## GTO 준수 방식 (프리플랍)

```python
if random.random() > gto_compliance:
    return None  # 휴리스틱 폴백
```

GTO 액션이 `"fold"`인데 콜 비용이 없으면 체크로 보정.

레이즈 사이즈: RFI 2.5bb / 3벳 = 오픈×3 / 4벳 = 3벳×2.5 (스택 70% 넘으면 올인).

---

## 검증·튜닝 도구 (E단계)

```bash
# 아레나: 프로파일 대전 (bb/100 비교)
python3 scripts/bot_arena.py --hands 600 --seats hard,medium,legacy --seed 99
# 시트 문법: 페르소나/파라미터 오버라이드 ("+"로 다중 오버라이드)
python3 scripts/bot_arena.py --seats "hard:persona=aggressive,hard:aggression_margin=0.12+bluff_freq=0.3,legacy"

# 회귀 테스트: 로직 변경 후 실행 — legacy보다 약해지면 FAIL(exit 1)
python3 scripts/ai_regression.py [--hands 1000]

# 파라미터 튜닝: 그리드 A/B 또는 진화(hill-climb). 결과는 tuning_results.json 누적
python3 scripts/tune_bot.py --profile hard --param aggression_margin --values 0.04,0.08,0.12 --hands 2000 --seeds 3
python3 scripts/tune_bot.py --profile hard --param semibluff_freq --evolve --start 0.55 --step 0.1 --rounds 5
```

- `legacy` = 개선 전 핸드랭크 휴리스틱 봇 (베이스라인, 아레나 스크립트에 보존)
- 매 핸드 스택 100bb 리셋 + **칩 총량 보존 assert** (엔진 퍼징 겸용)
- 검증 결과 (600핸드, seed=99): legacy -19.3 vs medium +19.3 vs hard +19.4 bb/100
- 튜닝 결과는 봇 코드에 자동 반영되지 않음 — 확인 후 `POSTFLOP_PROFILES` 수동 갱신
- 분산 주의: 차이가 ±10~20 bb/100 이내면 노이즈로 간주하고 핸드 수를 늘릴 것

---

## 현재 한계

- **포스트플랍 베팅 레인지 미반영**: 레인지 추정이 프리플랍 액션까지만.
  포스트플랍 벳/레이즈에 대한 레인지 좁히기는 어그레션 마진으로 근사
- **포스트플랍 GTO 없음**: 빈도는 휴리스틱. GTO Wizard 포스트플랍 수집은 장기 과제
- **3벳 레인지 근사**: 3벳한 상대도 RFI 레인지로 근사 (실제로는 더 타이트)
