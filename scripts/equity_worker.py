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

from collections import defaultdict

from core.card import Card, Suit, Rank
from ai.equity import (
    canonical_key, decode_key, mc_counts,
    exact_counts_river, street_of, _FULL_DECK,
    board_rank_table, equity_via_board_table,
)
from db.connection import get_connection

# 배치 인출/저장 크기 (작업 3 — 워커 배치 인출/저장)
BATCH_FETCH_RIVER = 500   # 리버는 스팟당 매우 빠르므로 크게
BATCH_FETCH_TURN = 500
BATCH_FETCH_FLOP = 20     # 플랍은 스팟당 분 단위 → 적게 인출
BATCH_COMMIT = 100        # executemany 커밋 단위

# 프리플랍 목표 샘플 수 (100만 = 오차 ±0.05%)
PREFLOP_TARGET = 1_000_000
# 멀티웨이 스팟 목표 샘플 수 (10만 = 오차 ±0.15%)
MULTIWAY_TARGET = 100_000
# 한 번에 누적하는 샘플 청크 (청크마다 커밋)
MC_CHUNK = 25_000

# 스트리트별 전체 고유 스팟 수 (수트 대칭 제거, 홀2장+보드)
SPOT_SPACE = {
    "preflop": 169,
    "flop": 1_286_792,
    "turn": 55_190_538,
    "river": 2_428_287_420,
}

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
            cur.close()
    conn.commit()
    return added


_EXACT_JOB_STREET_SQL = """
    SELECT id, street, spot_key FROM equity_cache
    WHERE exact = 0 AND num_opponents = 1 AND street = ?
    ORDER BY (total > 0) DESC, id
    LIMIT 1
"""


def next_exact_job(conn):
    """
    1:1 포스트플랍 스팟 중 미완료 — 리버 → 턴 → 플랍 순.
    같은 스트리트에선 게임에서 만난 스팟(total>0)이 스윕 등록분(total=0)보다 우선.

    CASE 표현식 정렬 대신 스트리트별 단순 쿼리 3번으로 분리 —
    idx_equity_pending 부분 인덱스(street, total, id)를 그대로 활용해
    각 쿼리가 인덱스만으로 즉시 첫 행을 찾는다 (대량 스캔 회피).
    """
    for street in ("river", "turn", "flop"):
        cur = conn.execute(_EXACT_JOB_STREET_SQL, (street,))
        row = cur.fetchone()
        cur.close()
        if row:
            return row
    return None


# ──────────────────────────────────────────
# 작업 3 — 워커 배치 인출/저장
#
# 계산 자체가 빨라질수록(작업 1·2) 스팟당 SQL round-trip 비용이 상대적으로
# 커진다. next_exact_job/next_mc_job으로 "1건 조회 → 1건 계산 → 1건 UPDATE"를
# 반복하는 대신, LIMIT 500 등으로 pending id 목록을 한 번에 메모리로 인출해
# 소진하고, 결과는 최대 BATCH_COMMIT개 단위로 모아 executemany로 커밋한다.
#
# 그라인드(scripts/grind.py)와 동시 실행돼도 안전하도록, 저장 시 항상
# "WHERE id=? AND exact=0" 조건을 걸어 이미 다른 프로세스가 먼저 처리한
# 행은 조용히 skip한다 (멱등).
# ──────────────────────────────────────────

def _fetch_pending_batch(conn, street: str, limit: int):
    """지정 스트리트의 미완료(exact=0) 스팟 id/spot_key를 최대 limit개 인출."""
    cur = conn.execute(
        """
        SELECT id, street, spot_key FROM equity_cache
        WHERE exact = 0 AND num_opponents = 1 AND street = ?
        ORDER BY (total > 0) DESC, id
        LIMIT ?
        """,
        (street, limit),
    )
    rows = cur.fetchall()
    cur.close()
    return rows


