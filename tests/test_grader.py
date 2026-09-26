#!/usr/bin/env python3
"""
플레이 평가 (Play Grader) + 세션 에퀴티 패널 테스트

실행: python3 tests/test_grader.py
"""

import sys
import os
import random
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── 테스트 격리 ──────────────────────────────────────────
# WebGameSession을 통해 GameRecorder/equity 캐시가 실제로 DB에 쓰기 때문에
# 실 DB(그라인드 데이터)와 격리한다 — tests/test_poker_full.py와 동일 방침
# (근거: docs/decisions/0026-stubbot-and-isolated-test-db.md).
os.environ["EV_PLUS_DB"] = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name

from core.card import Card, Suit, Rank
from gto.grader import (
    grade_preflop_action, grade_postflop_call, grade_postflop_fold,
    grade_postflop_bet_or_raise,
)

_RANK = {r.symbol: r for r in Rank}
_RANK["T"] = Rank.TEN
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


def test_preflop_grading():
    print("\n[G-1] 프리플랍 GTO 빈도 판정")
    rec = {"hand": "AKs", "frequencies": {"fold": 0.0, "call": 0.15, "raise": 0.85},
           "situation": "BTN RFI", "raise_size": "2.5bb", "raise_count": 0}

    r = grade_preflop_action("raise", rec)
    check("최고빈도 액션 = ✅", r.grade == "✅", f"={r.grade}")

    r = grade_preflop_action("call", rec)
    check("빈도 15% (5~25%) = 🟠", r.grade == "🟠", f"={r.grade}")

    r = grade_preflop_action("fold", rec)
    check("빈도 0% = 🔴", r.grade == "🔴", f"={r.grade}")

    rec2 = {"frequencies": {"fold": 0.55, "call": 0.35, "raise": 0.10}}
    r = grade_preflop_action("call", rec2)
    check("빈도 35% (>25%) = 🟡", r.grade == "🟡", f"={r.grade}")

    r = grade_preflop_action("fold", rec2)
    check("최고빈도 폴드 = ✅", r.grade == "✅", f"={r.grade}")

    r = grade_preflop_action("raise", None)
    check("데이터 없음 = ⬜", r.grade == "⬜", f"={r.grade}")

    r = grade_preflop_action("raise", {"frequencies": {}})
    check("빈 frequencies = ⬜", r.grade == "⬜", f"={r.grade}")


def test_postflop_call_grading():
    print("\n[G-2] 포스트플랍 콜 판정")
    # equity 60%, 팟 100, 콜 50 → EV = 0.6*150 - 50 = +40 → 좋은 콜
    r = grade_postflop_call(0.60, 100, 50, 20)
    check("+EV 콜 = ✅", r.grade == "✅", f"={r.grade}")
    check("+EV 콜 손실 없음", r.ev_loss_bb is None)

    # equity 20%, 팟 100, 콜 100 → EV = 0.2*200 - 100 = -60 → 블런더
    r = grade_postflop_call(0.20, 100, 100, 20)
    check("-EV 콜 감점", r.grade in ("🔴", "🟠"), f"={r.grade}")
    check("-EV 콜 손실 bb 산출", r.ev_loss_bb is not None and abs(r.ev_loss_bb) > 0,
          f"={r.ev_loss_bb}")
    check("손실 -60칩 = 3bb", r.ev_loss_bb is not None and abs(abs(r.ev_loss_bb) - 3.0) < 0.01,
          f"={r.ev_loss_bb}")


