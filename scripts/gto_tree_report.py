#!/usr/bin/env python3
"""
프리플랍 GTO 트리 수집 현황 리포트 생성기.

DB(gto_preflop_situations, 확정 수집)와 체크포인트(gto_tree_checkpoint.json, 발견됐지만
미수집인 frontier + 실패 기록)를 읽어 마크다운 리포트를 생성한다.

⚠️ "전체 대비 %"는 정의하지 않는다 — 데이터 기반 수집(docs/gto-preflop-tree.md) 원칙상
트리 전체 규모를 미리 알 수 없다(가정으로 열거하지 않음). 대신 "collected(확정 수집) /
frontier(발견됐지만 미수집) / failed(검증 실패 재시도 대상)" 3분류로 지금까지 안 상태만 보여준다.

사용:
    python3 scripts/gto_tree_report.py                       # docs/gto-preflop-progress.md 생성
    python3 scripts/gto_tree_report.py --out /path/to/x.md    # 다른 경로로 생성
"""
import argparse
import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from collect_gto_tree import (  # noqa: E402
    derive_node_meta, load_collected_from_db, Checkpoint,
    compute_children, ALLIN_FALLBACK_BB,
)
import gto_tree_worker as tw  # noqa: E402

DEFAULT_OUT = ROOT / "docs" / "gto-preflop-progress.md"
DEFAULT_CHECKPOINT = ROOT / "gto_tree_checkpoint.json"

POSITIONS = ["UTG", "HJ", "CO", "BTN", "SB", "BB"]


def node_key_str(tokens_or_key):
    """체크포인트는 토큰 리스트, DB는 '-' join 문자열 — 통일해서 '-'join 문자열로."""
    if isinstance(tokens_or_key, list):
        return "-".join(tokens_or_key)
    return tokens_or_key or ""


def depth_of(key: str) -> int:
    if key == "":
        return 0
    return len(key.split("-"))


def parent_of(key: str) -> str:
    if key == "":
        return None
    toks = key.split("-")
    return "-".join(toks[:-1])


def compute_reach_probs(collected_db: dict, epsilon: float = tw.EPSILON) -> dict:
    """루트("")부터 BFS로 collected 트리를 훑어 각 확정 수집 노드의 도달확률을 계산.

    collect_gto_tree.compute_children/seed_frontier_from_db와 동일한 전파 방식
    (부모 reach × branch_actions 빈도)을 재사용 — 로직 중복 없음. 루트가 없거나
    조상 체인이 끊긴 노드는 도달확률 미상(결과 dict에 키가 없음 → None으로 표시).
    """
    reach = {}
    if "" not in collected_db:
        return reach
    bfs = deque([("", 1.0)])
    seen = set()
    while bfs:
        key, r = bfs.popleft()
        if key in seen:
            continue
        seen.add(key)
        reach[key] = r
        node = collected_db.get(key)
        if node is None:
            continue
        size_map = {"raise": node["raise_size"], "allin": ALLIN_FALLBACK_BB}
        for child_key, _tokens, child_reach in compute_children(
            key, node["hands"], size_map, r, epsilon
        ):
            if child_key in collected_db:
                bfs.append((child_key, child_reach))
    return reach


def collect_data(checkpoint_path: Path):
    collected_db = load_collected_from_db()  # {action_seq: {...}}
    reach_probs = compute_reach_probs(collected_db)
    collected = {}
    for key, info in collected_db.items():
        if key is None:
            continue
        meta = derive_node_meta(key) or {}
        collected[key] = {
            "situation_label": meta.get("situation_label", "?"),
            "hero_position": meta.get("hero_position", "?"),
            "raise_size": info.get("raise_size"),
            "reach_prob": reach_probs.get(key),
        }

    frontier = {}
    failed = set()
    ckpt = Checkpoint(checkpoint_path)
    if ckpt.load():
        for tokens, reach in ckpt.frontier_items:
            key = node_key_str(tokens)
            if key in collected:
                continue
            meta = derive_node_meta(key) or {}
            frontier[key] = {
                "situation_label": meta.get("situation_label", "?"),
                "hero_position": meta.get("hero_position", "?"),
                "reach_prob": reach,
            }
        for key in ckpt.failed:
            if key not in collected:
                failed.add(key)

    return collected, frontier, failed