def next_exact_batch(conn):
    """
    배치 버전 next_exact_job — 리버 → 턴 → 플랍 순으로 스트리트 하나를 골라
    (street, jobs 리스트)를 반환. 빈 스트리트는 건너뛴다.
    """
    for street, limit in (
        ("river", BATCH_FETCH_RIVER),
        ("turn", BATCH_FETCH_TURN),
        ("flop", BATCH_FETCH_FLOP),
    ):
        jobs = _fetch_pending_batch(conn, street, limit)
        if jobs:
            return street, jobs
    return None, []


def _flush_exact_updates(conn, updates: list) -> int:
    """
    (wins, ties, total, id) 튜플 리스트를 BATCH_COMMIT 단위로 executemany 커밋.
    WHERE id=? AND exact=0 으로 멱등 유지 (동시 실행 중인 다른 프로세스가
    이미 처리한 행은 rowcount=0으로 조용히 skip).
    반환: 실제 커밋한 건수.
    """
    if not updates:
        return 0
    done = 0
    sql = (
        "UPDATE equity_cache SET wins=?, ties=?, total=?, exact=1, "
        "updated_at=datetime('now') WHERE id=? AND exact=0"
    )
    for i in range(0, len(updates), BATCH_COMMIT):
        chunk = updates[i:i + BATCH_COMMIT]
        cur = conn.executemany(sql, chunk)
        done += cur.rowcount if cur.rowcount and cur.rowcount > 0 else len(chunk)
        cur.close()
        conn.commit()
    return done


def process_river_batch(conn, jobs) -> list:
    """
    리버 배치를 실제 보드로 그룹화해 board_rank_table을 그룹당 1회만 구축.
    (조사 결과: 캐시에 쌓인 canonical 리버 스팟 20만 건 샘플에서 실제 보드
    기준 그룹 크기 평균 ~2, 최대 그룹 7 — board_rank_table 재사용 이득 있음.
    docs/ai-bot.md 참고.)

    반환: 출력용 로그 문자열 리스트.
    """
    groups: dict = defaultdict(list)
    for job in jobs:
        hole, board = decode_key(job["spot_key"])
        board_key = tuple(sorted((c.rank.rank_value, c.suit.value) for c in board))
        groups[board_key].append((job, hole, board))

    updates = []
    logs = []
    t0 = time.time()
    for board_key, items in groups.items():
        board = items[0][2]
        table = board_rank_table(board)
        for job, hole, _ in items:
            w, t, n = equity_via_board_table(hole, board, table)
            updates.append((w, t, n, job["id"]))

    saved = _flush_exact_updates(conn, updates)
    dt = time.time() - t0
    logs.append(
        f"✅ [배치-리버] {len(jobs)}스팟 → 실제보드 {len(groups)}그룹 "
        f"(board_rank_table {len(groups)}회 구축), 저장 {saved}건, {dt:.2f}s"
    )
    return logs


# ──────────────────────────────────────────
# 체계적 플랍 스윕 (큐가 비었을 때의 무한 작업 저장고)
# ──────────────────────────────────────────

SWEEP_BATCH = 50  # 한 번에 등록하는 스팟 수


def _get_cursor(conn) -> tuple:
    cur = conn.execute(
        "SELECT value FROM worker_meta WHERE key = 'flop_sweep_cursor'"
    )
    row = cur.fetchone()
    cur.close()
    if row is None:
        return 0, 0
    h, f = row["value"].split(":")
    return int(h), int(f)


def _set_cursor(conn, hand_idx: int, flop_idx: int) -> None:
    cur = conn.execute(
        "INSERT INTO worker_meta(key, value) VALUES('flop_sweep_cursor', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (f"{hand_idx}:{flop_idx}",),
    )
    cur.close()


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
            cur.close()
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
    cur = conn.execute(
        """
        SELECT id, street, spot_key, num_opponents, total FROM equity_cache
        WHERE exact = 0 AND street = 'preflop' AND total < ?
        ORDER BY total ASC, num_opponents ASC
        LIMIT 1
        """,
        (PREFLOP_TARGET,),
    )
    row = cur.fetchone()
    cur.close()
    return row


