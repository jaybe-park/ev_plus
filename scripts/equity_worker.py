#!/usr/bin/env python3
"""
에퀴티 전수조사 워커 — 시간 날 때마다 돌리는 백그라운드 계산기

모든 계산 결과는 스팟 단위로 즉시 DB에 커밋된다.
Ctrl+C로 언제든 중단해도 진행분은 저장되고, 다시 실행하면 이어서 계산한다.

작업 우선순위 (스팟당 비용이 싼 순서):
  1. 게임에서 만난 리버 스팟 전수조사   (990 조합,   <1초/스팟)
  2. 게임에서 만난 턴 스팟 전수조사     (4.6만 조합, ~10초/스팟)
  3. 게임에서 만난 플랍 스팟 전수조사   (107만 조합, 2~5분/스팟)
     (같은 스트리트에선 게임에서 만난 스팟(total>0)이 스윕 스팟보다 우선)
  4. 프리플랍 169핸드 × 상대 1~5명 고정밀 샘플링 누적
     (전수조사는 21억 조합이라 불가능 → 목표 샘플 수까지 점진 누적)
  5. 멀티웨이(상대 2명+) 스팟 샘플링 누적
  6. 체계적 플랍 스윕: 큐가 비면 전체 플랍 스팟 공간(~130만)을
     정해진 순서(AA부터)로 등록해가며 전수조사 — 사실상 무한 작업.
     진행 커서를 worker_meta에 저장해 중단/재개 안전.

사용법:
  python3 scripts/equity_worker.py                  # 무한 실행 (Ctrl+C 중단)
  python3 scripts/equity_worker.py --minutes 30     # 30분만 실행
  python3 scripts/equity_worker.py --preflop-first  # 프리플랍 845스팟부터 채움
  python3 scripts/equity_worker.py --status         # 진행 현황만 출력
"""

import argparse
import sqlite3
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.card import Card, Suit, Rank
from ai.equity import (
    canonical_key, decode_key, mc_counts,
    exact_counts_river, street_of, _FULL_DECK,
)
from db.connection import get_connection

# 프리플랍 목표 샘플 수 (100만 = 오차 ±0.05%)
PREFLOP_TARGET = 1_000_000
# 멀티웨이 스팟 목표 샘플 수 (10만 = 오차 ±0.15%)
MULTIWAY_TARGET = 100_000
# 한 번에 누적하는 샘플 청크 (청크마다 커밋)
MC_CHUNK = 25_000

_STREET_PRIORITY = {"river": 0, "turn": 1, "flop": 2}


def canonical_hands() -> list:
    """169개 대표 핸드 (AA부터 강한 순서 근사). 스윕 순서의 기준."""
    ranks_desc = sorted(Rank, key=lambda r: -r.rank_value)
    hands = []
    for i, r1 in enumerate(ranks_desc):
        for j, r2 in enumerate(ranks_desc):
            if j < i:
                continue
            if i == j:      # 페어
                hands.append([Card(r1, Suit.SPADES), Card(r1, Suit.HEARTS)])
            else:           # 수티드 + 오프수트
                hands.append([Card(r1, Suit.SPADES), Card(r2, Suit.SPADES)])
                hands.append([Card(r1, Suit.SPADES), Card(r2, Suit.HEARTS)])
    return hands


def seed_preflop_spots(conn) -> int:
    """169개 프리플랍 핸드 × 상대 1~5명 행을 큐에 등록 (이미 있으면 무시)"""
    added = 0
    for hole in canonical_hands():
        key = canonical_key(hole, [])
        for n_opp in range(1, 6):
            cur = conn.execute(
                "INSERT OR IGNORE INTO equity_cache"
                "(street, spot_key, num_opponents) VALUES('preflop', ?, ?)",
                (key, n_opp),
            )
            added += cur.rowcount
    conn.commit()
    return added


