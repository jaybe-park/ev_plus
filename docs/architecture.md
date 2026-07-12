# 아키텍처

## 전체 구조

```
브라우저 (React)
    │  HTTP (JSON)
    ▼
FastAPI 서버 (server/)
    │
    └─ WebGameSession (server/session.py)
            │
            ├─ TexasHoldem   (core/game.py)     ← 게임 엔진
            ├─ PokerBot      (ai/bot.py)         ← AI 봇 (ai/equity.py 사용)
            ├─ GTOAdvisor    (gto/advisor.py)    ← GTO 힌트
            ├─ grade_action  (gto/grader.py)     ← 플레이 평가(Play Grader)
            └─ GameRecorder  (db/recorder.py)    ← 핸드/액션 DB 자동 기록 (v6부터 연결)
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

gto/           ← core/card, db/ 사용
  loader.py    ← DB(gto_preflop_*) 로드 (앱 시작 시 캐시)
  advisor.py   ← gto/loader, core/card — 미수집 스팟은 gto_missing_spots_preflop에 기록
  grader.py    ← 플레이 평가(Play Grader) 판정 엔진 (GTO 빈도 / equity 기반)
  url_generator.py ← GTO Wizard 직접 이동 URL 생성

db/            ← 순수 SQLite 계층, 외부 의존 없음
  schema.py    ← 테이블/인덱스 DDL + 버전별 마이그레이션 (SCHEMA_VERSION)
  connection.py ← 커넥션 관리 (EV_PLUS_DB 환경변수로 테스트 격리)
  recorder.py  ← GameRecorder — 핸드/액션 기록 (RL 학습 데이터)

ai/            ← core/, db/ 사용
  bot.py       ← core/game, core/player, core/card, gto/advisor, ai/equity
  equity.py    ← MC 샘플링 + 전수조사 + equity_cache DB 누적

server/        ← core/, ai/, gto/, db/ 사용
  session.py   ← 핵심: 웹용 스텝 방식 게임 루프, GameRecorder/에퀴티/평가 연결
  main.py      ← FastAPI 라우터
  schemas.py   ← Pydantic 모델

scripts/       ← db/, ai/, core/ 사용
  equity_worker.py ← 에퀴티 전수조사/샘플링 워커
  bot_arena.py     ← 봇 vs 봇 시뮬레이션
  grind.py         ← 아레나 + 워커 동시 실행

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
  equity,           // 실시간 에퀴티 패널. waiting_for_action=true && 사람 미폴드 시만 값 존재
  hand_review,      // 플레이 평가(Play Grader). hand_over=true일 때만 값 존재
}
```

필드 상세 타입(`EquityInfo`, `HandReviewEntry` 등)은 [API 문서](api.md) 참고.