def next_mc_job(conn):
    """
    샘플 목표 미달 스팟 — 프리플랍 우선, 샘플 적은 것부터.

    기존엔 OR 조건 + 표현식 정렬 단일 쿼리라 인덱스를 못 타고 760만 행을
    스캔했다. 프리플랍(845행)과 멀티웨이(부분 인덱스 idx_equity_multiway_pending)
    쿼리 2개로 나눠 각각 인덱스로 즉시 첫 행을 찾도록 재구성.
    """
    cur = conn.execute(
        """
        SELECT id, street, spot_key, num_opponents, total FROM equity_cache
        WHERE exact = 0 AND street = 'preflop' AND total < ?
        ORDER BY total ASC, num_opponents ASC
        LIMIT 1
        """,
        (PREFLOP_TARGET,),
    )
    row = cur.fetchone()
    cur.close()
    if row:
        return row
    cur = conn.execute(
        """
        SELECT id, street, spot_key, num_opponents, total FROM equity_cache
        WHERE exact = 0 AND num_opponents > 1 AND total < ?
        ORDER BY num_opponents ASC, total ASC
        LIMIT 1
        """,
        (MULTIWAY_TARGET,),
    )
    row = cur.fetchone()
    cur.close()
    return row


def _upsert_exact(conn, street: str, spot_key: str, w: float, t: float, n: int) -> None:
    """자식 스팟의 정확값 저장 (커밋은 호출자가)"""
    cur = conn.execute(
        """
        INSERT INTO equity_cache(street, spot_key, num_opponents, wins, ties, total, exact)
        VALUES(?,?,1,?,?,?,1)
        ON CONFLICT(spot_key, num_opponents) DO UPDATE SET
            wins=excluded.wins, ties=excluded.ties, total=excluded.total,
            exact=1, updated_at=datetime('now')
        """,
        (street, spot_key, w, t, n),
    )
    cur.close()


def _lookup_exact(conn, spot_key: str):
    cur = conn.execute(
        "SELECT wins, ties, total FROM equity_cache "
        "WHERE spot_key=? AND num_opponents=1 AND exact=1",
        (spot_key,),
    )
    row = cur.fetchone()
    cur.close()
    return row


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
    cur = conn.execute(
        "UPDATE equity_cache SET wins=?, ties=?, total=?, exact=1, "
        "updated_at=datetime('now') WHERE id=? AND exact=0",
        (wins, ties, total, job["id"]),
    )
    cur.close()
    conn.commit()
    eq = (wins + 0.5 * ties) / total
    hit_info = f", 캐시적중 {hits}" if hits else ""
    return (f"✅ [전수] {job['street']:6s} {job['spot_key']:24s} "
            f"equity={eq:.4f} ({total:,}조합, {time.time()-t0:.1f}s{hit_info})")


def process_turn_flop_batch(conn, street: str, jobs) -> list:
    """
    턴/플랍 배치 — exact_turn_dp/exact_flop_dp는 이미 스트리트 분해 DP로
    자식 단위 커밋을 하므로(진행분 보존 목적) 계산 자체는 건별로 유지한다.
    다만 "다음 작업 조회" SQL 라운드트립은 배치 인출로 없애고, 최종 결과
    저장은 BATCH_COMMIT개 단위 executemany로 모아 커밋한다.

    각 job은 저장 시 "WHERE id=? AND exact=0"으로 멱등 체크 —
    그라인드가 동시에 같은 작업을 먼저 끝냈으면 조용히 skip.
    """
    logs = []
    pending_updates = []

    def flush():
        n = _flush_exact_updates(conn, pending_updates)
        pending_updates.clear()
        return n

    for job in jobs:
        hole, board = decode_key(job["spot_key"])
        t0 = time.time()
        if street == "turn":
            wins, ties, total, hits = exact_turn_dp(conn, hole, board)
        else:
            wins, ties, total, hits = exact_flop_dp(conn, hole, board)
        pending_updates.append((wins, ties, total, job["id"]))
        eq = (wins + 0.5 * ties) / total
        hit_info = f", 캐시적중 {hits}" if hits else ""
        logs.append(
            f"✅ [배치-{street}] {job['spot_key']:24s} "
            f"equity={eq:.4f} ({total:,}조합, {time.time()-t0:.1f}s{hit_info})"
        )
        if len(pending_updates) >= BATCH_COMMIT:
            flush()

    flush()
    return logs


