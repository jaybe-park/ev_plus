#!/usr/bin/env python3
"""
확률 검증 장치 — 에퀴티 숫자가 맞는지 외부 기준·독립 구현과 대조한다 (`--full` 전용).

- [V-1] 공개 프리플랍 기준값 23개 ±0.3%p (상수 테이블 경로)
- [V-2] 독립 평가기(`tests/indep_eval.py`, 프로젝트 import 없음) ↔ `evaluate_rank`·`HandEvaluator`
        랜덤 7장 5,000핸드 동일, 리버 1:1 전수 20스팟 동일
- [V-3] 레인지 결합 샘플러 ↔ 독립 전수 3케이스(가중치·블로커 교차·랜덤 상대 혼합, 리버) 3σ
- [V-4] 적응형 MC 정밀도 회귀: 고정 시드 턴 10스팟 × 10회, 전수 대비 rmse ≤ 1.3%p, ±2%p 안 ≥ 93%
- [V-5] 응답 시간 상한: 패널 1회(상대 2명 플랍) 중앙값 < 150ms, hard 봇 판단(플랍 vs2) 중앙값 < 60ms

`tests/run_all.py --full`에서만 돈다(FULL_FILES). 실행: python3 tests/test_equity_verify.py
"""

import math
import os
import random
import statistics
import sys
import tempfile
import time

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))
sys.path.insert(0, TESTS_DIR)

# 패널 측정이 세션을 만들므로 운영 poker.db 대신 임시 DB를 쓰게 한다
os.environ["EV_PLUS_DB"] = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name

import indep_eval as ie  # noqa: E402
from core.card import Card, Suit, Rank  # noqa: E402
from core.evaluator import HandEvaluator, evaluate_rank  # noqa: E402
from ai.equity import (  # noqa: E402
    equity_detail, exact_counts_river, exact_counts_turn, ranged_equity, RangeSampler, _ratio,
)

PASS = 0
FAIL = 0

# indep_eval 정수 카드 → 프로젝트 Card (수트 순서 s·h·d·c = indep_eval.SUIT_CHARS)
_SUITS = [Suit.SPADES, Suit.HEARTS, Suit.DIAMONDS, Suit.CLUBS]
_RANKS = {r.rank_value: r for r in Rank}


def to_card(c: int) -> Card:
    return Card(_RANKS[ie.RANK_OF[c]], _SUITS[ie.SUIT_OF[c]])


def cards(*specs) -> list:
    return [to_card(ie.parse(s)) for s in specs]


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}", flush=True)
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}", flush=True)


# 공개된 홀덤 프리플랍 vs 랜덤 핸드 에퀴티(%, 동률 지분 1/k). (표기, 상대 수, 값)
REFERENCE = [
    ("AA", 1, 85.2), ("KK", 1, 82.4), ("QQ", 1, 79.9), ("JJ", 1, 77.5), ("TT", 1, 75.1),
    ("99", 1, 72.1), ("88", 1, 69.2), ("77", 1, 66.2), ("66", 1, 63.3), ("55", 1, 60.3),
    ("44", 1, 57.0), ("33", 1, 53.7), ("22", 1, 50.3),
    ("AKs", 1, 67.0), ("AKo", 1, 65.3), ("AQs", 1, 66.2), ("AQo", 1, 64.4), ("AJs", 1, 65.4),
    ("KQs", 1, 63.4), ("72o", 1, 34.6), ("32o", 1, 32.3),
    ("AA", 2, 73.4), ("AA", 5, 49.3),
]
REFERENCE_TOL = 0.003


def _rep_hole(note: str) -> list:
    if len(note) == 2:
        return cards(note[0] + "s", note[1] + "h")
    if note[2] == "s":
        return cards(note[0] + "s", note[1] + "s")
    return cards(note[0] + "s", note[1] + "h")


def test_reference_values():
    print(f"\n[V-1] 공개 프리플랍 기준값 {len(REFERENCE)}개 ±0.3%p")
    for note, n_opp, pct in REFERENCE:
        r = equity_detail(_rep_hole(note), [], n_opp)
        check(f"{note} vs{n_opp} 테이블 {r.equity * 100:.2f}% ≈ 공개값 {pct}%",
              r.source == "preflop-table" and abs(r.equity - pct / 100) <= REFERENCE_TOL,
              f"={r}")


