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

# ── 테스트 격리 ──────────────────────────────────────────
# 에퀴티 계산은 DB를 쓰지 않지만(ADR 0034), gto.loader.get_raise_range·세션 기록 등
# db.connection.get_connection()을 인자 없이 호출하는 경로는 EV_PLUS_DB가 비어 있으면
# 운영 poker.db를 만들어 버린다 — 모듈 임포트 시점에 환경변수 자체를 격리한다.
os.environ["EV_PLUS_DB"] = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name

from core.card import Card, Suit, Rank
from core.game import Action
from core.player import Player
from ai.equity import (
    exact_counts_river, exact_counts_turn, mc_counts, _ratio,
    smart_equity, equity_detail, made_hand_rank,
)
from ai.bot import PokerBot, BotDifficulty, board_wetness, has_draw, opponent_range_info

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


def test_preflop_table():
    print("\n[E-1] 프리플랍 상수 테이블 — 기준값 대조 (ADR 0034)")
    from ai.preflop_equity_table import PREFLOP_EQUITY, PREFLOP_SAMPLES
    from ai.equity import preflop_notation
    check("169핸드 × 상대 1~5명 = 845값",
          len(PREFLOP_EQUITY) == 169 and all(len(v) == 5 for v in PREFLOP_EQUITY.values()),
          f"={len(PREFLOP_EQUITY)}")
    check("값마다 100만 샘플", PREFLOP_SAMPLES >= 1_000_000, f"={PREFLOP_SAMPLES}")
    # 경로·표본 수 확인용 대표값 4개(±0.2%p). 공개 기준값 23개 대조는 tests/test_equity_verify.py
    for hole, n_opp, expect in ((("As", "Ah"), 1, 0.852), (("Ah", "Kh"), 1, 0.670),
                                (("7s", "2h"), 1, 0.346), (("Ad", "Ac"), 5, 0.492)):
        r = equity_detail(cards(*hole), [], n_opp)
        check(f"{preflop_notation(cards(*hole))} vs{n_opp} ≈ {expect:.1%} (테이블 경로)",
              abs(r.equity - expect) <= 0.002 and r.source == "preflop-table"
              and r.samples == PREFLOP_SAMPLES, f"={r}")
    # 표기 변환: 수트 치환·홀카드 순서 불변, 수티드/오프수트 구분, 10 → T
    check("수트 치환 불변 (AhKh == AsKs)",
          smart_equity(cards("Ah", "Kh"), [], 1) == smart_equity(cards("As", "Ks"), [], 1))
    check("홀카드 순서 불변", preflop_notation(cards("Kh", "Ah")) == "AKs")
    check("AKo 표기", preflop_notation(cards("Ah", "Kd")) == "AKo")
    check("10 → T 표기", preflop_notation(cards("Th", "9h")) == "T9s")
    # 상대가 늘수록 단조 감소 (AA)
    aa = PREFLOP_EQUITY["AA"]
    check("AA 상대 수 증가 시 단조 감소", all(aa[i] > aa[i + 1] for i in range(4)), f"={aa}")
    # 테이블 값 = 지금 코드의 MC와 일치 (vs2 이상은 옛 동률 공식 과대분 실측 최대 +0.40%p 허용)
    from ai.equity import mc_adaptive
    random.seed(21)
    for hole, n_opp in ((("As", "Ah"), 2), (("Qh", "Jh"), 3), (("7s", "2h"), 1)):
        w, t, n, se = mc_adaptive(cards(*hole), [], n_opp, target_se=0.004, max_samples=20_000)
        est = _ratio(w, t, n)
        tab = PREFLOP_EQUITY[preflop_notation(cards(*hole))][n_opp - 1]
        check(f"{preflop_notation(cards(*hole))} vs{n_opp} 테이블 {tab:.4f} ≈ MC {est:.4f} (3σ+0.40%p)",
              abs(est - tab) <= 3 * se + 0.004, f"차이={est - tab:+.4f}, se={se:.4f}")


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
    e = _ratio(*mc_counts(cards("As", "Ah"), [], 1, 3000))
    check("AA vs1 ≈ 0.85", 0.80 <= e <= 0.90, f"={e:.3f}")

    e = _ratio(*mc_counts(cards("7s", "2h"), [], 1, 3000))
    check("72o vs1 ≈ 0.35", 0.29 <= e <= 0.41, f"={e:.3f}")

    e = _ratio(*mc_counts(cards("As", "Ah"), [], 4, 2000))
    check("AA vs4 ≈ 0.56 (멀티웨이 하락)", 0.45 <= e <= 0.68, f"={e:.3f}")

    # 넛플러시 드로우 (A하이 포함): 뜨거나 A페어로도 이김 → ~0.65
    e = _ratio(*mc_counts(cards("Ah", "5h"), cards("Kh", "9h", "2s"), 1, 2000))
    check("넛플러시드로우 ≈ 0.65", 0.55 <= e <= 0.75, f"={e:.3f}")