def next_exact_job(conn):
    """
    1:1 포스트플랍 스팟 중 미완료 — 리버 → 턴 → 플랍 순.
    같은 스트리트에선 게임에서 만난 스팟(total>0)이 스윕 등록분(total=0)보다 우선.
    """
    return conn.execute(
        """
        SELECT id, street, spot_key FROM equity_cache
        WHERE exact = 0 AND num_opponents = 1 AND street != 'preflop'
        ORDER BY CASE street WHEN 'river' THEN 0 WHEN 'turn' THEN 1 ELSE 2 END,
                 (total > 0) DESC, id
        LIMIT 1
        """
    ).fetchone()


# ──────────────────────────────────────────
# 체계적 플랍 스윕 (큐가 비었을 때의 무한 작업 저장고)
# ──────────────────────────────────────────

SWEEP_BATCH = 50  # 한 번에 등록하는 스팟 수


def _get_cursor(conn) -> tuple:
    row = conn.execute(
        "SELECT value FROM worker_meta WHERE key = 'flop_sweep_cursor'"
    ).fetchone()
    if row is None:
        return 0, 0
    h, f = row["value"].split(":")
    return int(h), int(f)


def _set_cursor(conn, hand_idx: int, flop_idx: int) -> None:
    conn.execute(
        "INSERT INTO worker_meta(key, value) VALUES('flop_sweep_cursor', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (f"{hand_idx}:{flop_idx}",),
    )


def sweep_flop_batch(conn) -> int:
    """
    커서 위치부터 플랍 스팟 SWEEP_BATCH개를 큐에 등록.
    핸드 순서: AA, AKs, AKo, ... (canonical_hands 순).
    핸드마다 남은 50장의 C(50,3)=19,600개 플랍을 조합 순서로 순회.
    수트 대칭 중복은 INSERT OR IGNORE로 자연 제거.
    반환: 등록한 스팟 수 (0이면 전체 스윕 완료)
    """
    from itertools import combinations
    from ai.equity import _FULL_DECK

    hands = canonical_hands()
    hand_idx, flop_idx = _get_cursor(conn)
    added = 0
    scanned = 0

    while added < SWEEP_BATCH and hand_idx < len(hands):
        hole = hands[hand_idx]
        deck = [c for c in _FULL_DECK if c not in hole]
        flops = list(combinations(deck, 3))

        while flop_idx < len(flops) and added < SWEEP_BATCH:
            key = canonical_key(hole, list(flops[flop_idx]))
            cur = conn.execute(
                "INSERT OR IGNORE INTO equity_cache"
                "(street, spot_key, num_opponents) VALUES('flop', ?, 1)",
                (key,),
            )
            added += cur.rowcount
            flop_idx += 1
            scanned += 1
            if scanned > 20000:  # 중복 구간에서 무한 스캔 방지
                break

        if flop_idx >= len(flops):
            hand_idx += 1
            flop_idx = 0
        if scanned > 20000:
            break

    _set_cursor(conn, hand_idx, flop_idx)
    conn.commit()
    return added


def next_preflop_job(conn):
    """프리플랍 스팟만 (--preflop-first용) — 샘플 적은 것부터"""
    return conn.execute(
        """
        SELECT id, street, spot_key, num_opponents, total FROM equity_cache
        WHERE exact = 0 AND street = 'preflop' AND total < ?
        ORDER BY total ASC, num_opponents ASC
        LIMIT 1
        """,
        (PREFLOP_TARGET,),
    ).fetchone()


def next_mc_job(conn):
    """샘플 목표 미달 스팟 — 프리플랍 우선, 샘플 적은 것부터"""
    return conn.execute(
        """
        SELECT id, street, spot_key, num_opponents, total FROM equity_cache
        WHERE exact = 0 AND (
            (street = 'preflop' AND total < ?) OR
            (num_opponents > 1 AND total < ?)
        )
        ORDER BY (street = 'preflop') DESC, total ASC
        LIMIT 1
        """,
        (PREFLOP_TARGET, MULTIWAY_TARGET),
    ).fetchone()


