#!/usr/bin/env python3
"""
봇 파라미터 자동 튜닝 — 아레나 A/B 대전으로 프로파일 수치 최적화

두 모드:
  [그리드]  후보값들을 같은 테이블에 앉혀 직접 대전
    python3 scripts/tune_bot.py --profile hard --param aggression_margin \\
        --values 0.04,0.08,0.12 --hands 2000 --seeds 3

  [진화]    현재값 ± step 3방향 대전 → 승자가 중심이 되어 반복 (hill-climb)
    python3 scripts/tune_bot.py --profile hard --param semibluff_freq \\
        --evolve --start 0.55 --step 0.1 --rounds 5 --hands 1500

결과는 tuning_results.json에 누적 저장 (봇 코드는 자동 수정하지 않음 —
결과를 보고 ai/bot.py의 POSTFLOP_PROFILES를 직접 갱신할 것).

분산 주의: 포커는 노이즈가 커서 핸드 수가 적으면 결과가 뒤집힌다.
값 차이가 bb/100 오차범위(±10~20) 안이면 "차이 없음"으로 해석할 것.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.bot_arena import run_arena

RESULTS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tuning_results.json")


def duel(profile: str, param: str, values: list, hands: int, seeds: list) -> dict:
    """후보값들을 좌석 배분해 대전. 반환: {값: bb/100 평균}"""
    # 좌석 배분: 후보 2개 → 3+3, 3개 → 2+2+2 (6좌석 채움)
    per = max(1, 6 // len(values))
    seats = []
    for v in values:
        seats += [f"{profile}:{param}={v}"] * per
    seats = seats[:6]

    totals = {str(v): 0.0 for v in values}
    counts = {str(v): 0 for v in values}
    for seed in seeds:
        profit, seat_profile = run_arena(seats, hands, big_blind=20, seed=seed)
        for name, chips in profit.items():
            val = seat_profile[name].split("=")[-1]
            totals[val] += chips
            counts[val] += 1
        print(f"  seed={seed} 완료")

    bb100 = {}
    for v in totals:
        n_seat_hands = counts[v] * hands
        bb100[v] = round(totals[v] / 20 / n_seat_hands * 100, 1)
    return bb100


def save_result(entry: dict):
    history = []
    if os.path.exists(RESULTS_FILE):
        history = json.load(open(RESULTS_FILE))
    history.append(entry)
    json.dump(history, open(RESULTS_FILE, "w"), indent=2, ensure_ascii=False)


def main():
    p = argparse.ArgumentParser(description="봇 파라미터 튜닝")
    p.add_argument("--profile", default="hard", choices=["easy", "medium", "hard"])
    p.add_argument("--param", required=True,
                   help="POSTFLOP_PROFILES 키 (aggression_margin, semibluff_freq 등)")
    p.add_argument("--values", type=str, help="[그리드] 쉼표 구분 후보값")
    p.add_argument("--evolve", action="store_true", help="[진화] hill-climb 모드")
    p.add_argument("--start", type=float, help="[진화] 시작값")
    p.add_argument("--step", type=float, default=0.02, help="[진화] 탐색 폭")
    p.add_argument("--rounds", type=int, default=5, help="[진화] 반복 횟수")
    p.add_argument("--hands", type=int, default=1500)
    p.add_argument("--seeds", type=int, default=2, help="시드 수 (분산 완화)")
    args = p.parse_args()

    seeds = list(range(101, 101 + args.seeds))
    t0 = time.time()

    if args.evolve:
        if args.start is None:
            sys.exit("--evolve에는 --start가 필요")
        center, step = args.start, args.step
        trail = []
        for r in range(1, args.rounds + 1):
            cands = sorted({round(center - step, 4), round(center, 4),
                            round(center + step, 4)})
            cands = [max(0.0, c) for c in cands]
            print(f"\n[라운드 {r}/{args.rounds}] {args.param} 후보: {cands}")
            bb100 = duel(args.profile, args.param, cands, args.hands, seeds)
            winner = max(bb100, key=bb100.get)
            print(f"  결과: {bb100} → 승자 {winner}")
            trail.append({"round": r, "candidates": bb100, "winner": winner})
            if float(winner) == center:
                step = round(step / 2, 4)  # 중심 유지 → 탐색 폭 축소
            center = float(winner)
        result = {"mode": "evolve", "final": center, "trail": trail}
        print(f"\n🏁 최종 추천값: {args.param} = {center}")
    else:
        if not args.values:
            sys.exit("--values 또는 --evolve 필요")
        values = [float(v) for v in args.values.split(",")]
        bb100 = duel(args.profile, args.param, values, args.hands, seeds)
        result = {"mode": "grid", "bb100": bb100}
        print(f"\n🏁 결과 (bb/100): {bb100}")
        print(f"   최고: {args.param} = {max(bb100, key=bb100.get)}")

    save_result({
        "at": datetime.now().isoformat(timespec="seconds"),
        "profile": args.profile, "param": args.param,
        "hands": args.hands, "seeds": seeds,
        "elapsed_sec": round(time.time() - t0),
        **result,
    })
    print(f"   기록: {RESULTS_FILE}")


if __name__ == "__main__":
    main()
