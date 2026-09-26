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


def test_multiway_tie_share():
    print("\n[E-13] 멀티웨이 동률 1/k (T-032)")
    from ai.equity import mc_counts, mc_counts_ranged, RangeSampler, _ratio
    royal = cards("As", "Ks", "Qs", "Js", "Ts")  # 모두 보드를 플레이 → 전원 스플릿
    hole = cards("2c", "3d")
    for n_opp, expect in ((1, 1 / 2), (2, 1 / 3), (5, 1 / 6)):
        e = _ratio(*mc_counts(hole, royal, n_opp, 200))
        check(f"로열 보드 vs{n_opp} = 1/{n_opp + 1}", abs(e - expect) < 1e-9, f"={e:.4f}")
        e = calculate_equity(hole, royal, n_opp, 200)
        check(f"calculate_equity 로열 보드 vs{n_opp} = 1/{n_opp + 1}",
              abs(e - expect) < 1e-9, f"={e:.4f}")
    # 레인지 경로도 같은 공식
    e = _ratio(*mc_counts_ranged(hole, royal, [RangeSampler({"88": 1.0}), None], 200))
    check("ranged 로열 보드 vs2 = 1/3", abs(e - 1 / 3) < 1e-9, f"={e:.4f}")
    # 일부만 동률: 나·상대A 동률, 상대B 패 → 1/2 (리버, 레인지로 고정)
    board = cards("Ah", "Kd", "8c", "5s", "2h")
    e = _ratio(*mc_counts_ranged(
        cards("Qc", "Jd"), board,
        [RangeSampler({"QJo": 1.0}), RangeSampler({"43s": 1.0})], 300))
    # QJo 콤보 중 Qc/Jd 블록 제외 나머지 전부 같은 하이카드 → 동률, 43s는 5-high 스트레이트(A-5)로 승
    check("43s(휠) 상대 포함 시 0", e == 0.0, f"={e:.4f}")
    e = _ratio(*mc_counts_ranged(
        cards("Qc", "Jd"), board,
        [RangeSampler({"QJo": 1.0}), RangeSampler({"76s": 1.0})], 300))
    check("나·상대A 동률 + 상대B 패 = 1/2", abs(e - 0.5) < 1e-9, f"={e:.4f}")

    # 멀티웨이 캐시 행은 읽지 않는다 (과거 1/2 공식 오염값)
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    eq.DB_PATH = tmp
    prev_env = os.environ.get("EV_PLUS_DB")
    os.environ["EV_PLUS_DB"] = tmp  # 세션 기록(recorder)도 임시 DB로
    try:
        key = canonical_key(hole, royal)
        eq.cache_contribute("river", key, 2, 0.0, 1_000_000.0, 1_000_000, exact=True)  # 오염값 0.5
        # 헤즈업 행에는 식별용 가짜 값(1.0)을 심어 "읽었는지"를 구분한다
        eq.cache_contribute("river", key, 1, 990.0, 0.0, 990, exact=True)
        e2 = smart_equity(hole, royal, 2, 300, use_cache=True, contribute=False)
        check("멀티웨이 캐시 오염값(0.5) 무시 → 1/3", abs(e2 - 1 / 3) < 1e-9, f"={e2:.4f}")
        e1 = smart_equity(hole, royal, 1, 300, use_cache=True, contribute=False)
        check("헤즈업 캐시는 그대로 사용", e1 == 1.0, f"={e1:.4f}")

        # 실제 패널 경로(세션 _get_equity_info): 3인 스플릿 → vs_random·vs_range 모두 1/3
        from server.session import WebGameSession
        from core.game import Street
        random.seed(3)
        s = WebGameSession(session_id="t032", human_name="Hero", chips=2000,
                           num_bots=2, difficulty="easy", small_blind=10)
        for p in s.game.players:
            p.is_folded = False
        s.human.hole_cards = list(hole)
        s.game.community_cards = list(royal)
        s.game.current_street = Street.RIVER
        s._equity_cache = {}
        info = s._get_equity_info()
        check("패널 vs_random 3인 스플릿 = 1/3", info is not None
              and abs(info["vs_random"] - 1 / 3) < 1e-3, f"={info and info['vs_random']}")
        check("패널 vs_range 3인 스플릿 = 1/3", info is not None
              and abs(info["vs_range"] - 1 / 3) < 1e-3, f"={info and info['vs_range']}")
    finally:
        eq._flush_contributions()
        eq.DB_PATH = None
        if prev_env is None:
            os.environ.pop("EV_PLUS_DB", None)
        else:
            os.environ["EV_PLUS_DB"] = prev_env
        if os.path.exists(tmp):
            os.remove(tmp)


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

        # 숏스택 팟오즈 (T-033): 44 on K9532 리버 vs1 exact 0.562.
        # 상대 1,000 올인(팟 150 → 1,150). 원값 팟오즈 46.5%+마진 → 폴드,
        # 스택 100이면 유효 팟오즈 100/350=28.6%+마진 → 콜이어야 한다.
        def _shove_state():
            return _bot_state("리버", ["Ks", "9d", "5c", "3h", "2s"], 1150, 1000, players=[
                {"name": "Bot", "chips": 0, "current_bet": 0,
                 "is_folded": False, "is_all_in": False, "is_human": False},
                {"name": "Villain", "chips": 0, "current_bet": 1000,
                 "is_folded": False, "is_all_in": True, "is_human": True},
            ])
        for chips, expect, label in ((100, Action.CALL, "숏스택(100) 큰 올인 → 콜"),
                                     (5000, Action.FOLD, "딥스택(5000) 같은 올인 → 폴드")):
            bot = _make_bot(["4h", "4d"], BotDifficulty.HARD)
            bot.player.chips = chips
            action, _ = bot.decide_action(_shove_state())
            check(f"봇 팟오즈 {label}", action == expect, f"={action}")
        bot = _make_bot(["4h", "4d"], BotDifficulty.HARD)
        bot.player.chips = 100
        check("봇 유효 콜·팟 = (100, 250)", bot._effective_call_pot(_shove_state()) == (100, 250),
              f"={bot._effective_call_pot(_shove_state())}")

        # bet_ratio (T-034): 팟 100에 내가 50 벳, 상대 150으로 레이즈 → 1.0 (이전 공식 0.5)
        from ai.bot import facing_bet_ratio
        r = facing_bet_ratio(300, 150, [50, 150])
        check("레이즈 받음 bet_ratio = 1.0", abs(r - 1.0) < 1e-9, f"={r}")
        r = facing_bet_ratio(150, 50, [0, 50])
        check("단순 벳 bet_ratio = 0.5 (팟 100에 50)", abs(r - 0.5) < 1e-9, f"={r}")
        r = facing_bet_ratio(200, 50, [0, 50, 50])
        check("벳+콜러 뒤 bet_ratio = 0.5 (콜러 칩 제외)", abs(r - 0.5) < 1e-9, f"={r}")
        r = facing_bet_ratio(300, 150, [0, 50, 150])
        check("제3자 벳 후 레이즈 bet_ratio = 1.0", abs(r - 1.0) < 1e-9, f"={r}")
        # 실제 판단에 반영: A7 on K9532 리버 exact 0.316, 팟오즈 100/400=25%.
        # hard 마진 0.02+0.08×ratio → ratio 1.0이면 35% 필요(폴드), 0.5였다면 31%(콜)
        bot = _make_bot(["Ah", "7d"], BotDifficulty.HARD)
        bot.player.current_bet = 50
        st = _bot_state("리버", ["Ks", "9d", "5c", "3h", "2s"], 300, 150, players=[
            {"name": "Bot", "chips": 950, "current_bet": 50,
             "is_folded": False, "is_all_in": False, "is_human": False},
            {"name": "Villain", "chips": 850, "current_bet": 150,
             "is_folded": False, "is_all_in": False, "is_human": True},
        ])
        action, _ = bot.decide_action(st)
        check("벳 후 팟 크기 레이즈를 받으면 A-high 폴드", action == Action.FOLD, f"={action}")
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

    # 결합 거절 샘플링 (T-034): 좁은 레인지 상대 두 명 — 리버라 정답을 전수로 계산
    from itertools import product
    from ai.equity import mc_counts_ranged, _ratio, _showdown_share, _notation_combos
    from core.evaluator import evaluate_rank
    hole, board = cards("Js", "Jh"), cards("2c", "3d", "4h", "Ks", "9c")
    known = set(hole) | set(board)
    ra = [p for n in ("AA", "55") for p in _notation_combos(n) if not (set(p) & known)]
    rb = [p for n in ("AA", "66") for p in _notation_combos(n) if not (set(p) & known)]
    mine = evaluate_rank(hole + board)
    share = n_ok = 0
    for a, b in product(ra, rb):
        if set(a) & set(b):
            continue
        w, t = _showdown_share(mine, [evaluate_rank(list(a) + board), evaluate_rank(list(b) + board)])
        share += w + 0.5 * t
        n_ok += 1
    truth = share / n_ok
    random.seed(34)
    n = 6000
    est = _ratio(*mc_counts_ranged(hole, board,
                                   [RangeSampler({"AA": 1, "55": 1}), RangeSampler({"AA": 1, "66": 1})], n))
    se = (truth * (1 - truth) / n) ** 0.5
    check(f"좁은 레인지 2명 결합분포: 정답 {truth:.3f}, 추정 {est:.3f} (3σ={3*se:.3f})",
          abs(est - truth) < 3 * se, f"차이={est - truth:+.3f}")
    # 순서를 바꿔도 같은 분포
    est2 = _ratio(*mc_counts_ranged(hole, board,
                                    [RangeSampler({"AA": 1, "66": 1}), RangeSampler({"AA": 1, "55": 1})], n))
    check("상대 순서 무관", abs(est2 - truth) < 3 * se, f"={est2:.3f}")
    # 레인지가 보드·내 카드에 전부 막히면 랜덤 상대로 취급
    blocked_all = RangeSampler({"JJ": 1.0})  # Js·Jh가 내 홀 → Jd Jc 1콤보만 남음
    check("레인지 블로커 사전 제거", len(blocked_all.restricted(known).combos) == 1)
    check("전부 막히면 restricted=None", RangeSampler({"KK": 1.0}).restricted(
        known | {c("Kh"), c("Kd")}) is None)

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


