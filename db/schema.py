"""
poker_simulator DB 스키마 정의 및 마이그레이션
"""

import sqlite3

SCHEMA_VERSION = 14

CREATE_GAMES = """
CREATE TABLE IF NOT EXISTS games (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    game_uuid       TEXT    NOT NULL UNIQUE,
    played_at       TEXT    NOT NULL,
    num_players     INTEGER NOT NULL CHECK(num_players BETWEEN 2 AND 6),
    small_blind     INTEGER NOT NULL,
    big_blind       INTEGER NOT NULL,
    dealer_pos      TEXT    NOT NULL CHECK(dealer_pos IN ('BTN','SB','BB','UTG','HJ','MP','CO','BTN/SB')),

    -- 홀카드: 포지션 키 JSON {"BTN":"AsJh","SB":"KdQd",...}
    hole_cards      TEXT    NOT NULL,

    -- 커뮤니티 카드 (카드 표기: As/Kd/Tc/9h 형식)
    flop_1          TEXT    CHECK(length(flop_1)  = 2),
    flop_2          TEXT    CHECK(length(flop_2)  = 2),
    flop_3          TEXT    CHECK(length(flop_3)  = 2),
    turn_card       TEXT    CHECK(length(turn_card)  = 2),
    river_card      TEXT    CHECK(length(river_card) = 2),

    -- 결과
    pot_total       INTEGER NOT NULL,
    winner_pos      TEXT    NOT NULL,  -- JSON 배열 ["BTN"] or ["BTN","CO"] (스플릿)
    player_results  TEXT    NOT NULL,  -- {"BTN":{"start":1000,"end":1150},...}

    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_PREFLOP_ACTIONS = """
CREATE TABLE IF NOT EXISTS preflop_actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    game_uuid       TEXT    NOT NULL REFERENCES games(game_uuid),
    action_seq      INTEGER NOT NULL,   -- 게임 전체 순서
    street_seq      INTEGER NOT NULL,   -- 프리플랍 내 순서

    -- 플레이어
    position        TEXT    NOT NULL CHECK(position IN ('BTN','SB','BB','UTG','HJ','MP','CO','BTN/SB')),
    is_human        INTEGER NOT NULL CHECK(is_human IN (0,1)),

    -- 베팅 라운드: 현재 몇 번째 공격인지
    bet_round       TEXT    NOT NULL CHECK(bet_round IN ('open','3bet','4bet','5bet')),

    -- 상황
    pot_before      INTEGER NOT NULL,
    stack_before    INTEGER NOT NULL,
    current_bet     INTEGER NOT NULL,
    call_amount     INTEGER NOT NULL,

    -- 액션
    action          TEXT    NOT NULL CHECK(action IN ('fold','call','raise','allin')),
    amount          INTEGER NOT NULL DEFAULT 0,
    amount_bb       REAL    NOT NULL DEFAULT 0,  -- BB 기준 환산 (2.5, 7.5, 22.0 ...)

    -- RL 학습용 컨텍스트
    equity          REAL,               -- 결정 시점 봇 계산 equity
    bot_profile     TEXT,               -- "hard/balanced", "human" 등
    players_state   TEXT,               -- 결정 직전 전원 상태 JSON
    reward          REAL,               -- 핸드 종료 후 역산 (bb 단위)

    -- GTO 빈도 (베팅 라운드 내 액션 단위, 사이즈는 amount_bb로 기록)
    gto_fold        REAL    CHECK(gto_fold  BETWEEN 0 AND 1),
    gto_call        REAL    CHECK(gto_call  BETWEEN 0 AND 1),
    gto_raise       REAL    CHECK(gto_raise BETWEEN 0 AND 1),
    gto_allin       REAL    CHECK(gto_allin BETWEEN 0 AND 1),

    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),

    UNIQUE(game_uuid, action_seq)
);
"""

CREATE_POSTFLOP_ACTIONS = """
CREATE TABLE IF NOT EXISTS postflop_actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    game_uuid       TEXT    NOT NULL REFERENCES games(game_uuid),
    action_seq      INTEGER NOT NULL,   -- 게임 전체 순서
    street_seq      INTEGER NOT NULL,   -- 해당 스트리트 내 순서

    -- 플레이어
    position        TEXT    NOT NULL CHECK(position IN ('BTN','SB','BB','UTG','HJ','MP','CO','BTN/SB')),
    is_human        INTEGER NOT NULL CHECK(is_human IN (0,1)),

    -- 스트리트
    street          TEXT    NOT NULL CHECK(street IN ('flop','turn','river')),

    -- 상황
    pot_before      INTEGER NOT NULL,
    stack_before    INTEGER NOT NULL,
    current_bet     INTEGER NOT NULL,
    call_amount     INTEGER NOT NULL,

    -- 액션
    action          TEXT    NOT NULL CHECK(action IN ('fold','check','call','raise','allin')),
    amount          INTEGER NOT NULL DEFAULT 0,

    -- RL 학습용 컨텍스트
    equity          REAL,
    bot_profile     TEXT,
    players_state   TEXT,

    -- GTO 빈도 (팟 기준 이산화)
    gto_fold        REAL    CHECK(gto_fold       BETWEEN 0 AND 1),
    gto_check       REAL    CHECK(gto_check      BETWEEN 0 AND 1),
    gto_call        REAL    CHECK(gto_call       BETWEEN 0 AND 1),
    gto_raise_33    REAL    CHECK(gto_raise_33   BETWEEN 0 AND 1),
    gto_raise_50    REAL    CHECK(gto_raise_50   BETWEEN 0 AND 1),
    gto_raise_75    REAL    CHECK(gto_raise_75   BETWEEN 0 AND 1),
    gto_raise_100   REAL    CHECK(gto_raise_100  BETWEEN 0 AND 1),
    gto_raise_150   REAL    CHECK(gto_raise_150  BETWEEN 0 AND 1),
    gto_allin       REAL    CHECK(gto_allin      BETWEEN 0 AND 1),

    -- RL 학습용 (포스트플랍만)
    state_vector    TEXT,   -- JSON, RL 붙일 때 채움
    reward          REAL,   -- 핸드 종료 후 역산해서 업데이트

    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),

    UNIQUE(game_uuid, action_seq)
);
"""

CREATE_SCHEMA_VERSION = """
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER NOT NULL,
    applied_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_preflop_pos   ON preflop_actions(position);
