# DB 스키마

SQLite 기반. `poker.db` 파일로 저장.  
v6부터 게임 세션과 연결되어 **모든 핸드/액션이 자동 기록**된다 (RL 학습 데이터).

현재 `SCHEMA_VERSION = 12` (`db/schema.py`). 마이그레이션은 `db/connection.py`가
현재 버전 초과분만 순서대로 실행한다 (`MIGRATIONS` dict, 버전별 1회성 DDL).
v12부터 마이그레이션 스텝은 **SQL 문자열 또는 콜러블**(conn을 받는 파이썬 함수)일 수
있다 — 순수 SQL로 표현 불가한 결정론적 데이터 백필(v12 캐노니컬 노드 키 계산)용.

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

**인덱스**: `idx_games_played (played_at)` — 시각 기준 조회/정렬용.

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

### gto_preflop_situations / gto_preflop_hands (v2)
프리플랍 GTO 레인지 데이터. `situations`가 상황(포지션/상대/타입) 단위,
`hands`가 상황별 169핸드 각각의 액션 빈도. 상세 데이터 현황은
[GTO 데이터 문서](gto-data.md) 참고.

| 테이블 | 컬럼 | 설명 |
|---|---|---|
| `gto_preflop_situations` | `position` / `vs_position` / `range_type` | open / vs_open / vs_3bet, `vs_position` NULL=RFI |
| | `raise_size` (REAL, v11) | bb 단위 실측 raise-to 값 (예: 2.5, 8.0, 13.5). v10까지는 TEXT("3x" 플레이스홀더)였으나 사이징이 배수 공식으로 추론 불가함이 확인돼(포지션마다 배수가 다름) 실측 숫자만 저장하도록 변경 — [GTO 데이터 문서](gto-data.md) 참고 |
| | `situation_label` | 사람이 읽는 설명 |
| | `action_seq` (TEXT, v12; ②'에서 실측 사이즈로 전환) | **노드 키** — 히어로 결정 직전까지의 액션 시퀀스(예: `"F-R2.5"` = CO vs HJ open, RFI UTG=`""`). 프리플랍 전체 트리 커버리지(④ 데이터 기반 워커)의 조회 키. `F`/`X`/`C`/`R{bb}` 토큰, 포지션 순서 UTG→…→BB. **레이즈 사이즈는 화면에서 읽은 실측값 verbatim**(②' 확정, 2026-07-16 — 깊이별 캐노니컬 사이즈로 뭉개던 ② 방식은 폐기). 저장: 워커(`scripts/collect_gto_tree.py`)가 실측 키를 그대로 저장, `/gto/preflop/save`의 `action_seq` 파라미터로 verbatim 우선(명시 안 하면 레거시 `gto/url_generator.situation_to_node_key`로 근사 파생). 런타임 조회: `gto/advisor.canonical_node_key`가 라이브 시퀀스를 **수집된 형제 노드의 실측 사이즈**로 스냅(하드코딩 테이블 아님, `gto/loader.get_children_by_prefix`로 데이터에서 읽음) — 매칭되는 형제가 없으면 추측하지 않고 `gto_missing_spots_preflop`(`range_type='seq'`)에 큐잉 후 None. nullable |
| | `hero_position` (TEXT, v12) | 결정 주체(시퀀스 파생, 조회용) |
| | `num_active` (INTEGER, v12) | 히어로 결정 시점 미폴드 인원(6 − 폴드 토큰 수, 파생) |
| `gto_preflop_hands` | `situation_id` | situations FK (ON DELETE CASCADE) |
| | `hand` | "AKs" / "AA" / "K7o" 등 169핸드 표기 |
| | `freq_fold/call/raise/allin` | 액션별 빈도 0~1, 합≈1.0 |

**인덱스**: `idx_gto_pre_sit (position, vs_position, range_type)` — 상황 조회(레거시 enum 키),
`idx_gto_pre_hand (situation_id, hand)` — 핸드별 빈도 조회,
`idx_gto_pre_seq (action_seq) UNIQUE` (v12) — 시퀀스 키 조회 + 노드 키 1:1 매칭 강제
(nullable → NULL 다수 허용). 두 조회 경로(enum / 시퀀스 키)는 **병렬 공존**하며 같은
레인지 객체를 가리킨다(`gto/loader.py`의 `_cache` / `_cache_by_seq`).

> v12 마이그레이션: 컬럼 3개 ADD + `backfill_v12`(결정론적 노드 키 백필, vs_3bet
> `vs_position` 반쪽 포맷 `"BB"`→`"BTN/BB"` 정규화) + 유니크 인덱스 생성. 데이터 손실 0
> (기존 11행/1778핸드 보존). `backfill_v12`가 그때 채운 노드 키는 **깊이 캐노니컬
> 사이즈**(예: 3벳은 항상 `R8`) 방식이라 ②'(실측 사이즈) 원칙과 다르다 — 별도
> 재마이그레이션 없이 ④ 워커가 실제로 재방문하며 실측 키로 자연히 덮어쓰는 방식으로
> 처리(D2 결정). 상세: [프리플랍 트리 커버리지 문서](gto-preflop-tree.md) "② 구현 결정" /
> "데이터 기반 트리 수집 방식" / "확정 결정 D1~D3".

### gto_postflop_situations / gto_postflop_hands (v2, 미사용)
포스트플랍 GTO 데이터용으로 v2에 스키마만 선반영. 아직 데이터 수집 전이라
`gto/loader.py`에서 사용하지 않는다 (봇은 equity 휴리스틱으로 대체).

