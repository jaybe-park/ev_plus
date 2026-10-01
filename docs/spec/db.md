# DB — 현재 사양

> 최종 갱신: 2026-10-01 · 관련 결정: [0030](../decisions/0030-sqlite-over-server-db.md), [0031](../decisions/0031-bot-hand-archive-human-hand-retain.md), [0033](../decisions/0033-no-direct-writes-to-shared-db.md), [0020](../decisions/0020-sqlite-single-writer.md), [0034](../decisions/0034-abolish-equity-cache.md), [0044](../decisions/0044-node-row-key-is-action-seq.md), [0046](../decisions/0046-limp-nodes-are-vs-limp-not-open.md)

## 무엇을 하는가

`poker.db` 하나(SQLite, WAL)에 핸드/액션 기록과 프리플랍 GTO 레인지를 담는다. 에퀴티는 저장하지 않는다(캐시 폐기, ADR 0034).
연결·스키마 버전·마이그레이션은 이 spec이 다룬다. 각 테이블 그룹의 **사용 규칙**(무엇을 언제 조회·저장하는가)은
해당 도메인 spec이 주인이다 — 프리플랍 GTO 테이블은 [`gto-preflop.md`](gto-preflop.md).
원본 컬럼 정의: `db/schema.py`.

## 규칙 (지금 유효한 것만)

### 연결·파일
- DB 파일 경로는 `EV_PLUS_DB` 환경변수(테스트 격리용) → 없으면 저장소 루트의 `poker.db` 순으로 정해진다(`db/connection.py::resolve_db_path`) — 강제 장치: 없음
- 앱 연결(`get_connection`)은 `PRAGMA foreign_keys=ON`, `journal_mode=WAL`, `busy_timeout=30000`(ms)을 적용하고 마이그레이션을 돌린다 — 근거: [0020](../decisions/0020-sqlite-single-writer.md) · 강제 장치: 없음
- 운영 DB를 읽기만 하는 도구(감사 `audit_gto_preflop.py`, 체크포인트 재시드, `prune_missing_spots.py --dry-run`)는 `get_readonly_connection`(`mode=ro`)을 쓴다 — 마이그레이션·PRAGMA 쓰기를 하지 않고, 파일이 없으면 만들지 않고 실패한다 — 근거: [0033](../decisions/0033-no-direct-writes-to-shared-db.md) · 강제 장치: `tests/test_gto_tree.py::test_audit_checks`, `::test_prune_missing_spots`(dry-run이 DB를 바꾸지 않음)
- 로컬 단일 사용자 SQLite를 유지한다(서버형 DB로 전환하지 않음) — 근거: [0030](../decisions/0030-sqlite-over-server-db.md)

### 쓰기 원칙 (DB 공통)
- 쓰기는 항상 메인 프로세스 1개만 한다. 병렬화는 DB에 닿지 않는 순수 계산에만 쓴다. 커넥션은 열고-쓰고-닫는다 — 근거: [0020](../decisions/0020-sqlite-single-writer.md) · 강제 장치: hook `.claude/hooks/block_dangerous.py`가 에이전트의 그라인드·튜닝·GTO 수집 동시 실행을 막는다(`tests/test_workflow.py::test_exclusive_runs`). 사람이 직접 여러 프로세스를 띄우면 장치 없음
- 게임 기록기는 액션마다 커밋하지 않고 핸드 종료 시 한 트랜잭션으로 일괄 INSERT한다(액션마다 커밋하면 쓰기 트랜잭션을 오래 점유해 다른 프로세스가 `busy_timeout`까지 블로킹됨) — 근거: [0020](../decisions/0020-sqlite-single-writer.md) · 강제 장치: 없음(`db/recorder.py::finish_hand`)
- 공유 운영 DB(`poker.db`)에 대한 수동 쓰기(삭제·갱신·구조 변경)는 `sqlite3` CLI·`python -c`로 하지 않고 `--dry-run`을 지원하는 스크립트를 경유한다 — 근거: [0033](../decisions/0033-no-direct-writes-to-shared-db.md) · 강제 장치: hook `.claude/hooks/block_dangerous.py`(에이전트 명령의 `sqlite3 … poker.db … DELETE/UPDATE/…`·`python -c … poker.db …` 차단, `tests/test_workflow.py::test_block_patterns`). 사람이 터미널에서 직접 실행하면 장치 없음

