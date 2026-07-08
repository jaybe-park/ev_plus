#!/usr/bin/env python3
"""
에퀴티 엔진 + 포스트플랍 봇 테스트

실행: python3 tests/test_equity.py
"""

import sys
import os
import random
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.card import Card, Suit, Rank
from core.game import Action
from core.player import Player
import ai.equity as eq
from ai.equity import (
    canonical_key, decode_key, calculate_equity, exact_counts_river,
    smart_equity, cache_lookup, made_hand_rank,
)
from ai.bot import PokerBot, BotDifficulty, board_wetness

_RANK = {r.symbol: r for r in Rank}
_RANK["T"] = Rank.TEN  # 10 별칭
_SUIT = {"s": Suit.SPADES, "h": Suit.HEARTS, "d": Suit.DIAMONDS, "c": Suit.CLUBS}

PASS = 0
FAIL = 0


def c(spec: str) -> Card:
    return Card(_RANK[spec[:-1]], _SUIT[spec[-1]])


def cards(*specs) -> list:
    return [c(s) for s in specs]


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


def test_canonical_key():
    print("\n[E-1] 수트 정규화 키")
    # 수트만 바꾼 같은 스팟 → 같은 키
    k1 = canonical_key(cards("Ah", "Kh"), cards("Qh", "7s", "2d"))
    k2 = canonical_key(cards("As", "Ks"), cards("Qs", "7d", "2c"))
    check("수트 치환 불변", k1 == k2, f"{k1} != {k2}")

    # 수티드 vs 오프수트 → 다른 키
    k3 = canonical_key(cards("Ah", "Kh"), [])
    k4 = canonical_key(cards("Ah", "Ks"), [])
    check("AKs != AKo", k3 != k4)

    # 홀카드 순서 무관
    k5 = canonical_key(cards("Kh", "Ah"), [])
    k6 = canonical_key(cards("Ah", "Kh"), [])
    check("홀카드 순서 불변", k5 == k6)

    # 인코딩/디코딩 왕복
    hole, board = cards("Ah", "Kh"), cards("Qh", "7s", "2d", "3c")
    key = canonical_key(hole, board)
    h2, b2 = decode_key(key)
    check("디코딩 왕복 (키 재생성 일치)", canonical_key(h2, b2) == key)
    check("디코딩 보드 길이", len(b2) == 4)


def test_exact_river():
    print("\n[E-2] 리버 전수조사")
    # 쿼드 에이스 → 절대 안 짐
    w, t, n = exact_counts_river(
        cards("As", "Ah"), cards("Ad", "Ac", "Kh", "Qd", "2s"))
    check("쿼드 equity=1.0", (w + 0.5 * t) / n == 1.0, f"={(w+0.5*t)/n}")
    check("리버 조합 수 990", n == 990, f"={n}")

    # 보드 플레이 (내 홀카드 무관 = 대부분 무승부 possible) — 2-7 오프 vs 로열 보드
    w, t, n = exact_counts_river(
        cards("2d", "7c"), cards("As", "Ks", "Qs", "Js", "Ts"))
    check("로열 보드 스플릿 다수", t > n * 0.9, f"ties={t}/{n}")


def test_mc_sanity():
    print("\n[E-3] Monte Carlo 근사 정확도")
    random.seed(42)
    e = calculate_equity(cards("As", "Ah"), [], 1, 3000)
    check("AA vs1 ≈ 0.85", 0.80 <= e <= 0.90, f"={e:.3f}")

    e = calculate_equity(cards("7s", "2h"), [], 1, 3000)
    check("72o vs1 ≈ 0.35", 0.29 <= e <= 0.41, f"={e:.3f}")

    e = calculate_equity(cards("As", "Ah"), [], 4, 2000)
    check("AA vs4 ≈ 0.56 (멀티웨이 하락)", 0.45 <= e <= 0.68, f"={e:.3f}")

    # 넛플러시 드로우 (A하이 포함): 뜨거나 A페어로도 이김 → ~0.65
    e = calculate_equity(cards("Ah", "5h"), cards("Kh", "9h", "2s"), 1, 2000)
    check("넛플러시드로우 ≈ 0.65", 0.55 <= e <= 0.75, f"={e:.3f}")


