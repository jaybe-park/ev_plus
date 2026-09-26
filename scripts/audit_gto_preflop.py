#!/usr/bin/env python3
"""
gto_preflop_situations / gto_preflop_hands 전수 검사 스크립트.

검사 항목:
1. 핸드별 빈도 합이 [0.9, 1.1] 범위 안인지 (로더 방어와 별개로 원본 DB 자체 검증)
2. 같은 range_type(open) 내에서 포지션 간 오픈 비율이 상식적인 순서인지
   (RFI: UTG < HJ < CO < BTN < SB 넓어지는 방향, 역전되면 의심)
3. 특정 액션이 부자연스럽게 100%/0%로 쏠린 스팟이 있는지
   (한 situation의 169핸드 전부가 fold=100%이거나, 전부 raise=100%인 경우 등)

4. 행의 3종 키(position/vs_position/range_type)와 hero_position이 action_seq에서
   유도한 값(gto.node_key.derive_node_meta)과 같은지 (T-001 — 덮어쓰기·라벨 불일치 탐지)
5. 수집 체크포인트 visited 중 결정 노드인데 DB에도 failed에도 없는 키 = 0 인지
   (덮어써져 사라진 노드 — scripts/requeue_lost_gto_nodes.py로 frontier에 되돌린다)

결과를 사람이 읽을 수 있는 리포트로 출력한다. DB는 읽기 전용으로 연다
(`EV_PLUS_DB` → 기본 poker.db, `--db`로 지정 가능).
"""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gto.node_key import derive_node_meta  # noqa: E402

DEFAULT_CHECKPOINT = ROOT / "gto_tree_checkpoint.json"

POSITIONS = ["UTG", "HJ", "CO", "BTN", "SB", "BB"]
POS_INDEX = {p: i for i, p in enumerate(POSITIONS)}


def default_db_path() -> str:
    return os.environ.get("EV_PLUS_DB", str(ROOT / "poker.db"))


def key_mismatches(situations) -> list:
    """[(action_seq, 설명)] — 저장 행의 3종 키·hero_position ≠ derive_node_meta(action_seq)."""
    out = []
    for s in situations:
        seq = s["action_seq"]
        if seq is None:
            out.append((seq, f"id={s['id']} action_seq 없음"))
            continue
        meta = derive_node_meta(seq)
        if meta is None:
            out.append((seq, f"id={s['id']} 결정 노드가 아님"))
            continue
        row = (s["position"], s["vs_position"], s["range_type"], s["hero_position"])
        want = (meta["hero_position"], meta["vs_position"], meta["range_type"],
                meta["hero_position"])
        if row != want:
            out.append((seq, f"id={s['id']} 저장={row} 유도={want}"))
    return out


def lost_visited(checkpoint_path, collected_keys: set):
    """체크포인트 visited 중 결정 노드인데 DB·failed에 없는 키. 체크포인트 없으면 None."""
    p = Path(checkpoint_path)
    if not p.exists():
        return None
    data = json.loads(p.read_text())
    failed = set(data.get("failed", []))
    return sorted(
        k for k in data.get("visited", [])
        if k not in collected_keys and k not in failed and derive_node_meta(k) is not None
    )


