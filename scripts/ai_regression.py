#!/usr/bin/env python3
"""
AI 회귀 테스트 — 봇 로직 변경 후 실력이 후퇴하지 않았는지 검증

고정 벤치마크: hard/medium 3좌석 vs legacy(개선 전 봇) 3좌석,
고정 시드 2개 × N핸드. 신버전 평균이 legacy 평균보다 나쁘면 FAIL(exit 1).

사용법:
  python3 scripts/ai_regression.py              # 기본 400핸드 × 2시드 (~2분)
  python3 scripts/ai_regression.py --hands 1000 # 더 정밀하게

기준 (2026-06 측정): hard/medium 평균 +19, legacy -19 bb/100.
차이가 +0 미만이면 회귀, 0~+15면 분산 가능성 경고.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.bot_arena import run_arena

SEATS = ["hard", "medium", "legacy", "legacy", "medium", "legacy"]
SEEDS = [99, 777]


def main():
    p = argparse.ArgumentParser(description="AI 회귀 테스트")
    p.add_argument("--hands", type=int, default=400)
    args = p.parse_args()

    new_chips, legacy_chips = [], []
    for seed in SEEDS:
        print(f"벤치마크 실행: seed={seed}, {args.hands}핸드 ...")
        profit, seat_profile = run_arena(SEATS, args.hands, big_blind=20, seed=seed)
        for name, chips in profit.items():
            (legacy_chips if seat_profile[name] == "legacy"
             else new_chips).append(chips)

    total_hands = args.hands * len(SEEDS)
    new_bb = sum(new_chips) / len(new_chips) / 20 / total_hands * 100 * len(SEEDS)
    leg_bb = sum(legacy_chips) / len(legacy_chips) / 20 / total_hands * 100 * len(SEEDS)
    diff = new_bb - leg_bb

    print(f"\n{'='*48}")
    print(f"  신버전(hard/medium) 평균: {new_bb:+7.1f} bb/100")
    print(f"  legacy 평균:             {leg_bb:+7.1f} bb/100")
    print(f"  차이:                    {diff:+7.1f} bb/100")
    print(f"{'='*48}")

    if diff <= 0:
        print("❌ FAIL — 신버전이 legacy보다 약함. 최근 변경을 재검토할 것.")
        sys.exit(1)
    elif diff < 15:
        print("⚠️  PASS(경고) — 우위가 작음. 분산일 수 있으니 --hands 늘려 재확인 권장.")
    else:
        print("✅ PASS — 신버전 우위 유지.")


if __name__ == "__main__":
    main()
