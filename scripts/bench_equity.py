#!/usr/bin/env python3
"""
에퀴티 실시간 경로 응답 시간 측정 (ADR 0034, T-036)

캐시 없이 매번 계산하므로 "봇 판단·패널이 체감상 그대로인가"를 이 스크립트로 잰다.
DB에 쓰지 않는다(패널 측정은 EV_PLUS_DB를 임시 파일로 격리한 세션을 쓴다).

사용법:
  python3 scripts/bench_equity.py            # 기본 반복 20회
  python3 scripts/bench_equity.py --reps 50
"""

import argparse
import os
import random
import statistics
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["EV_PLUS_DB"] = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name

from core.card import Card, Suit, Rank  # noqa: E402
from ai.equity import equity_detail  # noqa: E402

_FULL = [Card(r, s) for r in Rank for s in Suit]


def _spot(board_len: int):
    cards = random.sample(_FULL, 2 + board_len)
    return cards[:2], cards[2:]


def _ms(fn, reps: int):
    ts, extra = [], []
    for _ in range(reps):
        t0 = time.perf_counter()
        r = fn()
        ts.append((time.perf_counter() - t0) * 1000)
        extra.append(r)
    ts.sort()
    return statistics.median(ts), ts[int(len(ts) * 0.9) - 1] if len(ts) >= 10 else ts[-1], ts[-1], extra


def bench_equity(reps: int):
    print("\n[smart_equity/equity_detail] 랜덤 스팟, ms (중앙 / p90 / 최대), 평균 샘플 수")
    for street, blen in (("preflop", 0), ("flop", 3), ("turn", 4), ("river", 5)):
        for n_opp in (1, 2, 5):
            spots = [_spot(blen) for _ in range(reps)]
            it = iter(spots)
            med, p90, mx, res = _ms(lambda: equity_detail(*next(it), n_opp), reps)
            avg_n = statistics.mean(r.samples for r in res)
            print(f"  {street:7s} vs{n_opp}: {med:7.1f} / {p90:7.1f} / {mx:7.1f}  "
                  f"경로={res[0].source.split(':')[0]}  샘플≈{avg_n:,.0f}")


def bench_bot(reps: int):
    from core.player import Player
    from ai.bot import PokerBot, BotDifficulty
    print("\n[봇 포스트플랍 판단 1회] 랜덤 스팟, 헤즈업/3인, ms (중앙 / p90 / 최대)")
    for diff in (BotDifficulty.EASY, BotDifficulty.MEDIUM, BotDifficulty.HARD):
        for n_opp in (1, 2):
            for street, blen in (("플랍", 3), ("리버", 5)):
                def one():
                    hole, board = _spot(blen)
                    p = Player("Bot", chips=1000, is_human=False)
                    p.hole_cards = hole
                    bot = PokerBot(p, diff)
                    players = [{"name": "Bot", "chips": 1000, "current_bet": 0,
                                "is_folded": False, "is_all_in": False, "is_human": False}]
                    positions = {"Bot": "BTN"}
                    for i in range(n_opp):
                        players.append({"name": f"V{i}", "chips": 1000, "current_bet": 50,
                                        "is_folded": False, "is_all_in": False, "is_human": True})
                        positions[f"V{i}"] = ["BB", "SB"][i % 2]
                    st = {"street": street, "pot": 200, "current_bet": 50, "min_raise": 20,
                          "big_blind": 20, "community_cards": [str(c) for c in board],
                          "positions": positions, "players": players, "action_log": []}
                    return bot.decide_action(st)
                med, p90, mx, _ = _ms(one, reps)
                print(f"  {diff.value:6s} vs{n_opp} {street}: {med:7.1f} / {p90:7.1f} / {mx:7.1f}")


def bench_panel(reps: int):
    from server.session import WebGameSession
    from core.game import Street
    print("\n[에퀴티 패널 _get_equity_info 1회] 랜덤 스팟, 레인지 정보 없음, ms (중앙 / p90 / 최대)")
    streets = ((Street.PREFLOP, 0), (Street.FLOP, 3), (Street.TURN, 4), (Street.RIVER, 5))
    for num_bots in (1, 2, 5):
        for st, blen in streets:
            def one():
                s = WebGameSession(session_id="bench", human_name="Hero", chips=2000,
                                   num_bots=num_bots, difficulty="easy", small_blind=10)
                for p in s.game.players:
                    p.is_folded = False
                hole, board = _spot(blen)
                s.human.hole_cards = hole
                s.game.community_cards = board
                s.game.current_street = st
                s.action_log = []
                s._equity_cache = {}
                t0 = time.perf_counter()
                info = s._get_equity_info()
                return (time.perf_counter() - t0) * 1000, info["source"]
            ts = sorted(one()[0] for _ in range(reps))
            print(f"  상대 {num_bots}명 {st.name:8s}: {statistics.median(ts):7.1f} / "
                  f"{ts[int(len(ts) * 0.9) - 1] if len(ts) >= 10 else ts[-1]:7.1f} / {ts[-1]:7.1f}")


def main():
    ap = argparse.ArgumentParser(description="에퀴티 실시간 경로 응답 시간 측정")
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    random.seed(args.seed)
    print(f"python {sys.version.split()[0]} ({sys.implementation.name}), 반복 {args.reps}회")
    bench_equity(args.reps)
    bench_bot(args.reps)
    bench_panel(args.reps)


if __name__ == "__main__":
    main()
