# DB 스키마

SQLite 기반. `poker.db` 파일로 저장.  
v6부터 게임 세션과 연결되어 **모든 핸드/액션이 자동 기록**된다 (RL 학습 데이터).

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

**v6 RL 컨텍스트 컬럼** (preflop/postflop 공통): `equity`(봇 결정 시점 계산값),
`bot_profile`("hard/aggressive" 등), `players_state`(결정 직전 전원 상태 JSON),
`reward`(핸드 종료 후 bb 단위 역산). 포지션 CHECK에 HJ/BTN-SB 허용.

**인덱스 (v8)** — reward 역산 UPDATE(`WHERE game_uuid=? AND position=?`)가 저선택도
`idx_preflop_pos`/`idx_postflop_pos`(position 단일 인덱스)를 잘못 타던 문제를 해결하기 위해
복합 인덱스 `idx_preflop_game_pos`/`idx_postflop_game_pos (game_uuid, position)`로 교체.
기존 `idx_preflop_game`/`idx_postflop_game`(game_uuid 단일)은 복합 인덱스가 왼쪽 접두로
대체하므로 제거. `idx_preflop_pos`/`idx_postflop_pos`, `idx_preflop_human`/`idx_postflop_human`은
포지션별 VPIP/PFR 통계 집계용으로 유지.

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

### gto_missing_spots (v3)
플레이 중 만난 GTO 데이터 없는 스팟 큐. 수집모드가 소비.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `street` | TEXT | 현재 preflop만 |
| `position` | TEXT | 결정 주체 포지션 |
| `vs_position` | TEXT | RFI=`''` / vs_open=`'UTG'` / vs_3bet=`'UTG/HJ'` |
| `range_type` | TEXT | open / vs_open / vs_3bet |
| `gto_wizard_url` | TEXT | 직접 이동 URL (사전 계산) |
| `collected` | INTEGER | 수집 완료 여부 |

---

### equity_cache (v4)
에퀴티 계산 결과 누적 저장소. 봇 런타임과 `scripts/equity_worker.py`가 공유.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `street` | TEXT | preflop / flop / turn / river |
| `spot_key` | TEXT | 수트 정규화 키 `홀\|플랍\|턴\|리버` |
| `num_opponents` | INTEGER | 상대 수 (1~5) |
| `wins` / `ties` | REAL | 누적 승리/무승부 수 |
| `total` | INTEGER | 누적 샘플 수 (0 = 계산 대기) |
| `exact` | INTEGER | 1 = 전수조사 완료 (정확값, MC 누적 차단) |

- equity = `(wins + 0.5×ties) / total`
- 봇이 플레이 중 계산한 MC 결과가 자동 누적 → 만난 스팟이 워커 큐에 등록되는 효과
- 워커가 리버→턴→플랍(1:1) 순으로 전수조사, 프리플랍/멀티웨이는 고정밀 샘플링 누적

**인덱스 (v7)** — 행 수가 커져도(700만+) 작업 선택 쿼리가 느려지지 않도록
대기 중인 행만 담는 부분 인덱스 2개 추가:
- `idx_equity_pending(street, total, id) WHERE exact=0 AND num_opponents=1`
  — 1:1 전수조사 대기 큐 (`next_exact_job`)
- `idx_equity_multiway_pending(total) WHERE exact=0 AND num_opponents>1`
  — 멀티웨이 샘플링 대기 큐 (`next_mc_job`)

`exact=1`로 승격되거나 목표 샘플에 도달하면 조건에서 빠지므로 인덱스는 항상 작게 유지된다.
작업 선택 쿼리는 스트리트/조건별로 단순 쿼리를 나눠 실행 (CASE 표현식 정렬 회피).

**인덱스 정리 (v8)** — `idx_equity_street(street, exact, total)` 전체 인덱스(766만 행) 제거.
`idx_equity_pending` 부분 인덱스가 대기 조회를 전담하므로 잉여였고, 쓰기 비용만 유발했다.
`scripts/equity_worker.py` 실행 시작 시 `ANALYZE`를 1회 실행해 플래너 통계를 갱신한다
(`db/connection.py`에는 넣지 않음 — 모든 연결마다 돌면 안 되므로 워커 진입점에만 배치).

---

### worker_meta (v5)
에퀴티 워커의 플랍 스윕 진행 커서 저장 (key-value).

---

## 카드 표기 변환

`db/card_notation.py` — DB 저장 시 카드 표기 변환.

```
Card("A", "♠") → "As"   (DB 저장 형식)
Card("K", "♥") → "Kh"
Card("10","♦") → "Td"
```

---

## 기록 흐름 (v6에서 연결 완료)

`WebGameSession`이 `GameRecorder`를 내장:
- `_start_new_hand` → `start_hand()` (전원 홀카드/시작칩/딜러)
- `_apply` → `record_action()` (결정 직전 상태 + equity + 봇 프로파일)
- `_do_showdown` → `finish_hand()` (보드/팟/승자 + reward 역산)

기록 실패는 try/except로 무시되어 게임을 막지 않는다.
아레나/그라인드(`scripts/`)도 같은 세션을 쓰므로 자동 기록된다.
