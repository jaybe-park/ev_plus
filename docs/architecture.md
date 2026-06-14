# 아키텍처

## 전체 구조

```
브라우저 (React)
    │  HTTP (JSON)
    ▼
FastAPI 서버 (server/)
    │
    ├─ WebGameSession (server/session.py)
    │       │
    │       ├─ TexasHoldem (core/game.py)   ← 게임 엔진
    │       ├─ PokerBot    (ai/bot.py)       ← AI 봇
    │       └─ GTOAdvisor  (gto/advisor.py) ← GTO 힌트
    │
    └─ [미연결] DB Recorder (db/recorder.py)
```

## 모듈 의존성

```
core/          ← 순수 게임 로직, 외부 의존 없음
  card.py
  deck.py
  player.py
  evaluator.py
  game.py

ai/            ← core/ 사용
  bot.py       ← core/game, core/player, core/card, gto/advisor

gto/           ← core/card 사용
  loader.py    ← gto_data/ JSON 파일 로드
  advisor.py   ← gto/loader, core/card

server/        ← core/, ai/, gto/ 사용
  session.py   ← 핵심: 웹용 스텝 방식 게임 루프
  main.py      ← FastAPI 라우터
  schemas.py   ← Pydantic 모델

web/           ← server/ API 호출
  src/api.ts   ← fetch 래퍼
```

## 웹 게임 흐름

CLI와 달리 웹은 HTTP 요청 단위로 게임이 진행된다.  
사람 액션 1회 → 서버에서 봇들 자동 처리 → 다음 사람 차례까지 진행 → 상태 반환.

```
POST /game/start
  └─ WebGameSession 생성
     └─ 첫 핸드 시작, 봇 자동 처리
     └─ 사람 차례까지 진행
     └─ GameState 반환

POST /game/{id}/action  (사람이 액션할 때마다)
  └─ submit_action()
     ├─ 사람 액션 적용
     ├─ _run_until_human()
     │   ├─ 봇 액션 반복 처리
     │   ├─ 스트리트 전환 (플랍→턴→리버)
     │   └─ 사람 차례 또는 핸드 종료 시 중단
     └─ GameState 반환

POST /game/{id}/next-hand
  └─ next_hand()
     └─ 파산 플레이어 제거 → 새 핸드 시작
```

## 게임 상태 (GameState)

서버 → 프론트로 전달되는 단일 상태 객체. 프론트는 이것만 보고 UI를 그린다.

```typescript
{
  session_id, hand_number,
  street,           // "프리플랍" | "플랍" | "턴" | "리버"
  pot, current_bet, min_raise, big_blind,
  community_cards,  // ["A♠", "K♥", ...]
  players: [{
    name, chips, current_bet,
    is_folded, is_all_in, is_human,
    position,         // "BTN" | "SB" | "BB" | "UTG" | ...
    hole_cards,       // 사람: 항상 공개 / 봇: 핸드 중 null, 쇼다운 후 공개
  }],
  waiting_for_action, hand_over, game_over,
  winners, showdown_hands,
  gto_hint,         // "📊 GTO [AKs] BTN RFI: 레이즈 100%"
  action_log,       // 최근 30개 액션 문자열
  call_amount, min_raise_to,
}
```