def test_multiway_tie_share():
    print("\n[E-13] 멀티웨이 동률 1/k (T-032)")
    from ai.equity import RangeSampler, ranged_equity
    royal = cards("As", "Ks", "Qs", "Js", "Ts")  # 모두 보드를 플레이 → 전원 스플릿
    hole = cards("2c", "3d")
    for n_opp, expect in ((1, 1 / 2), (2, 1 / 3), (5, 1 / 6)):
        e = _ratio(*mc_counts(hole, royal, n_opp, 200))
        check(f"로열 보드 vs{n_opp} = 1/{n_opp + 1}", abs(e - expect) < 1e-9, f"={e:.4f}")
    # 레인지 경로도 같은 공식
    e = ranged_equity(hole, royal, [RangeSampler({"88": 1.0}), None], 200)
    check("ranged 로열 보드 vs2 = 1/3", abs(e - 1 / 3) < 1e-9, f"={e:.4f}")
    # 일부만 동률: 나·상대A 동률, 상대B 패 → 1/2 (리버, 레인지로 고정)
    board = cards("Ah", "Kd", "8c", "5s", "2h")
    e = ranged_equity(cards("Qc", "Jd"), board,
                      [RangeSampler({"QJo": 1.0}), RangeSampler({"43s": 1.0})], 300)
    # QJo 콤보 중 Qc/Jd 블록 제외 나머지 전부 같은 하이카드 → 동률, 43s는 5-high 스트레이트(A-5)로 승
    check("43s(휠) 상대 포함 시 0", e == 0.0, f"={e:.4f}")
    e = ranged_equity(cards("Qc", "Jd"), board,
                      [RangeSampler({"QJo": 1.0}), RangeSampler({"76s": 1.0})], 300)
    check("나·상대A 동률 + 상대B 패 = 1/2", abs(e - 0.5) < 1e-9, f"={e:.4f}")

    # smart_equity 멀티웨이(적응형 MC) 경로도 같은 공식
    e2 = smart_equity(hole, royal, 2)
    check("smart_equity 로열 보드 vs2 = 1/3", abs(e2 - 1 / 3) < 1e-9, f"={e2:.4f}")
    e1 = smart_equity(hole, royal, 1)  # 리버 1:1 = 전수
    check("smart_equity 로열 보드 vs1 (전수) = 1/2", abs(e1 - 1 / 2) < 1e-9, f"={e1:.4f}")

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    prev_env = os.environ.get("EV_PLUS_DB")
    os.environ["EV_PLUS_DB"] = tmp  # 세션 기록(recorder)도 임시 DB로
    try:
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
        check("패널 source = 실제 경로 mc:N", info is not None
              and info["source"] == f"mc:{info['samples']}" and info["samples"] >= 500,
              f"={info and (info['source'], info['samples'])}")
    finally:
        if prev_env is None:
            os.environ.pop("EV_PLUS_DB", None)
        else:
            os.environ["EV_PLUS_DB"] = prev_env
        if os.path.exists(tmp):
            os.remove(tmp)


def test_equity_paths():
    print("\n[E-4] 계산 경로 선택 — 프리플랍=테이블, 리버 1:1=전수, 그 밖=MC (ADR 0034)")
    random.seed(1)
    flop = (cards("Ah", "Kd"), cards("Qs", "7h", "2c"))
    river = (cards("As", "Ah"), cards("Ad", "Ac", "Kh", "Qd", "2s"))
    r = equity_detail(*river, 1)
    check("리버 1:1 → exact 990조합 (쿼드 = 1.0)",
          r.source == "exact" and r.samples == 990 and r.equity == 1.0, f"={r}")
    r = equity_detail(*river, 1, 40)
    check("리버 1:1은 샘플 수를 고정해도(easy) 전수", r.source == "exact", f"={r}")
    r = equity_detail(*flop, 1)
    check("플랍 → 적응형 MC (500~2,500 샘플)",
          r.source == f"mc:{r.samples}" and 500 <= r.samples <= 2_500, f"={r}")
    r = equity_detail(*flop, 1, 40)
    check("샘플 수 고정(easy 40) → mc:40", r.source == "mc:40" and r.samples == 40, f"={r}")
    r = equity_detail(cards("Ah", "Kd"), [], 1, 40)
    check("프리플랍은 샘플 수를 고정해도 테이블", r.source == "preflop-table", f"={r}")
    r = equity_detail(river[0], river[1], 2)
    check("리버 멀티웨이 → MC", r.source.startswith("mc:"), f"={r}")
    try:
        equity_detail(cards("Ah", "Kd"), cards("Ah", "7h", "2c"), 1)
        check("중복 카드 → ValueError", False)
    except ValueError:
        check("중복 카드 → ValueError", True)