def process_mc(conn, job) -> str:
    hole, board = decode_key(job["spot_key"])
    t0 = time.time()
    wins, ties, total = mc_counts(hole, board, job["num_opponents"], MC_CHUNK)
    cur = conn.execute(
        "UPDATE equity_cache SET wins=wins+?, ties=ties+?, total=total+?, "
        "updated_at=datetime('now') WHERE id=? AND exact=0",
        (wins, ties, total, job["id"]),
    )
    cur.close()
    conn.commit()
    cur = conn.execute(
        "SELECT wins, ties, total FROM equity_cache WHERE id=?", (job["id"],)
    )
    row = cur.fetchone()
    cur.close()
    eq = (row["wins"] + 0.5 * row["ties"]) / row["total"]
    target = PREFLOP_TARGET if job["street"] == "preflop" else MULTIWAY_TARGET
    return (f"📈 [샘플] {job['street']:7s} {job['spot_key']:24s} vs{job['num_opponents']} "
            f"equity={eq:.4f} ({row['total']:,}/{target:,}, {time.time()-t0:.1f}s)")


def next_mc_batch(conn, limit: int = 200):
    """next_mc_job의 배치 버전 — 프리플랍 우선, 없으면 멀티웨이."""
    cur = conn.execute(
        """
        SELECT id, street, spot_key, num_opponents, total FROM equity_cache
        WHERE exact = 0 AND street = 'preflop' AND total < ?
        ORDER BY total ASC, num_opponents ASC
        LIMIT ?
        """,
        (PREFLOP_TARGET, limit),
    )
    rows = cur.fetchall()
    cur.close()
    if rows:
        return rows
    cur = conn.execute(
        """
        SELECT id, street, spot_key, num_opponents, total FROM equity_cache
        WHERE exact = 0 AND num_opponents > 1 AND total < ?
        ORDER BY num_opponents ASC, total ASC
        LIMIT ?
        """,
        (MULTIWAY_TARGET, limit),
    )
    rows = cur.fetchall()
    cur.close()
    return rows


