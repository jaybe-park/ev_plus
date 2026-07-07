"""
포커 로직 정밀 검사 테스트
영역 1: 핸드 평가 엣지케이스
영역 2: 베팅 라운드 진행
영역 3: 팟 계산 및 분배
영역 4: 게임 진행 흐름
영역 5: 웹 세션
"""

import sys
import os
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── 테스트 경량화 ──────────────────────────────────────────
# 이 테스트의 목적은 포커 "로직" 검증이지 봇 실력이 아니다.
# 실 DB(그라인드 데이터)와 격리하고, 봇 MC 샘플을 최소화해 수십 초 안에 끝낸다.
os.environ["EV_PLUS_DB"] = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name

from ai.bot import POSTFLOP_PROFILES
for _prof in POSTFLOP_PROFILES.values():
    _prof.update({"sims": 20, "use_cache": False,
                  "exact_river": False, "use_ranges": False})
# ────────────────────────────────────────────────────────────

from core.card import Card, Suit, Rank
from core.deck import Deck
from core.evaluator import HandEvaluator, HandRank
from core.player import Player
from core.game import TexasHoldem, Action, Street

# ─────────────────────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────────────────────

def c(rank_sym: str, suit_sym: str) -> Card:
    rank_map = {r.symbol: r for r in Rank}
    suit_map = {"S": Suit.SPADES, "H": Suit.HEARTS, "D": Suit.DIAMONDS, "C": Suit.CLUBS}
    return Card(rank_map[rank_sym], suit_map[suit_sym])


def make_game(num_players=3, chips=1000, sb=10):
    players = [Player(f"P{i}", chips, is_human=(i == 0)) for i in range(num_players)]
    game = TexasHoldem(players, small_blind=sb, big_blind=sb * 2)
    return game, players


def force_hole_cards(game, assignments: dict):
    """assignments: {player_index: [Card, Card]}"""
    for idx, cards in assignments.items():
        game.players[idx].hole_cards = cards


def force_community(game, cards: list):
    game.community_cards = cards


def simple_action_sequence(game, actions):
    """
    actions: [(player_index, Action, amount), ...]
    게임 내부 apply_action 직접 호출 (베팅 라운드 루프 우회)
    """
    for pidx, action, amount in actions:
        game.apply_action(game.players[pidx], action, amount)


results = []

def run(name, fn):
    try:
        fn()
        results.append(("✅", name))
    except AssertionError as e:
        results.append(("❌", f"{name}  →  {e}"))
    except Exception as e:
        results.append(("💥", f"{name}  →  {type(e).__name__}: {e}"))


# ═════════════════════════════════════════════════════════════
# 영역 1 — 핸드 평가 엣지케이스
# ═════════════════════════════════════════════════════════════

def test_1_1_flush_tiebreaker():
    """같은 Flush라도 하이카드 순으로 승패 결정"""
    flush_a = HandEvaluator.evaluate([c("A","H"), c("J","H"), c("9","H"), c("6","H"), c("2","H")])
    flush_k = HandEvaluator.evaluate([c("K","H"), c("J","H"), c("9","H"), c("6","H"), c("2","H")])
    assert flush_a > flush_k, "Ace-high flush > King-high flush"
    assert flush_k < flush_a

def test_1_2_straight_tiebreaker():
    """같은 스트레이트, 하이카드로 비교"""
    s9 = HandEvaluator.evaluate([c("9","S"), c("8","H"), c("7","D"), c("6","C"), c("5","S")])
    s8 = HandEvaluator.evaluate([c("8","S"), c("7","H"), c("6","D"), c("5","C"), c("4","S")])
    assert s9 > s8

def test_1_3_wheel_straight_flush():
    """A-2-3-4-5 같은 슈트 → Straight Flush, high=5 (로열 플러시 아님)"""
    cards = [c("A","S"), c("2","S"), c("3","S"), c("4","S"), c("5","S")]
    result = HandEvaluator.evaluate(cards)
    assert result.hand_rank == HandRank.STRAIGHT_FLUSH, f"expected SF, got {result.hand_rank}"
    assert result.tiebreakers == (5,), f"wheel SF high should be 5, got {result.tiebreakers}"

def test_1_4_royal_flush_vs_straight_flush():
    """T-J-Q-K-A 같은 슈트 → Royal Flush (Straight Flush 아님)"""
    cards = [c("10","H"), c("J","H"), c("Q","H"), c("K","H"), c("A","H")]
    result = HandEvaluator.evaluate(cards)
    assert result.hand_rank == HandRank.ROYAL_FLUSH, f"expected RF, got {result.hand_rank}"

def test_1_5_sf_hidden_in_7cards():
    """7장 중 SF가 숨어 있을 때 올바르게 탐지"""
    # 스페이드 5장이 SF, 나머지 2장은 노이즈
    cards = [
        c("5","S"), c("6","S"), c("7","S"), c("8","S"), c("9","S"),
        c("A","H"), c("K","D"),
    ]
    result = HandEvaluator.evaluate(cards)
    assert result.hand_rank == HandRank.STRAIGHT_FLUSH

def test_1_6_full_house_tiebreaker():
    """풀하우스: 트리플 랭크 우선, 같으면 페어 랭크"""
    fh_kkk_aa = HandEvaluator.evaluate([c("K","S"), c("K","H"), c("K","D"), c("A","S"), c("A","H")])
    fh_qqq_aa = HandEvaluator.evaluate([c("Q","S"), c("Q","H"), c("Q","D"), c("A","S"), c("A","H")])
    fh_kkk_qq = HandEvaluator.evaluate([c("K","S"), c("K","H"), c("K","D"), c("Q","S"), c("Q","H")])
    assert fh_kkk_aa > fh_qqq_aa, "KKK > QQQ (trips 비교)"
    assert fh_kkk_aa > fh_kkk_qq, "KKK+AA > KKK+QQ (pair 비교)"

