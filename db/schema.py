"""
poker_simulator DB 스키마 정의 및 마이그레이션
"""

import sqlite3

SCHEMA_VERSION = 12

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
# 실측한 값만 저장한다 (docs/gto-data.md 2026-07-10 근본 원인 참고).
# v12: 프리플랍 전체 트리 커버리지(②)를 위해 캐노니컬 시퀀스 키 컬럼 추가.
#   - action_seq: 히어로 결정 직전까지의 액션 시퀀스를 캐노니컬 사이즈로 스냅한
#     노드 키(예: "R2.5-R8-F-F-F-F", RFI UTG는 ""). 임의 노드(스퀴즈/멀티웨이/4벳+)를
#     일반적으로 담기 위한 병렬 키. 기존 (position,vs_position,range_type) enum 키는
#     레거시/파생으로 nullable 유지(제거하지 않음 — 봇/조회/테스트 하위 호환).
#   - hero_position/num_active: 시퀀스에서 파생한 조회/디버깅용 컬럼.
#   UNIQUE(action_seq)는 별도 부분 유니크 인덱스(idx_gto_pre_seq)로 강제(NULL 다수 허용).
CREATE_GTO_PREFLOP_SITUATIONS = """
CREATE TABLE IF NOT EXISTS gto_preflop_situations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    position        TEXT    NOT NULL,   -- BTN, CO, MP, UTG, SB, BB
    vs_position     TEXT,               -- NULL = RFI, 오프너 포지션 = vs_open/vs_3bet
    range_type      TEXT    NOT NULL,   -- open | vs_open | vs_3bet
    raise_size      REAL,               -- bb 단위 실측 raise-to 값 (예: 2.5, 8.0, 13.5)
    situation_label TEXT    NOT NULL,   -- "BTN RFI", "BB vs BTN open"
    action_seq      TEXT,               -- v12: 캐노니컬 노드 키(히어로 결정 직전 시퀀스). NULL 허용
    hero_position   TEXT,               -- v12: 결정 주체(시퀀스 파생, 조회용)
    num_active      INTEGER,            -- v12: 히어로 결정 시점 미폴드 인원(6 - 폴드수, 파생)
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

# v12: 시퀀스 키(노드 키) 유니크 인덱스. nullable 컬럼이라 NULL은 서로 distinct로
# 취급돼 여러 행이 아직 키 없이(NULL) 공존 가능(부분/nullable 허용). 백필된 실측 값은
# 서로 distinct해야 함 → 저장/조회 노드 키의 1:1 매칭을 인덱스가 강제.
CREATE_GTO_PREFLOP_SEQ_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_gto_pre_seq ON gto_preflop_situations(action_seq);
"""

# v11: gto_missing_spots → gto_missing_spots_preflop 개명. 포스트플랍용 별도
# gto_missing_spots_postflop이 필요해질 것을 대비해 미리 이름공간 분리.
# (구 포스트플랍 텍스처 클래스 수집 계획은 폐기됨 — TODO.md "Epic: 포스트플랍
# 전략" 참고. gto_postflop_situations/hands 테이블은 여전히 미사용 상태.)
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

# v9: equity_cache(9,600만 행+) 풀스캔 GROUP BY가 --status에서 59초 걸리는 문제 해결.
# (street, num_opponents)별 요약을 쓰기 시점마다 증분 갱신해 --status가 이 작은
# 테이블만 읽도록 한다 (행 수 무관 즉시 응답). 정합성은 반드시 실제 풀스캔과 대조 검증.
CREATE_EQUITY_CACHE_STATS = """
CREATE TABLE IF NOT EXISTS equity_cache_stats (
    street          TEXT    NOT NULL,
    num_opponents   INTEGER NOT NULL,
    spots           INTEGER NOT NULL DEFAULT 0,
    exact_done      INTEGER NOT NULL DEFAULT 0,
    total_sum       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(street, num_opponents)
);
"""

# v10: next_mc_job/next_mc_batch의 프리플랍 대기 체크 쿼리
# (WHERE exact=0 AND street='preflop' AND total < ?)를 뒷받침하는 인덱스가
# 없어(v8에서 idx_equity_street를 "잉여"로 제거하며 이 쿼리를 놓침) 매 배치
# 호출마다 equity_cache 전체(1억 행)를 풀스캔(~3.1초) — 프리플랍은 이미
# 100% 완료라 항상 0건인데도 반복 발생. 프리플랍 대기 행만 담는(최대 845행)
# 부분 인덱스로 해소.
CREATE_EQUITY_PREFLOP_PENDING_INDEX = """
CREATE INDEX IF NOT EXISTS idx_equity_preflop_pending
ON equity_cache(total) WHERE exact = 0 AND street = 'preflop';
"""

CREATE_WORKER_META = """
CREATE TABLE IF NOT EXISTS worker_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

def backfill_v12(conn):
    """v12 백필: 기존 gto_preflop_situations 행에 캐노니컬 노드 키(action_seq) +
    hero_position + num_active를 결정론적으로 채우고, vs_3bet vs_position 포맷을
    정규화한다. 데이터 손실 0(기존 컬럼은 그대로 두고 파생 컬럼만 UPDATE).

    - 노드 키 생성은 gto.url_generator.situation_to_node_key를 **단일 소스**로 사용
      (런타임 조회 키 gto.advisor.canonical_node_key와 동일한 캐노니컬 사이즈 테이블).
    - vs_3bet 정규화: 우리 데이터 모델은 "오프너가 3벳에 대응"하는 레인지만 담으므로
      opener == hero(position)다. three_bettor만 저장된 행(예: BTN 행 vs_position="BB")을
      'opener/three_bettor'(="BTN/BB")로 정규화 — 인계된 포맷 불일치(UTG 행="UTG/HJ"는
      이미 정규형, BTN 행="BB"만 반쪽) 해소. 이로써 loader.get_vs_3bet_range의
      'opener/three_bettor' 조회 키와도 일치하게 됨(기존 enum 경로 조회도 정상화).

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


# 버전별 1회성 마이그레이션 (connection._migrate가 현재버전 초과분만 실행)
# 각 스텝은 SQL 문자열(executescript) 또는 콜러블(conn을 받는 파이썬 함수)일 수 있다.
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
    9: [
        CREATE_EQUITY_CACHE_STATS,
    ],
    10: [
        CREATE_EQUITY_PREFLOP_PENDING_INDEX,
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
        # 프리플랍 전체 트리 커버리지 ②: 캐노니컬 시퀀스 키 컬럼 추가 + 백필.
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
    # v4: 에퀴티 캐시 (전수조사 워커 + 봇 런타임 공유)
    CREATE_EQUITY_CACHE,
    # v5: 워커 진행 커서 (체계적 플랍 스윕 재개용)
    CREATE_WORKER_META,
    # v7: 대기 행 전용 부분 인덱스 (next_exact_job / next_mc_job 병목 해소)
    CREATE_EQUITY_PENDING_INDEX,
    CREATE_EQUITY_MULTIWAY_INDEX,
    # v8: (game_uuid, position) 복합 인덱스 — reward 역산 UPDATE 최적화
    CREATE_GAME_POS_INDEXES,
    # v9: equity_cache 집계 요약 테이블 (--status 풀스캔 회피)
    CREATE_EQUITY_CACHE_STATS,
    # v10: 프리플랍 대기 체크 쿼리(next_mc_job/next_mc_batch) 전용 부분 인덱스
    CREATE_EQUITY_PREFLOP_PENDING_INDEX,
]