def _upsert_exact(conn, street: str, spot_key: str, w: float, t: float, n: int) -> None:
    """자식 스팟의 정확값 저장 (커밋은 호출자가)"""
    conn.execute(
        """
        INSERT INTO equity_cache(street, spot_key, num_opponents, wins, ties, total, exact)
        VALUES(?,?,1,?,?,?,1)
        ON CONFLICT(spot_key, num_opponents) DO UPDATE SET
            wins=excluded.wins, ties=excluded.ties, total=excluded.total,
            exact=1, updated_at=datetime('now')
        """,
        (street, spot_key, w, t, n),
    )


def _lookup_exact(conn, spot_key: str):
    return conn.execute(
        "SELECT wins, ties, total FROM equity_cache "
        "WHERE spot_key=? AND num_opponents=1 AND exact=1",
        (spot_key,),
    ).fetchone()


def exact_turn_dp(conn, hole, board4) -> tuple:
    """
    턴 전수조사 — 스트리트 분해 DP.
    turn = 46개 리버 자식의 합 (수학적으로 직접 열거와 동일).
    자식 리버가 캐시에 있으면 재사용, 없으면 계산 후 저장 → 캐시가 풍부해짐.
    """
    known = set(hole) | set(board4)
    deck = [c for c in _FULL_DECK if c not in known]
    W = T = 0.0
    N = 0
    hits = 0
    for river in deck:
        b5 = board4 + [river]
        ck = canonical_key(hole, b5)
        row = _lookup_exact(conn, ck)
        if row:
            w, t, n = row["wins"], row["ties"], row["total"]
            hits += 1
        else:
            w, t, n = exact_counts_river(hole, b5)
            _upsert_exact(conn, "river", ck, w, t, n)
        W += w; T += t; N += n
    return W, T, N, hits


def exact_flop_dp(conn, hole, board3) -> tuple:
    """
    플랍 전수조사 — turn DP를 재귀 사용 (flop = 47개 턴 자식의 합).
    턴 자식마다 커밋 → 플랍 작업 도중 중단해도 자식 진행분은 보존.
    참고: 완성 조합을 순서쌍으로 세므로 total이 직접 열거의 2배지만 비율은 동일.
    """
    known = set(hole) | set(board3)
    deck = [c for c in _FULL_DECK if c not in known]
    W = T = 0.0
    N = 0
    hits = 0
    for turn in deck:
        b4 = board3 + [turn]
        ck = canonical_key(hole, b4)
        row = _lookup_exact(conn, ck)
        if row:
            w, t, n = row["wins"], row["ties"], row["total"]
            hits += 1
        else:
            w, t, n, _ = exact_turn_dp(conn, hole, b4)
            _upsert_exact(conn, "turn", ck, w, t, n)
        conn.commit()  # 턴 자식 단위로 진행분 보존
        W += w; T += t; N += n
    return W, T, N, hits


def process_exact(conn, job) -> str:
    hole, board = decode_key(job["spot_key"])
    t0 = time.time()
    hits = 0
    if job["street"] == "river":
        wins, ties, total = exact_counts_river(hole, board)
    elif job["street"] == "turn":
        wins, ties, total, hits = exact_turn_dp(conn, hole, board)
    else:
        wins, ties, total, hits = exact_flop_dp(conn, hole, board)
    conn.execute(
        "UPDATE equity_cache SET wins=?, ties=?, total=?, exact=1, "
        "updated_at=datetime('now') WHERE id=?",
        (wins, ties, total, job["id"]),
    )
    conn.commit()
    eq = (wins + 0.5 * ties) / total
    hit_info = f", 캐시적중 {hits}" if hits else ""
    return (f"✅ [전수] {job['street']:6s} {job['spot_key']:24s} "
            f"equity={eq:.4f} ({total:,}조합, {time.time()-t0:.1f}s{hit_info})")


