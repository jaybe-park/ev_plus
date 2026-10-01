#!/usr/bin/env python3
"""
프리플랍 vs 랜덤 핸드 에퀴티 상수 테이블 재생성 (ADR 0034)

현재 엔진(`ai.equity.mc_counts`, 동률 지분 1/k)으로 169핸드 × 상대 1~5명 = 845값을
값마다 고정 MC N샘플(기본 1,000,000)로 계산해 `ai/preflop_equity_table.py`를 다시 쓴다.
DB를 읽거나 쓰지 않는다. 전체 실행은 CPU 코어 수에 따라 1~2시간 — 사람이 돌린다.

사용법:
  python3 scripts/gen_preflop_table.py --dry-run                 # 소수 값만 기존 테이블과 3σ 비교 출력
  python3 scripts/gen_preflop_table.py --dry-run --hands AA 72o 52o --samples 50000
  python3 scripts/gen_preflop_table.py                           # 845값 재생성 → 테이블 파일 덮어쓰기

  --samples  값마다 MC 샘플 수 (기본: 전체 1,000,000 / dry-run 20,000)
  --hands    dry-run에서 비교할 표기 (기본 AA AKs 72o 52o, 상대 1~5명 각각)
  --workers  프로세스 수 (기본 CPU 수)
  --out      출력 모듈 경로 (기본 ai/preflop_equity_table.py)
  --seed     난수 시드 (값마다 seed + 순번)
"""

import argparse
import math
import os
import random
import sys
import time
from multiprocessing import get_context

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.card import Card, Suit, Rank  # noqa: E402
from ai.equity import mc_counts, _ratio  # noqa: E402

DEFAULT_OUT = os.path.join(ROOT, "ai", "preflop_equity_table.py")
_ORDER = "23456789TJQKA"
_RANK = {r.symbol if r.symbol != "10" else "T": r for r in Rank}
_DRY_HANDS = ("AA", "AKs", "72o", "52o")


def all_notations() -> list:
    """169 표기, 테이블 정렬 순서(높은 랭크 → 페어·수티드·오프수트 → 낮은 키커)."""
    notes = []
    for i in range(12, -1, -1):
        for j in range(i, -1, -1):
            hi, lo = _ORDER[i], _ORDER[j]
            if i == j:
                notes.append(hi + lo)
            else:
                notes.append(hi + lo + "s")
                notes.append(hi + lo + "o")

    def key(note):
        hi, lo = _ORDER.index(note[0]), _ORDER.index(note[1])
        kind = 0 if hi == lo else (1 if note.endswith("s") else 2)
        return (-hi, kind, -lo)

    return sorted(notes, key=key)


def rep_hole(note: str) -> list:
    """표기의 대표 홀카드 2장 (수트 치환에 대해 에퀴티가 같다)."""
    hi, lo = _RANK[note[0]], _RANK[note[1]]
    if len(note) == 3 and note[2] == "s":
        return [Card(hi, Suit.SPADES), Card(lo, Suit.SPADES)]
    return [Card(hi, Suit.SPADES), Card(lo, Suit.HEARTS)]


def _job(args):
    note, n_opp, samples, seed = args
    random.seed(seed)
    w, t, n = mc_counts(rep_hole(note), [], n_opp, samples)
    return note, n_opp, _ratio(w, t, n)


def compute(jobs, workers: int):
    with get_context("spawn").Pool(workers) as pool:
        return pool.map(_job, jobs, chunksize=1)


def render(table: dict, samples: int) -> str:
    lines = [
        '"""',
        "프리플랍 vs 랜덤 핸드 에퀴티 상수 테이블 — 자동 생성, 수동 편집 금지",
        "",
        "생성: python3 scripts/gen_preflop_table.py (현재 엔진 ai.equity.mc_counts, 동률 지분 1/k)",
        f"샘플: 값마다 {samples:,}회 고정 MC (표준오차 ≤ {50 / math.sqrt(samples):.2f}%p)",
        "",
        "PREFLOP_EQUITY[표기] = (vs1, vs2, vs3, vs4, vs5) — 표기는 'AA'/'AKs'/'AKo'.",
        '"""',
        "",
        f"PREFLOP_SAMPLES = {samples}",
        "",
        "PREFLOP_EQUITY = {",
    ]
    for note in all_notations():
        vals = ", ".join(f"{table[(note, k)]:.6f}" for k in range(1, 6))
        lines.append(f'    "{note}": ({vals}),')
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def dry_run(hands, samples: int, workers: int, seed: int) -> None:
    from ai.preflop_equity_table import PREFLOP_EQUITY, PREFLOP_SAMPLES
    jobs = [(h, k, samples, seed + i) for i, (h, k) in
            enumerate((h, k) for h in hands for k in range(1, 6))]
    t0 = time.perf_counter()
    res = compute(jobs, workers)
    print(f"[dry-run] 기존 테이블 vs 현재 엔진 MC {samples:,}샘플 — 파일을 쓰지 않음")
    print(f"{'표기':5s} {'vs':>2s} {'테이블':>8s} {'현재MC':>8s} {'차이%p':>7s} {'z':>6s}")
    over = 0
    for note, n_opp, est in res:
        tab = PREFLOP_EQUITY[note][n_opp - 1]
        # 지분 분산 ≤ 0.25 상한으로 두 추정의 표준오차를 합친다
        se = math.sqrt(0.25 / samples + 0.25 / PREFLOP_SAMPLES)
        z = (est - tab) / se
        flag = "  <-- >3σ" if abs(z) > 3 else ""
        over += abs(z) > 3
        print(f"{note:5s} {n_opp:2d} {tab:8.4f} {est:8.4f} {(est - tab) * 100:+7.3f} {z:+6.2f}{flag}")
    print(f"{len(res)}값, >3σ {over}개, {time.perf_counter() - t0:.1f}s")


def main():
    ap = argparse.ArgumentParser(description="프리플랍 에퀴티 845값 상수 테이블 재생성")
    ap.add_argument("--dry-run", action="store_true", help="소수 값만 기존 테이블과 비교, 파일 쓰기 없음")
    ap.add_argument("--samples", type=int, default=None)
    ap.add_argument("--hands", nargs="+", default=list(_DRY_HANDS))
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()

    valid = set(all_notations())
    bad = [h for h in args.hands if h not in valid]
    if bad:
        print(f"알 수 없는 표기: {bad}")
        sys.exit(1)

    if args.dry_run:
        dry_run(args.hands, args.samples or 20_000, args.workers, args.seed)
        return

    samples = args.samples or 1_000_000
    jobs = [(note, k, samples, args.seed + i) for i, (note, k) in
            enumerate((n, k) for n in all_notations() for k in range(1, 6))]
    print(f"845값 × {samples:,}샘플, 프로세스 {args.workers}개 — 시작")
    t0 = time.perf_counter()
    res = compute(jobs, args.workers)
    table = {(note, k): v for note, k, v in res}
    if len(table) != 845:
        print(f"845값이 아님: {len(table)}")
        sys.exit(1)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(render(table, samples))
    print(f"저장: {args.out} ({time.perf_counter() - t0:.0f}s)")


if __name__ == "__main__":
    main()