CREATE INDEX IF NOT EXISTS idx_preflop_human ON preflop_actions(is_human);
CREATE INDEX IF NOT EXISTS idx_postflop_street ON postflop_actions(street);
CREATE INDEX IF NOT EXISTS idx_postflop_pos    ON postflop_actions(position);
CREATE INDEX IF NOT EXISTS idx_postflop_human  ON postflop_actions(is_human);
CREATE INDEX IF NOT EXISTS idx_games_played    ON games(played_at);
"""

# v8: game_uuid 단일 컬럼 인덱스를 (game_uuid, position) 복합 인덱스로 대체.
# reward 역산 UPDATE(WHERE game_uuid=? AND position=?)가 왼쪽 접두로 이 인덱스를 탄다.
CREATE_GAME_POS_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_preflop_game_pos  ON preflop_actions(game_uuid, position);
CREATE INDEX IF NOT EXISTS idx_postflop_game_pos ON postflop_actions(game_uuid, position);
"""

# v11: raise_size를 TEXT("3x" 플레이스홀더) → REAL(bb 단위 실측 raise-to 숫자,
# 예: 8.0, 11.0, 13.5)로 변경. 사이징은 배수 공식으로 추론 불가 — GTO Wizard에서
# 실측한 값만 저장한다 (ADR 0004 참고).
# v12: 프리플랍 노드 키 컬럼 추가.
#   - action_seq: 히어로 결정 직전까지의 액션 시퀀스(노드 키, 예 "R2.5-R8-F-F-F-F",
#     RFI UTG는 ""). 스퀴즈·멀티웨이·4벳+ 노드도 담는다.
#   - hero_position/num_active: 시퀀스에서 파생한 조회/디버깅용 컬럼.
#   UNIQUE(action_seq)는 유니크 인덱스 idx_gto_pre_seq로 강제한다.
# v13 (ADR 0044): 노드의 유일 키는 action_seq 하나다. UNIQUE(position, vs_position,
#   range_type)를 제거하고(서로 다른 노드 — 예 R2.5-F와 R2.5-C — 가 같은 3종 키를 가질 수
#   있음) action_seq를 NOT NULL로 바꾼다. 3종 키는 action_seq에서 유도한 조회용 라벨이다.
#   SQLite는 제약 삭제 ALTER가 없어 테이블 재생성으로 옮긴다(rebuild_gto_preflop_situations_v13).
CREATE_GTO_PREFLOP_SITUATIONS = """
CREATE TABLE IF NOT EXISTS gto_preflop_situations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    position        TEXT    NOT NULL,   -- 히어로 포지션(action_seq에서 유도): UTG, HJ, CO, BTN, SB, BB
    vs_position     TEXT,               -- NULL = RFI, 레이저 좌석을 '/'로 연결(action_seq에서 유도)
    range_type      TEXT    NOT NULL,   -- open | vs_open | vs_3bet | vs_4bet ... (action_seq에서 유도)
    raise_size      REAL,               -- bb 단위 실측 raise-to 값 (예: 2.5, 8.0, 13.5)
    situation_label TEXT    NOT NULL,   -- "BTN RFI", "BB vs BTN open"
    action_seq      TEXT    NOT NULL,   -- 노드 키(히어로 결정 직전 시퀀스). 유일(idx_gto_pre_seq)
    hero_position   TEXT,               -- v12: 결정 주체(시퀀스 파생, 조회용)
    num_active      INTEGER             -- v12: 히어로 결정 시점 미폴드 인원(6 - 폴드수, 파생)
);
"""