def process_mc(conn, job) -> str:
    hole, board = decode_key(job["spot_key"])
    t0 = time.time()
    wins, ties, total = mc_counts(hole, board, job["num_opponents"], MC_CHUNK)
    conn.execute(
        "UPDATE equity_cache SET wins=wins+?, ties=ties+?, total=total+?, "
        "updated_at=datetime('now') WHERE id=? AND exact=0",
        (wins, ties, total, job["id"]),
    )
    conn.commit()
    row = conn.execute(
        "SELECT wins, ties, total FROM equity_cache WHERE id=?", (job["id"],)
    ).fetchone()
    eq = (row["wins"] + 0.5 * row["ties"]) / row["total"]
    target = PREFLOP_TARGET if job["street"] == "preflop" else MULTIWAY_TARGET
    return (f"📈 [샘플] {job['street']:7s} {job['spot_key']:24s} vs{job['num_opponents']} "
            f"equity={eq:.4f} ({row['total']:,}/{target:,}, {time.time()-t0:.1f}s)")


def _bar(pct: float, width: int = 20) -> str:
    filled = int(width * min(pct, 1.0))
    return "█" * filled + "░" * (width - filled)


def show_status(conn) -> None:
    print(f"\n{'='*68}")
    print("  에퀴티 캐시 현황")
    print(f"{'='*68}")
    rows = conn.execute(
        """
        SELECT street, num_opponents,
               COUNT(*) AS spots,
               SUM(exact) AS exact_done,
               AVG(total) AS avg_samples,
               SUM(MIN(total, CASE WHEN street='preflop' THEN ? ELSE ? END))
                   AS capped_samples
        FROM equity_cache
        GROUP BY street, num_opponents
        ORDER BY CASE street WHEN 'preflop' THEN 0 WHEN 'flop' THEN 1
                 WHEN 'turn' THEN 2 ELSE 3 END, num_opponents
        """,
        (PREFLOP_TARGET, MULTIWAY_TARGET),
    ).fetchall()
    if not rows:
        print("  (비어있음 — 게임을 플레이하거나 워커를 실행하면 채워집니다)")

    print("\n  [카테고리별 진행률]")
    for r in rows:
        target = PREFLOP_TARGET if r["street"] == "preflop" else MULTIWAY_TARGET
        if r["street"] != "preflop" and r["num_opponents"] == 1:
            # 전수조사 대상
            pct = r["exact_done"] / r["spots"] if r["spots"] else 0
            detail = f"전수조사 {r['exact_done']}/{r['spots']}"
        else:
            # 샘플 누적 대상 (스팟별 target 상한으로 집계)
            pct = r["capped_samples"] / (r["spots"] * target) if r["spots"] else 0
            detail = f"평균 {r['avg_samples']:,.0f}/{target:,} 샘플"
        print(f"  {r['street']:8s} vs{r['num_opponents']}  {_bar(pct)} "
              f"{pct*100:5.1f}%  스팟 {r['spots']:4d}개  {detail}")

    # 대기 큐: 전수조사 남은 스팟 (게임 유입 vs 스윕 구분)
    queue = conn.execute(
        """
        SELECT street,
               SUM(CASE WHEN total > 0 THEN 1 ELSE 0 END) AS from_play,
               SUM(CASE WHEN total = 0 THEN 1 ELSE 0 END) AS from_sweep
        FROM equity_cache
        WHERE exact = 0 AND num_opponents = 1 AND street != 'preflop'
        GROUP BY street
        ORDER BY CASE street WHEN 'river' THEN 0 WHEN 'turn' THEN 1 ELSE 2 END
        """
    ).fetchall()
    print("\n  [전수조사 대기 큐]")
    if not queue or all(q["from_play"] + q["from_sweep"] == 0 for q in queue):
        print("    비어있음 → 워커 실행 시 플랍 스윕으로 새 작업 생성")
    else:
        est = {"river": 1, "turn": 10, "flop": 180}  # 초/스팟
        for q in queue:
            n = q["from_play"] + q["from_sweep"]
            eta = n * est.get(q["street"], 60)
            eta_str = f"{eta/3600:.1f}시간" if eta >= 3600 else f"{eta//60}분" if eta >= 60 else f"{eta}초"
            print(f"    {q['street']:6s} {n:5d}개 대기 "
                  f"(게임 유입 {q['from_play']} / 스윕 {q['from_sweep']}) — 예상 {eta_str}")

    # 플랍 스윕 전체 진행률
    try:
        h, f = _get_cursor(conn)
        total_space = 169 * 19600
        done = h * 19600 + f
        pct = done / total_space
        print(f"\n  [플랍 스윕] {_bar(pct)} {pct*100:5.2f}%  "
              f"(핸드 {h}/169, 스캔 {done:,}/{total_space:,})")
    except Exception:
        pass
    print()


