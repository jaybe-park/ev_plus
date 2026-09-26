# DB — 현재 사양

> 최종 갱신: 2026-09-26 · 관련 결정: [0030](../decisions/0030-sqlite-over-server-db.md), [0031](../decisions/0031-bot-hand-archive-human-hand-retain.md), [0032](../decisions/0032-partial-index-only-for-pending-queues.md), [0033](../decisions/0033-no-direct-writes-to-shared-db.md), [0020](../decisions/0020-sqlite-single-writer.md), [0021](../decisions/0021-equity-stats-incremental.md), [0038](../decisions/0038-node-row-key-is-action-seq.md)

## 무엇을 하는가

`poker.db` 하나(SQLite, WAL)에 핸드/액션 기록, 프리플랍 GTO 레인지, 에퀴티 캐시를 함께 담는다.
연결·스키마 버전·마이그레이션은 이 spec이 다룬다. 각 테이블 그룹의 **사용 규칙**(무엇을 언제 조회·저장하는가)은
해당 도메인 spec이 주인이다 — 프리플랍 GTO 테이블은 [`gto-preflop.md`](gto-preflop.md), 에퀴티 캐시는 [`equity.md`](equity.md).
원본 컬럼 정의: `db/schema.py`.

## 규칙 (지금 유효한 것만)

### 연결·파일
- DB 파일 경로는 `EV_PLUS_DB` 환경변수(테스트 격리용) → 없으면 저장소 루트의 `poker.db` 순으로 정해진다 — 강제 장치: 없음(`db/connection.py::get_connection`)
- 모든 연결에 `PRAGMA foreign_keys=ON`, `journal_mode=WAL`, `busy_timeout=30000`(ms)을 적용한다 — 근거: [0020](../decisions/0020-sqlite-single-writer.md) · 강제 장치: 없음
- 로컬 단일 사용자 SQLite를 유지한다(서버형 DB로 전환하지 않음) — 근거: [0030](../decisions/0030-sqlite-over-server-db.md)

### 쓰기 원칙 (DB 공통 — 에퀴티 워커 세부는 `equity.md`)
- 쓰기(캐시 조회·저장 포함)는 항상 메인 프로세스 1개만 한다. 병렬화는 DB에 닿지 않는 순수 계산에만 쓴다. 커넥션은 열고-쓰고-닫는다 — 근거: [0020](../decisions/0020-sqlite-single-writer.md) · 강제 장치: `tests/test_workflow.py::test_exclusive_runs`(에이전트 동시 실행만 차단, 사람이 직접 여러 프로세스를 띄우면 장치 없음)
- 게임 기록기는 액션마다 커밋하지 않고 핸드 종료 시 한 트랜잭션으로 일괄 INSERT한다(원인: 액션마다 커밋하면 recorder가 쓰기 트랜잭션을 오래 점유해 다른 프로세스가 `busy_timeout`까지 블로킹됨) — 근거: [0020](../decisions/0020-sqlite-single-writer.md) · 강제 장치: 없음(`db/recorder.py::finish_hand`)
- 공유 운영 DB(`poker.db`)에 대한 수동 쓰기(삭제·갱신·구조 변경)는 사람이 직접 `sqlite3` CLI로 하지 않고 스크립트(가능하면 `--dry-run` 지원)를 경유한다 — 근거: [0033](../decisions/0033-no-direct-writes-to-shared-db.md) · 강제 장치: 없음(TODO 후보, 아래 알려진 한계 참고)

