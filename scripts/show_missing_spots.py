#!/usr/bin/env python3
"""
미수집 GTO 스팟 현황 조회

사용: python3 scripts/show_missing_spots.py [--all]
  --all : 수집된 스팟도 함께 출력
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.connection import get_connection


def main():
    show_all = "--all" in sys.argv
    conn = get_connection()

    where = "" if show_all else "WHERE collected = 0"
    rows = conn.execute(
        f"""
        SELECT id, street, range_type, position, vs_position,
               situation_label, gto_wizard_url, collected, discovered_at
        FROM gto_missing_spots_preflop
        {where}
        ORDER BY street, range_type, position, vs_position
        """
    ).fetchall()

    if not rows:
        label = "스팟" if show_all else "미수집 스팟"
        print(f"✅ {label} 없음")
        conn.close()
        return

    label = "전체 스팟" if show_all else "미수집 스팟"
    print(f"\n{'='*60}")
    print(f"  {label} 목록  ({len(rows)}개)")
    print(f"{'='*60}")

    current_type = None
    for r in rows:
        type_key = f"{r['street']} / {r['range_type']}"
        if type_key != current_type:
            current_type = type_key
            print(f"\n[{type_key}]")

        status = "✅" if r["collected"] else "❌"
        print(f"  {status} [{r['id']:3d}] {r['situation_label']}")
        if r["gto_wizard_url"]:
            print(f"       URL: {r['gto_wizard_url']}")
        print(f"       발견: {r['discovered_at']}")

    conn.close()
    print()


if __name__ == "__main__":
    main()
