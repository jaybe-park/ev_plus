#!/usr/bin/env python3
"""
gto_preflop_situations / gto_preflop_hands 전수 검사 스크립트.

검사 항목:
1. 핸드별 빈도 합이 [0.9, 1.1] 범위 안인지 (로더 방어와 별개로 원본 DB 자체 검증)
2. 같은 range_type(open) 내에서 포지션 간 오픈 비율이 상식적인 순서인지
   (RFI: UTG < HJ < CO < BTN < SB 넓어지는 방향, 역전되면 의심)
3. 특정 액션이 부자연스럽게 100%/0%로 쏠린 스팟이 있는지
   (한 situation의 169핸드 전부가 fold=100%이거나, 전부 raise=100%인 경우 등)

결과를 사람이 읽을 수 있는 리포트로 출력한다. TODO.md "HJ RFI 데이터 오염 확인 +
전체 프리플랍 GTO 스팟 전수 검사" 항목 참고.
"""
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "poker.db"

POSITIONS = ["UTG", "HJ", "CO", "BTN", "SB", "BB"]
POS_INDEX = {p: i for i, p in enumerate(POSITIONS)}


def main():
    conn = sqlite3.connect(DB_PATH)
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

    # --- 리포트 출력 ---
    print("=" * 70)
    print("gto_preflop_situations 전수 검사 리포트")
    print("=" * 70)
    print(f"총 situations: {len(situations)}")
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

    total_bad = len(problems) + len(order_problems)
    print(f"검사 결과: {'통과' if total_bad == 0 else f'{total_bad}건 이상 발견'}")
    return 0 if total_bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