| 테이블 | 컬럼 | 설명 |
|---|---|---|
| `gto_postflop_situations` | `street`, `ip_position`, `oop_position` | flop/turn/river, IP/OOP 포지션 |
| | `pot_type`, `action_sequence`, `raise_size` | SRP/3BP/4BP, "check-bet" 등 |
| `gto_postflop_hands` | `situation_id`, `hand` | situations FK, 169핸드 표기 |
| | `freq_check/fold/call/raise_33~100/allin` | 팟 대비 사이즈별 빈도 |

**인덱스**: `idx_gto_post_sit (street, ip_position, oop_position)`,
`idx_gto_post_hand (situation_id, hand)`.

---

### gto_missing_spots_preflop (v3, v11에 개명)
플레이 중 만난 GTO 데이터 없는 프리플랍 스팟 큐. 수집모드가 소비.
v11에서 `gto_missing_spots` → `gto_missing_spots_preflop`으로 개명 (포스트플랍 GTO
추상화 작업 시 별도 `gto_missing_spots_postflop`이 필요해질 것을 대비한 이름공간 분리).

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `street` | TEXT | 현재 preflop만 |
| `position` | TEXT | 결정 주체 포지션(레거시 enum 큐) 또는 히어로 포지션(seq 큐) |
| `vs_position` | TEXT | RFI=`''` / vs_open=`'UTG'` / vs_3bet=`'UTG/HJ'` (레거시 enum 큐). **`range_type='seq'`일 땐 이 컬럼에 실측 사이즈 노드 키(action_seq)를 저장**(②', `gto/advisor.py::_save_missing_seq`) — `UNIQUE(street,position,vs_position,range_type)`로 자연 dedupe |
| `range_type` | TEXT | open / vs_open / vs_3bet (레거시 enum 판정) / **`seq`**(②' 시퀀스 키 조회 실패 시, 실측 트리-인지 스냅이 매칭 실패한 라이브 노드) |
| `gto_wizard_url` | TEXT | 직접 이동 URL (사전 계산 — seq 큐는 `url_from_node_key`로 실측 키 그대로 생성해 화면과 정확히 일치) |
| `collected` | INTEGER | 수집 완료 여부 |

**인덱스**: `idx_gto_missing_preflop_collected (collected)` — 미수집(0) 큐 조회용.

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

### equity_cache_stats (v9)
`--status`의 카테고리별 진행률 집계가 equity_cache 풀스캔(9,600만 행+, 실측 59초)이던
문제를 해결하기 위한 요약 테이블. `(street, num_opponents)`별 `spots`/`exact_done`/
`total_sum`을 equity_cache 쓰기 시점마다(MC 기여, exact 승격, 신규 스팟 등록) 원자적
UPSERT로 증분 갱신 — `--status`는 이 작은 테이블만 읽어 행 수와 무관하게 즉시 응답한다
(실측 59s → 0.09s).

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `street` | TEXT | preflop / flop / turn / river |
| `num_opponents` | INTEGER | 상대 수 (1~5) |
| `spots` | INTEGER | 등록된 스팟 수 (exact 여부 무관) |
| `exact_done` | INTEGER | 전수조사(exact=1) 완료 스팟 수 |
| `total_sum` | INTEGER | 누적 샘플 수 총합 |

PRIMARY KEY(street, num_opponents). 갱신 로직은 `ai/equity.py`의 `bump_equity_stats`
(모든 쓰기 지점이 공유)에 모여 있고, 각 호출자는 쓰기 직전 상태(old total/exact)와
직후 상태를 비교해 정확한 델타만 반영한다 — 특히 `_batch_upsert_exact`는 같은 배치
안에 캐노니컬 키가 중복될 수 있어(수트 정규화로 다른 실제 카드가 같은 키로 겹침)
배치 내 마지막 값 기준으로만 델타를 계산해야 이중 집계를 피할 수 있다(실측으로 드리프트
확인 후 수정).

**1회 백필**: `python3 scripts/equity_worker.py --rebuild-stats`로 equity_cache
전체를 풀스캔해 초기값을 채운다(v9 마이그레이션 직후 1회만 필요). 검증: 백필 직후 +
워커 2분 실행 전후 모두 실제 `GROUP BY` 풀스캔과 완전 일치 확인함(2026-07-10).

---

**인덱스 추가 (v10)** — `next_mc_job`/`next_mc_batch`의 프리플랍 대기 체크 쿼리
(`WHERE exact=0 AND street='preflop' AND total < ?`)를 뒷받침하는 인덱스가 없어
(v8에서 `idx_equity_street` 제거 시 이 쿼리 하나를 놓침) `equity_cache`(1억 행+) 풀스캔이
매 배치 호출마다 발생 — 프리플랍은 이미 100% 완료라 항상 0건 반환하는데도 실측 ~3.1초
소요. `--workers` 병렬 압축계산(2초대)은 정상인데 이 숨은 지연이 매번 더해져 배치
전체가 10초+처럼 보였다. 부분 인덱스로 해소:
```sql
CREATE INDEX IF NOT EXISTS idx_equity_preflop_pending
ON equity_cache(total) WHERE exact = 0 AND street = 'preflop';
```
프리플랍 대기 행만 담으므로(최대 845행) 항상 작게 유지된다. 적용 후 `EXPLAIN QUERY PLAN`이
`SEARCH equity_cache USING INDEX idx_equity_preflop_pending`을 사용함을 확인, 해당 쿼리
실행 시간 3.1초 → 마이크로초 단위로 개선(2026-07-10 실측).

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