def test_cache():
    print("\n[E-4] equity_cache DB 누적")
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    eq.DB_PATH = tmp
    try:
        random.seed(1)
        hole, board = cards("Ah", "Kd"), cards("Qs", "7h", "2c")
        key = canonical_key(hole, board)

        smart_equity(hole, board, 1, 100, use_cache=True, contribute=True)
        eq._flush_contributions()  # 기여는 배치 버퍼링 → 명시 플러시
        row = cache_lookup(key, 1)
        check("MC 결과 캐시 저장 (플러시 후)", row is not None and row["total"] == 100,
              f"row={row}")

        smart_equity(hole, board, 1, 100, use_cache=True, contribute=True)
        eq._flush_contributions()
        row = cache_lookup(key, 1)
        check("재호출 시 누적 (200)", row["total"] == 200, f"={row['total']}")

        # 리버 전수조사 → exact 플래그
        hole_r, board_r = cards("As", "Ah"), cards("Ad", "Ac", "Kh", "Qd", "2s")
        e = smart_equity(hole_r, board_r, 1, 50, use_cache=True,
                         contribute=True, exact_river=True)
        row = cache_lookup(canonical_key(hole_r, board_r), 1)
        check("리버 exact 저장", row["exact"] == 1 and e == 1.0,
              f"row={row}, e={e}")

        # exact 이후엔 MC가 덮어쓰지 않음
        smart_equity(hole_r, board_r, 1, 50, use_cache=True, contribute=True)
        eq._flush_contributions()
        row = cache_lookup(canonical_key(hole_r, board_r), 1)
        check("exact 보호 (누적 안 됨)", row["total"] == 990, f"={row['total']}")
    finally:
        eq.DB_PATH = None
        if os.path.exists(tmp):
            os.remove(tmp)


def test_board_wetness():
    print("\n[E-5] 보드 텍스처")
    dry = board_wetness(cards("Ks", "7h", "2d"))
    wet = board_wetness(cards("Jh", "Th", "9h"))
    check("드라이 < 웻", dry < wet, f"dry={dry:.2f}, wet={wet:.2f}")
    check("드라이 보드 < 0.4", dry < 0.4, f"={dry:.2f}")
    check("모노톤 커넥티드 > 0.7", wet > 0.7, f"={wet:.2f}")


def _bot_state(street, community, pot, current_bet, players=None, positions=None):
    # 실제 game_state 형식: "Q♥" (심볼 수트)
    community_syms = [str(card) for card in cards(*community)]
    return {
        "street": street,
        "pot": pot,
        "current_bet": current_bet,
        "min_raise": 20,
        "big_blind": 20,
        "community_cards": community_syms,
        "positions": positions or {"Bot": "BTN", "Villain": "BB"},
        "players": players or [
            {"name": "Bot", "chips": 1000, "current_bet": 0,
             "is_folded": False, "is_all_in": False, "is_human": False},
            {"name": "Villain", "chips": 1000, "current_bet": 0,
             "is_folded": False, "is_all_in": False, "is_human": True},
        ],
        "action_log": [],
    }


def _make_bot(hole_specs, difficulty=BotDifficulty.MEDIUM):
    p = Player("Bot", chips=1000, is_human=False)
    p.hole_cards = cards(*hole_specs)
    return PokerBot(p, difficulty)


