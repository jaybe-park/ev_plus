#!/usr/bin/env python3
"""
플레이 평가 (Play Grader) + 세션 에퀴티 패널 테스트

실행: python3 tests/test_grader.py
"""

import sys
import os
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    test_session_equity_and_review()

    print(f"\n{'='*50}")
    print(f"  결과: {PASS} 통과 / {FAIL} 실패")
    print(f"{'='*50}")
    sys.exit(1 if FAIL else 0)