CREATE_GTO_PREFLOP_HANDS = """
CREATE TABLE IF NOT EXISTS gto_preflop_hands (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    situation_id    INTEGER NOT NULL REFERENCES gto_preflop_situations(id) ON DELETE CASCADE,
    hand            TEXT    NOT NULL,   -- "AKs", "AA", "K7o"
    freq_fold       REAL    NOT NULL DEFAULT 0.0,
    freq_call       REAL    NOT NULL DEFAULT 0.0,
    freq_raise      REAL    NOT NULL DEFAULT 0.0,
    freq_allin      REAL    NOT NULL DEFAULT 0.0,
    UNIQUE(situation_id, hand)
);
"""

CREATE_GTO_POSTFLOP_SITUATIONS = """
CREATE TABLE IF NOT EXISTS gto_postflop_situations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    street          TEXT    NOT NULL,   -- flop | turn | river
    ip_position     TEXT    NOT NULL,   -- in-position 플레이어
    oop_position    TEXT    NOT NULL,   -- out-of-position 플레이어
    pot_type        TEXT,               -- SRP | 3BP | 4BP
    action_sequence TEXT,               -- "check-bet" | "bet-raise" 등
    raise_size      TEXT,
    situation_label TEXT,
    UNIQUE(street, ip_position, oop_position, pot_type, action_sequence)
);
"""

CREATE_GTO_POSTFLOP_HANDS = """
CREATE TABLE IF NOT EXISTS gto_postflop_hands (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    situation_id    INTEGER NOT NULL REFERENCES gto_postflop_situations(id) ON DELETE CASCADE,
    hand            TEXT    NOT NULL,
    freq_check      REAL    DEFAULT 0.0,
    freq_fold       REAL    DEFAULT 0.0,
    freq_call       REAL    DEFAULT 0.0,
    freq_raise_33   REAL    DEFAULT 0.0,
    freq_raise_50   REAL    DEFAULT 0.0,
    freq_raise_75   REAL    DEFAULT 0.0,
    freq_raise_100  REAL    DEFAULT 0.0,
    freq_allin      REAL    DEFAULT 0.0,
    UNIQUE(situation_id, hand)
);
"""

CREATE_GTO_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_gto_pre_sit   ON gto_preflop_situations(position, vs_position, range_type);
CREATE INDEX IF NOT EXISTS idx_gto_pre_hand  ON gto_preflop_hands(situation_id, hand);
CREATE INDEX IF NOT EXISTS idx_gto_post_sit  ON gto_postflop_situations(street, ip_position, oop_position);
CREATE INDEX IF NOT EXISTS idx_gto_post_hand ON gto_postflop_hands(situation_id, hand);
"""

# v12: 시퀀스 키(노드 키) 유니크 인덱스. nullable 컬럼이라 NULL은 서로 distinct로
# 취급돼 여러 행이 아직 키 없이(NULL) 공존 가능(부분/nullable 허용). 백필된 실측 값은
# 서로 distinct해야 함 → 저장/조회 노드 키의 1:1 매칭을 인덱스가 강제.
CREATE_GTO_PREFLOP_SEQ_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_gto_pre_seq ON gto_preflop_situations(action_seq);
"""

