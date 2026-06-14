# GTO 데이터

프리플랍 레인지 데이터를 JSON으로 관리한다.  
GTO Wizard 등 외부 솔버에서 복사해 입력한다.

---

## 파일 구조

```
gto_data/preflop/
  open/          ← RFI (첫 오픈 레이즈) 레인지
    BTN.json
    CO.json
    MP.json
    UTG.json
    SB.json
  vs_open/       ← 오픈에 대한 수비 / 3벳 레인지
    BB_vs_BTN.json
    BB_vs_CO.json
    BB_vs_MP.json
    BB_vs_UTG.json
    SB_vs_BTN.json
```

### 현재 없는 데이터 (미입력)
- `vs_3bet/` — 3벳에 대한 4벳/콜/폴드 레인지
- 포스트플랍 레인지 전체
- BB_vs_SB, SB_vs_CO, SB_vs_MP, SB_vs_UTG 등 일부 vs_open 상황

---

## JSON 형식

### open/ (fold / raise)

```json
{
  "situation": "BTN open RFI",
  "actions": ["fold", "raise"],
  "raise_size": "2.5bb",
  "hands": {
    "AA":  {"fold": 0.0, "raise": 1.0},
    "AKs": {"fold": 0.0, "raise": 1.0},
    "JTo": {"fold": 0.15, "raise": 0.85},
    "72o": {"fold": 1.0,  "raise": 0.0}
  }
}
```

### vs_open/ (fold / call / raise)

```json
{
  "situation": "BB vs BTN open",
  "actions": ["fold", "call", "raise"],
  "raise_size": "3x",
  "hands": {
    "AA":  {"fold": 0.0, "call": 0.0,  "raise": 1.0},
    "AKs": {"fold": 0.0, "call": 0.33, "raise": 0.67},
    "72o": {"fold": 1.0, "call": 0.0,  "raise": 0.0}
  }
}
```

---

## 핸드 표기 규칙

| 표기 | 의미 | 예시 |
|---|---|---|
| `AKs` | suited (같은 무늬) | A♠K♠ |
| `AKo` | offsuit (다른 무늬) | A♠K♥ |
| `AA` | 페어 | A♠A♥ |

- 전체 169개 핸드 조합이 있어야 완전한 레인지
- 미입력 핸드는 자동으로 fold 100% 처리됨
- 빈도 합계는 반드시 1.0 (`fold + call + raise = 1.0`)

---

## 코드에서 사용하는 방법

```python
from gto.loader import get_open_range, get_vs_open_range, get_action_frequencies

# BTN RFI 레인지 로드
range_data = get_open_range("BTN")

# AKs 빈도 조회
freqs = get_action_frequencies(range_data, "AKs")
# → {"fold": 0.0, "raise": 1.0}

# BB vs BTN 레인지
range_data = get_vs_open_range("BB", "BTN")
```

`hand_to_notation(card1, card2)` 함수로 Card 객체 → 핸드 표기 변환 가능.

---

## GTO 어드바이저 (`gto/advisor.py`)

### 사람 플레이어 힌트

```python
advisor = GTOAdvisor()
rec = advisor.get_recommendation(hole_cards, my_position, positions, game_state, big_blind)
hint = advisor.format_hint(rec)
# → "📊 GTO [AKs] BTN RFI: 레이즈 100%"
```

### 봇 GTO 액션

```python
action = advisor.get_bot_action(
    hole_cards, my_pos, positions, game_state,
    big_blind, gto_compliance=0.7  # 70% 확률로 GTO 준수
)
# → "fold" | "call" | "raise" | None (데이터 없음)
```

---

## 데이터 추가 방법

1. GTO Wizard에서 원하는 상황 선택
2. 각 핸드의 액션 빈도 확인
3. 해당 경로에 JSON 파일 생성

데이터가 없는 상황(포지션 조합)은 GTO 힌트 없이 봇의 휴리스틱 전략으로 폴백된다.
