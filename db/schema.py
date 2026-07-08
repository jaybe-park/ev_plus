"""
poker_simulator DB 스키마 정의 및 마이그레이션
"""

SCHEMA_VERSION = 8

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

CREATE_GTO_PREFLOP_SITUATIONS = """
CREATE TABLE IF NOT EXISTS gto_preflop_situations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    position        TEXT    NOT NULL,   -- BTN, CO, MP, UTG, SB, BB
    vs_position     TEXT,               -- NULL = RFI, 오프너 포지션 = vs_open/vs_3bet
    range_type      TEXT    NOT NULL,   -- open | vs_open | vs_3bet
    raise_size      TEXT,               -- "2.5bb", "3x"
    situation_label TEXT    NOT NULL,   -- "BTN RFI", "BB vs BTN open"
    UNIQUE(position, vs_position, range_type)
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

CREATE_GTO_MISSING_SPOTS = """
CREATE TABLE IF NOT EXISTS gto_missing_spots (
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

CREATE_GTO_MISSING_INDEX = """
CREATE INDEX IF NOT EXISTS idx_gto_missing_collected ON gto_missing_spots(collected);
"""

CREATE_EQUITY_CACHE = """
CREATE TABLE IF NOT EXISTS equity_cache (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    street          TEXT    NOT NULL,   -- preflop | flop | turn | river
    spot_key        TEXT    NOT NULL,   -- 수트 정규화된 (홀카드|플랍|턴|리버) 키
    num_opponents   INTEGER NOT NULL,
    wins            REAL    NOT NULL DEFAULT 0,   -- 누적 승리 수
    ties            REAL    NOT NULL DEFAULT 0,   -- 누적 무승부 수
    total           INTEGER NOT NULL DEFAULT 0,   -- 누적 샘플 수 (0 = 계산 대기)
    exact           INTEGER NOT NULL DEFAULT 0,   -- 1 = 전수조사 완료 (정확값)
    updated_at      TEXT    DEFAULT (datetime('now')),
    UNIQUE(spot_key, num_opponents)
);
"""

# v8: idx_equity_street(766만 행 전체 인덱스) 제거됨 — idx_equity_pending 부분 인덱스가
# 대기 조회를 전담하므로 잉여. 쓰기 비용만 유발해 DROP.

# v7: exact=0 & num_opponents=1 대기 행만 담는 부분 인덱스.
# exact=1로 승격되면 인덱스에서 자동 제거되어 항상 작게 유지됨 (760만 행 스캔 회피).
CREATE_EQUITY_PENDING_INDEX = """
CREATE INDEX IF NOT EXISTS idx_equity_pending
ON equity_cache(street, total, id) WHERE exact = 0 AND num_opponents = 1;
"""

# v7: 멀티웨이(상대 2명+) 샘플링 대상 대기 행 전용 부분 인덱스 (next_mc_job 병목 해소)
CREATE_EQUITY_MULTIWAY_INDEX = """
CREATE INDEX IF NOT EXISTS idx_equity_multiway_pending
ON equity_cache(total) WHERE exact = 0 AND num_opponents > 1;
"""

CREATE_WORKER_META = """
CREATE TABLE IF NOT EXISTS worker_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# 버전별 1회성 마이그레이션 (connection._migrate가 현재버전 초과분만 실행)
MIGRATIONS = {
    6: [
        "DROP TABLE IF EXISTS preflop_actions;",
        "DROP TABLE IF EXISTS postflop_actions;",
        "DROP TABLE IF EXISTS games;",
    ],
    7: [
        CREATE_EQUITY_PENDING_INDEX,
        CREATE_EQUITY_MULTIWAY_INDEX,
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
    # v3: 미수집 스팟 큐
    CREATE_GTO_MISSING_SPOTS,
    CREATE_GTO_MISSING_INDEX,
    # v4: 에퀴티 캐시 (전수조사 워커 + 봇 런타임 공유)
    CREATE_EQUITY_CACHE,
    # v5: 워커 진행 커서 (체계적 플랍 스윕 재개용)
    CREATE_WORKER_META,
    # v7: 대기 행 전용 부분 인덱스 (next_exact_job / next_mc_job 병목 해소)
    CREATE_EQUITY_PENDING_INDEX,
    CREATE_EQUITY_MULTIWAY_INDEX,
    # v8: (game_uuid, position) 복합 인덱스 — reward 역산 UPDATE 최적화
    CREATE_GAME_POS_INDEXES,
]