# v11: gto_missing_spots → gto_missing_spots_preflop 개명(포스트플랍 큐와 이름공간 분리).
# 시퀀스 큐 행은 range_type='seq', 노드 키는 vs_position 칸(ADR 0035).
CREATE_GTO_MISSING_SPOTS_PREFLOP = """
CREATE TABLE IF NOT EXISTS gto_missing_spots_preflop (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    street          TEXT    NOT NULL DEFAULT 'preflop',  -- preflop | flop | turn | river
    position        TEXT    NOT NULL,   -- 결정 주체 포지션
    vs_position     TEXT    NOT NULL DEFAULT '',  -- RFI='' / vs_open='UTG' / vs_3bet='UTG/HJ'
    range_type      TEXT    NOT NULL,   -- open | vs_open | vs_3bet
    situation_label TEXT    NOT NULL,   -- 사람이 읽기 쉬운 설명
    gto_wizard_url  TEXT,               -- 직접 이동 URL (프리플랍만)
    discovered_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    collected       INTEGER NOT NULL DEFAULT 0,
    collected_at    TEXT,
    UNIQUE(street, position, vs_position, range_type)
);
"""

CREATE_GTO_MISSING_PREFLOP_INDEX = """
CREATE INDEX IF NOT EXISTS idx_gto_missing_preflop_collected ON gto_missing_spots_preflop(collected);
"""

# v4~v10의 에퀴티 캐시 스키마(equity_cache, worker_meta, equity_cache_stats와 대기 큐
# 부분 인덱스들)는 ADR 0034로 폐기됐다. 새 DB는 이 테이블들을 만들지 않고, 코드도 읽거나
# 쓰지 않는다. 기존 DB의 테이블은 DROP하지 않는다(운영 DB 직접 변경 금지, ADR 0033).
# 아래 MIGRATIONS의 v7·v9·v10 스텝은 이력 보존용 no-op이다.

def backfill_v12(conn):
    """v12 백필: 기존 gto_preflop_situations 행에 캐노니컬 노드 키(action_seq) +
    hero_position + num_active를 결정론적으로 채우고, vs_3bet vs_position 포맷을
    정규화한다. 데이터 손실 0(기존 컬럼은 그대로 두고 파생 컬럼만 UPDATE).

    - 노드 키는 gto.url_generator.situation_to_node_key(깊이-캐노니컬 사이즈)로 만든다.
    - vs_3bet 정규화: 데이터 모델은 "오프너가 3벳에 대응"하는 레인지만 담으므로
      opener == hero(position)다. three_bettor만 저장된 행(예: BTN 행 vs_position="BB")을
      'opener/three_bettor'(="BTN/BB")로 정규화해 loader.get_vs_3bet_range 조회 키와 맞춘다.

    connection._migrate가 이 함수를 콜러블 마이그레이션 스텝으로 호출한다(호출부에서
    최종 conn.commit 수행). 신규 DB(current==0)에서는 마이그레이션이 실행되지 않으므로
    (백필할 기존 데이터 없음) 호출되지 않는다.
    """
    from gto.url_generator import situation_to_node_key  # 지연 임포트(순환 방지)
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT id, position, vs_position, range_type FROM gto_preflop_situations"
    ).fetchall()
    for r in rows:
        rid, position, vs_position, range_type = (
            r["id"], r["position"], r["vs_position"], r["range_type"]
        )
        norm_vs = vs_position
        if range_type == "vs_3bet" and vs_position and "/" not in vs_position:
            # three_bettor만 저장된 반쪽 포맷 → opener(=hero=position)를 앞에 붙여 정규화
            norm_vs = f"{position}/{vs_position}"
        node_key = situation_to_node_key(position, norm_vs, range_type)
        num_active = None
        if node_key is not None:
            folds = sum(1 for t in node_key.split("-") if t == "F") if node_key else 0
            num_active = 6 - folds
        cur.execute(
            "UPDATE gto_preflop_situations "
            "SET vs_position=?, action_seq=?, hero_position=?, num_active=? WHERE id=?",
            (norm_vs, node_key, position, num_active, rid),
        )