### 스키마 버전·마이그레이션
- `SCHEMA_VERSION`(`db/schema.py`) 상수와 `schema_version` 테이블(적용 이력)로 버전을 관리한다. 연결마다 `_migrate()`가 현재 버전을 넘는 마이그레이션만 순서대로 실행한다 — 강제 장치: 없음(`db/connection.py::_migrate`)
- 신규 DB(이력 0)는 마이그레이션을 건너뛰고 `ALL_STATEMENTS`(최종 상태 DDL)만 실행한다. 기존 DB만 `MIGRATIONS[v]`를 순서대로 적용한다 — 이유: 마이그레이션에는 특정 버전에서만 유효한 `DROP`/`ALTER`(아직 존재하지 않는 테이블 대상)가 섞여 있어 신규 DB에 그대로 실행하면 에러가 나거나 불필요한 삭제가 된다 — 강제 장치: 없음
- 마이그레이션 스텝은 SQL 문자열 또는 콜러블(connection을 받는 파이썬 함수)일 수 있다. 콜러블은 순수 SQL로 표현 불가한 결정론적 데이터 백필(예: v12 노드 키 계산, `backfill_v12`)이나 테이블 재생성(v13)에 쓴다 — 강제 장치: `tests/test_poker_full.py::test_6_15_migration_normalizes_vs3bet_format`(v12 백필), `::test_7_14_migration_v13_preserves_data`(v13)
- 현재 버전은 **13**이다. v13은 `gto_preflop_situations`를 재생성해 `UNIQUE(position, vs_position, range_type)`를 없애고 `action_seq`를 `NOT NULL`로 바꾼다(행·id·핸드 보존) — 근거: [0038](../decisions/0038-node-row-key-is-action-seq.md) · 강제 장치: `tests/test_poker_full.py::test_7_14_migration_v13_preserves_data`
- 제약을 없애는 변경은 SQLite 공식 절차(새 테이블 → 복사 → 옛 테이블 DROP → 이름 변경)로 한다. 참조하는 FK가 `ON DELETE CASCADE`면 옛 테이블 DROP이 자식 행을 지우므로, 트랜잭션 밖에서 `PRAGMA foreign_keys=OFF` → 재생성 → `PRAGMA foreign_key_check` → 다시 ON 순서로 한다. 옮길 수 없는 행(예 키가 NULL)이 있으면 추측으로 채우거나 버리지 않고 예외로 멈춘다 — 강제 장치: `tests/test_poker_full.py::test_7_14_migration_v13_preserves_data`(핸드 보존·CASCADE 유지·NULL 중단)

### 인덱스
- 항상 조건이 걸리는 대기 큐(예: `exact=0`인 미완료 행)에는 **부분 인덱스**만 만든다. 조건 없는 전체 인덱스는 테이블이 커질수록 쓰기 비용만 늘고 읽기에는 안 쓰인다 — 근거: [0032](../decisions/0032-partial-index-only-for-pending-queues.md)
- 인덱스를 지우기 전에는 그 인덱스를 타는 것으로 보이는 모든 쿼리의 `EXPLAIN QUERY PLAN`을 확인한다. v8에서 "잉여"로 보고 지운 전체 인덱스가 실은 다른 쿼리 하나가 의존하던 인덱스였고, v10까지 배치마다 숨은 풀스캔(3.1초)으로 이어졌다 — 근거: [0032](../decisions/0032-partial-index-only-for-pending-queues.md) · 강제 장치: 없음(테스트 후보 — 워커 쿼리마다 `EXPLAIN QUERY PLAN`에 `SCAN`이 없는지 assert)

### 기록 흐름
`WebGameSession`이 내장한 `GameRecorder`(`db/recorder.py`)가 핸드 진행에 맞춰 아래 테이블에 쓴다. 기록 실패는 게임을 막지 않도록 호출부에서 무시한다(아레나/그라인드도 같은 세션을 써서 자동 기록됨).

| 호출 시점 | 메서드 | 대상 테이블 |
|---|---|---|
| 핸드 시작(홀카드·시작칩·딜러 확정) | `start_hand()` | `games` (INSERT) |
| 각 액션 결정 직전 | `record_action()` | 버퍼링만(DB 미접근) — `preflop_actions`/`postflop_actions` 예정 행 |
| 쇼다운/핸드 종료 | `finish_hand()` | `preflop_actions`, `postflop_actions`(버퍼 일괄 INSERT), `games`(보드·팟·승자 UPDATE), 두 액션 테이블(포지션별 `reward` 역산 UPDATE) — 한 트랜잭션 |