def test_short_stack_effective_call():
    print("\n[G-6] 숏스택 유효 콜·유효 팟 (T-033)")
    from core.pot_odds import effective_call_pot, pot_odds, call_ev

    # 리뷰 예시: 팟 100, 상대 1,000 올인, 내 스택 100, 에퀴티 40%
    #   실제: 100을 내고 300을 다툼 → EV = 0.4×300 − 100 = +20
    eff_call, eff_pot = effective_call_pot(1100, 1000, 100, 0, [1000])
    check("유효 콜 = 남은 칩 100", eff_call == 100, f"={eff_call}")
    check("유효 팟 = 200 (상대 초과분 900 제외)", eff_pot == 200, f"={eff_pot}")
    check("유효 팟오즈 = 1/3", abs(pot_odds(eff_call, eff_pot) - 1 / 3) < 1e-9)
    check("콜 EV = +20", abs(call_ev(0.4, eff_call, eff_pot) - 20) < 1e-9)
    # 폴드한 상대의 데드 머니도 내 기여 한도까지만
    check("데드 머니 캡", effective_call_pot(600, 300, 100, 0, [300, 300]) == (100, 200))
    # 스택 충분하면 원값 그대로
    check("딥스택 = 원값", effective_call_pot(300, 100, 5000, 0, [100]) == (100, 300))

    r = grade_postflop_call(0.40, 1100, 1000, 20, stack=(100, 0, [1000]))
    check("리뷰 예시 콜 = ✅", r.grade == "✅", f"={r.grade} {r.reason}")
    check("리뷰 예시 EV +20 표기", "EV=20.0" in r.reason, f"={r.reason}")
    r = grade_postflop_fold(0.40, 1100, 1000, 20, stack=(100, 0, [1000]))
    check("같은 상황 폴드 = 놓친 EV 🔴 (+1bb)", r.grade == "🔴"
          and r.ev_loss_bb is not None and abs(r.ev_loss_bb - 1.0) < 1e-9,
          f"={r.grade} {r.ev_loss_bb}")

    # 실제 세션 경로: 패널 팟오즈·콜 EV + 복기 판정이 유효값 기준인지
    import tempfile
    from server.session import WebGameSession
    from core.game import Street, Action
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    prev_env = os.environ.get("EV_PLUS_DB")
    os.environ["EV_PLUS_DB"] = tmp
    try:
        random.seed(5)
        s = WebGameSession(session_id="t033", human_name="Hero", chips=2000,
                           num_bots=2, difficulty="easy", small_blind=10)
        villain, folder = [p for p in s.game.players if p is not s.human][:2]
        # 리버: 나 50 기여·스택 100, 상대 1,050 기여(이번 스트리트 1,000 올인), 한 명은 50 내고 폴드
        s.human.hole_cards = cards("Ah", "Jd")  # vs 1명 리버 exact 0.352
        s.game.community_cards = cards("Ks", "9d", "5c", "3h", "2s")
        s.game.current_street = Street.RIVER
        s.human.chips, s.human.total_bet_this_round, s.human.current_bet = 100, 50, 0
        s.human.is_folded = s.human.is_all_in = False
        villain.chips, villain.total_bet_this_round, villain.current_bet = 0, 1050, 1000
        villain.is_folded, villain.is_all_in = False, True
        folder.total_bet_this_round, folder.current_bet, folder.is_folded = 50, 0, True
        for p in s.game.players[3:]:
            p.is_folded, p.total_bet_this_round, p.current_bet = True, 0, 0
        s.game.pot = sum(p.total_bet_this_round for p in s.game.players)  # 1,150
        s.game.current_bet = 1000
        s._equity_cache = {}
        s.hand_reviews = []

        info = s._get_equity_info()
        eq_ = info["vs_random"]
        check("세션 에퀴티 = exact 0.352", abs(eq_ - 0.352) < 0.001, f"={eq_}")
        check("패널 팟오즈 = 100/350", abs(info["pot_odds"] - round(100 / 350, 4)) < 1e-9,
              f"={info['pot_odds']}")
        check("패널 콜 EV = (eq×350−100)/20 (양수)",
              abs(info["call_ev_bb"] - round((eq_ * 350 - 100) / 20, 2)) < 0.011
              and info["call_ev_bb"] > 0, f"={info['call_ev_bb']}")

        s._grade_human_action(s.human, Action.CALL, 0, Street.RIVER, 1000)
        rv = s.hand_reviews[-1] if s.hand_reviews else {}
        check("복기: 숏스택 콜 = ✅", rv.get("grade") == "✅", f"={rv}")
        check("복기 팟오즈 = 유효값", rv.get("pot_odds") == info["pot_odds"], f"={rv.get('pot_odds')}")
    finally:
        if prev_env is None:
            os.environ.pop("EV_PLUS_DB", None)
        else:
            os.environ["EV_PLUS_DB"] = prev_env
        if os.path.exists(tmp):
            os.remove(tmp)