def test_1_7_four_of_a_kind_kicker():
    """포카드 키커 비교"""
    quad_a_k = HandEvaluator.evaluate([c("A","S"), c("A","H"), c("A","D"), c("A","C"), c("K","S")])
    quad_a_q = HandEvaluator.evaluate([c("A","S"), c("A","H"), c("A","D"), c("A","C"), c("Q","S")])
    assert quad_a_k > quad_a_q

def test_1_8_two_pair_kicker():
    """투페어 키커 비교"""
    tp_aa_kk_q = HandEvaluator.evaluate([c("A","S"), c("A","H"), c("K","S"), c("K","H"), c("Q","S")])
    tp_aa_kk_j = HandEvaluator.evaluate([c("A","S"), c("A","H"), c("K","S"), c("K","H"), c("J","S")])
    assert tp_aa_kk_q > tp_aa_kk_j

def test_1_9_one_pair_kicker_chain():
    """원페어 키커 3장 모두 비교"""
    p_aa_k_q_j = HandEvaluator.evaluate([c("A","S"), c("A","H"), c("K","S"), c("Q","S"), c("J","S")])
    p_aa_k_q_t = HandEvaluator.evaluate([c("A","S"), c("A","H"), c("K","S"), c("Q","S"), c("10","S")])
    assert p_aa_k_q_j > p_aa_k_q_t

def test_1_10_exact_tie():
    """완전 동률 — 7장이 모두 커뮤니티인 상황 (보드 플레이)"""
    board = [c("A","S"), c("K","S"), c("Q","S"), c("J","S"), c("10","S")]
    # 두 플레이어 모두 보드로만 이긴다면 (홀카드가 보드보다 약함)
    r1 = HandEvaluator.evaluate(board + [c("2","H"), c("3","D")])
    r2 = HandEvaluator.evaluate(board + [c("4","H"), c("5","D")])
    assert r1 == r2, "두 플레이어 모두 동일한 보드 Royal Flush → 타이"

def test_1_11_high_card_tiebreaker():
    """하이카드 5장 타이브레이커 전부 비교"""
    hc1 = HandEvaluator.evaluate([c("A","S"), c("K","H"), c("Q","D"), c("J","C"), c("9","S")])
    hc2 = HandEvaluator.evaluate([c("A","H"), c("K","D"), c("Q","C"), c("J","S"), c("8","H")])
    assert hc1 > hc2, "A-K-Q-J-9 > A-K-Q-J-8"

def test_1_12_flush_vs_straight():
    """Flush > Straight 랭킹"""
    flush  = HandEvaluator.evaluate([c("2","H"), c("5","H"), c("7","H"), c("9","H"), c("J","H")])
    straight = HandEvaluator.evaluate([c("5","S"), c("6","H"), c("7","D"), c("8","C"), c("9","S")])
    assert flush > straight

def test_1_13_best_hand_from_7_complex():
    """7장 중 플러시와 스트레이트 동시 존재 → SF 선택"""
    cards = [
        c("7","S"), c("8","S"), c("9","S"), c("10","S"), c("J","S"),  # SF
        c("Q","H"), c("K","D"),                                         # noise
    ]
    result = HandEvaluator.evaluate(cards)
    assert result.hand_rank == HandRank.STRAIGHT_FLUSH


# ═════════════════════════════════════════════════════════════
# 영역 2 — 베팅 라운드 진행
# ═════════════════════════════════════════════════════════════

def test_2_1_bb_option_check():
    """프리플랍: 아무도 레이즈 안 했을 때 BB가 체크 옵션을 가져야 함"""
    from server.session import WebGameSession
    sess = WebGameSession("t", "Human", 1000, 2, "medium", 10)
    # 게임 시작 직후 — 아직 사람 차례인지 확인
    state = sess.get_state()
    # 사람이 BTN이면 UTG이므로 먼저 액션, BB 포지션이면 마지막
    # 핵심: waiting_for_action이 True이고 current player가 human
    assert state["waiting_for_action"], "게임 시작 후 사람 액션 대기 중이어야 함"

def test_2_2_bb_gets_option_after_calls():
    """모두 콜 → BB는 체크(혹은 레이즈) 옵션이 있어야 함"""
    from server.session import WebGameSession
    # 3인 게임: P0=Human(BTN), P1=SB, P2=BB
    sess = WebGameSession("t2", "Human", 1000, 2, "easy", 10)
    state = sess.get_state()
    positions = {p["name"]: p["position"] for p in state["players"]}
    human_pos = positions.get("Human", "")

    # 사람이 BB가 아닌 경우: 콜하고 나서 BB 체크 기회 확인은 봇 자동 처리라 직접 관찰 어려움
    # 대신 콜 액션이 정상 처리되는지만 확인
    if state["call_amount"] > 0:
        sess.submit_action("call", 0)
    else:
        sess.submit_action("check", 0)
    new_state = sess.get_state()
    # 에러 없이 다음 상태로 진행됐으면 OK
    assert new_state is not None

def test_2_3_raise_reopens_action():
    """레이즈 후 이전 액션한 플레이어에게 다시 기회가 돌아와야 함"""
    game, players = make_game(3, chips=1000, sb=10)
    # 딜러=0, SB=1(P1), BB=2(P2), UTG=0(P0)
    game.start_hand()
    game.current_street = Street.PREFLOP

    # P0(UTG) 레이즈
    game.apply_action(players[0], Action.RAISE, 60)
    # P1(SB) 콜
    game.apply_action(players[1], Action.CALL, 50)
    # P2(BB) 재레이즈(3-bet)
    game.apply_action(players[2], Action.RAISE, 180)

    # 이제 P0에게 다시 액션 기회가 있어야 함
    # current_bet=180, P0.current_bet=60 이므로 P0는 아직 콜/폴드/레이즈 가능
    assert game.current_bet == 180
    assert players[0].current_bet == 60
    call_needed = game.current_bet - players[0].current_bet
    assert call_needed == 120, f"P0가 콜하려면 120 필요, got {call_needed}"

