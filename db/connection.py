"""
DB 연결 및 마이그레이션 관리
"""

import sqlite3
import os
from .schema import ALL_STATEMENTS, SCHEMA_VERSION, MIGRATIONS

_DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "poker.db"
)


def get_connection(db_path: str = None) -> sqlite3.Connection:
    """DB 연결 반환. 없으면 자동 생성 및 마이그레이션.
    db_path 미지정 시 환경변수 EV_PLUS_DB (테스트 격리용) → 기본 poker.db 순."""
    if db_path is None:
        db_path = os.environ.get("EV_PLUS_DB", _DEFAULT_DB_PATH)
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # 동시 읽기 성능 향상
    conn.execute("PRAGMA busy_timeout = 30000")  # 쓰기 락 경합 시 30초 대기
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection):
    """스키마 생성 및 버전 관리"""
    cur = conn.cursor()

    # schema_version 테이블 먼저 생성
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version     INTEGER NOT NULL,
            applied_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)

    row = cur.execute("SELECT MAX(version) as v FROM schema_version").fetchone()
    current = row["v"] or 0

    if current < SCHEMA_VERSION:
        # 기존 DB(버전 이력 있음)에서만 1회성 마이그레이션 실행.
        # 신규 DB(current == 0)는 ALL_STATEMENTS가 최종 상태를 그대로 만들므로
        # 마이그레이션(예: 이전 테이블 DROP, 특정 테이블 대상 인덱스 생성)을
        # 실행하면 안 됨 — 아직 테이블이 없거나 불필요한 삭제가 발생할 수 있음.
        if current > 0:
            for v in range(current + 1, SCHEMA_VERSION + 1):
                for stmt in MIGRATIONS.get(v, []):
                    cur.executescript(stmt)
        for stmt in ALL_STATEMENTS:
            cur.executescript(stmt)
        cur.execute(
            "INSERT INTO schema_version(version) VALUES(?)", (SCHEMA_VERSION,)
        )
        conn.commit()


def close(conn: sqlite3.Connection):
    conn.close()