### 스키마 버전·마이그레이션
- `SCHEMA_VERSION`(`db/schema.py`) 상수와 `schema_version` 테이블(적용 이력)로 버전을 관리한다. 연결마다 `_migrate()`가 현재 버전을 넘는 마이그레이션만 순서대로 실행한다 — 강제 장치: 없음(`db/connection.py::_migrate`)
- 신규 DB(이력 0)는 마이그레이션을 건너뛰고 `ALL_STATEMENTS`(최종 상태 DDL)만 실행한다. 기존 DB만 `MIGRATIONS[v]`를 순서대로 적용한다 — 마이그레이션에는 특정 버전에서만 유효한 `DROP`/`ALTER`가 섞여 있어 신규 DB에 실행하면 에러나 불필요한 삭제가 된다 — 강제 장치: 없음
- 마이그레이션 스텝은 SQL 문자열 또는 콜러블(connection을 받는 파이썬 함수)이다. 콜러블은 순수 SQL로 표현 불가한 결정론적 데이터 백필·재라벨(v12 `backfill_v12`, v14 `relabel_limp_nodes_v14`)이나 테이블 재생성(v13)에 쓴다 — 강제 장치: `tests/test_poker_full.py::test_6_15_migration_normalizes_vs3bet_format`(v12), `::test_7_14_migration_v13_preserves_data`(v13), `::test_7_15_migration_v14_relabels_limp_nodes`(v14)
- 현재 버전은 **14**다(운영 `poker.db`는 2026-10-01에 v14 적용, 적용 전 백업 `poker.db.pre-v14.backup`). v13은 `gto_preflop_situations`를 재생성해 `UNIQUE(position, vs_position, range_type)`를 없애고 `action_seq`를 `NOT NULL`로 바꾼다(행·id·핸드 보존). v14는 림프 노드가 `open`으로 저장된 행을 `vs_limp`로 재라벨링한다 — 근거: [0044](../decisions/0044-node-row-key-is-action-seq.md), [0046](../decisions/0046-limp-nodes-are-vs-limp-not-open.md)
- 제약을 없애는 변경은 SQLite 공식 절차(새 테이블 → 복사 → 옛 테이블 DROP → 이름 변경)로 한다. 참조하는 FK가 `ON DELETE CASCADE`면 옛 테이블 DROP이 자식 행을 지우므로, 트랜잭션 밖에서 `PRAGMA foreign_keys=OFF` → 재생성 → `PRAGMA foreign_key_check` → 다시 ON 순서로 한다. 옮길 수 없는 행(예 키가 NULL)이 있으면 추측으로 채우거나 버리지 않고 예외로 멈춘다 — 강제 장치: `tests/test_poker_full.py::test_7_14_migration_v13_preserves_data`
- 에퀴티 캐시 테이블(`equity_cache`, `equity_cache_stats`, `worker_meta`)은 `ALL_STATEMENTS`에 없다 — 새 DB는 만들지 않는다. v7·v9·v10 마이그레이션 스텝은 이력 보존용 no-op이다. 기존 DB의 테이블은 마이그레이션이 DROP하지 않는다 — 근거: [0034](../decisions/0034-abolish-equity-cache.md) · 강제 장치: `tests/test_equity.py::test_no_db_writes`(새 DB에 에퀴티 테이블 없음)

### 기록 흐름
`WebGameSession`이 내장한 `GameRecorder`(`db/recorder.py`)가 핸드 진행에 맞춰 아래 테이블에 쓴다. 기록 실패는 게임을 막지 않도록 호출부에서 무시한다(아레나/그라인드도 같은 세션을 써서 자동 기록됨).

