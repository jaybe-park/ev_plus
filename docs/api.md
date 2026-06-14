# API 명세

베이스 URL: `http://localhost:8000`  
개발 모드 문서 (Swagger): `http://localhost:8000/docs`

---

## 엔드포인트

### `POST /game/start`
새 게임 세션 생성. 첫 핸드를 시작하고 사람 차례까지 봇을 자동 진행한다.

**요청**
```json
{
  "player_name": "Player",
  "chips": 1000,
  "num_bots": 5,
  "difficulty": "medium",
  "small_blind": 10
}
```

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `player_name` | string | "Player" | 사람 플레이어 이름 |
| `chips` | int | 1000 | 시작 칩 |
| `num_bots` | int | 5 | AI 봇 수 (1~5) |
| `difficulty` | string | "medium" | `"easy"` / `"medium"` / `"hard"` |
| `small_blind` | int | 10 | 스몰 블라인드 (빅 블라인드 = ×2) |

**응답**: `GameState`

---

### `GET /game/{session_id}/state`
현재 게임 상태 조회.

**응답**: `GameState`

---

### `POST /game/{session_id}/action`
사람 플레이어의 액션 제출. 봇들을 자동으로 처리한 뒤 다음 사람 차례 상태를 반환한다.

**요청**
```json
{
  "action": "call",
  "amount": 0
}
```

| `action` 값 | 설명 | `amount` |
|---|---|---|
| `"fold"` | 폴드 | 무시 |
| `"check"` | 체크 | 무시 |
| `"call"` | 콜 | 무시 (서버에서 자동 계산) |
| `"raise"` | 레이즈 | 레이즈 총액 (예: 60) |
| `"allin"` | 올인 | 무시 |

**응답**: `GameState`

---

### `POST /game/{session_id}/next-hand`
현재 핸드가 종료된 후 다음 핸드를 시작한다. `hand_over: true` 상태에서 호출.

**응답**: `GameState`

---

## GameState 응답 형식

```typescript
{
  session_id: string
  hand_number: number          // 현재 핸드 번호 (1부터 시작)
  street: string               // "프리플랍" | "플랍" | "턴" | "리버"
  pot: number
  current_bet: number          // 이번 라운드 최고 베팅액
  min_raise: number            // 최소 레이즈 추가 크기
  big_blind: number
  community_cards: string[]    // ["A♠", "K♥", "Q♦", ...]
  players: PlayerState[]
  waiting_for_action: boolean  // true면 사람이 액션해야 함
  hand_over: boolean           // true면 /next-hand 호출 필요
  game_over: boolean           // true면 게임 종료 (사람 파산 또는 우승)
  winners: string[]            // 이번 핸드 승자 이름
  showdown_hands: Record<string, string>  // {name: "풀 하우스 [K♠ K♥ K♦ A♠ A♥]"}
  gto_hint: string | null      // 프리플랍 힌트, 없으면 null
  action_log: string[]         // 최근 30개 액션 문자열
  call_amount: number          // 콜에 필요한 추가 칩
  min_raise_to: number         // 레이즈 최소 총액
}

PlayerState {
  name: string
  chips: number
  current_bet: number
  is_folded: boolean
  is_all_in: boolean
  is_human: boolean
  position: string             // "BTN" | "SB" | "BB" | "UTG" | "MP" | "CO"
  hole_cards: string[] | null  // 사람: 항상 공개 / 봇: 핸드 중 null, 쇼다운 후 공개
}
```

---

## CORS

개발 모드에서 `localhost` 모든 포트 허용 (`allow_origin_regex`).  
프로덕션에서는 FastAPI가 `web/dist`를 직접 서빙하므로 CORS 불필요.