def test_headsup_range_uses_sb():
    print("\n[E-14] 헤즈업 BTN/SB 상대 레인지 = SB 레인지 (T-017, ADR 0005)")
    import gto.loader as gto_loader
    from db.connection import get_connection
    from ai.bot import opponent_range_info
    from server.session import WebGameSession
    from core.game import Street

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    prev_db, prev_env = eq.DB_PATH, os.environ.get("EV_PLUS_DB")
    eq.DB_PATH = tmp
    os.environ["EV_PLUS_DB"] = tmp
    try:
        conn = get_connection()
        # 좁은 SB RFI(AA·KK) + BB vs SB 콜 레인지(QQ·JJ)를 시딩
        for pos, vs, rtype, hands in (("SB", None, "open", {"AA": (0, 1), "KK": (0, 1)}),
                                      ("BB", "SB", "vs_open", {"QQ": (1, 0), "JJ": (1, 0)})):
            sid = conn.execute(
                "INSERT INTO gto_preflop_situations (position, vs_position, range_type, "
                "raise_size, situation_label) VALUES (?,?,?,3.0,?)",
                (pos, vs, rtype, f"{pos} {rtype}"),
            ).lastrowid
            for hand, (call, rz) in hands.items():
                conn.execute(
                    "INSERT INTO gto_preflop_hands (situation_id, hand, freq_fold, freq_call, "
                    "freq_raise, freq_allin) VALUES (?,?,0,?,?,0)", (sid, hand, call, rz))
        conn.commit()
        conn.close()
        gto_loader._cache = {}
        gto_loader._loaded = False

        st = {"positions": {"Hero": "BB", "Bot": "BTN/SB"},
              "action_log": ["[BTN/SB] Bot: 스몰 블라인드 (10)", "[BB] Hero: 빅 블라인드 (20)",
                             "[BTN/SB] Bot: 레이즈 (60)"]}
        (sampler, role), = opponent_range_info(st, [{"name": "Bot"}])
        check("BTN/SB 레이저 → raiser", role == "raiser", f"={role}")
        check("BTN/SB 레이저 레인지 = SB RFI(AA·KK 12콤보)",
              sampler is not None and len(sampler.combos) == 12,
              f"={sampler and len(sampler.combos)}")
        st2 = {"positions": {"Hero": "BTN/SB", "Bot": "BB"},
               "action_log": ["[BTN/SB] Hero: 레이즈 (60)", "[BB] Bot: 콜 (40)"]}
        (sampler2, role2), = opponent_range_info(st2, [{"name": "Bot"}])
        check("BTN/SB 오픈에 BB 콜 → BB vs SB 콜 레인지(QQ·JJ 12콤보)",
              role2 == "caller" and sampler2 is not None and len(sampler2.combos) == 12,
              f"={role2} {sampler2 and len(sampler2.combos)}")

        # 실제 패널 경로: 헤즈업 세션에서 봇(BTN/SB)이 오픈 → vs_range가 SB 레인지 기준
        random.seed(17)
        s = WebGameSession(session_id="t017", human_name="Hero", chips=2000,
                           num_bots=1, difficulty="easy", small_blind=10)
        bot_p = next(p for p in s.game.players if p is not s.human)
        s.game.dealer_index = s.game.players.index(bot_p)
        pos = s.game.get_positions()
        check("헤즈업 봇 라벨 = BTN/SB", pos.get(bot_p.name) == "BTN/SB", f"={pos}")
        for p in s.game.players:
            p.is_folded = False
        s.human.hole_cards = cards("Qh", "Qd")
        s.game.community_cards = cards("7c", "4d", "2s")
        s.game.current_street = Street.FLOP
        s.action_log = [f"[BTN/SB] {bot_p.name}: 레이즈 (60)", f"[BB] Hero: 콜 (40)", "── 플랍 ──"]
        s._equity_cache = {}
        info = s._get_equity_info()
        check("패널 상대 role = raiser", info["opponents"][0]["role"] == "raiser",
              f"={info['opponents']}")
        check("패널 vs_range(QQ vs AA·KK ≈ 0.19)가 vs_random(≈0.8)과 다름",
              info["vs_range"] < 0.35 and info["vs_random"] > 0.65,
              f"range={info['vs_range']} random={info['vs_random']}")
    finally:
        eq._flush_contributions()
        gto_loader._cache = {}
        gto_loader._loaded = False
        eq.DB_PATH = prev_db
        if prev_env is None:
            os.environ.pop("EV_PLUS_DB", None)
        else:
            os.environ["EV_PLUS_DB"] = prev_env
        if os.path.exists(tmp):
            os.remove(tmp)


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