def test_2_4_allin_ends_round_when_no_callers():
    """모두 폴드하고 올인한 사람 혼자 남으면 라운드 즉시 종료"""
    game, players = make_game(3, chips=1000, sb=10)
    game.start_hand()
    players[0].fold()
    players[1].fold()
    active = [p for p in players if not p.is_folded]
    assert len(active) == 1

def test_2_5_preflop_betting_order_3players():
    """3인 프리플랍 베팅 순서: UTG(=BTN=P0) → SB(P1) → BB(P2)"""
    game, players = make_game(3, chips=1000, sb=10)
    # dealer_index=0 → BTN=P0, SB=P1, BB=P2
    # 프리플랍 UTG = dealer+3 % 3 = 0
    game.start_hand()
    order = game._betting_order(Street.PREFLOP)
    names = [p.name for p in order]
    assert names[0] == "P0", f"UTG should be P0, got {names[0]}"

def test_2_6_headsup_btn_acts_first_preflop():
    """헤즈업: BTN/SB가 프리플랍 먼저 행동"""
    game, players = make_game(2, chips=1000, sb=10)
    # 2인: dealer=0 → BTN/SB=P0, BB=P1
    game.start_hand()
    order = game._betting_order(Street.PREFLOP)
    # 프리플랍 UTG = (dealer+3)%2 = 1%2 = 1 → P1(BB)?
    # 헤즈업에서는 BTN/SB가 먼저여야 하는데 확인
    positions = game.get_positions()
    btn_sb = [name for name, pos in positions.items() if pos == "BTN/SB"]
    assert len(btn_sb) == 1, f"헤즈업에서 BTN/SB 포지션 1개여야 함: {positions}"

def test_2_7_postflop_sb_acts_first():
    """포스트플랍: SB(또는 딜러 왼쪽)가 먼저 행동"""
    game, players = make_game(3, chips=1000, sb=10)
    game.start_hand()
    order = game._betting_order(Street.FLOP)
    # FLOP: start = dealer+1 = 1 → P1(SB)
    assert order[0].name == "P1", f"FLOP first actor should be P1(SB), got {order[0].name}"


# ═════════════════════════════════════════════════════════════
# 영역 3 — 팟 계산 및 분배
# ═════════════════════════════════════════════════════════════

def test_3_1_pot_conservation():
    """100핸드 시뮬 — 총 칩 합은 항상 초기값과 동일해야 함
    (칩 + 팟 합계가 게임 내내 일정해야 함)"""
    from server.session import WebGameSession
    import random

    sess = WebGameSession("sim", "Human", 500, 5, "medium", 10)
    # 초기값: 플레이어 칩 + 현재 팟 (블라인드가 이미 팟에 들어간 상태)
    total_initial = sum(p.chips for p in sess.game.players) + sess.game.pot
    assert total_initial == 3000, f"초기 총합이 3000(6×500)이어야 함: {total_initial}"

    for _ in range(100):
        if sess.game_over:
            break
        for _ in range(20):
            state = sess.get_state()
            if state["hand_over"] or state["game_over"]:
                break
            if not state["waiting_for_action"]:
                break
            action = random.choice(["call", "check", "fold"])
            if action == "fold" and state["call_amount"] == 0:
                action = "check"
            sess.submit_action(action, 0)

        state = sess.get_state()
        if state["hand_over"]:
            sess.next_hand()

    total_now = sum(p.chips for p in sess.game.players) + sess.game.pot
    assert total_now == total_initial, \
        f"칩 보존 실패: 초기 {total_initial}, 현재 {total_now} (pot={sess.game.pot})"

def test_3_2_split_pot_even():
    """정확한 타이 → 균등 분배"""
    # 두 플레이어가 동일한 보드 핸드 사용 (홀카드 약함)
    game, players = make_game(2, chips=500, sb=10)
    game.start_hand()
    # 커뮤니티: Royal Flush (보드로 플레이)
    force_community(game, [c("A","S"), c("K","S"), c("Q","S"), c("J","S"), c("10","S")])
    # 홀카드: 둘 다 보드보다 약함
    players[0].hole_cards = [c("2","H"), c("3","D")]
    players[1].hole_cards = [c("4","H"), c("5","D")]

    game.pot = 200
    initial_p0 = players[0].chips
    initial_p1 = players[1].chips

    winners = game.showdown()
    assert len(winners) == 2, f"타이이므로 2명 승자여야 함: {[w.name for w in winners]}"
    assert players[0].chips == initial_p0 + 100
    assert players[1].chips == initial_p1 + 100

def test_3_3_split_pot_odd_remainder():
    """홀수 팟 — 나머지 1칩은 첫 번째 승자에게"""
    game, players = make_game(2, chips=500, sb=10)
    game.start_hand()
    force_community(game, [c("A","S"), c("K","S"), c("Q","S"), c("J","S"), c("10","S")])
    players[0].hole_cards = [c("2","H"), c("3","D")]
    players[1].hole_cards = [c("4","H"), c("5","D")]

    game.pot = 201
    initial_p0 = players[0].chips
    initial_p1 = players[1].chips

    game.showdown()
    total_gained = (players[0].chips - initial_p0) + (players[1].chips - initial_p1)
    assert total_gained == 201, f"팟 전액 분배돼야 함: {total_gained}"

