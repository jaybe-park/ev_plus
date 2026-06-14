# AI 봇

`ai/bot.py` — `PokerBot` 클래스.

---

## 난이도별 전략

| 난이도 | GTO 준수율 | 전략 요약 |
|---|---|---|
| Easy | 40% | 핸드 강도 기반 단순 확률 베팅 |
| Medium | 70% | 팟 오즈 계산 + 세미 블러프 |
| Hard | 95% | 포지션 + 블러프 빈도 + 다양한 베팅 사이즈 |

---

## 의사결정 흐름

```
decide_action(game_state)
  │
  ├─ [프리플랍] GTO 레인지 조회
  │     ├─ 데이터 있음 → gto_compliance 확률로 GTO 액션 반환
  │     └─ 데이터 없음 → 아래 휴리스틱으로 폴백
  │
  └─ [포스트플랍 / GTO 미적용]
        └─ _evaluate_hand_strength() → 0.0~1.0
             ├─ Easy:   strength 임계값 기반 단순 분기
             ├─ Medium: 팟 오즈(call / pot+call)와 strength 비교
             └─ Hard:   스트리트별 블러프 빈도 + 다양한 레이즈 배율
```

---

## 핸드 강도 평가

### 프리플랍
홀카드 2장의 랭크 합 + 수티드/페어/커넥터 보너스로 0~1 산출.

```
score = (rank1 + rank2) / 28
+0.20  페어
+0.05  suited
+0.03  connector (랭크 차이 ≤ 2)
```

### 포스트플랍
`HandEvaluator.evaluate(hole + community)` → `hand_rank.rank_value / 10`  
(HIGH_CARD=0.1 ~ ROYAL_FLUSH=1.0)

---

## GTO 준수 방식

```python
# gto_compliance 확률로만 GTO 따름, 나머지는 휴리스틱
if random.random() > gto_compliance:
    return None  # 휴리스틱 폴백
```

GTO 액션이 `"fold"`인데 콜 비용이 없으면 체크로 보정.

---

## 현재 한계

- **포스트플랍 GTO 없음**: 포스트플랍은 핸드 강도 휴리스틱만 사용
- **포지션 미반영**: Hard 난이도도 포지션 유리/불리를 완전히 반영하지 않음
- **상대 레인지 추정 없음**: 리얼 GTO는 상대 레인지를 역산하지만 현재는 미구현