def test_grader():
    print("\n[E-11] 플레이 평가 (Play Grader) 판정 규칙")
    from gto.grader import (
        grade_preflop_action, grade_postflop_call, grade_postflop_fold,
        grade_postflop_bet_or_raise,
    )

    # 프리플랍: 데이터 없음 → ⬜
    g = grade_preflop_action("call", None)
    check("GTO 데이터 없음 → ⬜", g.grade == "⬜", f"={g.grade}")

    # 프리플랍: 최빈 액션과 일치 → ✅
    rec = {"frequencies": {"raise": 0.8, "fold": 0.2}}
    g = grade_preflop_action("raise", rec)
    check("최빈 액션 일치 → ✅", g.grade == "✅", f"={g.grade}")

    # 프리플랍: 저빈도 액션 선택 → 🔴 (블런더)
    g = grade_preflop_action("call", rec)  # call 빈도 0% (frequencies에 없음)
    check("저빈도(<5%) 액션 → 🔴", g.grade == "🔴", f"={g.grade}")

    # 프리플랍: 중간 빈도(5~25%) → 🟠
    rec2 = {"frequencies": {"raise": 0.7, "call": 0.15, "fold": 0.15}}
    g = grade_preflop_action("call", rec2)
    check("중간 빈도(5~25%) → 🟠", g.grade == "🟠", f"={g.grade}")

    # 프리플랍: 준수 빈도(>25%) → 🟡
    rec3 = {"frequencies": {"raise": 0.6, "call": 0.4}}
    g = grade_preflop_action("call", rec3)
    check("준수 빈도(>25%) → 🟡", g.grade == "🟡", f"={g.grade}")

    # 포스트플랍 콜: EV 양수 → ✅
    g = grade_postflop_call(0.8, pot=100, call_amount=20, big_blind=20)
    check("콜 EV 양수 → ✅", g.grade == "✅" and g.ev_loss_bb is None, f"={g.grade}")

    # 포스트플랍 콜: EV 음수 → 🔴 + bb 손실 추정
    g = grade_postflop_call(0.1, pot=100, call_amount=50, big_blind=20)
    check("콜 EV 음수 → 🔴", g.grade == "🔴", f"={g.grade}")
    check("bb 손실 추정치 존재(양수)", g.ev_loss_bb is not None and g.ev_loss_bb > 0, f"={g.ev_loss_bb}")

    # 포스트플랍 폴드: equity 낮음(팟오즈 이하) → 적절한 폴드 ✅
    g = grade_postflop_fold(0.1, pot=100, call_amount=20, big_blind=20)
    check("적절한 폴드 → ✅", g.grade == "✅", f"={g.grade}")

    # 포스트플랍 폴드: equity 높은데 폴드 → 놓친 EV 🔴
    g = grade_postflop_fold(0.9, pot=100, call_amount=20, big_blind=20)
    check("놓친 EV 폴드 → 🔴", g.grade == "🔴", f"={g.grade}")
    check("놓친 EV bb 손실 추정치", g.ev_loss_bb is not None and g.ev_loss_bb > 0, f"={g.ev_loss_bb}")

    # 넛급 핸드 체크 → 밸류 놓침 경고
    g = grade_postflop_bet_or_raise(0.95, "check")
    check("넛급 체크 → ⚠️ 밸류 놓침", g.grade == "⚠️", f"={g.grade}")

    # 저 equity 레이즈 → 블러프 중립 🟡
    g = grade_postflop_bet_or_raise(0.15, "raise")
    check("저equity 레이즈 → 🟡 블러프", g.grade == "🟡", f"={g.grade}")

    # 중간 equity 벳 → 데이터부족 ⬜ (v1 제한 판정)
    g = grade_postflop_bet_or_raise(0.5, "raise")
    check("중간 equity 벳 → ⬜ (제한 판정)", g.grade == "⬜", f"={g.grade}")


