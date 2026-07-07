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
- **전수조사 비용**: 리버 990조합(<1초) / 턴 4.6만(~10초) / 플랍 107만(2~5분).
  프리플랍은 21억 조합이라 전수 불가 → 고정밀 샘플링 누적 (169핸드 × 상대 1~5명).

### 백그라운드 워커

```bash
python3 scripts/equity_worker.py               # 무한 실행 (Ctrl+C 안전)
python3 scripts/equity_worker.py --minutes 30       # 시간 제한
python3 scripts/equity_worker.py --preflop-first    # 프리플랍 845스팟부터 (순수 워커용)
python3 scripts/equity_worker.py --status           # 현황
```

스팟 단위로 커밋하므로 언제 중단해도 진행분이 보존되고 재실행 시 이어서 계산한다.

우선순위: 리버 → 턴 → 플랍 전수조사 (게임에서 만난 스팟 우선)
→ 프리플랍/멀티웨이 샘플 누적 → **체계적 플랍 스윕**.

스윕은 큐가 비었을 때 전체 플랍 스팟 공간(~130만)을 AA부터 정해진 순서로
등록·전수조사하는 무한 작업 저장고다. 진행 커서는 `worker_meta`에 저장되어
재시작해도 이어진다. 게임에서 새 스팟을 만나면 스윕보다 항상 먼저 처리된다.

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