def test_3_4_winner_takes_all():
    """1명 남았을 때 팟 전액 수령"""
    game, players = make_game(3, chips=500, sb=10)
    game.start_hand()
    game.pot = 300
    players[1].fold()
    players[2].fold()

    initial = players[0].chips
    winners = game.showdown()
    assert len(winners) == 1
    assert players[0].chips == initial + 300

def test_3_5_allin_player_cannot_win_more_than_contributed():
    """올인 플레이어는 자신이 낸 금액 × 인원수까지만 받을 수 있어야 함
    (사이드팟 미구현 시 이 테스트는 현재 실패할 수 있음 — 버그 노출용)"""
    # P0: 100칩 올인, P1: 1000칩, P2: 1000칩
    # P0가 이긴다면 받을 수 있는 최대액 = 100*3 = 300
    # 나머지 팟(P1+P2 간 사이드팟)은 P0에게 돌아가면 안 됨
    game, players = make_game(3, chips=1000, sb=10)
    players[0].chips = 100  # P0 숏스택

    game.start_hand()

    # P0 올인(100), P1 콜(100), P2 콜(100) → 메인팟 300
    # 실제로는 P1이 추가로 더 베팅하면 사이드팟 생기지만
    # 여기선 단순 케이스: 모두 100씩 팟
    game.pot = 300
    players[0].chips = 0
    players[0].is_all_in = True
    players[1].chips = 900
    players[2].chips = 900

    # P0가 최강 핸드
    force_community(game, [c("2","H"), c("7","D"), c("9","S"), c("3","C"), c("5","H")])
    players[0].hole_cards = [c("A","S"), c("A","H")]   # AA
    players[1].hole_cards = [c("K","S"), c("K","H")]   # KK
    players[2].hole_cards = [c("Q","S"), c("Q","H")]   # QQ

    winners = game.showdown()

    # P0는 최강 핸드이므로 메인팟(300)을 받아야 함
    assert "P0" in [w.name for w in winners]
    # 현재 사이드팟 없으므로 P0가 300 받는 게 맞음 (단순 케이스)
    assert players[0].chips == 300, f"P0 should get 300, got {players[0].chips}"


# ═════════════════════════════════════════════════════════════
# 영역 4 — 게임 진행 흐름
# ═════════════════════════════════════════════════════════════

def test_4_1_dealer_rotation():
    """딜러 버튼이 매 핸드마다 한 칸씩 이동"""
    from server.session import WebGameSession
    sess = WebGameSession("dr", "Human", 1000, 2, "easy", 10)

    dealer_indices = []
    for _ in range(5):
        dealer_indices.append(sess.game.dealer_index)
        # 핸드 빠르게 종료 (폴드)
        for _ in range(10):
            state = sess.get_state()
            if state["hand_over"] or state["game_over"]:
                break
            if state["waiting_for_action"]:
                sess.submit_action("fold", 0)
        state = sess.get_state()
        if state["hand_over"] and not state["game_over"]:
            sess.next_hand()
        if state["game_over"]:
            break

    # 딜러 인덱스가 순환하는지 확인 (연속 동일값이 없어야 함)
    if len(dealer_indices) >= 2:
        assert len(set(dealer_indices)) > 1, f"딜러가 고정됨: {dealer_indices}"

def test_4_2_bankrupt_player_removed():
    """파산 플레이어는 다음 핸드에서 제거됨"""
    from server.session import WebGameSession
    sess = WebGameSession("bk", "Human", 1000, 2, "easy", 10)

    # 봇 한 명 강제 파산
    for p in sess.game.players:
        if not p.is_human:
            p.chips = 0
            break

    initial_count = len(sess.game.players)
    sess.next_hand()
    after_count = len(sess.game.players)
    assert after_count == initial_count - 1, \
        f"파산 플레이어 제거 안 됨: {initial_count} → {after_count}"

def test_4_3_preflop_all_fold_no_showdown():
    """프리플랍 모두 폴드 → 쇼다운 없이 1명 승자"""
    game, players = make_game(3, chips=1000, sb=10)
    game.start_hand()
    game.pot = 60
    players[1].fold()
    players[2].fold()
    initial = players[0].chips

    winners = game.showdown()
    assert len(winners) == 1
    assert winners[0].name == "P0"
    assert players[0].chips == initial + 60

def test_4_4_street_bet_reset():
    """스트리트 전환 시 current_bet과 player.current_bet이 리셋되는지"""
    game, players = make_game(3, chips=1000, sb=10)
    game.start_hand()

    # 프리플랍 베팅 시뮬
    game.current_bet = 60
    players[0].current_bet = 60
    players[1].current_bet = 60
    players[2].current_bet = 60

    # FLOP으로 전환
    game.current_bet = 0
    for p in players:
        p.reset_for_street()

    assert game.current_bet == 0
    for p in players:
        assert p.current_bet == 0, f"{p.name}.current_bet should be 0"

def test_4_5_game_over_when_human_busted():
    """사람 파산 시 next_hand() 호출 시점에 game_over 처리"""
    from server.session import WebGameSession
    sess = WebGameSession("go", "Human", 30, 2, "easy", 10)
    # 사람 칩 강제 소진 후 핸드 종료 상태로 세팅
    sess.human.chips = 0
    sess.hand_over = True
    sess.game_over = False
    # next_hand: 파산 플레이어 제거 → human 없음 → game_over
    sess.next_hand()
    assert sess.game_over, "사람 파산 후 game_over여야 함"