def test_mc_precision():
    print("\n[E-15] 적응형 MC 정밀도 — 같은 스팟 반복 시 표준오차 ≤ 1%p (ADR 0045)")
    import statistics
    from ai.equity import TARGET_SE
    random.seed(15)
    # 턴 1:1: 정답을 전수(4.5만 조합)로 구해 추정치와 대조. p≈0.5 근처라 샘플이 가장 많이 필요한 스팟.
    hole, board = cards("Ah", "5h"), cards("Kh", "9h", "2s", "3c")  # 넛플러시 드로우 + 휠 드로우
    w, t, n = exact_counts_turn(hole, board)
    truth = (w + 0.5 * t) / n
    runs = [equity_detail(hole, board, 1) for _ in range(30)]
    ests = [r.equity for r in runs]
    sd = statistics.pstdev(ests)
    bias = statistics.mean(ests) - truth
    # 30회 표본 표준편차의 상대 오차 ≈ 13% → 3σ 상한 ≈ 1.4배
    check(f"턴 1:1 반복 30회 표준편차 {sd:.4f} ≤ {TARGET_SE}×1.4", sd <= TARGET_SE * 1.4,
          f"={sd:.4f}")
    check(f"턴 1:1 평균 {statistics.mean(ests):.4f} ≈ 전수 {truth:.4f} (±3·SE/√30)",
          abs(bias) <= 3 * TARGET_SE / 30 ** 0.5, f"차이={bias:+.4f}")
    within = sum(1 for e in ests if abs(e - truth) <= 2 * TARGET_SE)
    check(f"개별 추정 {within}/30이 전수값 ±2%p(2σ) 안", within >= 25, f"={within}")
    # 플랍 3인: 반복 표준편차만 검사(정답 전수는 비쌈)
    hole, board = cards("Jc", "Td"), cards("9s", "8h", "2c")
    ests = [smart_equity(hole, board, 2) for _ in range(20)]
    sd = statistics.pstdev(ests)
    check(f"플랍 vs2 반복 20회 표준편차 {sd:.4f} ≤ {TARGET_SE}×1.5", sd <= TARGET_SE * 1.5,
          f"={sd:.4f}")
    # easy(고정 40샘플)는 의도적으로 목표보다 거칠다 (ADR 0014)
    ests = [smart_equity(hole, board, 2, 40) for _ in range(30)]
    check("easy 40샘플은 표준편차가 목표보다 크다(해상도 차이 유지)",
          statistics.pstdev(ests) > TARGET_SE * 3, f"={statistics.pstdev(ests):.4f}")

    # 레인지 반영 에퀴티(hard 봇·패널 vs_range)도 같은 목표 (ADR 0045)
    from itertools import product
    from ai.equity import ranged_equity, RangeSampler, _showdown_share, _notation_combos
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
    samplers = [RangeSampler({"AA": 1, "55": 1}), RangeSampler({"AA": 1, "66": 1})]
    ests = [ranged_equity(hole, board, samplers) for _ in range(30)]
    sd = statistics.pstdev(ests)
    check(f"레인지 2명 리버 반복 30회 표준편차 {sd:.4f} ≤ {TARGET_SE}×1.4", sd <= TARGET_SE * 1.4,
          f"={sd:.4f}")
    bias = statistics.mean(ests) - truth
    check(f"레인지 2명 평균 {statistics.mean(ests):.4f} ≈ 전수 {truth:.4f} (±3·SE/√30)",
          abs(bias) <= 3 * TARGET_SE / 30 ** 0.5, f"차이={bias:+.4f}")
    ests = [ranged_equity(cards("Qh", "Qd"), cards("7c", "4d", "2s"),
                          [RangeSampler({"AA": 1, "KK": 1, "AKs": 1})]) for _ in range(20)]
    sd = statistics.pstdev(ests)
    check(f"레인지 1명 플랍 반복 20회 표준편차 {sd:.4f} ≤ {TARGET_SE}×1.5", sd <= TARGET_SE * 1.5,
          f"={sd:.4f}")