def test_bot_decisions():
    print("\n[E-6] 봇 의사결정")
    eq.DB_PATH = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    try:
        random.seed(7)

        # 리버 넛 (로열 플러시) + 상대 벳 → 절대 폴드하지 않음
        folds = 0
        for _ in range(10):
            bot = _make_bot(["Ah", "Kh"])
            bot.player.current_bet = 0
            st = _bot_state("리버", ["Qh", "Jh", "Th", "2s", "3d"], 300, 100)
            action, _ = bot.decide_action(st)
            if action == Action.FOLD:
                folds += 1
        check("리버 넛으로 폴드 없음", folds == 0, f"folds={folds}/10")

        # 트래시 + 거대 벳 → 대부분 폴드
        folds = 0
        for _ in range(10):
            bot = _make_bot(["7c", "2d"])
            st = _bot_state("리버", ["As", "Kh", "Qd", "Jc", "9s"], 200, 400)
            action, _ = bot.decide_action(st)
            if action == Action.FOLD:
                folds += 1
        check("리버 트래시 폴드 다수", folds >= 8, f"folds={folds}/10")

        # 벳 없음 + 트래시 → 대부분 체크 (블러프 소수 허용)
        checks = 0
        for _ in range(20):
            bot = _make_bot(["7c", "2d"])
            st = _bot_state("플랍", ["As", "Kh", "Qd"], 100, 0)
            action, _ = bot.decide_action(st)
            if action == Action.CHECK:
                checks += 1
        check("트래시는 대부분 체크", checks >= 14, f"checks={checks}/20")

        # 플러시 드로우 + 팟오즈 좋은 콜 → 폴드하지 않음 (콜 or 레이즈)
        folds = 0
        for _ in range(10):
            bot = _make_bot(["Ah", "5h"])
            st = _bot_state("플랍", ["Kh", "9h", "2s"], 300, 60)
            action, _ = bot.decide_action(st)
            if action == Action.FOLD:
                folds += 1
        check("좋은 오즈 드로우 폴드 없음", folds == 0, f"folds={folds}/10")

        # 세미블러프 존재 확인: 드로우로 벳 없는 상황에서 가끔 벳
        bets = 0
        for _ in range(30):
            bot = _make_bot(["Ah", "5h"], BotDifficulty.HARD)
            st = _bot_state("플랍", ["Kh", "9h", "2s"], 100, 0)
            action, _ = bot.decide_action(st)
            if action in (Action.RAISE, Action.ALL_IN):
                bets += 1
        check("세미블러프 발생 (hard)", bets >= 3, f"bets={bets}/30")

        # 포지션 점수
        bot = _make_bot(["Ah", "Kh"])
        st = _bot_state("플랍", ["Ks", "7h", "2d"], 100, 0,
                        positions={"Bot": "BTN", "V1": "SB", "V2": "BB"},
                        players=[
                            {"name": "Bot", "chips": 1000, "current_bet": 0,
                             "is_folded": False, "is_all_in": False, "is_human": False},
                            {"name": "V1", "chips": 1000, "current_bet": 0,
                             "is_folded": False, "is_all_in": False, "is_human": True},
                            {"name": "V2", "chips": 1000, "current_bet": 0,
                             "is_folded": False, "is_all_in": False, "is_human": True},
                        ])
        check("BTN 포지션 = 1.0", bot._position_score(st) == 1.0)
        st["positions"] = {"Bot": "SB", "V1": "BTN", "V2": "BB"}
        check("SB 포지션 = 0.0", bot._position_score(st) == 0.0)
    finally:
        if os.path.exists(eq.DB_PATH):
            os.remove(eq.DB_PATH)
        eq.DB_PATH = None


