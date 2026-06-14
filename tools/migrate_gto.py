"""
GTO 데이터 마이그레이션: JSON → SQLite

실행:
    python tools/migrate_gto.py

완료 후 gto_data/ 디렉터리 삭제 가능.
"""

import sys
import os
import json
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.connection import get_connection

GTO_DATA_ROOT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "gto_data", "preflop")

# JSON 파일 → (position, vs_position, range_type) 매핑
OPEN_POSITIONS   = ["BTN", "CO", "MP", "UTG", "SB"]
VS_OPEN_MAP = {
    # "파일명_위치": (my_pos, vs_pos)
    "BB_vs_BTN": ("BB", "BTN"),
    "BB_vs_CO":  ("BB", "CO"),
    "BB_vs_MP":  ("BB", "MP"),
    "BB_vs_UTG": ("BB", "UTG"),
    "SB_vs_BTN": ("SB", "BTN"),
}


def migrate(db_path: str = None, dry_run: bool = False):
    conn = get_connection(db_path) if db_path else get_connection()
    cur = conn.cursor()

    inserted_situations = 0
    inserted_hands = 0

    # ── open 레인지 ──────────────────────────────────────
    for pos in OPEN_POSITIONS:
        path = os.path.join(GTO_DATA_ROOT, "open", f"{pos}.json")
        if not os.path.exists(path):
            print(f"  [SKIP] {path} 없음")
            continue

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        label = data.get("situation", f"{pos} RFI")
        raise_size = data.get("raise_size", "")
        hands = data.get("hands", {})

        if not dry_run:
            cur.execute("""
                INSERT OR IGNORE INTO gto_preflop_situations
                    (position, vs_position, range_type, raise_size, situation_label)
                VALUES (?, NULL, 'open', ?, ?)
            """, (pos, raise_size, label))

            cur.execute("""
                SELECT id FROM gto_preflop_situations
                WHERE position = ? AND vs_position IS NULL AND range_type = 'open'
            """, (pos,))
            sit_id = cur.fetchone()["id"]
        else:
            sit_id = f"<{pos}-open>"

        inserted_situations += 1
        hand_count = 0

        for hand, freqs in hands.items():
            fold  = freqs.get("fold",  0.0)
            call  = freqs.get("call",  0.0)
            raise_ = freqs.get("raise", 0.0)
            allin = freqs.get("allin", 0.0)

            if not dry_run:
                cur.execute("""
                    INSERT OR REPLACE INTO gto_preflop_hands
                        (situation_id, hand, freq_fold, freq_call, freq_raise, freq_allin)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (sit_id, hand, fold, call, raise_, allin))
            hand_count += 1

        inserted_hands += hand_count
        print(f"  [open/{pos}] {label}: {hand_count}개 핸드")

    # ── vs_open 레인지 ────────────────────────────────────
    for fname, (my_pos, vs_pos) in VS_OPEN_MAP.items():
        path = os.path.join(GTO_DATA_ROOT, "vs_open", f"{fname}.json")
        if not os.path.exists(path):
            print(f"  [SKIP] {path} 없음")
            continue

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        label = data.get("situation", f"{my_pos} vs {vs_pos} open")
        raise_size = data.get("raise_size", "")
        hands = data.get("hands", {})

        if not dry_run:
            cur.execute("""
                INSERT OR IGNORE INTO gto_preflop_situations
                    (position, vs_position, range_type, raise_size, situation_label)
                VALUES (?, ?, 'vs_open', ?, ?)
            """, (my_pos, vs_pos, raise_size, label))

            cur.execute("""
                SELECT id FROM gto_preflop_situations
                WHERE position = ? AND vs_position = ? AND range_type = 'vs_open'
            """, (my_pos, vs_pos))
            sit_id = cur.fetchone()["id"]
        else:
            sit_id = f"<{my_pos}-vs-{vs_pos}>"

        inserted_situations += 1
        hand_count = 0

        for hand, freqs in hands.items():
            fold  = freqs.get("fold",  0.0)
            call  = freqs.get("call",  0.0)
            raise_ = freqs.get("raise", 0.0)
            allin = freqs.get("allin", 0.0)

            if not dry_run:
                cur.execute("""
                    INSERT OR REPLACE INTO gto_preflop_hands
                        (situation_id, hand, freq_fold, freq_call, freq_raise, freq_allin)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (sit_id, hand, fold, call, raise_, allin))
            hand_count += 1

        inserted_hands += hand_count
        print(f"  [vs_open/{fname}] {label}: {hand_count}개 핸드")

    if not dry_run:
        conn.commit()

    conn.close()

    print()
    print(f"완료: 상황 {inserted_situations}개, 핸드 {inserted_hands}개 마이그레이션")
    return inserted_situations, inserted_hands


def verify(db_path: str = None):
    """마이그레이션 결과 검증"""
    conn = get_connection(db_path) if db_path else get_connection()
    cur = conn.cursor()

    print("\n=== 마이그레이션 검증 ===")

    rows = cur.execute("""
        SELECT s.situation_label, s.range_type, COUNT(h.id) as hand_count
        FROM gto_preflop_situations s
        JOIN gto_preflop_hands h ON h.situation_id = s.id
        GROUP BY s.id
        ORDER BY s.range_type, s.position
    """).fetchall()

    for r in rows:
        print(f"  {r['situation_label']}: {r['hand_count']}개 핸드")

    # 알려진 오류 케이스 체크
    print("\n=== 알려진 오류 확인 ===")
    checks = [
        ("BB", "UTG", "AKs", "AKs vs UTG: fold가 0이어야 정상"),
        ("BB", "BTN", "AA",  "AA: raise=1.0이어야 정상"),
    ]
    for pos, vs_pos, hand, note in checks:
        row = cur.execute("""
            SELECT h.freq_fold, h.freq_raise
            FROM gto_preflop_hands h
            JOIN gto_preflop_situations s ON s.id = h.situation_id
            WHERE s.position = ? AND s.vs_position = ? AND h.hand = ?
        """, (pos, vs_pos, hand)).fetchone()
        if row:
            status = "⚠️  오류 있음" if (hand == "AKs" and row["freq_fold"] > 0) else "✅"
            print(f"  {status} {note}: fold={row['freq_fold']}, raise={row['freq_raise']}")

    conn.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="GTO JSON → SQLite 마이그레이션")
    parser.add_argument("--dry-run", action="store_true", help="실제 저장 없이 확인만")
    parser.add_argument("--verify-only", action="store_true", help="검증만 실행")
    parser.add_argument("--db", default=None, help="DB 파일 경로 (기본: poker.db)")
    args = parser.parse_args()

    if args.verify_only:
        verify(args.db)
    else:
        print("=== GTO 데이터 마이그레이션 시작 ===")
        if args.dry_run:
            print("(dry-run 모드: DB에 저장하지 않음)\n")
        migrate(args.db, dry_run=args.dry_run)
        if not args.dry_run:
            verify(args.db)