def test_borderline_band():
    print("\n[G-7] 콜·폴드 경계 구간 — |에퀴티−팟오즈| < 2×표준오차 = ⬜ (ADR 0039, T-033)")
    from ai.equity import equity_detail, exact_counts_turn, standard_error, EquityResult

    # 표준오차: 전수·상수 테이블은 0, MC는 sqrt(p(1-p)/n)
    check("exact SE = 0", standard_error(EquityResult(0.4, "exact", 990)) == 0.0)
    check("preflop-table SE = 0", standard_error(EquityResult(0.6, "preflop-table", 10**6)) == 0.0)
    check("mc:2500 p=0.5 SE = 1%p", abs(standard_error(EquityResult(0.5, "mc:2500", 2500)) - 0.01) < 1e-12)

    # 순수 함수: 팟 200·콜 100 → 팟오즈 33.3%. SE 1%p → 경계 ±2%p
    r = grade_postflop_call(0.32, 200, 100, 20, se=0.01)
    check("오차 안 −EV 콜 = ⬜ 경계", r.grade == "⬜" and "경계" in r.reason, f"={r.grade} {r.reason}")
    check("경계 사유에 에퀴티·팟오즈·오차", all(k in r.reason for k in ("에퀴티 32.0%", "팟오즈 33.3%", "오차 ±2.0%p")),
          f"={r.reason}")
    r = grade_postflop_fold(0.35, 200, 100, 20, se=0.01)
    check("오차 안 폴드 = ⬜ 경계", r.grade == "⬜", f"={r.grade} {r.reason}")
    r = grade_postflop_call(0.25, 200, 100, 20, se=0.01)
    check("오차 밖 −EV 콜 = 🔴", r.grade == "🔴" and "오차 ±2.0%p" in r.reason, f"={r.grade} {r.reason}")
    r = grade_postflop_fold(0.45, 200, 100, 20, se=0.01)
    check("오차 밖 높은 에퀴티 폴드 = 🔴", r.grade == "🔴", f"={r.grade}")
    r = grade_postflop_call(0.33, 200, 100, 20, se=0.0)
    check("전수(se=0)는 경계 없음: 0.3%p 부족 콜도 🔴", r.grade == "🔴" and "오차 0(전수)" in r.reason,
          f"={r.grade} {r.reason}")
    r = grade_postflop_call(0.34, 200, 100, 20)
    check("전수 0.7%p 이득 콜 = ✅", r.grade == "✅" and "에퀴티 34.0%" in r.reason, f"={r.reason}")

    # 실제 MC 경로 반복: 턴 1:1(적응형 MC) 손익분기 스팟. 고치기 전엔 🔴/✅가 반반.
    hole, board = cards("Ah", "Td"), cards("Ks", "9d", "5c", "3h")
    w, t, n = exact_counts_turn(hole, board)
    exact_eq = (w + 0.5 * t) / n
    call = 1000
    pot = round(call * (1 - exact_eq) / exact_eq)  # 팟오즈 ≈ 정답 에퀴티
    random.seed(33)
    grades = []
    for _ in range(40):
        d = equity_detail(hole, board, 1)
        grades.append(grade_postflop_call(d.equity, pot, call, 20, se=standard_error(d)).grade)
    n_border = grades.count("⬜")
    check(f"손익분기 콜 40회 중 ⬜ ≥ 36 (2σ ≈ 95%) — 실제 {n_border}", n_border >= 36, f"={grades}")
    grades_f = []
    for _ in range(40):
        d = equity_detail(hole, board, 1)
        grades_f.append(grade_postflop_fold(d.equity, pot, call, 20, se=standard_error(d)).grade)
    check(f"손익분기 폴드 40회 중 ⬜ ≥ 36 — 실제 {grades_f.count('⬜')}", grades_f.count("⬜") >= 36,
          f"={grades_f}")
    far_pot = round(call * (1 - (exact_eq + 0.08)) / (exact_eq + 0.08))  # 팟오즈 = 정답+8%p
    bad = [grade_postflop_call(d.equity, far_pot, call, 20, se=standard_error(d)).grade
           for d in (equity_detail(hole, board, 1) for _ in range(10))]
    check("팟오즈가 8%p 높은 콜은 반복해도 항상 🔴", bad == ["🔴"] * 10, f"={bad}")

    # 세션 경로: 플랍 2인(적응형 MC) 콜 → 복기 사유에 오차, 에퀴티·팟오즈 근처면 ⬜
    import tempfile
    from server.session import WebGameSession
    from core.game import Street, Action
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    prev_env = os.environ.get("EV_PLUS_DB")
    os.environ["EV_PLUS_DB"] = tmp
    try:
        random.seed(9)
        s = WebGameSession(session_id="t033b", human_name="Hero", chips=5000,
                           num_bots=1, difficulty="easy", small_blind=10)
        villain = [p for p in s.game.players if p is not s.human][0]
        s.human.hole_cards = hole
        s.game.community_cards = board
        s.game.current_street = Street.TURN
        # 턴: 이전 스트리트까지 둘 다 mine씩, 상대가 이번 스트리트 call 벳 → 팟 = 2·mine + call.
        # 팟오즈 = call/(팟+call)이 정답 에퀴티(≈44.5%)가 되도록 mine을 맞춘다(1칩 반올림 오차).
        mine = (pot - call) // 2
        s.human.chips, s.human.total_bet_this_round, s.human.current_bet = 4000, mine, 0
        s.human.is_folded = s.human.is_all_in = False
        villain.chips = 3000
        villain.total_bet_this_round, villain.current_bet = mine + call, call
        villain.is_folded, villain.is_all_in = False, False
        s.game.current_bet = call
        s.game.pot = 2 * mine + call
        s._equity_cache = {}
        s.hand_reviews = []
        info = s._get_equity_info()
        check("세션 에퀴티 경로 = MC(오차 있음)", info["source"].startswith("mc:") and info["vs_random_se"] > 0,
              f"={info['source']} {info.get('vs_random_se')}")
        s._grade_human_action(s.human, Action.CALL, 0, Street.TURN, call)
        rv = s.hand_reviews[-1] if s.hand_reviews else {}
        check("세션 복기: 손익분기 콜 = ⬜ 경계", rv.get("grade") == "⬜", f"={rv}")
        check("세션 복기 사유에 에퀴티·팟오즈·오차", all(k in rv.get("reason", "") for k in ("에퀴티", "팟오즈", "오차 ±")),
              f"={rv.get('reason')}")
    finally:
        if prev_env is None:
            os.environ.pop("EV_PLUS_DB", None)
        else:
            os.environ["EV_PLUS_DB"] = prev_env
        if os.path.exists(tmp):
            os.remove(tmp)


