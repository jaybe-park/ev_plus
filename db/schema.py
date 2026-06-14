"""
poker_simulator DB 스키마 정의 및 마이그레이션
"""

SCHEMA_VERSION = 1

CREATE_GAMES = """
CREATE TABLE IF NOT EXISTS games (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    game_uuid       TEXT    NOT NULL UNIQUE,
    played_at       TEXT    NOT NULL,
    num_players     INTEGER NOT NULL CHECK(num_players BETWEEN 2 AND 6),
    small_blind     INTEGER NOT NULL,
    big_blind       INTEGER NOT NULL,
    dealer_pos      TEXT    NOT NULL CHECK(dealer_pos IN ('BTN','SB','BB','UTG','MP','CO')),

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
    position        TEXT    NOT NULL CHECK(position IN ('BTN','SB','BB','UTG','MP','CO')),
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
    position        TEXT    NOT NULL CHECK(position IN ('BTN','SB','BB','UTG','MP','CO')),
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
CREATE INDEX IF NOT EXISTS idx_preflop_game  ON preflop_actions(game_uuid);
CREATE INDEX IF NOT EXISTS idx_preflop_pos   ON preflop_actions(position);
CREATE INDEX IF NOT EXISTS idx_preflop_human ON preflop_actions(is_human);
CREATE INDEX IF NOT EXISTS idx_postflop_game   ON postflop_actions(game_uuid);
CREATE INDEX IF NOT EXISTS idx_postflop_street ON postflop_actions(street);
CREATE INDEX IF NOT EXISTS idx_postflop_pos    ON postflop_actions(position);
CREATE INDEX IF NOT EXISTS idx_postflop_human  ON postflop_actions(is_human);
CREATE INDEX IF NOT EXISTS idx_games_played    ON games(played_at);
"""

ALL_STATEMENTS = [
    CREATE_GAMES,
    CREATE_PREFLOP_ACTIONS,
    CREATE_POSTFLOP_ACTIONS,
    CREATE_SCHEMA_VERSION,
    CREATE_INDEXES,
]