def test_indep_evaluator():
    print("\n[V-2] 독립 평가기 대조 — 랜덤 7장 5,000핸드 + 리버 1:1 전수 20스팟")
    t0 = time.perf_counter()
    rng = random.Random(123)
    mism_fast = mism_slow = 0
    for _ in range(5000):
        ints = rng.sample(ie.DECK, 7)
        hand = [to_card(c) for c in ints]
        mine = ie.rank7(ints)
        if evaluate_rank(hand) != mine:
            mism_fast += 1
        slow = HandEvaluator.evaluate(hand)
        if (slow.hand_rank.rank_value, tuple(slow.tiebreakers)) != mine:
            mism_slow += 1
    check("evaluate_rank = 독립 평가기 (5,000핸드)", mism_fast == 0, f"불일치={mism_fast}")
    check("HandEvaluator = 독립 평가기 (5,000핸드)", mism_slow == 0, f"불일치={mism_slow}")
    # 경계 핸드: 휠, 스틸 휠, 보드 로열, 트립스 두 개 풀하우스
    for specs, expect in ((("As", "2d", "3c", "4h", "5s", "Kd", "Qh"), (5, (5,))),
                          (("As", "2s", "3s", "4s", "5s", "Kd", "Qh"), (9, (5,))),
                          (("As", "Ks", "Qs", "Js", "Ts", "2d", "7c"), (10, (14,))),
                          (("9h", "9d", "9c", "5h", "5d", "5c", "2s"), (7, (9, 5)))):
        got_i = ie.rank7([ie.parse(s) for s in specs])
        got_p = evaluate_rank(cards(*specs))
        check(f"{' '.join(specs)} → {expect}", got_i == expect and got_p == expect,
              f"독립={got_i}, 프로젝트={got_p}")
    t_eval = time.perf_counter() - t0

    t1 = time.perf_counter()
    rng = random.Random(456)
    mism = 0
    for _ in range(20):
        ints = rng.sample(ie.DECK, 7)
        hole, board = ints[:2], ints[2:]
        truth, n_i = ie.exact_river_1(hole, board)
        w, t, n = exact_counts_river([to_card(c) for c in hole], [to_card(c) for c in board])
        if n != n_i or abs(_ratio(w, t, n) - truth) > 1e-12:
            mism += 1
    check("exact_counts_river = 독립 전수 (20스팟)", mism == 0, f"불일치={mism}")
    print(f"  (평가기 {t_eval:.2f}s, 리버 전수 {time.perf_counter() - t1:.2f}s)")


SAMPLER_CASES = [
    ("가중치", ("Js", "Jh"), ("2c", "3d", "4h", "Ks", "9c"),
     [{"AA": 0.2, "55": 1}, {"AA": 1, "66": 0.3}], 0),
    # 내 홀·보드가 레인지 콤보를 막고(ATs는 As Ts 1콤보만), 두 상대 레인지가 A 카드를 서로 다툰다
    ("블로커 교차", ("Ah", "Td"), ("Ac", "8s", "4d", "2h", "Tc"),
     [{"AKo": 0.5, "ATs": 1, "88": 0.3}, {"AQo": 1, "KTs": 1, "T8s": 0.4}], 0),
    ("랜덤 상대 혼합", ("Ah", "Ad"), ("Ks", "7c", "2d", "9h", "3s"),
     [{"KK": 1, "QQ": 1}], 1),
]


def test_ranged_sampler_exact():
    print("\n[V-3] 레인지 결합 샘플러 ↔ 독립 전수 (리버 3케이스, 고정 MC 20,000샘플, 3σ)")
    random.seed(5)
    n = 20_000
    for label, hole_s, board_s, ranges, n_random in SAMPLER_CASES:
        truth = ie.exact_ranged([ie.parse(s) for s in hole_s], [ie.parse(s) for s in board_s],
                                ranges, n_random)
        samplers = [RangeSampler(r) for r in ranges] + [None] * n_random
        est = ranged_equity(cards(*hole_s), cards(*board_s), samplers, n)
        se = math.sqrt(max(truth * (1 - truth), 1e-6) / n)
        check(f"{label}: 전수 {truth:.4f}, 추정 {est:.4f} (3σ={3 * se:.4f})",
              abs(est - truth) <= 3 * se, f"z={(est - truth) / se:+.2f}")