def test_panel_vs_range_basis():
    print("\n[G-8] 에퀴티 패널 = vs_range 한 기준, 출처·표본 수 = 실제 계산 (T-006)")
    import gto.loader as gto_loader
    from db.connection import get_connection
    from server.session import WebGameSession
    from core.game import Street
    from core.pot_odds import effective_call_pot, call_ev

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    prev_env = os.environ.get("EV_PLUS_DB")
    os.environ["EV_PLUS_DB"] = tmp
    try:
        conn = get_connection()
        sid = conn.execute(
            "INSERT INTO gto_preflop_situations (position, vs_position, range_type, raise_size, "
            "situation_label, action_seq) VALUES ('SB', NULL, 'open', 3.0, 'SB RFI', 'F-F-F-F')"
        ).lastrowid
        for hand in ("AA", "KK"):
            conn.execute("INSERT INTO gto_preflop_hands (situation_id, hand, freq_fold, freq_call, "
                         "freq_raise, freq_allin) VALUES (?,?,0,0,1,0)", (sid, hand))
        conn.commit()
        conn.close()
        gto_loader._cache = {}
        gto_loader._loaded = False

        random.seed(21)
        s = WebGameSession(session_id="t006", human_name="Hero", chips=2000,
                           num_bots=1, difficulty="easy", small_blind=10)
        bot_p = next(p for p in s.game.players if p is not s.human)
        s.game.dealer_index = s.game.players.index(bot_p)  # 봇 = BTN/SB 레이저
        for p in s.game.players:
            p.is_folded = p.is_all_in = False
        # 플랍: 프리플랍 봇 오픈·나 콜(각 60), 플랍에서 봇 100 벳 → 내 차례
        s.human.hole_cards = cards("Qh", "Qd")
        s.game.community_cards = cards("7c", "4d", "2s")
        s.game.current_street = Street.FLOP
        s.action_log = [f"[BTN/SB] {bot_p.name}: 레이즈 → 60", "[BB] Hero: 콜 (40)", "── 플랍 ──"]
        s.human.chips, s.human.total_bet_this_round, s.human.current_bet = 1940, 60, 0
        bot_p.chips, bot_p.total_bet_this_round, bot_p.current_bet = 1840, 160, 100
        s.game.current_bet, s.game.pot = 100, 220
        s._equity_cache = {}
        s.equity_history, s._equity_history_streets = [], set()

        info = s._get_equity_info()
        check("레인지 반영 표시", info["range_applied"] is True, f"={info}")
        check("vs_range(QQ vs AA·KK) ≠ vs_random", info["vs_range"] < 0.35 < 0.65 < info["vs_random"],
              f"range={info['vs_range']} random={info['vs_random']}")
        check("출처 = vs_range의 적응형 MC(mc:N, N=샘플 수)",
              info["source"] == f"mc:{info['samples']}" and 500 <= info["samples"] <= 2500,
              f"={info['source']} {info['samples']}")
        eff_call, eff_pot = effective_call_pot(220, 100, *s._human_stack())
        want_ev = round(call_ev(info["vs_range"], eff_call, eff_pot) / 20, 2)
        check("콜 EV = vs_range 기준", abs(info["call_ev_bb"] - want_ev) <= 0.011,
              f"={info['call_ev_bb']} want {want_ev}")
        check("스트리트 추이 = vs_range", info["history"] == [{"street": "플랍", "vs_range": info["vs_range"]}],
              f"={info['history']}")

        # 레인지 정보가 없으면(상대가 레이즈·콜 기록 없음) vs_random 계산 그대로 — 출처도 그것
        s.action_log = ["── 플랍 ──"]
        s._equity_cache = {}
        info2 = s._get_equity_info()
        check("레인지 없음 → range_applied=False, vs_range = vs_random",
              info2["range_applied"] is False and info2["vs_range"] == info2["vs_random"], f"={info2}")
        check("레인지 없음 출처 = vs_random 경로(mc:N)", info2["source"] == f"mc:{info2['samples']}",
              f"={info2['source']}")

        # 프리플랍: 사람 차례면 항상 에퀴티가 나온다(상수 테이블, 즉시) — 패널이 비는 이유 없음
        random.seed(3)
        s3 = WebGameSession(session_id="t006p", human_name="Hero", chips=2000,
                            num_bots=5, difficulty="easy", small_blind=10)
        st = s3.get_state()
        check("프리플랍 사람 차례에 에퀴티 존재", st["street"] == "프리플랍" and st["waiting_for_action"]
              and st["equity"] is not None, f"={st['street']} {st['waiting_for_action']} {st['equity']}")
        if st["equity"] and not st["equity"]["range_applied"]:
            check("프리플랍 레인지 없음 → 프리플랍 표 100만 샘플",
                  st["equity"]["source"] == "preflop-table" and st["equity"]["samples"] == 1_000_000,
                  f"={st['equity']['source']}")
    finally:
        gto_loader._cache = {}
        gto_loader._loaded = False
        if prev_env is None:
            os.environ.pop("EV_PLUS_DB", None)
        else:
            os.environ["EV_PLUS_DB"] = prev_env
        if os.path.exists(tmp):
            os.remove(tmp)


