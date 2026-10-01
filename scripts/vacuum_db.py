#!/usr/bin/env python3
"""
DB 파일 공간 회수(VACUUM).

v15 마이그레이션(ADR 0051)의 DROP COLUMN은 지운 데이터의 페이지를 freelist로 돌려줄 뿐
파일 크기를 줄이지 않는다. 이 스크립트가 VACUUM으로 파일을 다시 써서 줄인다.

사용:
    python3 scripts/vacuum_db.py             # = --dry-run
    python3 scripts/vacuum_db.py --dry-run   # 현재 크기·페이지·예상 회수량만 출력(읽기 전용 연결)
    python3 scripts/vacuum_db.py --apply     # 스키마를 최신(v15)으로 올린 뒤 VACUUM, 크기 전후 출력
DB: `--db` → `EV_PLUS_DB` → poker.db.

--apply 주의: VACUUM은 DB 크기만큼 임시 공간이 필요하고, 도는 동안 다른 프로세스의 쓰기를 막는다.
서버·그라인드를 끈 상태에서 실행한다. 되돌릴 수 없으므로(지운 컬럼 데이터는 이미 없음) 필요하면
먼저 파일을 백업한다.
"""
import argparse
import os
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db.connection import get_connection, get_readonly_connection, resolve_db_path  # noqa: E402
from db.schema import SCHEMA_VERSION, _RL_COLUMNS_V15  # noqa: E402


def _fmt(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{int(n)}B"
        n /= 1024
    return f"{n:.1f}GB"


def file_bytes(db_path: str) -> int:
    """DB 본 파일 + WAL 파일 크기."""
    total = 0
    for p in (db_path, db_path + "-wal"):
        try:
            total += os.path.getsize(p)
        except OSError:
            pass
    return total


def page_stats(conn) -> dict:
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    page_count = conn.execute("PRAGMA page_count").fetchone()[0]
    freelist = conn.execute("PRAGMA freelist_count").fetchone()[0]
    return {"page_size": page_size, "page_count": page_count, "freelist": freelist,
            "free_bytes": page_size * freelist}


def schema_version(conn) -> int:
    try:
        return conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] or 0
    except sqlite3.OperationalError:
        return 0


def rl_column_bytes(conn) -> dict:
    """아직 남아 있는 RL 컬럼(v15 미적용 DB)의 대략적인 데이터 크기. {table.col: bytes}.
    값 길이 합이라 페이지 단위 실제 회수량과는 조금 다르다(추정)."""
    out = {}
    for table, cols in _RL_COLUMNS_V15.items():
        try:
            existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        except sqlite3.OperationalError:
            continue
        present = [c for c in cols if c in existing]
        if not present:
            continue
        expr = ", ".join(f"SUM(COALESCE(length(CAST({c} AS BLOB)), 0))" for c in present)
        row = conn.execute(f"SELECT {expr} FROM {table}").fetchone()
        for c, v in zip(present, row):
            out[f"{table}.{c}"] = v or 0
    return out


def report(conn, db_path: str) -> dict:
    st = page_stats(conn)
    ver = schema_version(conn)
    size = file_bytes(db_path)
    print(f"DB: {db_path}")
    print(f"파일 크기(본+WAL): {_fmt(size)}")
    print(f"스키마 버전: {ver} (코드 {SCHEMA_VERSION})")
    print(f"page_size={st['page_size']} page_count={st['page_count']} "
          f"freelist_count={st['freelist']} → 빈 페이지 {_fmt(st['free_bytes'])}")
    rl = rl_column_bytes(conn)
    rl_total = sum(rl.values())
    if rl:
        print("v15 미적용 — 남아 있는 RL 컬럼 데이터(값 길이 합, 추정):")
        for k, v in rl.items():
            print(f"  {k}: {_fmt(v)}")
        print(f"  합계 {_fmt(rl_total)}")
    expected = st["free_bytes"] + rl_total
    print(f"예상 회수량(빈 페이지 + RL 컬럼 추정): 약 {_fmt(expected)} "
          f"→ VACUUM 후 약 {_fmt(max(0, size - expected))}")
    free_disk = shutil.disk_usage(os.path.dirname(os.path.abspath(db_path))).free
    print(f"디스크 여유: {_fmt(free_disk)} (VACUUM은 DB 크기만큼 임시 공간 필요)")
    return {"size": size, "expected": expected, "free_disk": free_disk, **st}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="DB VACUUM(공간 회수). 기본은 dry-run")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="크기·예상 회수량만 출력(기본)")
    mode.add_argument("--apply", action="store_true", help="스키마 최신화 후 VACUUM 실행")
    ap.add_argument("--db", default=None)
    args = ap.parse_args(argv)
    db_path = resolve_db_path(args.db)

    if not args.apply:
        conn = get_readonly_connection(db_path)
        try:
            report(conn, db_path)
        finally:
            conn.close()
        print("[dry-run] 아무것도 바꾸지 않았습니다. 실행: --apply")
        return 0

    if not os.path.exists(db_path):
        print(f"DB 파일이 없습니다: {db_path}")
        return 1
    before = file_bytes(db_path)
    conn = get_connection(db_path)  # 연결 시 v15 마이그레이션(DROP COLUMN)이 적용된다
    try:
        info = report(conn, db_path)
        if info["free_disk"] < info["size"]:
            print("디스크 여유가 DB 크기보다 작습니다 — VACUUM을 하지 않습니다.")
            return 1
        conn.isolation_level = None  # VACUUM은 트랜잭션 밖에서만
        conn.execute("VACUUM")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        integrity = conn.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        conn.close()
    after = file_bytes(db_path)
    print(f"VACUUM 완료: {_fmt(before)} → {_fmt(after)} (회수 {_fmt(before - after)}), "
          f"quick_check={integrity}")
    return 0 if integrity == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