def test_precision_regression():
    print("\n[V-4] 적응형 MC 정밀도 회귀 — 턴 1:1 10스팟 × 10회 vs 전수 (ADR 0045)")
    rng = random.Random(2026)
    full = [Card(r, s) for r in Rank for s in Suit]
    random.seed(41)
    errs = []
    for _ in range(10):
        cs = rng.sample(full, 6)
        hole, board = cs[:2], cs[2:]
        truth = _ratio(*exact_counts_turn(hole, board))
        for _ in range(10):
            errs.append(equity_detail(hole, board, 1).equity - truth)
    rmse = math.sqrt(statistics.fmean(e * e for e in errs))
    within = sum(1 for e in errs if abs(e) <= 0.02) / len(errs)
    check(f"rmse {rmse * 100:.2f}%p ≤ 1.3%p", rmse <= 0.013, f"={rmse:.4f}")
    check(f"±2%p 안 {within:.0%} ≥ 93%", within >= 0.93, f"={within:.2f}")


def _median_ms(fn, reps: int) -> tuple:
    ts = []
    for _ in range(reps):
        ts.append(fn())
    return statistics.median(ts), max(ts)


def test_response_time():
    print("\n[V-5] 응답 시간 상한 (중앙값, 반복 9회)")
    from server.session import WebGameSession
    from core.game import Street
    from core.player import Player
    from ai.bot import PokerBot, BotDifficulty
    full = [Card(r, s) for r in Rank for s in Suit]
    random.seed(7)

    def panel_once() -> float:
        s = WebGameSession(session_id="verify", human_name="Hero", chips=2000,
                           num_bots=2, difficulty="easy", small_blind=10)
        for p in s.game.players:
            p.is_folded = False
        cs = random.sample(full, 5)
        s.human.hole_cards = cs[:2]
        s.game.community_cards = cs[2:]
        s.game.current_street = Street.FLOP
        s.action_log = []
        s._equity_cache = {}
        t0 = time.perf_counter()
        s._get_equity_info()
        return (time.perf_counter() - t0) * 1000

    med, mx = _median_ms(panel_once, 9)
    check(f"패널 1회 상대 2명 플랍 {med:.1f}ms < 150ms (최대 {mx:.1f}ms)", med < 150, f"={med:.1f}")

    def bot_once() -> float:
        cs = random.sample(full, 5)
        p = Player("Bot", chips=1000, is_human=False)
        p.hole_cards = cs[:2]
        bot = PokerBot(p, BotDifficulty.HARD)
        players = [{"name": "Bot", "chips": 1000, "current_bet": 0,
                    "is_folded": False, "is_all_in": False, "is_human": False}]
        positions = {"Bot": "BTN"}
        for i in range(2):
            players.append({"name": f"V{i}", "chips": 1000, "current_bet": 50,
                            "is_folded": False, "is_all_in": False, "is_human": True})
            positions[f"V{i}"] = ["BB", "SB"][i]
        st = {"street": "플랍", "pot": 200, "current_bet": 50, "min_raise": 20,
              "big_blind": 20, "community_cards": [str(c) for c in cs[2:]],
              "positions": positions, "players": players, "action_log": []}
        t0 = time.perf_counter()
        bot.decide_action(st)
        return (time.perf_counter() - t0) * 1000

    med, mx = _median_ms(bot_once, 9)
    check(f"hard 봇 판단 1회 플랍 vs2 {med:.1f}ms < 60ms (최대 {mx:.1f}ms)", med < 60, f"={med:.1f}")


if __name__ == "__main__":
    print("=" * 50)
    print("  확률 검증 장치 (--full)")
    print("=" * 50)
    t_start = time.perf_counter()
    test_reference_values()
    test_indep_evaluator()
    test_ranged_sampler_exact()
    test_precision_regression()
    test_response_time()
    print(f"\n{'=' * 50}")
    print(f"  결과: {PASS} 통과 / {FAIL} 실패 ({time.perf_counter() - t_start:.1f}s)")
    print(f"{'=' * 50}")
    sys.exit(1 if FAIL else 0)