def test_postflop_fold_grading():
    print("\n[G-3] 포스트플랍 폴드 판정")
    # equity 15%, 팟오즈 33% → 정상 폴드
    r = grade_postflop_fold(0.15, 100, 50, 20)
    check("낮은 equity 폴드 = ✅", r.grade == "✅", f"={r.grade}")

    # equity 60%, 팟오즈 33% → 놓친 EV
    r = grade_postflop_fold(0.60, 100, 50, 20)
    check("높은 equity 폴드 감점", r.grade in ("🔴", "🟠"), f"={r.grade}")
    check("놓친 EV bb 산출", r.ev_loss_bb is not None and abs(r.ev_loss_bb) > 0,
          f"={r.ev_loss_bb}")

    # 경계: equity = 팟오즈 + 마진 이내 → 정상 폴드
    r = grade_postflop_fold(0.36, 100, 50, 20)  # 팟오즈 33.3% + 5% = 38.3%
    check("마진 이내 폴드 = ✅", r.grade == "✅", f"={r.grade}")


def test_postflop_bet_grading():
    print("\n[G-4] 벳/레이즈/체크 제한 판정 (v1)")
    # 고equity 체크 → 밸류 놓침 경고
    r = grade_postflop_bet_or_raise(0.80, "check")
    check("고equity 체크 = 경고", r.grade in ("⚠️", "🟡"), f"={r.grade}")

    # 저equity 레이즈 → 블러프 (중립성 판정)
    r = grade_postflop_bet_or_raise(0.20, "raise")
    check("저equity 레이즈 = 블러프 표시", "블러프" in r.reason, f"={r.reason}")
    check("블러프 = 블런더 아님", r.grade not in ("🔴", "🟠"), f"={r.grade}")

    # 평범한 상황 → 판정 유보
    r = grade_postflop_bet_or_raise(0.50, "raise")
    check("중간 equity 레이즈 = 판정 유보", r.grade in ("⬜", "⚪"), f"={r.grade}")