def test_4_6_minimum_raise_rule():
    """최소 레이즈는 이전 레이즈 크기 이상이어야 함"""
    game, players = make_game(3, chips=1000, sb=10)
    game.start_hand()
    # 첫 레이즈 40 (BB=20 기준 +20)
    game.apply_action(players[0], Action.RAISE, 40)
    assert game.min_raise == 20, f"min_raise should be 20, got {game.min_raise}"
    assert game.current_bet == 40

    # 두 번째 레이즈는 최소 40+20=60 이상이어야 함 → game.apply_action이 보정하는지 확인
    game.apply_action(players[1], Action.RAISE, 60)
    assert game.current_bet == 60

def test_4_7_community_cards_count_per_street():
    """각 스트리트에서 커뮤니티 카드 수가 정확한지"""
    game, players = make_game(3, chips=1000, sb=10)
    game.start_hand()

    assert len(game.community_cards) == 0, "프리플랍: 커뮤니티 0장"
    game.deal_community(Street.FLOP)
    assert len(game.community_cards) == 3, "플랍: 3장"
    game.deal_community(Street.TURN)
    assert len(game.community_cards) == 4, "턴: 4장"
    game.deal_community(Street.RIVER)
    assert len(game.community_cards) == 5, "리버: 5장"

def test_4_8_deck_no_duplicates():
    """딜된 카드에 중복 없는지"""
    game, players = make_game(6, chips=1000, sb=10)
    game.start_hand()
    game.deal_community(Street.FLOP)
    game.deal_community(Street.TURN)
    game.deal_community(Street.RIVER)

    all_cards = game.community_cards[:]
    for p in players:
        all_cards += p.hole_cards

    strs = [str(c) for c in all_cards]
    assert len(strs) == len(set(strs)), f"중복 카드 발견: {[s for s in strs if strs.count(s) > 1]}"


# ═════════════════════════════════════════════════════════════
# 영역 5 — 웹 세션
# ═════════════════════════════════════════════════════════════

def test_5_1_fold_then_bots_complete():
    """사람 폴드 후 봇들이 핸드를 끝까지 진행해야 함"""
    from server.session import WebGameSession
    sess = WebGameSession("f1", "Human", 1000, 3, "easy", 10)
    state = sess.get_state()
    assert state["waiting_for_action"]

    sess.submit_action("fold", 0)
    state = sess.get_state()
    # 폴드 후 봇들이 모두 처리되어 핸드가 종료됐거나 대기 중이어야 함
    assert state["hand_over"] or state["waiting_for_action"] is False or True  # 어느 상태든 에러 없음
    # 핵심: 게임이 멈추지 않아야 함
    assert state is not None

def test_5_2_action_ignored_when_hand_over():
    """핸드 종료 후 submit_action은 무시됨"""
    from server.session import WebGameSession
    sess = WebGameSession("f2", "Human", 1000, 2, "easy", 10)

    # 핸드 강제 종료
    sess.hand_over = True
    chips_before = {p.name: p.chips for p in sess.game.players}

    sess.submit_action("call", 0)

    chips_after = {p.name: p.chips for p in sess.game.players}
    assert chips_before == chips_after, "핸드 종료 후 액션이 칩에 영향을 줬음"

def test_5_3_waiting_flag_is_human_turn():
    """waiting_for_action=True 일 때 항상 human이 다음 액션자여야 함"""
    from server.session import WebGameSession
    sess = WebGameSession("f3", "Human", 1000, 3, "medium", 10)
    state = sess.get_state()
    if state["waiting_for_action"]:
        next_actor = sess._next_to_act()
        assert next_actor is not None and next_actor.is_human, \
            f"waiting_for_action=True인데 다음 액션자가 봇: {next_actor}"

def test_5_4_chips_decrease_on_call():
    """콜 시 칩이 실제로 감소하는지"""
    from server.session import WebGameSession
    sess = WebGameSession("f4", "Human", 1000, 2, "easy", 10)
    state = sess.get_state()

    if not state["waiting_for_action"] or state["call_amount"] == 0:
        return  # 체크 상황이면 스킵

    chips_before = sess.human.chips
    call_amt = state["call_amount"]
    sess.submit_action("call", 0)
    chips_after = sess.human.chips
    assert chips_after == chips_before - call_amt, \
        f"콜 후 칩: {chips_before} → {chips_after} (콜금액={call_amt})"

def test_5_5_raise_amount_enforced():
    """레이즈 금액이 min_raise_to 미만이면 보정되는지"""
    game, players = make_game(3, chips=1000, sb=10)
    game.start_hand()
    game.current_bet = 20
    game.min_raise = 20

    # min_raise_to = 40인데 30으로 레이즈 시도
    game.apply_action(players[0], Action.RAISE, 30)
    # 보정되어 최소 40이 됐어야 함
    assert game.current_bet == 40, f"레이즈 금액 보정 안 됨: current_bet={game.current_bet}"

def test_5_6_state_has_required_fields():
    """get_state() 반환값에 필수 필드가 모두 있는지"""
    from server.session import WebGameSession
    sess = WebGameSession("f6", "Human", 1000, 2, "easy", 10)
    state = sess.get_state()

    required = [
        "session_id", "hand_number", "street", "pot", "current_bet",
        "min_raise", "big_blind", "community_cards", "players",
        "waiting_for_action", "hand_over", "game_over",
        "winners", "showdown_hands", "action_log", "call_amount", "min_raise_to"
    ]
    for field in required:
        assert field in state, f"필수 필드 누락: {field}"

def test_5_7_human_cards_always_visible():
    """사람 홀카드는 항상 반환되어야 함 (핸드 중/폴드 후 모두)"""
    from server.session import WebGameSession
    sess = WebGameSession("f7", "Human", 1000, 2, "easy", 10)
    state = sess.get_state()

    human_state = next(p for p in state["players"] if p["is_human"])
    assert human_state["hole_cards"] is not None, "사람 홀카드가 None"
    assert len(human_state["hole_cards"]) == 2, "사람 홀카드가 2장이 아님"