def test_no_db_writes():
    print("\n[E-16] 에퀴티 계산은 DB를 열지 않는다 — 게임을 쳐도 에퀴티 행이 늘지 않음 (ADR 0034)")
    import sqlite3
    import ai.equity as eq_mod
    from ai.equity import ranged_equity, RangeSampler
    real_connect = sqlite3.connect
    calls = []

    def spy(*a, **k):
        calls.append(a)
        return real_connect(*a, **k)

    sqlite3.connect = spy
    try:
        random.seed(2)
        hole = cards("Ah", "Kd")
        for board in ([], cards("Qs", "7h", "2c"), cards("Qs", "7h", "2c", "9d"),
                      cards("Qs", "7h", "2c", "9d", "3s")):
            for n_opp in (1, 3):
                equity_detail(hole, board, n_opp)
                smart_equity(hole, board, n_opp, 40)
        ranged_equity(hole, cards("Qs", "7h", "2c"), [RangeSampler({"QQ": 1.0})], 100)
        # medium 봇 포스트플랍 판단(적응형 MC 경로)
        bot = _make_bot(["Ah", "Kd"], BotDifficulty.MEDIUM)
        bot.decide_action(_bot_state("플랍", ["Qs", "7h", "2c"], 100, 0))
    finally:
        sqlite3.connect = real_connect
    check("에퀴티·봇 판단 중 sqlite3.connect 호출 0회", not calls, f"={len(calls)}회")
    src = open(eq_mod.__file__, encoding="utf-8").read()
    check("ai/equity.py가 DB 모듈을 참조하지 않음",
          "get_connection" not in src and "import sqlite3" not in src and "db.connection" not in src)

    # 실제 세션 경로: 새 DB에 에퀴티 테이블이 생기지 않고, 패널을 여러 번 계산해도 그대로
    from server.session import WebGameSession
    from core.game import Street
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    os.remove(tmp)  # get_connection이 새로 만들게
    prev_env = os.environ.get("EV_PLUS_DB")
    os.environ["EV_PLUS_DB"] = tmp
    try:
        s = WebGameSession(session_id="t036", human_name="Hero", chips=2000,
                           num_bots=2, difficulty="medium", small_blind=10)
        for p in s.game.players:
            p.is_folded = False
        s.human.hole_cards = cards("Ah", "Kd")
        for st, board in ((Street.PREFLOP, []), (Street.FLOP, cards("Qs", "7h", "2c")),
                          (Street.RIVER, cards("Qs", "7h", "2c", "9d", "3s"))):
            s.game.community_cards = board
            s.game.current_street = st
            s._equity_cache = {}
            info = s._get_equity_info()
            if st == Street.PREFLOP:
                check("패널 프리플랍 source = preflop-table", info["source"] == "preflop-table",
                      f"={info['source']}")
        from db.connection import get_connection
        conn = get_connection(tmp)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        eq_tables = sorted(t for t in tables if t.startswith("equity") or t == "worker_meta")
        check("새 DB에 equity_cache·equity_cache_stats·worker_meta 없음", not eq_tables,
              f"={eq_tables}")
        check("게임 기록 테이블은 그대로 생성", "games" in tables, f"={sorted(tables)}")
    finally:
        if prev_env is None:
            os.environ.pop("EV_PLUS_DB", None)
        else:
            os.environ["EV_PLUS_DB"] = prev_env
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(tmp + suffix):
                os.remove(tmp + suffix)


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