def build_mermaid(collected: dict, frontier: dict, failed: set) -> str:
    """알려진 노드(collected ∪ frontier ∪ failed) 전체를 부모-자식 관계로 트리 렌더."""
    all_keys = set(collected) | set(frontier) | set(failed)
    all_keys.add("")  # 루트

    # 조상 체인이 끊긴 노드(부모가 all_keys에 없는 경우) 대비: 부모 체인 전부 채워넣기
    expanded = set(all_keys)
    for key in list(all_keys):
        k = key
        while k:
            p = parent_of(k)
            expanded.add(p if p is not None else "")
            k = p if p else ""
    all_keys = expanded

    ids = {key: f"n{i}" for i, key in enumerate(sorted(all_keys, key=lambda k: (depth_of(k), k)))}

    lines = ["```mermaid", "graph TD"]

    def label_for(key: str) -> str:
        if key == "":
            root_reach = collected.get("", {}).get("reach_prob")
            reach_str = f" ({root_reach*100:.1f}%)" if root_reach is not None else ""
            return f"ROOT{reach_str}"
        reach = None
        if key in collected:
            lbl = collected[key]["situation_label"]
            reach = collected[key].get("reach_prob")
        elif key in frontier:
            lbl = frontier[key]["situation_label"]
            reach = frontier[key].get("reach_prob")
        else:
            meta = derive_node_meta(key)
            lbl = meta["situation_label"] if meta else key
        # mermaid 라벨에 특수문자(따옴표 등) 이스케이프
        lbl = lbl.replace('"', "'")
        reach_str = f" · 도달 {reach*100:.2f}%" if reach is not None else ""
        return f'{lbl}{reach_str}<br/><small>{key or "(root)"}</small>'

    for key in sorted(all_keys, key=lambda k: (depth_of(k), k)):
        nid = ids[key]
        lines.append(f'    {nid}["{label_for(key)}"]')

    for key in sorted(all_keys, key=lambda k: (depth_of(k), k)):
        if key == "":
            continue
        p = parent_of(key)
        p = p if p is not None else ""
        if p in ids:
            lines.append(f"    {ids[p]} --> {ids[key]}")

    lines.append("")
    for key in all_keys:
        nid = ids[key]
        if key in collected:
            lines.append(f"    class {nid} collected")
        elif key in failed:
            lines.append(f"    class {nid} failed")
        elif key in frontier:
            lines.append(f"    class {nid} frontier")
        else:
            lines.append(f"    class {nid} unknown")

    lines.append("    classDef collected fill:#22c55e,color:#052e16,stroke:#166534,stroke-width:1px;")
    lines.append("    classDef frontier fill:#fbbf24,color:#451a03,stroke:#92400e,stroke-width:1px;")
    lines.append("    classDef failed fill:#ef4444,color:#450a0a,stroke:#7f1d1d,stroke-width:1px;")
    lines.append("    classDef unknown fill:#e5e7eb,color:#374151,stroke:#9ca3af,stroke-dasharray: 3 3;")
    lines.append("```")
    return "\n".join(lines)