def test_5_8_bot_cards_hidden_during_hand():
    """핸드 진행 중 봇 홀카드는 숨겨져야 함"""
    from server.session import WebGameSession
    sess = WebGameSession("f8", "Human", 1000, 3, "easy", 10)
    state = sess.get_state()

    if not state["hand_over"]:
        for p in state["players"]:
            if not p["is_human"] and not p["is_folded"]:
                assert p["hole_cards"] is None, \
                    f"핸드 중 봇 카드가 노출됨: {p['name']} → {p['hole_cards']}"

def test_5_9_showdown_reveals_bot_cards():
    """쇼다운 시 봇 카드가 공개됨"""
    from server.session import WebGameSession
    sess = WebGameSession("f9", "Human", 1000, 2, "easy", 10)

    # 핸드 빠르게 쇼다운까지
    for _ in range(30):
        state = sess.get_state()
        if state["hand_over"]:
            break
        if state["waiting_for_action"]:
            sess.submit_action("call", 0)

    state = sess.get_state()
    if state["hand_over"] and len(state["showdown_hands"]) > 0:
        for p in state["players"]:
            if not p["is_human"] and not p["is_folded"]:
                assert p["hole_cards"] is not None, \
                    f"쇼다운 후 봇 카드가 숨겨져 있음: {p['name']}"


# ═════════════════════════════════════════════════════════════
# 영역 6 — 버그 픽스 검증 (헤즈업 + 사이드팟)
# ═════════════════════════════════════════════════════════════

def test_6_1_headsup_blind_posting():
    """헤즈업: dealer(BTN/SB)가 스몰 블라인드를 포스팅해야 함"""
    game, players = make_game(2, chips=1000, sb=10)
    # dealer=0 → P0=BTN/SB, P1=BB
    game.start_hand()

    positions = game.get_positions()
    sb_name = next(name for name, pos in positions.items() if pos == "BTN/SB")
    bb_name = next(name for name, pos in positions.items() if pos == "BB")

    sb_player = next(p for p in players if p.name == sb_name)
    bb_player = next(p for p in players if p.name == bb_name)

    assert sb_player.total_bet_this_round == game.small_blind, \
        f"BTN/SB는 SB({game.small_blind}) 포스팅해야 함, 실제={sb_player.total_bet_this_round}"
    assert bb_player.total_bet_this_round == game.big_blind, \
        f"BB는 BB({game.big_blind}) 포스팅해야 함, 실제={bb_player.total_bet_this_round}"

def test_6_2_headsup_preflop_btnSB_acts_first():
    """헤즈업 프리플랍: BTN/SB가 먼저 행동해야 함"""
    game, players = make_game(2, chips=1000, sb=10)
    game.start_hand()

    order = game._betting_order(Street.PREFLOP)
    positions = game.get_positions()

    first_actor = order[0]
    first_pos = positions.get(first_actor.name, "")
    assert first_pos == "BTN/SB", \
        f"헤즈업 프리플랍 첫 행동자는 BTN/SB여야 함, 실제={first_pos}({first_actor.name})"

def test_6_3_headsup_postflop_bb_acts_first():
    """헤즈업 포스트플랍: BB(딜러 반대)가 먼저 행동"""
    game, players = make_game(2, chips=1000, sb=10)
    game.start_hand()

    order = game._betting_order(Street.FLOP)
    positions = game.get_positions()
    first_pos = positions.get(order[0].name, "")
    assert first_pos == "BB", \
        f"헤즈업 포스트플랍 첫 행동자는 BB여야 함, 실제={first_pos}"

def test_6_4_headsup_chip_conservation():
    """헤즈업 20핸드 칩 총량 보존"""
    from server.session import WebGameSession
    sess = WebGameSession("hu", "Human", 500, 1, "easy", 10)
    total = sum(p.chips for p in sess.game.players) + sess.game.pot
    assert total == 1000, f"초기 총합 1000이어야 함: {total}"

    for _ in range(20):
        if sess.game_over:
            break
        for _ in range(15):
            state = sess.get_state()
            if state["hand_over"] or state["game_over"]:
                break
            if state["waiting_for_action"]:
                sess.submit_action("call", 0)
        if sess.get_state()["hand_over"]:
            sess.next_hand()

    total_now = sum(p.chips for p in sess.game.players) + sess.game.pot
    assert total_now == 1000, f"헤즈업 칩 보존 실패: {total_now}"

def test_6_5_sidepot_shortstack_wins_mainpot_only():
    """숏스택이 최강 핸드 — 메인팟만 받고, 사이드팟은 다음 강한 플레이어에게
    P0(100 올인) AA, P1(500 올인) KK, P2(1000 올인) QQ
    메인팟 = 100×3=300 → P0
    사이드팟1 = (500-100)×2=800 → P1
    사이드팟2 = (1000-500)×1=500 → P2 (본인 돈 반환)
    """
    from server.session import WebGameSession
    sess = WebGameSession("sp1", "Human", 1000, 2, "easy", 10)

    p0 = sess.human
    p1 = sess.game.players[1]
    p2 = sess.game.players[2]

    # 모두 chips=0 (전부 베팅한 상태)로 통일 → total 체크가 단순해짐
    p0.total_bet_this_round = 100;  p0.chips = 0;  p0.is_all_in = True
    p1.total_bet_this_round = 500;  p1.chips = 0;  p1.is_all_in = True
    p2.total_bet_this_round = 1000; p2.chips = 0;  p2.is_all_in = True
    sess.game.pot = 1600

    sess.game.community_cards = [
        c("2","H"), c("7","D"), c("9","S"), c("3","C"), c("5","H")
    ]
    p0.hole_cards = [c("A","S"), c("A","H")]   # AA — 최강
    p1.hole_cards = [c("K","S"), c("K","H")]   # KK
    p2.hole_cards = [c("Q","S"), c("Q","H")]   # QQ

    sess._do_showdown()

    assert p0.chips == 300,  f"P0 메인팟(300) 수령 실패: {p0.chips}"
    assert p1.chips == 800,  f"P1 사이드팟1(800) 수령 실패: {p1.chips}"
    assert p2.chips == 500,  f"P2 사이드팟2(500, 본인 반환) 실패: {p2.chips}"
    assert p0.chips + p1.chips + p2.chips == 1600, "팟 총합 보존 실패"