def test_session_equity_and_review():
    print("\n[G-5] 세션 에퀴티 패널 + 핸드 리뷰 통합")
    from server.session import WebGameSession
    from core.game import Street

    random.seed(7)
    session = WebGameSession(
        session_id="test", human_name="Hero", chips=2000,
        num_bots=2, difficulty="easy", small_blind=10,
    )

    # 넛급 핸드 강제 세팅: 리버 로열 플러시
    session.human.hole_cards = cards("As", "Ks")
    session.game.community_cards = cards("Qs", "Js", "Ts", "2d", "7c")
    session.game.current_street = Street.RIVER
    session._equity_calc_cache = {}

    info = session._get_equity_info()
    check("equity 정보 생성", info is not None)
    if info:
        check("넛 핸드 vs_random > 0.85", info["vs_random"] > 0.85,
              f"={info['vs_random']}")
        check("vs_range 존재", 0.0 <= info["vs_range"] <= 1.0, f"={info['vs_range']}")
        check("상대 수 일치", info["num_opponents"] == 2, f"={info['num_opponents']}")
        check("상대별 브레이크다운", len(info["opponents"]) == 2,
              f"={len(info['opponents'])}")
        roles = {o["role"] for o in info["opponents"]}
        check("role 값 유효", roles <= {"raiser", "caller", "unknown"}, f"={roles}")
        check("히스토리 누적", len(info["history"]) >= 1, f"={len(info['history'])}")

        # 같은 스트리트+상황 재호출 → 캐시 재사용 (동일 객체/값)
        info2 = session._get_equity_info()
        check("스트리트 내 캐시 재사용", info2["vs_random"] == info["vs_random"])

    # 핸드를 끝까지 진행해 hand_review 확인 (새 세션으로 정상 플로우)
    random.seed(11)
    session2 = WebGameSession(
        session_id="test2", human_name="Hero", chips=2000,
        num_bots=2, difficulty="easy", small_blind=10,
    )
    reviewed = False
    for _ in range(5):  # 사람이 액션할 기회가 없는 핸드 대비 최대 5핸드
        guard = 0
        while not session2.hand_over and not session2.game_over:
            state = session2.get_state()
            if state["waiting_for_action"]:
                call_amt = state["call_amount"]
                session2.submit_action("call" if call_amt > 0 else "check", 0)
            guard += 1
            if guard > 60:
                break
        state = session2.get_state()
        if state["hand_over"] and state["hand_review"]:
            reviewed = True
            hr = state["hand_review"]
            check("hand_review 존재", len(hr) >= 1, f"={len(hr)}")
            item = hr[0]
            check("리뷰 항목 필드", all(k in item for k in
                  ("street", "action", "grade", "reason")), f"={item}")
            break
        if session2.game_over:
            break
        session2.next_hand()
    check("핸드 리뷰 생성됨", reviewed)


if __name__ == "__main__":
    print("=" * 50)
    print("  플레이 평가 (Play Grader) 테스트")
    print("=" * 50)

    test_preflop_grading()
    test_postflop_call_grading()
    test_postflop_fold_grading()
    test_postflop_bet_grading()
    test_short_stack_effective_call()
    test_borderline_band()
    test_panel_vs_range_basis()
    test_session_equity_and_review()

    print(f"\n{'='*50}")
    print(f"  결과: {PASS} 통과 / {FAIL} 실패")
    print(f"{'='*50}")
    sys.exit(1 if FAIL else 0)