def build_report(collected: dict, frontier: dict, failed: set) -> str:
    total_c = len(collected)
    total_f = len(frontier)
    total_x = len(failed)

    by_pos = {p: 0 for p in POSITIONS}
    for info in collected.values():
        hp = info["hero_position"]
        if hp in by_pos:
            by_pos[hp] += 1

    by_depth = {}
    for key in collected:
        d = depth_of(key)
        by_depth[d] = by_depth.get(d, 0) + 1

    lines = []
    lines.append("# 프리플랍 GTO 트리 수집 현황")
    lines.append("")
    lines.append("자동 생성됨 — `python3 scripts/gto_tree_report.py`로 재생성.")
    lines.append("")
    lines.append("⚠️ **\"전체 대비 %\"는 정의하지 않음** — 데이터 기반 수집 원칙상 트리 전체")
    lines.append("규모를 미리 알 수 없다(`docs/gto-preflop-tree.md` 참고). 아래는 지금까지")
    lines.append("**확정 수집(collected) / 발견됐지만 미수집(frontier) / 검증 실패(failed)**")
    lines.append("3분류 현황이다.")
    lines.append("")
    lines.append("## 요약")
    lines.append("")
    lines.append(f"- ✅ **확정 수집**: {total_c}개")
    lines.append(f"- 🟡 **발견됨(미수집, 다음 후보)**: {total_f}개")
    lines.append(f"- 🔴 **검증 실패(재시도 대상)**: {total_x}개")
    lines.append("")
    lines.append("### 포지션별 확정 수집 (히어로 기준)")
    lines.append("")
    lines.append("| 포지션 | 수집 수 |")
    lines.append("|---|---|")
    for p in POSITIONS:
        lines.append(f"| {p} | {by_pos[p]} |")
    lines.append("")
    lines.append("### 깊이별 확정 수집 (액션 수 기준, 0=RFI)")
    lines.append("")
    lines.append("| 깊이(액션 수) | 수집 수 |")
    lines.append("|---|---|")
    for d in sorted(by_depth):
        lines.append(f"| {d} | {by_depth[d]} |")
    lines.append("")
    lines.append("## 트리 다이어그램")
    lines.append("")
    lines.append("초록=확정 수집 · 노랑=발견됨(미수집) · 빨강=검증 실패 · 회색 점선=조상 경로(자체는 미방문)")
    lines.append("")
    lines.append(build_mermaid(collected, frontier, failed))
    lines.append("")
    lines.append("## 확정 수집 스팟 목록 (도달확률 내림차순)")
    lines.append("")
    lines.append("도달확률 = 루트부터 이 노드까지 오는 실전 빈도의 누적곱(콤보가중, "
                 "부모 도달확률 × 이 노드로 이어지는 액션 빈도). 조상 체인이 끊겨")
    lines.append("계산 불가하면 `?`로 표시.")
    lines.append("")
    lines.append("| action_seq | 상황 | 히어로 | raise_size | 도달확률 |")
    lines.append("|---|---|---|---|---|")

    def reach_sort_key(k):
        r = collected[k].get("reach_prob")
        return -(r if r is not None else -1)  # None(미상)은 맨 뒤로

    for key in sorted(collected, key=reach_sort_key):
        info = collected[key]
        r = info.get("reach_prob")
        r_str = f"{r*100:.3f}%" if r is not None else "?"
        lines.append(f"| `{key or '(root)'}` | {info['situation_label']} | "
                     f"{info['hero_position']} | {info['raise_size']} | {r_str} |")
    lines.append("")
    if frontier:
        lines.append("## 다음 수집 후보 (도달확률 내림차순, frontier)")
        lines.append("")
        lines.append("| action_seq | 상황 | 히어로 | 도달확률 |")
        lines.append("|---|---|---|---|")
        for key, info in sorted(frontier.items(), key=lambda kv: -kv[1]["reach_prob"]):
            lines.append(f"| `{key}` | {info['situation_label']} | "
                         f"{info['hero_position']} | {info['reach_prob']:.4f} |")
        lines.append("")
    if failed:
        lines.append("## 검증 실패 (재시도 대상)")
        lines.append("")
        for key in sorted(failed):
            lines.append(f"- `{key}`")
        lines.append("")

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="프리플랍 GTO 트리 수집 현황 리포트 생성")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="출력 마크다운 경로")
    ap.add_argument("--checkpoint", default=str(DEFAULT_CHECKPOINT), help="체크포인트 JSON 경로")
    args = ap.parse_args()

    collected, frontier, failed = collect_data(Path(args.checkpoint))
    report = build_report(collected, frontier, failed)

    out_path = Path(args.out)
    out_path.write_text(report, encoding="utf-8")
    print(f"[생성 완료] {out_path}")
    print(f"  확정 수집: {len(collected)}개 / 발견됨(미수집): {len(frontier)}개 / 검증 실패: {len(failed)}개")


if __name__ == "__main__":
    main()