def test_ranged_equity():
    print("\n[E-8] 레인지 기반 equity")
    from ai.equity import RangeSampler, ranged_equity

    random.seed(11)
    # KK vs {AA만} 레인지 → ~0.18 (압도적 열세)
    aa_only = RangeSampler({"AA": 1.0})
    e = ranged_equity(cards("Kh", "Kd"), [], [aa_only], 800)
    check("KK vs AA레인지 ≈ 0.18", 0.10 <= e <= 0.28, f"={e:.3f}")

    # KK vs 랜덤 → ~0.82, 레인지가 좁아지면 하락해야 함
    e_random = _ratio(*mc_counts(cards("Kh", "Kd"), [], 1, 800))
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
    from ai.equity import _showdown_share, _notation_combos
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
    est = ranged_equity(hole, board,
                        [RangeSampler({"AA": 1, "55": 1}), RangeSampler({"AA": 1, "66": 1})], n)
    se = (truth * (1 - truth) / n) ** 0.5
    check(f"좁은 레인지 2명 결합분포: 정답 {truth:.3f}, 추정 {est:.3f} (3σ={3*se:.3f})",
          abs(est - truth) < 3 * se, f"차이={est - truth:+.3f}")
    # 순서를 바꿔도 같은 분포
    est2 = ranged_equity(hole, board,
                         [RangeSampler({"AA": 1, "66": 1}), RangeSampler({"AA": 1, "55": 1})], n)
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
        e_u = _ratio(*mc_counts(cards("Qh", "Qd"), [], 1, 800))
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
    prev_env = os.environ.get("EV_PLUS_DB")
    os.environ["EV_PLUS_DB"] = tmp
    try:
        conn = get_connection()
        # 좁은 SB RFI(AA·KK) + BB vs SB 콜 레인지(QQ·JJ)를 시딩
        for pos, vs, rtype, seq, hands in (
                ("SB", None, "open", "F-F-F-F", {"AA": (0, 1), "KK": (0, 1)}),
                ("BB", "SB", "vs_open", "F-F-F-F-R3", {"QQ": (1, 0), "JJ": (1, 0)})):
            sid = conn.execute(
                "INSERT INTO gto_preflop_situations (position, vs_position, range_type, "
                "raise_size, situation_label, action_seq) VALUES (?,?,?,3.0,?,?)",
                (pos, vs, rtype, f"{pos} {rtype}", seq),
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
        gto_loader._cache = {}
        gto_loader._loaded = False
        if prev_env is None:
            os.environ.pop("EV_PLUS_DB", None)
        else:
            os.environ["EV_PLUS_DB"] = prev_env
        if os.path.exists(tmp):
            os.remove(tmp)


def _three_bet_pot_state():
    """UTG(Villain) 2.5bb 오픈 → BTN(Bot) 8bb 3벳 → UTG 콜, 플랍 Q 아래 로우 보드.
    레인지 출발점이 action_log든 preflop_seq든 같은 핸드가 되도록 둘 다 채운다."""
    st = _bot_state("플랍", ["7c", "4d", "2s"], 340, 0,
                    positions={"Bot": "BTN", "Villain": "UTG"})
    st["action_log"] = ["[UTG] Villain: 레이즈 (50)", "[BTN] Bot: 레이즈 (160)",
                        "[UTG] Villain: 콜 (110)", "── 플랍 ──"]
    st["preflop_seq"] = [
        {"position": "UTG", "action": "raise", "amount_bb": 2.5},
        {"position": "BTN", "action": "raise", "amount_bb": 8.0},
        {"position": "UTG", "action": "call", "amount_bb": 8.0},
    ]
    return st


def test_medium_range_flag():
    print("\n[E-6d] 3벳팟 레인지 분기: hard·medium+use_ranges는 ranged_equity, medium 기본·easy는 vs 랜덤 (T-005)")
    import gto.loader as gto_loader
    import ai.bot as bot_mod
    from db.connection import get_connection

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    prev_env = os.environ.get("EV_PLUS_DB")
    os.environ["EV_PLUS_DB"] = tmp
    try:
        conn = get_connection()
        # UTG 레인지를 AA·KK만으로 좁게 심는다(RFI 오픈 + BTN 3벳에 대한 콜 노드 둘 다)
        for pos, vs, rtype, seq, col in (
                ("UTG", None, "open", "", "freq_raise"),
                ("UTG", "BTN", "vs_3bet", "R2.5-F-F-R8-F-F", "freq_call")):
            sid = conn.execute(
                "INSERT INTO gto_preflop_situations (position, vs_position, range_type, "
                "raise_size, situation_label, action_seq) VALUES (?,?,?,2.5,?,?)",
                (pos, vs, rtype, f"{pos} {rtype}", seq),
            ).lastrowid
            for hand in ("AA", "KK"):
                conn.execute(
                    f"INSERT INTO gto_preflop_hands (situation_id, hand, freq_fold, {col}) "
                    "VALUES (?,?,0,1)", (sid, hand))
        conn.commit()
        conn.close()
        gto_loader._cache = {}
        gto_loader._loaded = False

        # T-005 아레나 측정(ADR 0041)에서 채택 기준 미달 → medium 기본값은 vs 랜덤 유지
        check("medium 프로파일 use_ranges = False (T-005 측정 결과 미채택)",
              bot_mod.POSTFLOP_PROFILES["medium"]["use_ranges"] is False)
        check("hard 프로파일 use_ranges = True",
              bot_mod.POSTFLOP_PROFILES["hard"]["use_ranges"] is True)
        check("easy 프로파일 use_ranges = False (vs 랜덤 40샘플 유지)",
              bot_mod.POSTFLOP_PROFILES["easy"]["use_ranges"] is False)

        # QQ on 742r: vs 랜덤 ≈ 0.82, vs {AA,KK} ≈ 0.085
        eq_u = smart_equity(cards("Qh", "Qd"), cards("7c", "4d", "2s"), 1, None)
        random.seed(5)
        med = _make_bot(["Qh", "Qd"], BotDifficulty.MEDIUM)
        med.decide_action(_three_bet_pot_state())
        check(f"medium(기본) 3벳팟 last_equity(={med.last_equity})는 vs 랜덤 쪽(> 0.65)",
              med.last_equity is not None and med.last_equity > 0.65)
        # 아레나 측정에 쓴 경로: medium + use_ranges 오버라이드 → ranged_equity
        random.seed(5)
        bot = PokerBot(med.player, BotDifficulty.MEDIUM, overrides={"use_ranges": 1.0})
        bot.decide_action(_three_bet_pot_state())
        eq_r = bot.last_equity
        check(f"medium+use_ranges 3벳팟 last_equity(={eq_r}) ≈ vs AA·KK(< 0.35), vs 랜덤(={eq_u:.3f})과 다름",
              eq_r is not None and eq_r < 0.35 and eq_u > 0.65)
        hard = _make_bot(["Qh", "Qd"], BotDifficulty.HARD)
        hard.decide_action(_three_bet_pot_state())
        check(f"hard 3벳팟 last_equity(={hard.last_equity}) < 0.35 (레인지 반영)",
              hard.last_equity is not None and hard.last_equity < 0.35)

        # 같은 상황에서 easy는 레인지를 조회하지 않는다(경로 분기 확인)
        easy = _make_bot(["Qh", "Qd"], BotDifficulty.EASY)
        called = []
        easy._opponent_ranges = lambda state, opps: called.append(1) or None
        easy.decide_action(_three_bet_pot_state())
        check("easy는 상대 레인지를 조회하지 않음", not called, f"={len(called)}회")
        check("easy last_equity는 vs 랜덤 쪽(> 0.5)", easy.last_equity is not None
              and easy.last_equity > 0.5, f"={easy.last_equity}")
    finally:
        gto_loader._cache = {}
        gto_loader._loaded = False
        if prev_env is None:
            os.environ.pop("EV_PLUS_DB", None)
        else:
            os.environ["EV_PLUS_DB"] = prev_env
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(tmp + suffix):
                os.remove(tmp + suffix)


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


def test_made_hand_rank():
    print("\n[E-7] made hand rank (드로우 판별)")
    r = made_hand_rank(cards("Ah", "5h"), cards("Kh", "9h", "2s"))
    check("플러시 드로우 = 하이카드(1)", r == 1, f"={r}")
    r = made_hand_rank(cards("Ks", "9d"), cards("Kh", "9h", "2s"))
    check("투페어 = 3", r == 3, f"={r}")


def test_has_draw():
    print("\n[E-7b] 봇 드로우 판정은 아웃 기반 (플러시 드로우 / OESD / 거트샷, ADR 0049)")
    # 오버카드만: 옛 기준(equity ≥ 0.30)은 드로우로 봤다 — AK on Q72r eq ≈ 0.555
    check("AK on Q72r 드로우 아님", not has_draw(cards("Ah", "Kd"), cards("Qs", "7c", "2h")))
    check("KQ on J72r 드로우 아님", not has_draw(cards("Kh", "Qd"), cards("Js", "7c", "2h")))
    check("98s on 762 OESD", has_draw(cards("9h", "8h"), cards("7s", "6c", "2d")))
    check("A5 on K43 거트샷(2)", has_draw(cards("Ah", "5d"), cards("Ks", "4c", "3h")))
    check("A5s on K93 드로우 아님(백도어뿐)", not has_draw(cards("Ah", "5h"), cards("Ks", "9c", "3d")))
    check("JT on Q93 거트샷(K)", has_draw(cards("Jh", "Td"), cards("Qs", "9c", "3h")))
    check("A5s on Kh9h2s 플러시 드로우", has_draw(cards("Ah", "5h"), cards("Kh", "9h", "2s")))
    check("플랍 3장 같은 수트 = 백도어, 드로우 아님", not has_draw(cards("Ah", "5h"), cards("Kh", "9c", "2s")))
    check("턴 플러시 드로우(홀 1장 + 보드 3장)", has_draw(cards("Ah", "5d"), cards("Kh", "9h", "2h", "3c")))
    check("보드만 4연속(홀 무관) 거트샷 포함", has_draw(cards("Ah", "2d"), cards("9s", "8c", "7h", "6d")))
    check("완성 스트레이트는 드로우 아님(메이드)", not has_draw(cards("Th", "9d"), cards("8s", "7c", "6h")))
    check("휠 거트샷 A-2-3-5 → 4", has_draw(cards("Ah", "2d"), cards("3s", "5c", "9h")))
    check("브로드웨이 OESD JQ on KT2", has_draw(cards("Jh", "Qd"), cards("Ks", "Tc", "2h")))
    # 봇 판단에서 쓰이는 방식: 메이드 핸드(페어 이상)·리버는 호출자가 제외
    # KQ on J72r(eq ≈ 0.485): medium은 밸류(≥0.55)도 순수 블러프(<0.30)도 아니라 체크만 나와야 한다.
    # 옛 기준(equity ≥ 0.30 = 드로우)이면 BTN 세미블러프 40%가 섞였다.
    random.seed(3)
    bot = _make_bot(["Kh", "Qd"], BotDifficulty.MEDIUM)
    st = _bot_state("플랍", ["Js", "7c", "2h"], 100, 0)
    bets = sum(bot.decide_action(st)[0] in (Action.RAISE, Action.ALL_IN) for _ in range(30))
    check("KQ 오버카드 플랍 30회 벳 0 (세미블러프 경로 없음)", bets == 0, f"bets={bets}/30")


def test_bot_no_open_fold():
    print("\n[E-6b] 봇은 콜할 금액이 0이면 폴드하지 않는다(오픈 폴드 금지)")
    bot = _make_bot(["7c", "2d"], BotDifficulty.MEDIUM)
    # 내부 판단이 FOLD를 내더라도 decide_action은 체크로 바꾼다
    bot._postflop_decision = lambda state: (Action.FOLD, 0)
    st = _bot_state("플랍", ["As", "Kh", "Qd"], 100, 0)
    check("벳 없는 플랍 FOLD → CHECK", bot.decide_action(st) == (Action.CHECK, 0), f"={bot.decide_action(st)}")
    st_pre = _bot_state("프리플랍", [], 30, 20)
    bot.player.current_bet = 20  # BB, 림프 팟 → 콜 금액 0
    bot._try_gto_action = lambda state: (Action.FOLD, 0)
    check("프리플랍 BB 옵션 FOLD → CHECK", bot.decide_action(st_pre) == (Action.CHECK, 0))
    # 콜 금액이 있으면 폴드는 그대로
    bot.player.current_bet = 0
    bot._postflop_decision = lambda state: (Action.FOLD, 0)
    st2 = _bot_state("플랍", ["As", "Kh", "Qd"], 100, 50)
    check("콜 금액 50이면 FOLD 유지", bot.decide_action(st2) == (Action.FOLD, 0))


def test_role_unknown_without_range():
    print("\n[E-6c] 상대 레인지 데이터가 없으면 role = unknown")
    import gto.loader as gto_loader
    # 이 테스트의 DB(EV_PLUS_DB 임시)에는 GTO 데이터가 없다 → 레인지 조회가 None
    gto_loader._cache = {}
    gto_loader._loaded = False
    try:
        state = {
            "positions": {"Bot": "BB", "V1": "UTG", "V2": "CO"},
            "action_log": ["[UTG] V1: 레이즈 → 50", "[CO] V2: 콜 (50)", "[BB] Bot: 콜 (30)", "── 플랍 ──"],
        }
        info = opponent_range_info(state, [{"name": "V1", "is_folded": False}, {"name": "V2", "is_folded": False}])
        check("레인지 없음 → sampler None", all(s is None for s, _ in info), f"={info}")
        check("레이저도 콜러도 role unknown", [r for _, r in info] == ["unknown", "unknown"], f"={[r for _, r in info]}")
        check("sampler 없는 상대는 항상 unknown", all(r == "unknown" for s, r in info if s is None))
    finally:
        gto_loader._cache = {}
        gto_loader._loaded = False


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


def test_gto_allin_action_and_hint():
    """[E-13] T-014: GTO 샘플 액션이 allin이면 봇이 Action.ALL_IN을 실행하고,
    사람 힌트 문자열에 '올인 N%'가 번역돼 보인다(ADR 0002 "화면 그대로만" —
    allin을 레이즈로 뭉개거나 휴리스틱으로 떨어뜨리지 않음)."""
    print("\n[E-13] GTO 올인 처리 (T-014)")
    from db.connection import get_connection
    import gto.loader as gto_loader
    from gto.advisor import GTOAdvisor

    conn = get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO gto_preflop_situations "
        "(position, vs_position, range_type, raise_size, situation_label, action_seq) "
        "VALUES ('UTG', NULL, 'open', 2.5, 'UTG RFI(올인 테스트)', '')"
    )
    conn.commit()
    sid = conn.execute(
        "SELECT id FROM gto_preflop_situations "
        "WHERE position='UTG' AND range_type='open' AND vs_position IS NULL"
    ).fetchone()["id"]
    conn.execute(
        "INSERT OR IGNORE INTO gto_preflop_hands "
        "(situation_id, hand, freq_fold, freq_call, freq_raise, freq_allin) "
        "VALUES (?, 'AA', 0.0, 0.0, 0.0, 1.0)", (sid,)
    )
    conn.commit()
    conn.close()
    gto_loader._cache = {}
    gto_loader._loaded = False

    # 힌트 문자열: "올인 100%" 번역 확인 (gto/advisor.py format_hint)
    advisor = GTOAdvisor()
    gs = {"street": "프리플랍", "current_bet": 20, "preflop_seq": []}
    rec = advisor.get_recommendation(cards("Ac", "Ad"), "UTG", {"Bot": "UTG"}, gs, big_blind=20)
    check("올인 100% 레인지 조회됨", rec is not None and rec["frequencies"].get("allin") == 1.0,
          f"rec={rec}")
    hint = advisor.format_hint(rec)
    check("힌트에 '올인 100%' 번역 포함", hint is not None and "올인 100%" in hint, f"hint={hint}")

    # 봇: sample_action이 "allin"으로 고정된 스팟에서, hard 봇이 준수율(0.95)만큼
    # Action.ALL_IN을 실행한다(레이즈로 뭉개지거나 휴리스틱 폴백으로 새지 않음).
    random.seed(42)
    N = 60
    allins = 0
    for _ in range(N):
        p = Player("Bot", chips=1000, is_human=False)
        p.hole_cards = cards("Ac", "Ad")
        bot = PokerBot(p, BotDifficulty.HARD)
        st = {
            "street": "프리플랍", "pot": 30, "current_bet": 20, "min_raise": 20, "big_blind": 20,
            "positions": {"Bot": "UTG"}, "preflop_seq": [],
            "players": [
                {"name": "Bot", "chips": 1000, "current_bet": 0,
                 "is_folded": False, "is_all_in": False, "is_human": False},
            ],
        }
        action, _ = bot.decide_action(st)
        if action == Action.ALL_IN:
            allins += 1
    check("hard 봇이 GTO allin(freq=1.0)을 준수율만큼 Action.ALL_IN으로 실행",
          allins >= int(N * 0.8), f"allins={allins}/{N} (기대: 준수율 0.95 근방)")


if __name__ == "__main__":
    print("=" * 50)
    print("  에퀴티 엔진 + 봇 테스트")
    print("=" * 50)

    test_preflop_table()
    test_exact_river()
    test_mc_sanity()
    test_multiway_tie_share()
    test_equity_paths()
    test_mc_precision()
    test_no_db_writes()
    test_board_wetness()
    test_bot_decisions()
    test_ranged_equity()
    test_headsup_range_uses_sb()
    test_medium_range_flag()
    test_fast_evaluator()
    test_made_hand_rank()
    test_has_draw()
    test_bot_no_open_fold()
    test_role_unknown_without_range()
    test_grader()
    test_gto_allin_action_and_hint()

    print(f"\n{'='*50}")
    print(f"  결과: {PASS} 통과 / {FAIL} 실패")
    print(f"{'='*50}")
    sys.exit(1 if FAIL else 0)
