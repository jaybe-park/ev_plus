#!/usr/bin/env python3
"""
프리플랍 GTO DB·수집 체크포인트 전수 검사(읽기 전용).

검사 항목:
1. 핸드별 빈도 합이 [FREQ_SUM_MIN, FREQ_SUM_MAX] 안인지 (gto.loader와 같은 상수)
2. RFI 오픈 비율이 UTG < HJ < CO < BTN < SB 순으로 넓어지는지
3. 한 노드의 핸드 전부가 fold=100% 또는 raise=100%인 붕괴
4. 행의 3종 키·hero_position = derive_node_meta(action_seq)
5. 자식 노드 핸드 ⊆ 부모 노드에서 히어로가 직전 액션을 한 핸드(빈도 > ε) — 레인지 밖 핸드
   저장(ADR 0002) 탐지. 부모가 미수집이거나 히어로의 첫 결정이면 생략
6. 체크포인트 visited 중 결정 노드인데 DB·failed에 없는 키 = 0
7. DB에서 재구성한 frontier ⊆ 체크포인트 frontier ∪ visited ∪ failed — frontier 유실 탐지
6·7이 실패하면 `python3 scripts/collect_gto_tree.py --reseed-checkpoint`로 재시드한다.

DB는 읽기 전용으로 연다(`--db` → `EV_PLUS_DB` → poker.db). 체크포인트가 없으면 6·7 생략.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import gto_tree_worker as tw  # noqa: E402
import collect_gto_tree as ct  # noqa: E402
from db.connection import get_readonly_connection, resolve_db_path  # noqa: E402
from gto.loader import FREQ_SUM_MIN, FREQ_SUM_MAX, freq_sum_ok, read_preflop_nodes  # noqa: E402
from gto.loader import collected_by_seq  # noqa: E402
from gto.node_key import derive_node_meta, split_key, _replay, POSITIONS  # noqa: E402

DEFAULT_CHECKPOINT = ROOT / "gto_tree_checkpoint.json"


def key_mismatches(nodes) -> list:
    """[(action_seq, 설명)] — 저장 행의 3종 키·hero_position ≠ derive_node_meta(action_seq)."""
    out = []
    for s in nodes:
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


def hero_prev_action(node_key: str):
    """노드 키 → (부모 키, 히어로의 직전 액션 토큰). 히어로의 첫 결정이면 None."""
    tokens = split_key(node_key)
    actors, hero_seat = _replay(tokens)
    if hero_seat is None:
        return None
    last = None
    for i, seat in enumerate(actors):
        if seat == hero_seat:
            last = i
    if last is None:
        return None
    return "-".join(tokens[:last]), tokens[last]


def _supports(freqs: dict, token: str, parent_raise_size, epsilon: float) -> bool:
    """부모 노드의 핸드 빈도에서 토큰 액션 빈도가 epsilon을 넘는가."""
    if token in ("C", "X"):
        return (freqs.get("call") or 0) > epsilon
    if token == "F":
        return (freqs.get("fold") or 0) > epsilon
    size = float(token[1:])
    if parent_raise_size is not None and abs(size - parent_raise_size) < 1e-9:
        return (freqs.get("raise") or 0) > epsilon
    if parent_raise_size is not None:
        return (freqs.get("allin") or 0) > epsilon
    return (freqs.get("raise") or 0) + (freqs.get("allin") or 0) > epsilon


def range_outside_parent(nodes, epsilon: float = tw.EPSILON) -> list:
    """[(action_seq, 설명)] — 자식 노드에 부모의 직전 액션 지지 집합 밖 핸드가 있다."""
    by_seq = {n["action_seq"]: n for n in nodes if n["action_seq"] is not None}
    out = []
    for n in nodes:
        seq = n["action_seq"]
        if seq is None:
            continue
        prev = hero_prev_action(seq)
        if prev is None:
            continue
        parent_key, token = prev
        parent = by_seq.get(parent_key)
        if parent is None:
            continue
        support = {h for h, f in parent["hands"].items()
                   if _supports(f, token, parent["raise_size"], epsilon)}
        extra = sorted(set(n["hands"]) - support)
        if extra:
            out.append((seq, f"id={n['id']} 핸드 {len(n['hands'])}개 중 {len(extra)}개가 부모 "
                             f"{parent_key!r}의 {token} 지지 집합({len(support)}핸드) 밖 "
                             f"(예: {extra[:5]})"))
    return out


def load_checkpoint(checkpoint_path):
    p = Path(checkpoint_path)
    if not p.exists():
        return None
    return json.loads(p.read_text())


def lost_visited(checkpoint_path, collected_keys: set):
    """체크포인트 visited 중 결정 노드인데 DB·failed에 없는 키. 체크포인트 없으면 None."""
    data = load_checkpoint(checkpoint_path)
    if data is None:
        return None
    return sorted(ct.lost_visited_keys(data.get("visited", []), data.get("failed", []),
                                       dict.fromkeys(collected_keys)))


def lost_frontier(checkpoint_path, collected: dict, epsilon: float = tw.EPSILON):
    """DB 재구성 frontier 중 체크포인트 frontier·visited·failed 어디에도 없는 (reach, 키).
    체크포인트 없으면 None."""
    data = load_checkpoint(checkpoint_path)
    if data is None:
        return None
    known = set(data.get("visited", [])) | set(data.get("failed", []))
    known |= {"-".join(f["tokens"]) for f in data.get("frontier", [])}
    seed, _ = ct.seed_frontier_from_db(collected, epsilon)
    missing = [(reach, "-".join(tokens)) for tokens, reach in seed
               if "-".join(tokens) not in known]
    return sorted(missing, reverse=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="프리플랍 GTO DB 전수 검사(읽기 전용)")
    ap.add_argument("--db", default=None, help="기본: EV_PLUS_DB → poker.db")
    ap.add_argument("--checkpoint", default=str(DEFAULT_CHECKPOINT))
    args = ap.parse_args(argv)
    db_path = resolve_db_path(args.db)

    conn = get_readonly_connection(db_path)
    try:
        nodes = read_preflop_nodes(conn)
    finally:
        conn.close()

    problems = []  # (label, reason)
    open_ratios = {}  # position -> fold100 count
    for s in nodes:
        label = s["situation_label"] or f"{s['position']} {s['range_type']} vs {s['vs_position']}"
        hands = s["hands"]
        if not hands:
            problems.append((label, "핸드 데이터 없음(0행)"))
            continue
        bad = [(h, round(sum(f.values()), 3)) for h, f in hands.items() if not freq_sum_ok(f)]
        if bad:
            problems.append((label, f"빈도합 이상 {len(bad)}개 핸드 (예: {bad[:5]})"))
        n = len(hands)
        fold100 = sum(1 for f in hands.values() if (f.get("fold") or 0) >= 0.999)
        raise100 = sum(1 for f in hands.values() if (f.get("raise") or 0) >= 0.999)
        if n >= 100 and fold100 == n:
            problems.append((label, f"전체 {n}핸드가 전부 fold=100% (완전 붕괴 의심)"))
        if n >= 100 and raise100 == n:
            problems.append((label, f"전체 {n}핸드가 전부 raise=100% (완전 붕괴 의심)"))
        if s["range_type"] == "open" and s["vs_position"] is None:
            open_ratios[s["position"]] = fold100

    rfi_positions = [p for p in POSITIONS[:5] if p in open_ratios]
    order_problems = []
    for p1, p2 in zip(rfi_positions, rfi_positions[1:]):
        if open_ratios[p1] < open_ratios[p2]:
            order_problems.append(
                f"{p1}(fold100={open_ratios[p1]}) < {p2}(fold100={open_ratios[p2]}) "
                f"— {p2}가 {p1}보다 좁게 열려 순서 역전")

    mismatches = key_mismatches(nodes)
    outside = range_outside_parent(nodes)
    collected = collected_by_seq(nodes)
    lost = lost_visited(args.checkpoint, set(collected))
    lost_fr = lost_frontier(args.checkpoint, collected)

    print("=" * 70)
    print("gto_preflop_situations 전수 검사 리포트")
    print("=" * 70)
    print(f"DB: {db_path}")
    print(f"총 situations: {len(nodes)}")
    print()

    print(f"-- 3종 키 = derive_node_meta(action_seq) 불일치 ({len(mismatches)}건) --")
    for seq, why in mismatches:
        print(f"  [FAIL] {seq!r}: {why}")
    if not mismatches:
        print("  없음")
    print()

    print(f"-- 자식 핸드 ⊆ 부모의 직전 액션 지지 집합 위반 ({len(outside)}건) --")
    for seq, why in outside:
        print(f"  [FAIL] {seq!r}: {why}")
    if not outside:
        print("  없음")
    print()

    reseed = "python3 scripts/collect_gto_tree.py --reseed-checkpoint"
    if lost is None:
        print(f"-- 체크포인트 검사: 체크포인트 없음({args.checkpoint}), 생략 --")
    else:
        print(f"-- visited인데 DB·failed에 없음 ({len(lost)}건) --")
        for k in lost:
            print(f"  [FAIL] {k!r} — `{reseed}`로 visited에서 빼고 다시 수집")
        if not lost:
            print("  없음")
        print()
        print(f"-- DB 재구성 frontier인데 체크포인트 frontier·visited·failed에 없음 ({len(lost_fr)}건) --")
        for reach, k in lost_fr:
            meta = derive_node_meta(k)
            print(f"  [FAIL] {k!r} reach={reach:.5f} {meta and meta['situation_label']} — `{reseed}`")
        if not lost_fr:
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

    print(f"-- 문제 스팟 ({len(problems)}건, 빈도합 기준 [{FREQ_SUM_MIN}, {FREQ_SUM_MAX}]) --")
    if not problems:
        print("  없음 — 모든 스팟 검증 통과")
    else:
        for label, reason in problems:
            print(f"  [FAIL] {label}: {reason}")
    print()

    total_bad = (len(problems) + len(order_problems) + len(mismatches) + len(outside)
                 + len(lost or []) + len(lost_fr or []))
    print(f"검사 결과: {'통과' if total_bad == 0 else f'{total_bad}건 이상 발견'}")
    return 0 if total_bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
