#!/usr/bin/env python3
"""
scripts/slim_db.py 단위 테스트 — 임시 DB로 제외/유지 동작을 검증한다.

실행: python3 tests/test_slim_db.py
"""

import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import slim_db  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, cond: bool):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name}")


def make_src_db(path: str):
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE kept_a (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            val  TEXT
        );
        CREATE TABLE kept_b (
            id   INTEGER PRIMARY KEY,
            n    INTEGER
        );
        CREATE INDEX idx_kept_b_n ON kept_b(n);
        CREATE TABLE excluded_c (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            junk TEXT
        );
    """)
    conn.executemany("INSERT INTO kept_a (val) VALUES (?)", [("a1",), ("a2",), ("a3",)])
    conn.executemany("INSERT INTO kept_b (id, n) VALUES (?, ?)", [(1, 10), (2, 20)])
    conn.executemany("INSERT INTO excluded_c (junk) VALUES (?)", [("x1",), ("x2",), ("x3",), ("x4",)])
    conn.execute("PRAGMA user_version = 7")
    conn.commit()
    conn.close()


def main():
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "src.db")
        dst = os.path.join(tmp, "src.db.slim")
        make_src_db(src)

        print("[dry-run 실행 확인 — 예외 없이 끝나야 함]")
        slim_db.do_dry_run(src, {"excluded_c"})
        check("dst 파일이 dry-run 후에도 생성되지 않음", not os.path.exists(dst))

        print("[real-run]")
        slim_db.do_real_run(src, dst, {"excluded_c"})
        check("dst 파일 생성됨", os.path.exists(dst))

        conn = sqlite3.connect(dst)
        conn.row_factory = sqlite3.Row

        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()}
        check("kept_a 존재", "kept_a" in tables)
        check("kept_b 존재", "kept_b" in tables)
        check("excluded_c 부재", "excluded_c" not in tables)

        a_count = conn.execute("SELECT COUNT(*) AS c FROM kept_a").fetchone()["c"]
        b_count = conn.execute("SELECT COUNT(*) AS c FROM kept_b").fetchone()["c"]
        check("kept_a 행 수 일치(3)", a_count == 3)
        check("kept_b 행 수 일치(2)", b_count == 2)

        idx = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()}
        check("kept_b 인덱스 복사됨", "idx_kept_b_n" in idx)

        seq_row = conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name='kept_a'"
        ).fetchone()
        check("kept_a AUTOINCREMENT 시퀀스 복사됨(>=3)", seq_row is not None and seq_row["seq"] >= 3)

        uv = conn.execute("PRAGMA user_version").fetchone()[0]
        check("user_version 복사됨(7)", uv == 7)

        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        check("integrity_check == ok", integrity == "ok")

        conn.close()

        print("[dst 이미 존재하면 real-run 거부]")
        raised = False
        try:
            slim_db.do_real_run(src, dst, {"excluded_c"})
        except FileExistsError:
            raised = True
        check("기존 dst 있으면 FileExistsError", raised)

    print(f"\n결과: {PASS} PASS, {FAIL} FAIL")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