### 카드 표기 변환
`db/card_notation.py`가 내부 `Card` 객체 ↔ DB 저장 문자열을 변환한다: 랭크+수트 2자리(예: `As`, `Kd`, `Tc` — 10은 `T`). `games.hole_cards`/`flop_*`/`turn_card`/`river_card`는 이 표기로 저장된다 — 강제 장치: 없음

### 보존·백업
- 봇 전용 핸드(사람 미참여)는 자동 보존 상한 없이 계속 쌓인다. RL 학습 데이터로서 삭제하지 않고, N일 경과분을 Parquet/JSONL.gz로 내보낸 뒤 DB에서 제거하는 아카이브가 계획됐지만 미구현이다(`bot_version` 컬럼이 선행 조건). 사람 참여 핸드는 영구 보존 대상으로 아카이브 후보에서 제외한다 — 근거: [0031](../decisions/0031-bot-hand-archive-human-hand-retain.md)
- 정기 자동 백업은 없다. 대용량 스냅샷 백업 파일(`*.db.*backup*`)이 작업 중 임시로 남는 경우가 있어 `.gitignore`로 커밋 추적만 막아 둔다 — 파일 자체의 보관·삭제는 사람이 판단

### 미사용 테이블
- `gto_postflop_situations`/`gto_postflop_hands`는 포스트플랍 GTO 데이터용으로 스키마만 선반영돼 있다. 데이터가 없고 `gto/loader.py`도 이 테이블을 쓰지 않는다(봇은 에퀴티 휴리스틱으로 대체) — 강제 장치: 없음

## 화면·경로·데이터

| 테이블 | 용도 | 주인 spec |
|---|---|---|
| `games` | 핸드 단위 결과(참가자·보드·팟·승자) | db |
| `preflop_actions` / `postflop_actions` | 액션별 기록 + RL 컨텍스트(`equity`/`bot_profile`/`players_state`/`reward`) + 저장 시점 GTO 빈도 스냅샷 | db |
| `gto_preflop_situations` / `gto_preflop_hands` | 프리플랍 GTO 노드·핸드 빈도 | [gto-preflop.md](gto-preflop.md) |
| `gto_postflop_situations` / `gto_postflop_hands` | 포스트플랍 GTO(미사용) | 없음 |
| `gto_missing_spots_preflop` | 미수집 프리플랍 스팟 큐 | [gto-preflop.md](gto-preflop.md) |
| `equity_cache` / `equity_cache_stats` | 에퀴티 계산 결과 캐시·집계 | [equity.md](equity.md) |
| `worker_meta` | 에퀴티 워커 진행 커서(key-value) | [equity.md](equity.md) |
| `schema_version` | 적용된 마이그레이션 버전 이력 | db |

## 알려진 한계

- `equity_cache`가 파일 15GB 중 12.7GB(테이블 8.5GB + UNIQUE 인덱스 4.2GB), freelist 0이라 행을 지워도 `VACUUM INTO` 없이는 줄지 않는다 — D-23, D-15, T-036
- 봇 핸드 아카이브(내보내기 후 삭제)는 설계만 있고 미구현.
- 공유 운영 DB에 대한 수동 CLI 쓰기를 막는 장치가 없다(사람이 직접 `sqlite3 poker.db`로 `DELETE`/`UPDATE`/`DROP` 등을 실행한 이력 있음, 모두 의도된 작업이었음) — TODO 후보.
- 인덱스 삭제가 숨은 풀스캔을 유발한 사고가 2회 있었고, 이를 막는 자동 검증(`EXPLAIN QUERY PLAN` 회귀 테스트)은 아직 없다.