def process_mc_batch(conn, jobs) -> list:
    """
    MC 배치 — 각 스팟 계산 자체는 mc_counts()로 건별 수행하되(스팟마다
    num_opponents/목표가 다르므로 계산 병합은 불가), UPDATE는
    BATCH_COMMIT개 단위 executemany로 모아 커밋해 라운드트립을 줄인다.
    wins/ties/total은 "누적(+=)"이라 executemany에도 그대로 적용 가능.
    """
    logs = []
    pending = []
    sql = (
        "UPDATE equity_cache SET wins=wins+?, ties=ties+?, total=total+?, "
        "updated_at=datetime('now') WHERE id=? AND exact=0"
    )

    def flush():
        if not pending:
            return
        cur = conn.executemany(sql, pending)
        cur.close()
        conn.commit()
        pending.clear()

    for job in jobs:
        hole, board = decode_key(job["spot_key"])
        t0 = time.time()
        wins, ties, total = mc_counts(hole, board, job["num_opponents"], MC_CHUNK)
        pending.append((wins, ties, total, job["id"]))
        if len(pending) >= BATCH_COMMIT:
            flush()
        new_total = job["total"] + total
        target = PREFLOP_TARGET if job["street"] == "preflop" else MULTIWAY_TARGET
        logs.append(
            f"📈 [배치샘플] {job['street']:7s} {job['spot_key']:24s} vs{job['num_opponents']} "
            f"({new_total:,}/{target:,}, {time.time()-t0:.1f}s)"
        )
    flush()
    return logs


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
    prev_street = None
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

        # 스트리트별 전체 공간 대비 발견율 (vs1, 각 스트리트당 한 번만)
        if prev_street != r["street"] and r["street"] in SPOT_SPACE and r["num_opponents"] == 1:
            discovered = r["spots"]  # 발견 = DB에 등록된 스팟 수
            total_space = SPOT_SPACE[r["street"]]
            coverage_pct = (discovered / total_space * 100) if total_space else 0
            coverage_str = f"{coverage_pct:.2f}%" if coverage_pct < 1 else f"{coverage_pct:.1f}%"
            if r["street"] == "preflop":
                # 프리플랍은 샘플링 대상 — 목표 샘플 도달 스팟 수 표시
                reached = conn.execute(
                    "SELECT COUNT(*) AS n FROM equity_cache "
                    "WHERE street='preflop' AND num_opponents=1 AND total >= ?",
                    (PREFLOP_TARGET,),
                ).fetchone()["n"]
                extra = f"목표 샘플 도달 {reached:,}"
            else:
                extra = f"정확값 {int(r['exact_done']):,}"
            print(f"              발견 {discovered:,} / 전체 {total_space:,} "
                  f"({coverage_str}) · {extra}")
            prev_street = r["street"]

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

    print("통계 갱신 중...")
    cur = conn.execute("ANALYZE")
    cur.close()
    conn.commit()

    deadline = time.time() + args.minutes * 60 if args.minutes else None
    done_count = 0
    print("워커 시작 — Ctrl+C로 언제든 중단 가능 (진행분은 저장됨)\n")

    try:
        while True:
            if deadline and time.time() >= deadline:
                print(f"\n⏰ 시간 제한 도달 — {done_count}개 작업 완료")
                break

            # --preflop-first: 프리플랍 샘플링을 최우선으로 (배치)
            if args.preflop_first:
                try:
                    jobs = next_mc_batch(conn, BATCH_FETCH_TURN)
                    jobs = [j for j in jobs if j["street"] == "preflop"]
                except sqlite3.OperationalError:
                    time.sleep(1.0)
                    continue
                if jobs:
                    try:
                        for line in process_mc_batch(conn, jobs):
                            print(line)
                    except sqlite3.OperationalError:
                        print("⏳ DB 쓰기 경합 — 1초 후 재시도")
                        time.sleep(1.0)
                    done_count += len(jobs)
                    continue
                # 프리플랍 전부 목표 도달 → 일반 우선순위로 진행

            try:
                street, jobs = next_exact_batch(conn)
            except sqlite3.OperationalError:
                time.sleep(1.0)
                continue
            if jobs:
                try:
                    if street == "river":
                        lines = process_river_batch(conn, jobs)
                    else:
                        lines = process_turn_flop_batch(conn, street, jobs)
                    for line in lines:
                        print(line)
                except sqlite3.OperationalError:
                    print("⏳ DB 쓰기 경합 — 1초 후 재시도")
                    time.sleep(1.0)
                    continue
                done_count += len(jobs)
            else:
                try:
                    jobs = next_mc_batch(conn)
                except sqlite3.OperationalError:
                    time.sleep(1.0)
                    continue
                if jobs:
                    try:
                        for line in process_mc_batch(conn, jobs):
                            print(line)
                    except sqlite3.OperationalError:
                        print("⏳ DB 쓰기 경합 — 1초 후 재시도")
                        time.sleep(1.0)
                        continue
                    done_count += len(jobs)
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

    except KeyboardInterrupt:
        print(f"\n⏸  중단됨 — {done_count}개 작업 저장 완료. 재실행하면 이어서 계산합니다.")

    show_status(conn)
    conn.close()


if __name__ == "__main__":
    main()