def rebuild_gto_preflop_situations_v13(conn):
    """v13: gto_preflop_situations 테이블 재생성 — UNIQUE(position, vs_position, range_type)
    제거 + action_seq NOT NULL. 모든 행(id 포함)과 gto_preflop_hands는 그대로 보존한다.

    SQLite 공식 "테이블 스키마 변경" 절차(새 테이블 생성 → 복사 → 옛 테이블 삭제 → 이름 변경)를
    따른다. gto_preflop_hands가 ON DELETE CASCADE FK로 이 테이블을 참조하므로, 옛 테이블 DROP이
    핸드를 지우지 않도록 foreign_keys를 잠시 끈다(PRAGMA는 트랜잭션 밖에서만 바뀌므로 먼저
    커밋). 복사 뒤 foreign_key_check로 고아 핸드가 없는지 확인한 다음 다시 켠다.

    action_seq가 NULL인 행이 있으면 노드 키를 알 수 없어 옮길 수 없다 — 추측으로 채우거나
    조용히 버리지 않고 예외를 낸다.
    """
    conn.commit()
    nulls = conn.execute(
        "SELECT COUNT(*) FROM gto_preflop_situations WHERE action_seq IS NULL"
    ).fetchone()[0]
    if nulls:
        raise RuntimeError(
            f"v13 마이그레이션 중단: action_seq가 NULL인 gto_preflop_situations {nulls}행 — "
            "노드 키를 먼저 채우거나 지운 뒤 다시 실행하세요(추측으로 채우지 않음)."
        )
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.executescript(
            """
            BEGIN;
            CREATE TABLE gto_preflop_situations_v13 (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                position        TEXT    NOT NULL,
                vs_position     TEXT,
                range_type      TEXT    NOT NULL,
                raise_size      REAL,
                situation_label TEXT    NOT NULL,
                action_seq      TEXT    NOT NULL,
                hero_position   TEXT,
                num_active      INTEGER
            );
            INSERT INTO gto_preflop_situations_v13
                (id, position, vs_position, range_type, raise_size, situation_label,
                 action_seq, hero_position, num_active)
            SELECT id, position, vs_position, range_type, raise_size, situation_label,
                   action_seq, hero_position, num_active
            FROM gto_preflop_situations;
            DROP TABLE gto_preflop_situations;
            ALTER TABLE gto_preflop_situations_v13 RENAME TO gto_preflop_situations;
            CREATE INDEX IF NOT EXISTS idx_gto_pre_sit
                ON gto_preflop_situations(position, vs_position, range_type);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_gto_pre_seq
                ON gto_preflop_situations(action_seq);
            COMMIT;
            """
        )
        orphans = conn.execute("PRAGMA foreign_key_check(gto_preflop_hands)").fetchall()
        if orphans:
            raise RuntimeError(f"v13 마이그레이션 후 고아 핸드 {len(orphans)}행 — FK 확인 필요")
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def relabel_limp_nodes_v14(conn):
    """v14 (ADR 0046): 림프 노드가 range_type='open'/situation_label "{H} RFI"로 저장된
    행(예 action_seq="F-F-F-F-C"가 "BB RFI")을 'vs_limp'로 재라벨링한다.

    range_type='open'으로 저장된 행만 대상으로 새 derive_node_meta를 재계산해
    'vs_limp'로 나오는 행만 옮긴다(그 밖의 행·라벨은 건드리지 않음 — 추측 재라벨 금지).
    action_seq가 없거나(NULL, v13 이후 없음) 재계산 결과가 없으면(결정 노드 아님) 스킵.
    """
    from gto.node_key import derive_node_meta
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT id, action_seq FROM gto_preflop_situations WHERE range_type='open'"
    ).fetchall()
    for r in rows:
        meta = derive_node_meta(r["action_seq"]) if r["action_seq"] else None
        if meta is None or meta["range_type"] != "vs_limp":
            continue
        cur.execute(
            "UPDATE gto_preflop_situations "
            "SET vs_position=?, range_type=?, situation_label=? WHERE id=?",
            (meta["vs_position"], meta["range_type"], meta["situation_label"], r["id"]),
        )