def main():
    parser = argparse.ArgumentParser(description="에퀴티 전수조사 워커")
    parser.add_argument("--minutes", type=float, default=None, help="실행 시간 제한(분)")
    parser.add_argument("--preflop-first", action="store_true",
                        help="프리플랍 845스팟 샘플링을 전수조사보다 우선")
    parser.add_argument("--status", action="store_true", help="진행 현황만 출력")
    args = parser.parse_args()

    conn = get_connection()

    if args.status:
        show_status(conn)
        conn.close()
        return

    added = seed_preflop_spots(conn)
    if added:
        print(f"프리플랍 스팟 {added}개 큐에 등록")

    deadline = time.time() + args.minutes * 60 if args.minutes else None
    done_count = 0
    print("워커 시작 — Ctrl+C로 언제든 중단 가능 (진행분은 저장됨)\n")

    try:
        while True:
            if deadline and time.time() >= deadline:
                print(f"\n⏰ 시간 제한 도달 — {done_count}개 작업 완료")
                break

            # --preflop-first: 프리플랍 샘플링을 최우선으로
            if args.preflop_first:
                try:
                    job = next_preflop_job(conn)
                except sqlite3.OperationalError:
                    time.sleep(1.0)
                    continue
                if job:
                    try:
                        print(process_mc(conn, job))
                    except sqlite3.OperationalError:
                        print("⏳ DB 쓰기 경합 — 1초 후 재시도")
                        time.sleep(1.0)
                    done_count += 1
                    continue
                # 프리플랍 전부 목표 도달 → 일반 우선순위로 진행

            try:
                job = next_exact_job(conn)
            except sqlite3.OperationalError:
                time.sleep(1.0)
                continue
            if job:
                try:
                    print(process_exact(conn, job))
                except sqlite3.OperationalError:
                    print("⏳ DB 쓰기 경합 — 1초 후 재시도")
                    time.sleep(1.0)
                    continue
            else:
                job = next_mc_job(conn)
                if job:
                    try:
                        print(process_mc(conn, job))
                    except sqlite3.OperationalError:
                        print("⏳ DB 쓰기 경합 — 1초 후 재시도")
                        time.sleep(1.0)
                    continue
                else:
                    # 큐 소진 → 체계적 플랍 스윕으로 새 작업 생성
                    added = sweep_flop_batch(conn)
                    if added == 0:
                        print("\n🎉 플랍 스윕까지 전부 완료 (사실상 도달 불가)")
                        break
                    h, f = _get_cursor(conn)
                    print(f"🧭 [스윕] 플랍 스팟 {added}개 등록 (커서: 핸드 {h}/169)")
                    continue
            done_count += 1

    except KeyboardInterrupt:
        print(f"\n⏸  중단됨 — {done_count}개 작업 저장 완료. 재실행하면 이어서 계산합니다.")

    show_status(conn)
    conn.close()


if __name__ == "__main__":
    main()