def main(argv=None):
    ap = argparse.ArgumentParser(description="프리플랍 GTO DB 전수 검사(읽기 전용)")
    ap.add_argument("--db", default=None, help="기본: EV_PLUS_DB → poker.db")
    ap.add_argument("--checkpoint", default=str(DEFAULT_CHECKPOINT))
    args = ap.parse_args(argv)
    db_path = args.db or default_db_path()

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT * FROM gto_preflop_situations ORDER BY range_type, position")
    situations = cur.fetchall()

    problems = []  # list of (situation_label, reason)
    open_ratios = {}  # position -> fold100_count (for RFI 순서 검사)

    for s in situations:
        sid = s["id"]
        label = s["situation_label"] or f"{s['position']} {s['range_type']} vs {s['vs_position']}"
        cur.execute(
            "SELECT hand, freq_fold, freq_call, freq_raise, freq_allin "
            "FROM gto_preflop_hands WHERE situation_id=?",
            (sid,),
        )
        hands = cur.fetchall()

        if not hands:
            problems.append((label, "핸드 데이터 없음(0행)"))
            continue

        # 1) 빈도합 검증
        bad_sum_hands = []
        for h in hands:
            total = (h["freq_fold"] or 0) + (h["freq_call"] or 0) + \
                    (h["freq_raise"] or 0) + (h["freq_allin"] or 0)
            if not (0.9 <= total <= 1.1):
                bad_sum_hands.append((h["hand"], round(total, 3)))
        if bad_sum_hands:
            problems.append((
                label,
                f"빈도합 이상 {len(bad_sum_hands)}개 핸드 (예: {bad_sum_hands[:5]})",
            ))

        # 3) 특정 액션 100%/0% 쏠림 (전체 169핸드 중 한 액션이 완전히 0이거나
        #    fold=100%인 핸드 비율이 비정상적으로 높은지)
        n = len(hands)
        fold100 = sum(1 for h in hands if (h["freq_fold"] or 0) >= 0.999)
        raise100 = sum(1 for h in hands if (h["freq_raise"] or 0) >= 0.999)
        allin_any = sum(1 for h in hands if (h["freq_allin"] or 0) > 0.001)
        call_any = sum(1 for h in hands if (h["freq_call"] or 0) > 0.001)

        if n >= 100 and fold100 == n:
            problems.append((label, f"전체 {n}핸드가 전부 fold=100% (완전 붕괴 의심)"))
        if n >= 100 and raise100 == n:
            problems.append((label, f"전체 {n}핸드가 전부 raise=100% (완전 붕괴 의심)"))

        if s["range_type"] == "open" and s["vs_position"] is None:
            open_ratios[s["position"]] = fold100

    # 2) RFI 포지션 간 오픈 비율 순서 검사 (fold100 카운트가 작을수록 넓게 오픈)
    rfi_positions = [p for p in ["UTG", "HJ", "CO", "BTN", "SB"] if p in open_ratios]
    order_problems = []
    for i in range(len(rfi_positions) - 1):
        p1, p2 = rfi_positions[i], rfi_positions[i + 1]
        if open_ratios[p1] < open_ratios[p2]:
            order_problems.append(
                f"{p1}(fold100={open_ratios[p1]}) < {p2}(fold100={open_ratios[p2]}) "
                f"— {p2}가 {p1}보다 좁게 열려 순서 역전"
            )

    # 4) 3종 키 = derive_node_meta(action_seq)
    mismatches = key_mismatches(situations)
    # 5) visited인데 DB·failed에 없음
    collected_keys = {s["action_seq"] for s in situations if s["action_seq"] is not None}
    lost = lost_visited(args.checkpoint, collected_keys)
    conn.close()

    # --- 리포트 출력 ---
    print("=" * 70)
    print("gto_preflop_situations 전수 검사 리포트")
    print("=" * 70)
    print(f"DB: {db_path}")
    print(f"총 situations: {len(situations)}")
    print()

    print(f"-- 3종 키 = derive_node_meta(action_seq) 불일치 ({len(mismatches)}건) --")
    for seq, why in mismatches:
        print(f"  [FAIL] {seq!r}: {why}")
    if not mismatches:
        print("  없음")
    print()

    if lost is None:
        print(f"-- visited인데 DB·failed에 없음: 체크포인트 없음({args.checkpoint}), 검사 생략 --")
    else:
        print(f"-- visited인데 DB·failed에 없음 ({len(lost)}건) --")
        for k in lost:
            print(f"  [FAIL] {k!r} — scripts/requeue_lost_gto_nodes.py로 frontier에 되돌리세요")
        if not lost:
            print("  없음")
    print()

    print("-- RFI 오픈 비율 (fold100 카운트, 작을수록 넓게 오픈) --")
    for p in rfi_positions:
        print(f"  {p}: fold100={open_ratios[p]}/169")
    if order_problems:
        print("  [경고] 순서 역전 발견:")
        for op in order_problems:
            print(f"    - {op}")
    else:
        print("  [OK] UTG < HJ < CO < BTN < SB 방향으로 정상 정렬")
    print()

    print(f"-- 문제 스팟 ({len(problems)}건) --")
    if not problems:
        print("  없음 — 모든 스팟 검증 통과")
    else:
        for label, reason in problems:
            print(f"  [FAIL] {label}: {reason}")
    print()

    total_bad = len(problems) + len(order_problems) + len(mismatches) + len(lost or [])
    print(f"검사 결과: {'통과' if total_bad == 0 else f'{total_bad}건 이상 발견'}")
    return 0 if total_bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