def test_ranged_equity():
    print("\n[E-8] 레인지 기반 equity")
    from ai.equity import RangeSampler, ranged_equity

    random.seed(11)
    # KK vs {AA만} 레인지 → ~0.18 (압도적 열세)
    aa_only = RangeSampler({"AA": 1.0})
    e = ranged_equity(cards("Kh", "Kd"), [], [aa_only], 800)
    check("KK vs AA레인지 ≈ 0.18", 0.10 <= e <= 0.28, f"={e:.3f}")

    # KK vs 랜덤 → ~0.82, 레인지가 좁아지면 하락해야 함
    e_random = calculate_equity(cards("Kh", "Kd"), [], 1, 800)
    check("KK vs 랜덤 > vs AA레인지", e_random > e + 0.3,
          f"random={e_random:.3f}, ranged={e:.3f}")

    # 콤보 수 검증
    check("AA = 6콤보", len(RangeSampler({"AA": 1.0}).combos) == 6)
    check("AKs = 4콤보", len(RangeSampler({"AKs": 1.0}).combos) == 4)
    check("AKo = 12콤보", len(RangeSampler({"AKo": 1.0}).combos) == 12)

    # 블록 카드 회피: A 2장 블록 → 유일하게 남은 (Ad,Ac) 콤보만 샘플돼야 함
    s = RangeSampler({"AA": 1.0})
    blocked = {c("As"), c("Ah")}
    ok = all(
        (pair := s.sample(blocked)) is not None
        and pair[0] not in blocked and pair[1] not in blocked
        for _ in range(20)
    )
    check("블록 회피 샘플링", ok)
    # 콤보가 전멸하면 None (랜덤 폴백 신호)
    check("전멸 시 None", s.sample({c("As"), c("Ah"), c("Ad")}) is None)

    # GTO 레인지 연동 (DB에 RFI 데이터 있을 때만)
    from gto.loader import get_raise_range
    utg = get_raise_range("UTG")
    if utg:
        sampler = RangeSampler(utg)
        # QQ vs UTG 오픈 레인지: 랜덤(~0.80)보다 낮아야 함 (레인지가 강함)
        e_r = ranged_equity(cards("Qh", "Qd"), [], [sampler], 800)
        e_u = calculate_equity(cards("Qh", "Qd"), [], 1, 800)
        check("QQ vs UTG레인지 < vs 랜덤", e_r < e_u - 0.03,
              f"ranged={e_r:.3f}, random={e_u:.3f}")
    else:
        print("  ⏭  UTG RFI 데이터 없음 — GTO 연동 테스트 스킵")


def test_fast_evaluator():
    print("\n[E-9] 고속 7카드 평가기 등가성")
    from core.evaluator import HandEvaluator, evaluate_rank
    from core.card import Card as _C
    full = [Card(r, s) for r in Rank for s in Suit]
    random.seed(77)
    mismatch = 0
    for i in range(3000):
        n = 7 if i % 10 < 8 else (6 if i % 10 == 8 else 5)
        hand = random.sample(full, n)
        old = HandEvaluator.evaluate(hand)
        if (old.hand_rank.rank_value, old.tiebreakers) != evaluate_rank(hand):
            mismatch += 1
    check("랜덤 3000세트 완전 일치", mismatch == 0, f"불일치={mismatch}")


def test_street_dp():
    print("\n[E-10] 스트리트 분해 DP 정합성")
    import importlib
    from db.connection import get_connection
    w = importlib.import_module("scripts.equity_worker")
    from ai.equity import exact_counts_turn

    hole = cards("Ah", "Kd")
    board4 = cards("Kh", "9s", "2c", "7d")
    direct = exact_counts_turn(hole, board4)

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = get_connection(tmp)
    try:
        W, T, N, hits = w.exact_turn_dp(conn, hole, board4)
        conn.commit()
        check("턴 DP == 직접 열거", (W, T, N) == direct, f"{(W,T,N)} vs {direct}")
        W2, T2, N2, hits2 = w.exact_turn_dp(conn, hole, board4)
        check("웜 캐시 46/46 적중 + 동일값", hits2 == 46 and (W2, T2, N2) == direct)
    finally:
        conn.close()
        os.remove(tmp)


def test_made_hand_rank():
    print("\n[E-7] made hand rank (드로우 판별)")
    r = made_hand_rank(cards("Ah", "5h"), cards("Kh", "9h", "2s"))
    check("플러시 드로우 = 하이카드(1)", r == 1, f"={r}")
    r = made_hand_rank(cards("Ks", "9d"), cards("Kh", "9h", "2s"))
    check("투페어 = 3", r == 3, f"={r}")


if __name__ == "__main__":
    print("=" * 50)
    print("  에퀴티 엔진 + 봇 테스트")
    print("=" * 50)

    test_canonical_key()
    test_exact_river()
    test_mc_sanity()
    test_cache()
    test_board_wetness()
    test_bot_decisions()
    test_ranged_equity()
    test_fast_evaluator()
    test_street_dp()
    test_made_hand_rank()

    print(f"\n{'='*50}")
    print(f"  결과: {PASS} 통과 / {FAIL} 실패")
    print(f"{'='*50}")
    sys.exit(1 if FAIL else 0)