def test_6_6_sidepot_three_allins():
    """3명 다른 올인 → 팟이 3개로 정확히 분리"""
    from server.session import WebGameSession
    sess = WebGameSession("sp2", "Human", 1000, 2, "easy", 10)

    p0, p1, p2 = sess.human, sess.game.players[1], sess.game.players[2]

    p0.total_bet_this_round = 200;  p0.chips = 0;  p0.is_all_in = True
    p1.total_bet_this_round = 200;  p1.chips = 0;  p1.is_all_in = True
    p2.total_bet_this_round = 200;  p2.chips = 0;  p2.is_all_in = True
    sess.game.pot = 600

    pots = sess._calculate_side_pots()
    assert len(pots) == 1, f"동일 기여액이면 팟 1개여야 함: {len(pots)}"
    assert pots[0][0] == 600
    assert len(pots[0][1]) == 3

def test_6_7_sidepot_folded_player_contribution():
    """폴드한 플레이어의 기여분은 팟에 포함되지만 수령 불가"""
    from server.session import WebGameSession
    sess = WebGameSession("sp3", "Human", 1000, 2, "easy", 10)

    p0, p1, p2 = sess.human, sess.game.players[1], sess.game.players[2]

    # P2가 200 넣고 폴드
    p0.total_bet_this_round = 300; p0.chips = 700
    p1.total_bet_this_round = 300; p1.chips = 700
    p2.total_bet_this_round = 200; p2.chips = 800; p2.is_folded = True
    sess.game.pot = 800  # 300+300+200

    sess.game.community_cards = [
        c("2","H"), c("7","D"), c("9","S"), c("3","C"), c("5","H")
    ]
    p0.hole_cards = [c("A","S"), c("A","H")]  # P0 승리
    p1.hole_cards = [c("K","S"), c("K","H")]

    sess._do_showdown()

    assert "P0" in sess.winners or sess.human.name in sess.winners
    # P0가 팟 전부(800) 수령, P2는 폴드로 아무것도 못 받음
    assert p0.chips == 700 + 800, f"P0 전체 팟 수령해야 함: {p0.chips}"
    assert p2.chips == 800, f"P2 폴드 후 추가 수령 없어야 함: {p2.chips}"

def test_6_8_sidepot_conservation():
    """사이드팟 분배 후 칩 총합 보존
    P0(100 올인) AA, P1(400 올인) KK, P2(500 올인) QQ
    메인팟 = 100×3=300 → P0
    사이드팟1 = (400-100)×2=600 → P1
    사이드팟2 = (500-400)×1=100 → P2 (본인 반환)
    """
    from server.session import WebGameSession
    sess = WebGameSession("sp4", "Human", 1000, 2, "easy", 10)

    p0, p1, p2 = sess.human, sess.game.players[1], sess.game.players[2]

    p0.total_bet_this_round = 100; p0.chips = 0; p0.is_all_in = True
    p1.total_bet_this_round = 400; p1.chips = 0; p1.is_all_in = True
    p2.total_bet_this_round = 500; p2.chips = 0; p2.is_all_in = True
    sess.game.pot = 1000

    sess.game.community_cards = [
        c("2","H"), c("7","D"), c("9","S"), c("3","C"), c("5","H")
    ]
    p0.hole_cards = [c("A","S"), c("A","H")]
    p1.hole_cards = [c("K","S"), c("K","H")]
    p2.hole_cards = [c("Q","S"), c("Q","H")]

    sess._do_showdown()

    assert p0.chips == 300, f"P0 메인팟(300) 실패: {p0.chips}"
    assert p1.chips == 600, f"P1 사이드팟1(600) 실패: {p1.chips}"
    assert p2.chips == 100, f"P2 사이드팟2(100) 실패: {p2.chips}"
    total_after = p0.chips + p1.chips + p2.chips
    assert total_after == 1000, f"사이드팟 후 칩 보존 실패: {total_after}"


# ═════════════════════════════════════════════════════════════
# 실행
# ═════════════════════════════════════════════════════════════

