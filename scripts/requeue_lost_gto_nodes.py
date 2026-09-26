#!/usr/bin/env python3
"""
덮어써져 사라진 프리플랍 GTO 노드를 수집 대상(frontier)으로 되돌린다 (T-001).

배경: 저장 API가 예전에 (position, vs_position, range_type)으로 행을 찾아, 같은 3종 키를
가진 다른 노드(예: F-F-F-R2.5-F 와 F-F-F-R2.5-C)를 덮어썼다. 수집 워커는 저장한 노드를
체크포인트 `visited`에 넣으므로, 덮어써져 DB에서 사라진 노드도 "이미 방문"으로 남아
다시 수집되지 않는다.

이 스크립트는 체크포인트의 `visited` 중 **결정 노드인데 DB에 없고 failed에도 없는 키**를
찾아 `visited`에서 빼고 `frontier`에 넣는다. 도달확률(reach)은 수집된 조상 노드들의 콤보
가중 빈도를 곱해 다시 계산하고, 조상 데이터가 없어 계산할 수 없으면 1.0(최우선)으로 둔다.

- 기본은 드라이런(무엇을 바꿀지 출력만). 실제 체크포인트 수정은 `--apply`.
- DB는 읽기만 한다(`EV_PLUS_DB` → 기본 poker.db, 읽기 전용으로 연다).
- 체크포인트는 수집 워커와 같은 원자적 방식(tmp → replace)으로 쓴다. 수집 워커가 도는
  동안에는 실행하지 않는다.

사용:
    python3 scripts/requeue_lost_gto_nodes.py                     # 드라이런
    python3 scripts/requeue_lost_gto_nodes.py --apply             # 체크포인트 수정
    python3 scripts/requeue_lost_gto_nodes.py --checkpoint /path/ckpt.json --db /path/x.db
"""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import gto_tree_worker as tw  # noqa: E402
from gto.node_key import derive_node_meta, split_key  # noqa: E402

DEFAULT_CHECKPOINT = ROOT / "gto_tree_checkpoint.json"


def default_db_path() -> str:
    return os.environ.get("EV_PLUS_DB", str(ROOT / "poker.db"))


def load_collected(db_path: str) -> dict:
    """{action_seq: {"hands": {...}, "raise_size": float|None}} — 읽기 전용."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, action_seq, raise_size FROM gto_preflop_situations "
            "WHERE action_seq IS NOT NULL"
        ).fetchall()
        out = {}
        for r in rows:
            hands = {}
            for h in conn.execute(
                "SELECT hand, freq_fold, freq_call, freq_raise, freq_allin "
                "FROM gto_preflop_hands WHERE situation_id=?", (r["id"],)
            ):
                fr = {}
                for col, act in (("freq_fold", "fold"), ("freq_call", "call"),
                                 ("freq_raise", "raise"), ("freq_allin", "allin")):
                    if (h[col] or 0) > 0:
                        fr[act] = h[col]
                hands[h["hand"]] = fr
            out[r["action_seq"]] = {"hands": hands, "raise_size": r["raise_size"]}
        return out
    finally:
        conn.close()


def _token_action(token: str, parent: dict) -> str:
    if token == "F":
        return "fold"
    if token in ("C", "X"):
        return "call"
    # 레이즈 토큰: 부모 노드의 실측 레이즈 사이즈와 같으면 raise, 아니면 allin
    try:
        size = float(token[1:])
    except ValueError:
        return "raise"
    rs = parent.get("raise_size")
    if rs is not None and abs(size - rs) < 1e-9:
        return "raise"
    return "allin"


def compute_reach(node_key: str, collected: dict):
    """루트부터 조상 노드의 콤보 가중 액션 빈도를 곱한 도달확률. 조상이 없으면 None."""
    tokens = split_key(node_key)
    reach = 1.0
    for i, tok in enumerate(tokens):
        parent = collected.get("-".join(tokens[:i]))
        if parent is None:
            return None
        agg = tw.aggregate_frequencies(parent["hands"])
        reach *= agg.get(_token_action(tok, parent), 0.0)
    return reach


def find_lost(ckpt: dict, collected: dict) -> list:
    """visited 중 결정 노드인데 DB·failed 어디에도 없는 키(정렬)."""
    failed = set(ckpt.get("failed", []))
    lost = []
    for key in ckpt.get("visited", []):
        if key in collected or key in failed:
            continue
        if derive_node_meta(key) is None:
            continue  # 베팅 종료 노드 — 수집 대상 아님(워커도 visited로만 둔다)
        lost.append(key)
    return sorted(lost)


def plan(ckpt: dict, collected: dict) -> list:
    """[(key, reach, reach_known, already_in_frontier)] — frontier에 되돌릴 항목."""
    in_frontier = {"-".join(f["tokens"]) for f in ckpt.get("frontier", [])}
    items = []
    for key in find_lost(ckpt, collected):
        reach = compute_reach(key, collected)
        items.append((key, 1.0 if reach is None else reach, reach is not None, key in in_frontier))
    return items


def apply(ckpt: dict, items: list) -> dict:
    lost = {k for k, _, _, _ in items}
    ckpt["visited"] = sorted(k for k in ckpt.get("visited", []) if k not in lost)
    frontier = list(ckpt.get("frontier", []))
    existing = {"-".join(f["tokens"]) for f in frontier}
    for key, reach, _, _ in items:
        if key not in existing:
            frontier.append({"tokens": split_key(key), "reach": reach})
    frontier.sort(key=lambda f: -f["reach"])
    ckpt["frontier"] = frontier
    return ckpt


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--checkpoint", default=str(DEFAULT_CHECKPOINT))
    ap.add_argument("--db", default=None, help="기본: EV_PLUS_DB → poker.db")
    ap.add_argument("--apply", action="store_true", help="체크포인트를 실제로 수정")
    args = ap.parse_args(argv)

    ckpt_path = Path(args.checkpoint)
    if not ckpt_path.exists():
        print(f"체크포인트 없음: {ckpt_path} — 되돌릴 것이 없습니다.")
        return 0
    ckpt = json.loads(ckpt_path.read_text())
    db_path = args.db or default_db_path()
    collected = load_collected(db_path)
    items = plan(ckpt, collected)

    print(f"DB: {db_path} (노드 {len(collected)}개) · 체크포인트: {ckpt_path}")
    print(f"visited {len(ckpt.get('visited', []))} / frontier {len(ckpt.get('frontier', []))} "
          f"/ failed {len(ckpt.get('failed', []))}")
    print(f"사라진 결정 노드(visited인데 DB·failed에 없음): {len(items)}개")
    for key, reach, known, already in items:
        meta = derive_node_meta(key)
        note = "" if known else " (조상 미수집 → reach 1.0)"
        dup = " [이미 frontier에 있음]" if already else ""
        print(f"  {key!r:40} {meta['situation_label']:<24} reach={reach:.5f}{note}{dup}")

    if not items:
        return 0
    if not args.apply:
        print("\n드라이런 — 바꾸지 않았습니다. 적용하려면 --apply")
        return 0
    apply(ckpt, items)
    tmp = ckpt_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(ckpt, ensure_ascii=False, indent=2))
    tmp.replace(ckpt_path)
    print(f"\n적용: visited에서 {len(items)}개 제거, frontier에 추가 → {ckpt_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