# 버전별 1회성 마이그레이션 (connection._migrate가 현재버전 초과분만 실행)
# 각 스텝은 SQL 문자열(executescript) 또는 콜러블(conn을 받는 파이썬 함수)일 수 있다.
MIGRATIONS = {
    6: [
        "DROP TABLE IF EXISTS preflop_actions;",
        "DROP TABLE IF EXISTS postflop_actions;",
        "DROP TABLE IF EXISTS games;",
    ],
    7: [
        # (폐기, ADR 0034) equity_cache 대기 큐 부분 인덱스 2개 — no-op
    ],
    8: [
        # 저선택도 idx_preflop_pos/idx_postflop_pos 위 game_uuid 단일 인덱스는
        # 복합 인덱스(game_uuid, position)가 왼쪽 접두로 대체 → DROP
        "DROP INDEX IF EXISTS idx_preflop_game;",
        "DROP INDEX IF EXISTS idx_postflop_game;",
        CREATE_GAME_POS_INDEXES,
        # idx_equity_street(766만 행 전체 인덱스) 잉여 — idx_equity_pending이 대기 조회 전담
        "DROP INDEX IF EXISTS idx_equity_street;",
    ],
    9: [
        # (폐기, ADR 0034) equity_cache_stats 요약 테이블 — no-op
    ],
    10: [
        # (폐기, ADR 0034) equity_cache 프리플랍 대기 부분 인덱스 — no-op
    ],
    11: [
        # 근본 버그(콜/올인 색상 임계값 오탐)로 손상된 프리플랍 GTO 데이터 전량
        # 무효화 + raise_size TEXT("3x" 플레이스홀더) → REAL(실측 bb) 재정의.
        # 이미 데이터를 지우는 참이라 컬럼 마이그레이션 대신 DROP 후 재생성.
        "DROP TABLE IF EXISTS gto_preflop_hands;",
        "DROP TABLE IF EXISTS gto_preflop_situations;",
        "DROP INDEX IF EXISTS idx_gto_missing_collected;",
        "ALTER TABLE gto_missing_spots RENAME TO gto_missing_spots_preflop;",
    ],
    12: [
        # 노드 키 컬럼 추가 + 백필.
        # SQLite ADD COLUMN은 UNIQUE 제약을 인라인으로 못 붙이므로(문서 제약) 컬럼만
        # 추가하고, 유니크는 아래 부분 유니크 인덱스로 별도 강제한다.
        "ALTER TABLE gto_preflop_situations ADD COLUMN action_seq TEXT;",
        "ALTER TABLE gto_preflop_situations ADD COLUMN hero_position TEXT;",
        "ALTER TABLE gto_preflop_situations ADD COLUMN num_active INTEGER;",
        # 콜러블 스텝: 기존 행 결정론적 백필 + vs_3bet 포맷 정규화(반드시 인덱스 생성 전).
        backfill_v12,
        # 백필로 채워진 action_seq가 서로 distinct임을 유니크 인덱스로 강제.
        CREATE_GTO_PREFLOP_SEQ_INDEX,
    ],
    13: [
        # ADR 0044: 노드 유일 키 = action_seq. 3종 키 UNIQUE 제거(테이블 재생성).
        rebuild_gto_preflop_situations_v13,
    ],
    14: [
        # ADR 0046: 림프 노드가 'open'/"{H} RFI"로 저장된 기존 행을 'vs_limp'로 재라벨링.
        relabel_limp_nodes_v14,
    ],
}

ALL_STATEMENTS = [
    CREATE_GAMES,
    CREATE_PREFLOP_ACTIONS,
    CREATE_POSTFLOP_ACTIONS,
    CREATE_SCHEMA_VERSION,
    CREATE_INDEXES,
    # v2: GTO 데이터
    CREATE_GTO_PREFLOP_SITUATIONS,
    CREATE_GTO_PREFLOP_HANDS,
    CREATE_GTO_POSTFLOP_SITUATIONS,
    CREATE_GTO_POSTFLOP_HANDS,
    CREATE_GTO_INDEXES,
    # v12: 프리플랍 시퀀스 키(노드 키) 유니크 인덱스
    CREATE_GTO_PREFLOP_SEQ_INDEX,
    # v3: 미수집 스팟 큐 (v11: gto_missing_spots → gto_missing_spots_preflop 개명)
    CREATE_GTO_MISSING_SPOTS_PREFLOP,
    CREATE_GTO_MISSING_PREFLOP_INDEX,
    # v8: (game_uuid, position) 복합 인덱스 — reward 역산 UPDATE 최적화
    CREATE_GAME_POS_INDEXES,
]
