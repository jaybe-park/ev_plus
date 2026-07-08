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
  equity: EquityInfo | null       // 에퀴티 패널. waiting_for_action=true이고
                                   // 사람이 폴드하지 않았을 때만 값 존재
  hand_review: HandReviewEntry[] | null  // 플레이 평가. hand_over=true일 때만 값 존재
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

EquityInfo {
  vs_random: number            // 랜덤 핸드 대비 승률 (0~1)
  vs_range: number             // 살아있는 상대 전원의 레인지를 반영한 종합 승률
  pot_odds: number | null      // call_amount / (pot + call_amount), 콜할 게 없으면 null
  call_ev_bb: number | null    // 콜 EV (bb 단위), 콜할 게 없으면 null
  source: string                // "exact" (리버 1:1 전수조사) | "mc:1000" (몬테카를로)
  samples: number               // 계산에 사용한 시뮬레이션 샘플 수
  num_opponents: number
  opponents: EquityOpponent[]
  history: EquityHistoryEntry[] // 이번 핸드에서 스트리트가 바뀔 때마다 한 번씩 기록
}

EquityOpponent {
  name: string
  position: string
  role: "raiser" | "caller" | "unknown"  // 프리플랍 액션으로 추정한 상대 역할
  equity: number | null        // 이 상대 1인 레인지 기준 1:1 승률 추정
                                // (레인지 정보 없으면 vs_random 값을 재사용)
}

EquityHistoryEntry {
  street: string    // "프리플랍" | "플랍" | "턴" | "리버"
  vs_random: number
}

HandReviewEntry {
  street: string
  action: string                // "fold" | "check" | "call" | "raise" | "allin"
  grade: string                 // "✅" | "🟡" | "🟠" | "🔴" | "⬜" | "⚠️"
  reason: string                 // 한글 평가 설명
  ev_loss_bb: number | null      // 손실 추정치 (bb, 음수). 손실 없으면 null
  pot_odds: number | null
  equity: number | null
  gto_freq: Record<string, number> | null  // 프리플랍만 값 존재 (GTO 빈도 딕셔너리)
}
```

---

### `GET /session/{session_id}/review`
세션 전체 동안 사람이 한 액션들의 누적 평가 요약을 반환한다.

**응답**:
```typescript
{
  total_actions: number            // 평가된 사람 액션 총 개수
  grade_counts: Record<string, number>  // 등급 기호별 개수, 예: {"✅": 12, "🔴": 3}
  total_ev_loss_bb: number         // ev_loss_bb 합계 (음수 = 손실)
  gto_match_rate: number | null    // 프리플랍 액션 중 "✅" 비율 (GTO 데이터 있는 액션 기준)
                                    // 프리플랍 평가 데이터가 없으면 null
}
```

세션이 없으면 404.

---

## CORS

개발 모드에서 `localhost` 모든 포트 허용 (`allow_origin_regex`).  
프로덕션에서는 FastAPI가 `web/dist`를 직접 서빙하므로 CORS 불필요.
