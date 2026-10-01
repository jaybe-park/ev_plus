#!/usr/bin/env python3
"""
미수집 큐(gto_missing_spots_preflop)에서 옛 간단 라벨(enum) 행을 지운다.

ADR 0035 이후 큐에는 정확한 노드 키 행(range_type='seq')만 들어가고 수집기도 그 행만 읽는다.
그 전에 쌓인 enum 행(range_type='open'/'vs_open'/'vs_3bet' 등)은 처리될 경로가 없다.

사용:
    python3 scripts/prune_missing_spots.py --dry-run   # 지울 행만 출력(읽기 전용 연결)
    python3 scripts/prune_missing_spots.py --apply     # 실제 삭제(한 트랜잭션)
DB: `--db` → `EV_PLUS_DB` → poker.db. 옵션 없이 실행하면 아무것도 하지 않는다.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db.connection import get_connection, get_readonly_connection, resolve_db_path  # noqa: E402

TARGET_WHERE = "range_type != 'seq'"


def target_rows(conn) -> list:
    return conn.execute(
        "SELECT id, position, vs_position, range_type, situation_label, collected "
        f"FROM gto_missing_spots_preflop WHERE {TARGET_WHERE} ORDER BY id"
    ).fetchall()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="미수집 큐의 옛 enum 행 삭제")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="지울 행만 출력")
    mode.add_argument("--apply", action="store_true", help="실제 삭제")
    ap.add_argument("--db", default=None)
    args = ap.parse_args(argv)
    db_path = resolve_db_path(args.db)
    if not (args.dry_run or args.apply):
        ap.print_help()
        return 2

    conn = get_readonly_connection(db_path) if args.dry_run else get_connection(db_path)
    try:
        rows = target_rows(conn)
        total = conn.execute("SELECT COUNT(*) FROM gto_missing_spots_preflop").fetchone()[0]
        pending = sum(1 for r in rows if not r["collected"])
        print(f"DB: {db_path}")
        print(f"큐 전체 {total}행 중 enum 행 {len(rows)}개(미수집 {pending}) — 대상")
        for r in rows:
            print(f"  id={r['id']:>3} {r['range_type']:8} {r['position']:4} "
                  f"vs={r['vs_position']!r:12} collected={r['collected']} {r['situation_label']}")
        if args.dry_run:
            print("[dry-run] 삭제하지 않았습니다.")
            return 0
        cur = conn.execute(f"DELETE FROM gto_missing_spots_preflop WHERE {TARGET_WHERE}")
        conn.commit()
        print(f"삭제: {cur.rowcount}행")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