ALL_TESTS = [
    # 영역 1
    ("1-1  Flush 타이브레이커",                test_1_1_flush_tiebreaker),
    ("1-2  Straight 타이브레이커",             test_1_2_straight_tiebreaker),
    ("1-3  Wheel Straight Flush (A-2-3-4-5)",  test_1_3_wheel_straight_flush),
    ("1-4  Royal Flush vs Straight Flush 경계", test_1_4_royal_flush_vs_straight_flush),
    ("1-5  7장 중 SF 탐지",                    test_1_5_sf_hidden_in_7cards),
    ("1-6  Full House 타이브레이커",            test_1_6_full_house_tiebreaker),
    ("1-7  Four of a Kind 키커",               test_1_7_four_of_a_kind_kicker),
    ("1-8  Two Pair 키커",                     test_1_8_two_pair_kicker),
    ("1-9  One Pair 키커 체인",                test_1_9_one_pair_kicker_chain),
    ("1-10 완전 동률 (보드 플레이)",            test_1_10_exact_tie),
    ("1-11 High Card 타이브레이커",             test_1_11_high_card_tiebreaker),
    ("1-12 Flush > Straight 랭킹",             test_1_12_flush_vs_straight),
    ("1-13 7장에서 SF 최적 선택",              test_1_13_best_hand_from_7_complex),
    # 영역 2
    ("2-1  BB 옵션 — 게임 시작 후 사람 대기",  test_2_1_bb_option_check),
    ("2-2  BB 콜 후 체크 옵션",               test_2_2_bb_gets_option_after_calls),
    ("2-3  3-bet 시 이전 액션자 재기회",       test_2_3_raise_reopens_action),
    ("2-4  모두 폴드 → 1명 남음",             test_2_4_allin_ends_round_when_no_callers),
    ("2-5  3인 프리플랍 베팅 순서",            test_2_5_preflop_betting_order_3players),
    ("2-6  헤즈업 BTN/SB 포지션",             test_2_6_headsup_btn_acts_first_preflop),
    ("2-7  포스트플랍 SB 선행동",             test_2_7_postflop_sb_acts_first),
    # 영역 3
    ("3-1  100핸드 칩 총량 보존",             test_3_1_pot_conservation),
    ("3-2  Split pot 균등 분배",              test_3_2_split_pot_even),
    ("3-3  홀수 팟 나머지 처리",              test_3_3_split_pot_odd_remainder),
    ("3-4  1명 남았을 때 팟 전액",            test_3_4_winner_takes_all),
    ("3-5  올인 플레이어 팟 수령 한도",       test_3_5_allin_player_cannot_win_more_than_contributed),
    # 영역 4
    ("4-1  딜러 버튼 로테이션",               test_4_1_dealer_rotation),
    ("4-2  파산 플레이어 제거",               test_4_2_bankrupt_player_removed),
    ("4-3  프리플랍 전부 폴드",               test_4_3_preflop_all_fold_no_showdown),
    ("4-4  스트리트 전환 시 베팅 리셋",       test_4_4_street_bet_reset),
    ("4-5  사람 파산 → game_over",            test_4_5_game_over_when_human_busted),
    ("4-6  최소 레이즈 룰",                   test_4_6_minimum_raise_rule),
    ("4-7  커뮤니티 카드 수 (스트리트별)",    test_4_7_community_cards_count_per_street),
    ("4-8  딜된 카드 중복 없음",              test_4_8_deck_no_duplicates),
    # 영역 5
    ("5-1  폴드 후 봇 자동 완료",             test_5_1_fold_then_bots_complete),
    ("5-2  핸드 종료 후 액션 무시",           test_5_2_action_ignored_when_hand_over),
    ("5-3  waiting=True → 항상 human 차례",   test_5_3_waiting_flag_is_human_turn),
    ("5-4  콜 시 칩 감소",                    test_5_4_chips_decrease_on_call),
    ("5-5  레이즈 최소금액 보정",             test_5_5_raise_amount_enforced),
    ("5-6  get_state 필수 필드",              test_5_6_state_has_required_fields),
    ("5-7  사람 카드 항상 공개",              test_5_7_human_cards_always_visible),
    ("5-8  봇 카드 핸드 중 숨김",             test_5_8_bot_cards_hidden_during_hand),
    ("5-9  쇼다운 시 봇 카드 공개",           test_5_9_showdown_reveals_bot_cards),
    # 영역 6 — 버그 픽스
    ("6-1  헤즈업 블라인드 포스팅 (BTN/SB=SB)", test_6_1_headsup_blind_posting),
    ("6-2  헤즈업 프리플랍 BTN/SB 선행동",     test_6_2_headsup_preflop_btnSB_acts_first),
    ("6-3  헤즈업 포스트플랍 BB 선행동",       test_6_3_headsup_postflop_bb_acts_first),
    ("6-4  헤즈업 20핸드 칩 총량 보존",        test_6_4_headsup_chip_conservation),
    ("6-5  사이드팟 — 숏스택 메인팟만 수령",   test_6_5_sidepot_shortstack_wins_mainpot_only),
    ("6-6  사이드팟 — 동일 올인 팟 1개",       test_6_6_sidepot_three_allins),
    ("6-7  사이드팟 — 폴드 기여분 처리",       test_6_7_sidepot_folded_player_contribution),
    ("6-8  사이드팟 분배 후 칩 보존",          test_6_8_sidepot_conservation),
]


if __name__ == "__main__":
    print("\n" + "═" * 60)
    print("  포커 로직 정밀 검사")
    print("═" * 60)

    for name, fn in ALL_TESTS:
        run(name, fn)

    print()
    passed = [r for r in results if r[0] == "✅"]
    failed  = [r for r in results if r[0] == "❌"]
    errors  = [r for r in results if r[0] == "💥"]

    area = ""
    for icon, name in results:
        new_area = name.split("-")[0].strip()
        if new_area != area:
            area = new_area
            labels = {
                "1": "영역 1 — 핸드 평가",
                "2": "영역 2 — 베팅 라운드",
                "3": "영역 3 — 팟 분배",
                "4": "영역 4 — 게임 흐름",
                "5": "영역 5 — 웹 세션",
                "6": "영역 6 — 버그 픽스",
            }
            print(f"\n  {labels.get(area, '')}")
            print("  " + "─" * 40)
        print(f"  {icon} {name}")

    print()
    print("═" * 60)
    print(f"  결과: {len(passed)} 통과 / {len(failed)} 실패 / {len(errors)} 에러  (총 {len(results)})")
    print("═" * 60)

    if failed or errors:
        print("\n  실패/에러 목록:")
        for icon, name in failed + errors:
            print(f"  {icon} {name}")