| 호출 시점 | 메서드 | 대상 테이블 |
|---|---|---|
| 핸드 시작(홀카드·시작칩·딜러 확정) | `start_hand()` | `games` (INSERT) |
| 각 액션 결정 직전 | `record_action()` | 버퍼링만(DB 미접근) — `preflop_actions`/`postflop_actions` 예정 행 |
| 쇼다운/핸드 종료 | `finish_hand()` | `preflop_actions`, `postflop_actions`(버퍼 일괄 INSERT), `games`(보드·팟·승자 UPDATE), 두 액션 테이블(포지션별 `reward` 역산 UPDATE) — 한 트랜잭션 |

기록 테이블을 읽는 코드는 지금 없다(조회 계층 없음).

### 카드 표기 변환
`db/card_notation.py`가 내부 `Card` 객체 ↔ DB 저장 문자열을 변환한다: 랭크+수트 2자리(예: `As`, `Kd`, `Tc` — 10은 `T`). `games.hole_cards`/`flop_*`/`turn_card`/`river_card`는 이 표기로 저장된다 — 강제 장치: 없음

### 보존·백업
- 봇 전용 핸드(사람 미참여)는 자동 보존 상한 없이 계속 쌓인다. N일 경과분을 Parquet/JSONL.gz로 내보낸 뒤 DB에서 제거하는 아카이브가 계획됐지만 미구현이다(`bot_version` 컬럼이 선행 조건). 사람 참여 핸드는 영구 보존 대상으로 아카이브 후보에서 제외한다 — 근거: [0031](../decisions/0031-bot-hand-archive-human-hand-retain.md)
- 정기 자동 백업은 없다. 스냅샷 백업 파일(`*.db.*backup*`, `poker.db.bak`)은 `.gitignore`로 커밋 추적만 막는다 — 파일 자체의 보관·삭제는 사람이 판단

### 미사용 테이블
- `gto_postflop_situations`/`gto_postflop_hands`는 포스트플랍 GTO 데이터용으로 스키마만 있다. 데이터가 없고 `gto/loader.py`도 이 테이블을 쓰지 않는다 — 강제 장치: 없음

## 화면·경로·데이터

| 테이블 | 용도 | 주인 spec |
|---|---|---|
| `games` | 핸드 단위 결과(참가자·보드·팟·승자) | db |
| `preflop_actions` / `postflop_actions` | 액션별 기록 + RL 컨텍스트(`equity`/`bot_profile`/`players_state`/`reward`) + 저장 시점 GTO 빈도 스냅샷 | db |
| `gto_preflop_situations` / `gto_preflop_hands` | 프리플랍 GTO 노드·핸드 빈도 | [gto-preflop.md](gto-preflop.md) |
| `gto_postflop_situations` / `gto_postflop_hands` | 포스트플랍 GTO(미사용) | 없음 |
| `gto_missing_spots_preflop` | 미수집 프리플랍 스팟 큐 | [gto-preflop.md](gto-preflop.md) |
| `schema_version` | 적용된 마이그레이션 버전 이력 | db |

## 알려진 한계

- 옛 DB 파일에는 `equity_cache`/`equity_cache_stats`/`worker_meta`가 남아 있을 수 있다(코드는 읽거나 쓰지 않음). 운영 `poker.db`에는 없다(약 2.2GB, D-15).
- 기록 테이블(`games`·액션 테이블, 약 2.1GB)은 쓰기만 되고 읽는 코드가 없다(처리는 DECISIONS D-31).
- 봇 핸드 아카이브(내보내기 후 삭제)는 설계만 있고 미구현.
- 사람이 터미널에서 직접 `sqlite3 poker.db`로 쓰는 것은 막지 못한다(hook은 에이전트 명령만 본다).
- 인덱스를 지울 때 숨은 풀스캔을 막는 자동 검증(`EXPLAIN QUERY PLAN` 회귀 테스트)은 없다.