def test_board_rank_table():
    print("\n[E-12] 보드 중심 리버 계산 (board_rank_table) 정합성")
    from ai.equity import board_rank_table, equity_via_board_table

    full = [Card(r, s) for r in Rank for s in Suit]
    random.seed(2026)
    mismatch = 0
    cases = 0
    for _ in range(100):
        board = random.sample(full, 5)
        table = board_rank_table(board)
        rest = [c for c in full if c not in board]
        for _ in range(5):
            hole = random.sample(rest, 2)
            direct = exact_counts_river(hole, board)
            via_table = equity_via_board_table(hole, board, table)
            cases += 1
            if direct != via_table:
                mismatch += 1
    check(f"랜덤 보드 100 × 홀 5 = {cases}케이스 완전 일치", mismatch == 0,
          f"불일치={mismatch}")


if __name__ == "__main__":
    print("=" * 50)
    print("  에퀴티 엔진 + 봇 테스트")
    print("=" * 50)

    test_canonical_key()
    test_exact_river()
    test_mc_sanity()
    test_multiway_tie_share()
    test_cache()
    test_board_wetness()
    test_bot_decisions()
    test_ranged_equity()
    test_headsup_range_uses_sb()
    test_fast_evaluator()
    test_street_dp()
    test_made_hand_rank()
    test_grader()
    test_board_rank_table()

    print(f"\n{'='*50}")
    print(f"  결과: {PASS} 통과 / {FAIL} 실패")
    print(f"{'='*50}")
    sys.exit(1 if FAIL else 0)
