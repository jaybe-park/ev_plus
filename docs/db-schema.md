# DB 스키마

SQLite 기반. `poker.db` 파일로 저장.  
현재 스키마와 기록 모듈은 구현됐지만 **게임 세션과 연결이 안 된 상태**다.

---

## 테이블 구조

### games
핸드(게임) 단위 기록.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `game_uuid` | TEXT | 핸드 고유 ID |
| `played_at` | TEXT | 플레이 시각 |
| `num_players` | INTEGER | 참여 플레이어 수 |
| `small_blind` | INTEGER | |
| `big_blind` | INTEGER | |
| `dealer_pos` | TEXT | 딜러 포지션 |
| `hole_cards` | TEXT | JSON `{"BTN":"AsJh","SB":"KdQd"}` |
| `flop_1~3` | TEXT | 플랍 카드 (2자리 표기, 예: `As`) |
| `turn_card` | TEXT | |
| `river_card` | TEXT | |
| `pot_total` | INTEGER | 최종 팟 크기 |
| `winner_pos` | TEXT | JSON 배열 `["BTN"]` |
| `player_results` | TEXT | JSON `{"BTN":{"start":1000,"end":1150}}` |

---

### preflop_actions
프리플랍 액션 기록. GTO 빈도와 함께 저장.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `game_uuid` | TEXT | games 참조 |
| `action_seq` | INTEGER | 게임 전체 순서 |
| `position` | TEXT | BTN/SB/BB/UTG/MP/CO |
| `is_human` | INTEGER | 0 또는 1 |
| `bet_round` | TEXT | `open` / `3bet` / `4bet` / `5bet` |
| `pot_before` | INTEGER | 액션 전 팟 크기 |
| `stack_before` | INTEGER | 액션 전 스택 |
| `current_bet` | INTEGER | 현재 베팅액 |
| `call_amount` | INTEGER | 콜 비용 |
| `action` | TEXT | fold/call/raise/allin |
| `amount_bb` | REAL | BB 단위 환산 (2.5, 7.5 ...) |
| `gto_fold/call/raise` | REAL | GTO 권장 빈도 0~1 |

---

### postflop_actions
포스트플랍 액션 기록. RL 학습용 필드 포함.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `street` | TEXT | flop/turn/river |
| `action` | TEXT | fold/check/call/raise/allin |
| `gto_raise_33~150` | REAL | 팟 대비 사이즈별 GTO 빈도 |
| `state_vector` | TEXT | JSON (RL 학습용, 미사용) |
| `reward` | REAL | 핸드 종료 후 역산 보상 (미사용) |

---

## 카드 표기 변환

`db/card_notation.py` — DB 저장 시 카드 표기 변환.

```
Card("A", "♠") → "As"   (DB 저장 형식)
Card("K", "♥") → "Kh"
Card("10","♦") → "Td"
```

---

## 연결 방법 (미구현)

`server/session.py`의 `_apply()` 메서드에서 각 액션 시 `db/recorder.py`를 호출하면 된다.

```python
# session.py _apply() 내부에서 호출 예시
from db.recorder import record_action
record_action(game_uuid, player, action, amount, gto_freqs)
```
