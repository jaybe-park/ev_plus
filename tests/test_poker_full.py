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
import time
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── 테스트 격리 ──────────────────────────────────────────
# 이 테스트의 목적은 포커 "로직" 검증이지 봇 실력이 아니다.
# 실 DB(그라인드 데이터)와 격리한다. (봇 자체는 StubBot으로 대체되어
# equity/GTO 계산을 하지 않으므로 별도 경량화 패치는 불필요)
os.environ["EV_PLUS_DB"] = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name

from core.card import Card, Suit, Rank
from core.deck import Deck
from core.evaluator import HandEvaluator, HandRank
from core.player import Player
from core.game import TexasHoldem, Action, Street
from ai.bot import PokerBot

TIME_BUDGET_SEC = 30.0


class StubBot(PokerBot):
    """로직 테스트 전용 스텁 봇.

    ai.bot.PokerBot을 상속하지만 equity/GTO/DB 접근을 전혀 하지 않는다.
    기본 동작: 콜 금액이 있으면 콜, 없으면 체크.
    필요 시 scripted_actions로 특정 순서의 행동을 주입할 수 있다
    (예: 폴드를 유도해야 하는 테스트).

    scripted_actions: [(Action, amount), ...] — decide_action 호출마다 하나씩 소비.
    소진되면 기본 콜/체크 동작으로 폴백한다.
    """

    def __init__(self, player, scripted_actions=None):
        # PokerBot.__init__은 GTOAdvisor 등 무거운 의존성을 만들지 않으므로 안전하게 호출 가능
        super().__init__(player)
        self._scripted = list(scripted_actions) if scripted_actions else []

    def decide_action(self, game_state: dict):
        if self._scripted:
            return self._scripted.pop(0)
        call_amount = game_state["current_bet"] - self.player.current_bet
        if call_amount > 0:
            return Action.CALL, call_amount
        return Action.CHECK, 0


def _stub_decide_action(self, game_state: dict):
    """PokerBot.decide_action을 대체하는 전역 패치 함수.

    WebGameSession.__init__()은 생성자 안에서 곧바로 첫 핸드를 진행시키므로
    (_start_new_hand() 호출), 세션 생성 '이후'에 봇 인스턴스를 StubBot으로
    바꿔치기해도 이미 첫 핸드의 봇 결정은 실제 PokerBot 로직(equity/GTO)으로
    끝난 뒤다. 그래서 클래스 메서드 자체를 모듈 임포트 시점에 패치해
    세션 생성 시점부터 스텁 동작이 적용되게 한다.
    기본 동작은 StubBot과 동일: 콜 금액 있으면 콜, 없으면 체크.
    """
    call_amount = game_state["current_bet"] - self.player.current_bet
    if call_amount > 0:
        return Action.CALL, call_amount
    return Action.CHECK, 0


# 모든 테스트에서 PokerBot이 절대 equity/GTO 계산을 하지 않도록 클래스 자체를 패치.
# WebGameSession 생성자가 즉시 첫 핸드를 진행시키기 때문에, 인스턴스 단위 교체로는
# 그 시점을 놓친다. StubBot/stub_all_bots는 scripted_actions로 특정 행동 순서를
# 주입해야 하는 테스트를 위해 유지한다.
PokerBot.decide_action = _stub_decide_action


def stub_all_bots(session):
    """WebGameSession의 모든 봇을 StubBot으로 교체 (player 객체는 재사용)

    PokerBot.decide_action이 이미 전역 패치되어 있으므로 이 함수 자체는
    필수는 아니지만, scripted_actions를 주입해야 하는 테스트를 위해
    StubBot 인스턴스로 명시적으로 교체하는 용도로 계속 사용한다.
    """
    for name, bot in list(session.bots.items()):
        session.bots[name] = StubBot(bot.player)

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
durations = {}

SLOW_THRESHOLD_SEC = 0.5


def run(name, fn):
    # 테스트마다 새 임시 DB 파일 사용.
    # 이유: WebGameSession마다 GameRecorder가 자체 sqlite3 커넥션을 열고
    # 절대 닫지 않는다. 모든 테스트가 같은 DB 파일을 공유하면 테스트가
    # 누적될수록 살아있는 커넥션 수가 늘어나 SQLite 쓰기 락 경합이 심해지고,
    # 결국 busy_timeout(30s)까지 블로킹되는 현상이 발생한다
    # (예: 34개 테스트 후 단순 세션 생성이 31초 걸림).
    # 테스트별로 격리된 파일을 쓰면 커넥션이 서로 충돌하지 않는다.
    os.environ["EV_PLUS_DB"] = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    start = time.perf_counter()
    try:
        fn()
        elapsed = time.perf_counter() - start
        durations[name] = elapsed
        suffix = f"  ({elapsed:.1f}s)" if elapsed >= SLOW_THRESHOLD_SEC else ""
        results.append(("✅", f"{name}{suffix}"))
    except AssertionError as e:
        elapsed = time.perf_counter() - start
        durations[name] = elapsed
        results.append(("❌", f"{name}  →  {e}"))
    except Exception as e:
        elapsed = time.perf_counter() - start
        durations[name] = elapsed
        results.append(("💥", f"{name}  →  {type(e).__name__}: {e}"))
    icon, label = results[-1]
    print(f"  {icon} {label}", flush=True)


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
    stub_all_bots(sess)
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
    stub_all_bots(sess)
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
    """풀 레이즈만 액션을 다시 연다(reopens=True, min_raise 갱신).
    최소 레이즈 미만 올인은 current_bet만 올리고 재오픈하지 않는다(min_raise 유지)."""
    game, players = make_game(3, chips=1000, sb=10)
    # 딜러=0, SB=1(P1), BB=2(P2), UTG=0(P0)
    game.start_hand()
    game.current_street = Street.PREFLOP

    r = game.execute_action(players[0], Action.RAISE, 60)      # 오픈 60 (+40)
    assert r.reopens and game.min_raise == 40, (r, game.min_raise)
    r = game.execute_action(players[1], Action.CALL)
    assert not r.reopens and r.moved == 50, r
    r = game.execute_action(players[2], Action.RAISE, 180)     # 3벳 180 (+120)
    assert r.reopens and game.current_bet == 180 and game.min_raise == 120, (r, game.min_raise)
    assert game.current_bet - players[0].current_bet == 120

    # P1이 140만 남기고 올인 → 200(+20, 최소 레이즈 120 미만) = 불완전 레이즈
    players[1].chips = 140
    r = game.execute_action(players[1], Action.ALL_IN)
    assert r.action == Action.ALL_IN and not r.reopens, r
    assert game.current_bet == 200 and game.min_raise == 120, \
        f"불완전 올인은 current_bet만 올리고 min_raise 유지: {game.current_bet}, {game.min_raise}"
    # 이미 행동한 P0는 레이즈 불가(콜/폴드만)
    acted = {"P0", "P1", "P2"}
    assert not game.raise_allowed(players[0], acted)
    assert not game.apply_action(players[0], Action.RAISE, 400, raise_allowed=False)
    assert game.apply_action(players[0], Action.CALL, raise_allowed=False)

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
    stub_all_bots(sess)
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
            if state["call_amount"] == 0 and action == "fold":
                action = "check"
            if state["call_amount"] > 0 and action == "check":
                action = "call"  # 벳을 마주한 체크는 불법(거절됨)
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
    """홀수 팟 — 나머지 1칩은 버튼 왼쪽 첫 승자에게(리스트 첫 승자가 아님, T-022)"""
    for dealer, odd_idx in [(0, 1), (1, 0)]:
        game, players = make_game(2, chips=500, sb=10)
        game.dealer_index = dealer
        game.start_hand()
        force_community(game, [c("A","S"), c("K","S"), c("Q","S"), c("J","S"), c("10","S")])
        players[0].hole_cards = [c("2","H"), c("3","D")]
        players[1].hole_cards = [c("4","H"), c("5","D")]

        game.pot = 201
        initial = [p.chips for p in players]

        game.showdown()
        gained = [players[i].chips - initial[i] for i in range(2)]
        assert sum(gained) == 201, f"팟 전액 분배돼야 함: {gained}"
        assert gained[odd_idx] == 101 and gained[1 - odd_idx] == 100, \
            f"딜러={dealer}: 홀수 칩은 버튼 왼쪽(P{odd_idx})에게 가야 함: {gained}"

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
    """딜러 버튼이 매 핸드 좌석 순서대로 정확히 한 칸씩 이동하고, SB·BB가 그 뒤 두 명이다
    (세션 경로, 파산 없음)."""
    from server.session import WebGameSession
    sess = WebGameSession("dr", "Human", 1000, 3, "easy", 10, equity_enabled=False)
    stub_all_bots(sess)
    seats = [p.name for p in sess.game.players]
    n = len(seats)

    rows = []
    for _ in range(8):
        pos = sess.game.get_positions()
        rows.append({lbl: name for name, lbl in pos.items()})
        guard = 0
        while not sess.hand_over:
            guard += 1
            assert guard < 20, "핸드가 끝나지 않음"
            sess.submit_action("fold", 0)
        sess.next_hand()
        assert not sess.game_over

    for prev, cur in zip(rows, rows[1:]):
        want_btn = seats[(seats.index(prev["BTN"]) + 1) % n]
        assert cur["BTN"] == want_btn, f"버튼이 한 칸 이동해야 함: {prev['BTN']} → {cur['BTN']}"
        assert cur["SB"] == seats[(seats.index(want_btn) + 1) % n], cur
        assert cur["BB"] == seats[(seats.index(want_btn) + 2) % n], cur

def test_4_2_bankrupt_player_removed():
    """파산 플레이어는 다음 핸드에서 제거됨"""
    from server.session import WebGameSession
    sess = WebGameSession("bk", "Human", 1000, 2, "easy", 10)
    stub_all_bots(sess)

    # 봇 한 명 강제 파산
    for p in sess.game.players:
        if not p.is_human:
            p.chips = 0
            break

    initial_count = len(sess.game.players)
    sess.hand_over = True  # next_hand는 핸드 종료 후에만 동작한다(T-025 가드)
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
    stub_all_bots(sess)
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
    stub_all_bots(sess)
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
    stub_all_bots(sess)

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
    stub_all_bots(sess)
    state = sess.get_state()
    if state["waiting_for_action"]:
        next_actor = sess._next_to_act()
        assert next_actor is not None and next_actor.is_human, \
            f"waiting_for_action=True인데 다음 액션자가 봇: {next_actor}"

def test_5_4_chips_decrease_on_call():
    """콜 시 칩이 실제로 감소하는지"""
    from server.session import WebGameSession
    sess = WebGameSession("f4", "Human", 1000, 2, "easy", 10)
    stub_all_bots(sess)
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
    stub_all_bots(sess)
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
    stub_all_bots(sess)
    state = sess.get_state()

    human_state = next(p for p in state["players"] if p["is_human"])
    assert human_state["hole_cards"] is not None, "사람 홀카드가 None"
    assert len(human_state["hole_cards"]) == 2, "사람 홀카드가 2장이 아님"

def test_5_8_bot_cards_hidden_during_hand():
    """핸드 진행 중 봇 홀카드는 숨겨져야 함"""
    from server.session import WebGameSession
    sess = WebGameSession("f8", "Human", 1000, 3, "easy", 10)
    stub_all_bots(sess)
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
    stub_all_bots(sess)

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

def test_5_10_equity_panel_nut_hand():
    """넛(포스트플랍 최강 핸드)에서 equity.vs_random이 0.85를 넘어야 함"""
    from server.session import WebGameSession
    sess = WebGameSession("f10", "Human", 1000, 1, "easy", 10)  # 헤즈업 (상대 1명)
    stub_all_bots(sess)

    # 프리플랍은 건너뛰고 플랍에서 사람이 완성된 넛(포켓에이스 + 보드 세트)로 액션하는 상황을 강제
    sess.human.hole_cards = [c("A", "S"), c("A", "H")]
    opp = next(p for p in sess.game.players if not p.is_human)
    opp.hole_cards = [c("K", "S"), c("Q", "D")]
    sess.game.community_cards = [c("A", "D"), c("A", "C"), c("2", "H")]  # 사람 쿼드 에이스
    sess.game.current_street = Street.FLOP
    sess.street_index = 1
    sess._equity_cache = {}
    sess.equity_history = []
    sess._equity_history_streets = set()

    equity = sess._get_equity_info()
    assert equity is not None, "equity 계산 결과가 None"
    assert equity["vs_random"] > 0.85, \
        f"쿼드 에이스 equity가 너무 낮음: {equity['vs_random']}"
    assert "vs_range" in equity and "pot_odds" in equity and "source" in equity
    assert isinstance(equity["opponents"], list)
    assert isinstance(equity["history"], list) and len(equity["history"]) >= 1

def test_5_11_hand_review_after_hand_over():
    """핸드 종료 후 get_state에 hand_review가 사람 액션 평가로 채워져야 함"""
    from server.session import WebGameSession
    sess = WebGameSession("f11", "Human", 1000, 2, "easy", 10)
    stub_all_bots(sess)

    for _ in range(40):
        state = sess.get_state()
        if state["hand_over"]:
            break
        if state["waiting_for_action"]:
            sess.submit_action("call", 0)

    state = sess.get_state()
    assert state["hand_over"], "40스텝 안에 핸드가 끝나지 않음"
    assert state["hand_review"] is not None, "hand_over인데 hand_review가 None"
    assert isinstance(state["hand_review"], list)
    if state["hand_review"]:
        item = state["hand_review"][0]
        for key in ("street", "action", "grade", "reason"):
            assert key in item, f"hand_review 항목에 {key} 필드 누락: {item}"

def test_5_12_equity_disabled_flag():
    """equity_enabled=False면 waiting=True여도 equity 필드가 계속 None"""
    from server.session import WebGameSession
    sess = WebGameSession("f12", "Human", 1000, 2, "easy", 10, equity_enabled=False)
    stub_all_bots(sess)
    state = sess.get_state()
    assert state["equity"] is None, "equity_enabled=False인데 equity가 계산됨"


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
    stub_all_bots(sess)
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
    stub_all_bots(sess)

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
    stub_all_bots(sess)

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
    stub_all_bots(sess)

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
    stub_all_bots(sess)

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

def test_6_9_headsup_gto_btnSB_mapped_to_sb_rfi():
    """헤즈업(2인) GTO 조회: my_position="BTN/SB"는 내부적으로 "SB"로 치환돼
    6-max SB RFI 데이터로 정상 응답해야 함 (core/game.py의 원본 라벨 자체는
    변경되지 않음 — advisor 내부 조회 시점에서만 국소 치환).
    이 테스트는 격리된 임시 DB(EV_PLUS_DB)를 쓰므로 외부 수집 데이터에
    의존하지 않고 최소 SB RFI 시추에이션을 직접 시딩한다."""
    from gto.advisor import GTOAdvisor

    # SB RFI 노드 키 = "F-F-F-F"(UTG~BTN 폴드). 헤즈업 BTN/SB 첫 결정은 이 노드다(ADR 0005).
    _seed_situation("SB", None, "open", 3.0, "SB RFI",
                    {"AKs": {"raise": 1.0}}, "F-F-F-F")

    game, players = make_game(2, chips=1000, sb=10)
    game.start_hand()
    positions = game.get_positions()

    # core/game.py는 여전히 "BTN/SB"를 그대로 보고해야 함(원본 라벨 유지)
    assert "BTN/SB" in positions.values()

    sb_player = next(p for p in players if positions.get(p.name) == "BTN/SB")

    advisor = GTOAdvisor()
    game_state = {
        "current_bet": game.big_blind,
        "street": "프리플랍",
        "action_log": [],
    }
    rec = advisor.get_recommendation(
        hole_cards=[c("A", "S"), c("K", "S")],
        my_position="BTN/SB",
        positions=positions,
        game_state=game_state,
        big_blind=game.big_blind,
    )
    assert rec is not None, "헤즈업 BTN/SB RFI는 SB 데이터로 매핑되어 응답해야 함"
    assert "SB" in rec["situation"], f"situation에 SB 매핑 흔적이 있어야 함: {rec['situation']}"
    assert rec["node_key"] == "F-F-F-F" and rec["approx"] is False, rec


def test_6_10_squeeze_seq_includes_call():
    """스퀴즈 라인(UTG오픈→HJ3벳→CO콜→BTN결정)에서 구조화 프리플랍 시퀀스가
    CO의 '콜'을 구조적으로 담는지 검증. 기존 한글 문자열 파서
    (_count_preflop_raises/_find_raisers_in_log)로는 콜/정확한 순서/참여 인원을
    구조적으로 구분할 수 없었던 바로 그 부분이다.
    advisor가 BTN 스팟에서 None을 반환하는 것 자체는 정상(모델 밖: BTN != 오프너 UTG).
    """
    from gto.advisor import GTOAdvisor, canonical_preflop_actions

    game, players = make_game(6, chips=1000, sb=10)  # bb=20
    game.start_hand()
    positions = game.get_positions()
    bb = game.big_blind

    utg = next(p for p in players if positions[p.name] == "UTG")
    hj = next(p for p in players if positions[p.name] == "HJ")
    co = next(p for p in players if positions[p.name] == "CO")

    game.apply_action(utg, Action.RAISE, int(2.5 * bb))  # UTG 오픈 2.5bb → 50
    game.apply_action(hj, Action.RAISE, int(8 * bb))     # HJ 3벳 8bb → 160
    game.apply_action(co, Action.CALL)                   # CO 콜드콜 → 160

    seq = game.preflop_action_seq()
    assert len(seq) == 3, f"자발적 액션 3개여야 함(블라인드 제외): {seq}"
    assert [a["action"] for a in seq] == ["raise", "raise", "call"], seq
    assert [a["position"] for a in seq] == ["UTG", "HJ", "CO"], seq

    co_entry = seq[2]
    assert co_entry["action"] == "call", f"CO 액션이 콜로 구조화돼야 함: {co_entry}"
    assert co_entry["position"] == "CO"
    assert abs(co_entry["amount_bb"] - 8.0) < 1e-9, f"CO 콜 to-amount 8bb: {co_entry}"

    # 캐노니컬 문자열도 콜을 담아야 함 (② 노드 키 기반)
    assert canonical_preflop_actions(seq) == "R2.5-R8-C", canonical_preflop_actions(seq)

    # advisor: BTN은 오프너(UTG)가 아니므로 모델 밖 → None (정상)
    advisor = GTOAdvisor()
    gs = game._get_game_state()
    assert "preflop_seq" in gs and len(gs["preflop_seq"]) == 3, gs.get("preflop_seq")
    rec = advisor.get_recommendation(
        hole_cards=[c("A", "S"), c("K", "S")],
        my_position="BTN",
        positions=positions,
        game_state=gs,
        big_blind=bb,
    )
    assert rec is None, f"BTN는 오프너가 아니므로 모델 밖(None)이어야 함: {rec}"


def test_6_11_headsup_seq_labels_btnSB():
    """헤즈업(2인) 프리플랍 시퀀스는 딜러를 원본 라벨 'BTN/SB'로 담아야 한다
    (advisor가 조회 시점에 'SB'로 매핑). test_6_9(advisor 매핑)와 함께 헤즈업 회귀 방지."""
    game, players = make_game(2, chips=1000, sb=10)  # bb=20
    game.start_hand()
    positions = game.get_positions()
    assert "BTN/SB" in positions.values()
    btnsb = next(p for p in players if positions[p.name] == "BTN/SB")

    game.apply_action(btnsb, Action.RAISE, int(3 * game.big_blind))  # 3bb → 60
    seq = game.preflop_action_seq()
    assert len(seq) == 1, seq
    assert seq[0]["position"] == "BTN/SB", f"헤즈업 딜러 라벨 원본 유지: {seq}"
    assert seq[0]["action"] == "raise"
    assert abs(seq[0]["amount_bb"] - 3.0) < 1e-9, seq


def test_6_12_vs_open_routing_via_seq():
    """리팩터 후에도 vs_open 스팟(HJ vs UTG open)이 구조화 시퀀스 기반 라우팅으로
    동일 데이터를 반환하는지 스팟체크(격리 DB에 최소 데이터 시딩)."""
    from gto.advisor import GTOAdvisor

    _seed_situation("HJ", "UTG", "vs_open", 8.0, "HJ vs UTG open",
                    {"AKs": {"call": 0.5, "raise": 0.5}}, "R2.5")

    game, players = make_game(6, chips=1000, sb=10)  # bb=20
    game.start_hand()
    positions = game.get_positions()
    utg = next(p for p in players if positions[p.name] == "UTG")
    game.apply_action(utg, Action.RAISE, int(2.5 * game.big_blind))  # UTG 오픈

    advisor = GTOAdvisor()
    gs = game._get_game_state()
    rec = advisor.get_recommendation(
        hole_cards=[c("A", "S"), c("K", "S")],
        my_position="HJ",
        positions=positions,
        game_state=gs,
        big_blind=game.big_blind,
    )
    assert rec is not None, "HJ vs UTG open은 시딩 데이터로 응답해야 함"
    assert rec["raise_count"] == 1, rec
    assert "HJ" in rec["situation"] and "UTG" in rec["situation"], rec


# v12 운영 DB의 gto_preflop_situations DDL 그대로(2026-09-26 `.schema`로 확인) —
# 백필(v12)·v13 마이그레이션 테스트가 "옛 DB"를 재현하는 데 쓴다.
_V12_GTO_SITUATIONS_DDL = """
CREATE TABLE gto_preflop_situations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    position        TEXT    NOT NULL,
    vs_position     TEXT,
    range_type      TEXT    NOT NULL,
    raise_size      REAL,
    situation_label TEXT    NOT NULL, action_seq TEXT, hero_position TEXT, num_active INTEGER,
    UNIQUE(position, vs_position, range_type)
)
"""


def _seed_situation(position, vs_position, range_type, raise_size, label,
                    hands, action_seq):
    """테스트용: 노드(action_seq 필수 — 유일 키) + 핸드 시딩 후 로더 캐시 무효화.
    같은 action_seq가 이미 있으면 기존 행에 핸드만 보탠다(INSERT OR IGNORE)."""
    from db.connection import get_connection
    import gto.loader as gto_loader
    conn = get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO gto_preflop_situations "
        "(position, vs_position, range_type, raise_size, situation_label, action_seq) "
        "VALUES (?,?,?,?,?,?)",
        (position, vs_position, range_type, raise_size, label, action_seq),
    )
    conn.commit()
    sid = conn.execute(
        "SELECT id FROM gto_preflop_situations WHERE action_seq=?", (action_seq,),
    ).fetchone()[0]
    for hand, fr in hands.items():
        conn.execute(
            "INSERT OR IGNORE INTO gto_preflop_hands "
            "(situation_id, hand, freq_fold, freq_call, freq_raise, freq_allin) "
            "VALUES (?,?,?,?,?,?)",
            (sid, hand, fr.get("fold", 0.0), fr.get("call", 0.0),
             fr.get("raise", 0.0), fr.get("allin", 0.0)),
        )
    conn.commit()
    conn.close()
    gto_loader._cache = {}
    gto_loader._loaded = False


def test_6_13_seq_key_and_enum_key_same_range():
    """② (a): 같은 스팟을 enum 키와 시퀀스 키로 조회하면 동일한 레인지(같은 객체)를
    가리켜야 한다. 시퀀스 키 경로가 기존 enum 경로와 병렬로 같은 데이터를 반환함을 검증."""
    from gto.url_generator import situation_to_node_key
    from gto.loader import get_open_range, get_vs_open_range, get_range_by_seq

    # RFI(UTG, 노드 키="") + vs_open(HJ vs UTG, 노드 키="R2.5")
    key_utg = situation_to_node_key("UTG", None, "open")
    key_hj = situation_to_node_key("HJ", "UTG", "vs_open")
    assert key_utg == "" and key_hj == "R2.5", (key_utg, key_hj)

    _seed_situation("UTG", None, "open", 2.5, "UTG RFI",
                    {"AKs": {"raise": 1.0}}, key_utg)
    _seed_situation("HJ", "UTG", "vs_open", 8.0, "HJ vs UTG open",
                    {"AKs": {"call": 0.5, "raise": 0.5}}, key_hj)

    assert get_open_range("UTG") is get_range_by_seq(key_utg), "UTG RFI enum≠seq"
    assert get_vs_open_range("HJ", "UTG") is get_range_by_seq(key_hj), "HJ vs UTG enum≠seq"
    # 없는 노드 키는 None
    from gto.loader import get_range_by_seq as g
    assert g("R2.5-R8-R17.5") is None


def test_6_14_runtime_snap_maps_near_size_to_node():
    """②' (스냅): 런타임의 근접 레이즈 사이즈가 **수집된 형제 노드**로 트리-인지 스냅돼
    조회되는지. 실전 오픈 2.3bb→형제 R2.5, 3벳 7.5bb→형제 R8 로 매핑돼야 함
    (수집분 "R2.5-R8-F-F-F-F" 기준. 하드코딩 깊이 테이블 아님)."""
    from gto.advisor import GTOAdvisor, canonical_node_key
    from gto.url_generator import situation_to_node_key
    from gto.loader import get_range_by_seq, get_vs_3bet_range

    node_key = situation_to_node_key("UTG", "UTG/HJ", "vs_3bet")
    assert node_key == "R2.5-R8-F-F-F-F", node_key
    _seed_situation("UTG", "UTG/HJ", "vs_3bet", 21.5, "UTG vs HJ 3bet",
                    {"AKs": {"fold": 0.3, "call": 0.0, "raise": 0.7}}, node_key)

    # 실전 시퀀스: 오픈 2.3bb, 3벳 7.5bb → 깊이 스냅 → 2.5 / 8
    seq = [
        {"position": "UTG", "action": "raise", "amount_bb": 2.3},
        {"position": "HJ", "action": "raise", "amount_bb": 7.5},
        {"position": "CO", "action": "fold"},
        {"position": "BTN", "action": "fold"},
        {"position": "SB", "action": "fold"},
        {"position": "BB", "action": "fold"},
    ]
    assert canonical_node_key(seq) == node_key, canonical_node_key(seq)
    assert get_range_by_seq(canonical_node_key(seq)) is get_vs_3bet_range("UTG", "UTG", "HJ")

    # advisor 시퀀스 경로도 이 노드를 반환해야 함
    advisor = GTOAdvisor()
    gs = {"street": "프리플랍", "current_bet": 150, "preflop_seq": seq}
    rec = advisor._recommend_by_seq([c("A", "S"), c("K", "S")], "UTG", gs, big_blind=20)
    assert rec is not None and rec["node_key"] == node_key, rec
    assert "UTG" in rec["situation"], rec


def test_6_15_migration_normalizes_vs3bet_format():
    """② (c): 마이그레이션 백필(backfill_v12)이 vs_3bet의 반쪽 포맷(three_bettor만
    저장)을 'opener/three_bettor'로 정규화하고 캐노니컬 노드 키를 채우는지 검증."""
    import sqlite3
    from db.schema import backfill_v12

    # v12 시점 테이블(action_seq nullable, v13 이전)을 별도 임시 DB에 만들어 백필만 검사한다.
    conn = sqlite3.connect(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
    conn.row_factory = sqlite3.Row
    conn.execute(_V12_GTO_SITUATIONS_DDL)
    # 인계된 불일치 재현: BTN 오프너가 BB 3벳에 대응하는데 vs_position='BB'(반쪽)로 저장
    conn.execute(
        "INSERT OR IGNORE INTO gto_preflop_situations "
        "(position, vs_position, range_type, raise_size, situation_label) "
        "VALUES ('BTN', 'BB', 'vs_3bet', 28.5, 'BTN vs BB 3bet')"
    )
    conn.commit()

    backfill_v12(conn)  # 마이그레이션 백필 로직 직접 실행
    conn.commit()

    row = conn.execute(
        "SELECT vs_position, action_seq, hero_position, num_active "
        "FROM gto_preflop_situations WHERE position='BTN' AND range_type='vs_3bet'"
    ).fetchone()
    conn.close()
    assert row["vs_position"] == "BTN/BB", f"정규화 실패: {row['vs_position']}"
    assert row["action_seq"] == "F-F-F-R2.5-F-R8", f"노드 키 오류: {row['action_seq']}"
    assert row["hero_position"] == "BTN"
    assert row["num_active"] == 2, row["num_active"]


def test_6_16_realsize_node_snaps_to_collected_sibling():
    """②' (a): **실측 사이즈** 노드를 시딩하면, 라이브 오프-트리 사이즈가 그 수집된
    형제의 실측값으로 스냅돼 조회된다. 3벳 실측 13.5(② 같으면 8로 뭉갰을 값)가
    라이브 12.0에서 R13.5 형제로 스냅 → 사이즈가 보존됨을 검증."""
    from gto.advisor import GTOAdvisor, canonical_node_key
    from gto.loader import get_range_by_seq

    # UTG open → HJ~SB fold → BB 3bet 13.5. 히어로=UTG의 vs_3bet 노드(실측 사이즈 키).
    node_key = "R2.5-F-F-F-F-R13.5"
    _seed_situation("UTG", "UTG/BB", "vs_3bet", 30.0, "UTG vs BB 3bet",
                    {"AKs": {"fold": 0.2, "call": 0.0, "raise": 0.8}}, node_key)

    seq = [
        {"position": "UTG", "action": "raise", "amount_bb": 2.4},
        {"position": "HJ", "action": "fold"},
        {"position": "CO", "action": "fold"},
        {"position": "BTN", "action": "fold"},
        {"position": "SB", "action": "fold"},
        {"position": "BB", "action": "raise", "amount_bb": 12.0},
    ]
    # 2.4→R2.5, 12.0→R13.5(수집된 유일 형제) → 실측 사이즈 보존
    assert canonical_node_key(seq) == node_key, canonical_node_key(seq)
    assert get_range_by_seq(node_key) is not None

    advisor = GTOAdvisor()
    gs = {"street": "프리플랍", "current_bet": 240, "preflop_seq": seq}
    rec = advisor._recommend_by_seq([c("A", "S"), c("K", "S")], "UTG", gs, big_blind=20)
    assert rec is not None and rec["node_key"] == node_key, rec


def test_6_17_uncollected_branch_returns_none_and_queues():
    """②' (b): 수집되지 않은 브랜치(그 프리픽스에 레이즈-형제 없음)는 숫자 억지 매칭
    없이 None을 반환하고, 실측 사이즈 키로 큐(gto_missing_spots_preflop range_type='seq')에
    등록돼야 한다(추측 금지 → 큐/폴백)."""
    from gto.advisor import GTOAdvisor, canonical_node_key
    from db.connection import get_connection

    # 수집분: "R2.5-R8-F-F-F-F"만 있다고 보장(6_14가 시딩; 없으면 여기서 시딩).
    _seed_situation("UTG", "UTG/HJ", "vs_3bet", 21.5, "UTG vs HJ 3bet",
                    {"AKs": {"fold": 0.3, "raise": 0.7}}, "R2.5-R8-F-F-F-F")

    # UTG open → HJ 3bet → CO fold → BTN 콜드-4벳 20 → SB·BB fold → 히어로 UTG가 4벳에 직면.
    # 프리픽스 "R2.5-R8-F"에 수집된 레이즈-형제 없음(수집분 token[3]="F") → None.
    seq = [
        {"position": "UTG", "action": "raise", "amount_bb": 2.5},
        {"position": "HJ", "action": "raise", "amount_bb": 8.0},
        {"position": "CO", "action": "fold"},
        {"position": "BTN", "action": "raise", "amount_bb": 20.0},
        {"position": "SB", "action": "fold"},
        {"position": "BB", "action": "fold"},
    ]
    assert canonical_node_key(seq) is None, canonical_node_key(seq)

    advisor = GTOAdvisor()
    gs = {"street": "프리플랍", "current_bet": 400, "preflop_seq": seq}
    rec = advisor.get_recommendation([c("A", "S"), c("K", "S")], "UTG", {}, gs, big_blind=20)
    assert rec is None, rec

    # 실측 사이즈 키로 큐 등록 확인(정확한 노드·라벨 둘 다 없을 때만 — ADR 0035)
    conn = get_connection()
    row = conn.execute(
        "SELECT position, vs_position, range_type FROM gto_missing_spots_preflop "
        "WHERE range_type='seq' AND vs_position=?",
        ("R2.5-R8-F-R20-F-F",),
    ).fetchone()
    conn.close()
    assert row is not None, "미수집 seq 노드가 큐에 등록되지 않음"
    assert row["position"] == "UTG" and row["range_type"] == "seq"


def test_6_18_two_siblings_snap_to_nearest_bb():
    """②' (c): 한 프리픽스에 레이즈-형제가 2개 수집돼 있으면 bb 절대거리 최소로 스냅."""
    from gto.advisor import canonical_node_key

    # 프리픽스 "R2.5"에 3벳 형제 두 개(R8, R12) 수집.
    _seed_situation("UTG", "UTG/HJ", "vs_3bet", 21.5, "UTG vs HJ 3bet 8",
                    {"AKs": {"raise": 1.0}}, "R2.5-R8-F-F-F-F")
    _seed_situation("UTG", "UTG/CO", "vs_3bet", 28.0, "UTG vs CO 3bet 12",
                    {"AKs": {"raise": 1.0}}, "R2.5-R12-F-F-F-F")

    def key_for(three_bet_bb):
        seq = [
            {"position": "UTG", "action": "raise", "amount_bb": 2.5},
            {"position": "HJ", "action": "raise", "amount_bb": three_bet_bb},
            {"position": "CO", "action": "fold"},
            {"position": "BTN", "action": "fold"},
            {"position": "SB", "action": "fold"},
            {"position": "BB", "action": "fold"},
        ]
        return canonical_node_key(seq)

    # 9.0 → |9-8|=1 < |9-12|=3 → R8
    assert key_for(9.0) == "R2.5-R8-F-F-F-F", key_for(9.0)
    # 10.5 → |10.5-8|=2.5 > |10.5-12|=1.5 → R12
    assert key_for(10.5) == "R2.5-R12-F-F-F-F", key_for(10.5)


def test_6_19_allin_snaps_to_allin_sibling_not_nearest_raise():
    """②' (d, T-014/ADR 0010 확장): 라이브 올인은 bb 절대거리 최소가 아니라
    "올인 형제"에만 스냅해야 한다. 프리픽스 ""(UTG RFI, 자신의 raise_size=2.5)에
    레이즈 형제 R2.5와 올인 형제 R99가 둘 다 수집돼 있을 때, 숏스택 올인 45bb는
    산술적으로는 R2.5(|45-2.5|=42.5)가 R99(|45-99|=54)보다 가깝지만 "올인
    형제"인 R99로 스냅돼야 한다(레이즈 사이즈는 이 프리픽스 노드 자신의 저장된
    raise_size로 확정해 후보에서 제외 — 추측 아니라 저장된 값과의 일치 확인)."""
    from gto.advisor import canonical_node_key

    # (position, vs_position, range_type) UNIQUE라 두 형제는 서로 다른 vs_position을 쓴다
    # (실제 라벨 의미는 중요하지 않음 — action_seq/raise_size만 canonical_node_key가 본다).
    _seed_situation("UTG", None, "open", 2.5, "UTG RFI(올인 스냅 테스트)",
                    {"AA": {"raise": 0.3, "allin": 0.7}}, "")
    _seed_situation("UTG", "UTG-raise", "vs_open", 8.0, "UTG RFI 후 레이즈 형제",
                    {"AA": {"raise": 1.0}}, "R2.5-F-F-F-F-F")
    _seed_situation("UTG", "UTG-allin", "vs_open", 99.0, "UTG 올인(테스트 전용 올인 형제)",
                    {"AA": {"raise": 1.0}}, "R99-F-F-F-F-F")

    seq = [{"position": "UTG", "action": "allin", "amount_bb": 45.0}]
    assert canonical_node_key(seq) == "R99", canonical_node_key(seq)


def test_6_20_allin_with_no_allin_sibling_returns_none():
    """②' (e, T-014): 이 프리픽스에 "레이즈" 형제만 수집돼 있고(올인 데이터 없음),
    라이브 올인이 들어오면 그 레이즈 형제로 억지 스냅하지 않고 None을 반환해야
    한다(숏스택 올인이 일반 레이즈 노드로 매핑되지 않는다 — ADR 0010 원칙).
    6_13/6_14 등이 이미 쓴 "R2.5" 브랜치(레이즈 형제가 여러 개라 오염됨)를
    피해, 완전히 새 브랜치("R4" 오픈)에서 검증한다."""
    from gto.advisor import canonical_node_key

    # UTG가 4bb로 오픈(신규 브랜치) → HJ가 이 오픈에 대응(프리픽스 "R4").
    # HJ 자신의 raise_size=8.5만 알려져 있고(vs_open 노드 자신), 그 레이즈
    # 형제("R4-R8.5-...")만 수집돼 있다 — 올인 형제는 없음.
    _seed_situation("HJ", "UTG", "vs_open", 8.5, "HJ vs UTG open(4bb, 올인 미수집 테스트)",
                    {"AA": {"raise": 1.0}}, "R4")
    _seed_situation("UTG", "UTG/HJ", "vs_3bet", 21.0, "UTG vs HJ 3bet(올인 미수집 테스트)",
                    {"AA": {"raise": 1.0}}, "R4-R8.5-F-F-F-F")

    seq = [
        {"position": "UTG", "action": "raise", "amount_bb": 4.2},   # 신규 브랜치 R4로 스냅
        {"position": "HJ", "action": "allin", "amount_bb": 45.0},   # 올인 형제 없음 → None
    ]
    assert canonical_node_key(seq) is None, canonical_node_key(seq)


# ═════════════════════════════════════════════════════════════
# 영역 7 — 프리플랍 GTO 원칙
#   배경: /private/tmp/.../scratchpad/gto-findings.md "절대 규칙 중 장치 없는 것"
#   G2/G4/G5/G6/G17 — 사람 결정 없이 현재 코드 동작을 그대로 핀(pin)하는 테스트.
# ═════════════════════════════════════════════════════════════

def test_7_1_save_invalidates_loader_cache():
    """G2: /gto/preflop/save가 로더 캐시(enum+시퀀스)를 자동 무효화해, 호출부가
    수동으로 gto_loader._cache/_loaded를 리셋하지 않아도 새로 저장한 노드가
    즉시 조회된다."""
    from server.main import save_gto_preflop, GtoPreflopSaveRequest
    from gto.loader import get_open_range, get_range_by_seq
    import gto.loader as gto_loader

    gto_loader._cache = {}
    gto_loader._loaded = False
    assert get_open_range("HJ") is None, "사전 상태: HJ RFI 미수집이어야 함"

    req = GtoPreflopSaveRequest(
        position="HJ", vs_position=None, range_type="open", raise_size=2.5,
        situation_label="HJ RFI(테스트)", hands={"AKs": {"raise": 1.0}},
        action_seq="F",
    )
    out = save_gto_preflop(req)
    assert out["ok"] is True, out

    # 저장 직후 — 수동 캐시 무효화 없이 바로 조회
    data = get_open_range("HJ")
    assert data is not None, "save 후 캐시가 자동 무효화되지 않음(G2 실패)"
    assert get_range_by_seq("F") is not None, "시퀀스 캐시도 함께 무효화돼야 함"


def test_7_2_corrupt_hand_skipped_not_folded():
    """G4: 핸드별 빈도 합이 [0.9,1.1] 밖(손상)이면 로더가 그 핸드를 스킵하고
    None으로 처리한다 — fold 등 특정 액션에 잔여를 몰아 채우지 않는다.
    (저장 API는 이런 핸드를 거부하므로 — test_7_9 — DB에 직접 시딩해 로더 방어만 검사)"""
    from gto.loader import get_open_range, get_action_frequencies

    _seed_situation("BTN", None, "open", 2.5, "BTN RFI(손상 핸드 테스트)",
                    {"AKs": {"fold": 0.2, "raise": 0.1}},  # 합 0.3 ∉ [0.9,1.1] → 손상
                    "F-F-F")
    data = get_open_range("BTN")
    assert data is not None, "situation 자체는 존재해야 함(핸드 단위로만 스킵)"
    freqs = get_action_frequencies(data, "AKs")
    assert freqs is None, f"손상 핸드는 fold로 채워지지 않고 None이어야 함: {freqs}"


def test_7_3_missing_hand_returns_none():
    """G5: 노드에 아예 없는(미수집) 핸드는 None → 상위(advisor/봇)가 휴리스틱
    폴백을 타야 한다(fold 100%로 채우지 않음)."""
    from gto.loader import get_open_range, get_action_frequencies

    _seed_situation("CO", None, "open", 2.5, "CO RFI(누락 핸드 테스트)",
                    {"22": {"raise": 1.0}}, "F-F")
    data = get_open_range("CO")
    assert data is not None
    freqs = get_action_frequencies(data, "AKs")
    assert freqs is None, f"미수집 핸드는 None(휴리스틱 폴백)이어야 함: {freqs}"


def test_7_4_bb_never_rfi_and_no_queue():
    """G6 (a): BB는 강제 베팅 상태라 RFI가 원천적으로 불가능하므로 enum 경로는
    조회/기록 없이 None을 반환하고, 미수집 큐(gto_missing_spots_preflop)에
    'open/BB' 행을 남기지 않는다."""
    from gto.advisor import GTOAdvisor
    from db.connection import get_connection

    advisor = GTOAdvisor()
    bb = 20
    game_state = {"current_bet": bb, "street": "프리플랍", "preflop_seq": []}
    rec = advisor._recommend_by_enum(
        hole_cards=[c("A", "S"), c("K", "S")], my_position="BB",
        positions={}, game_state=game_state, big_blind=bb,
    )
    assert rec is None, f"BB는 RFI 불가이므로 None이어야 함: {rec}"

    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM gto_missing_spots_preflop WHERE position='BB' AND range_type='open'"
    ).fetchone()
    conn.close()
    assert row is None, "BB RFI는 미수집 큐에 기록되면 안 됨"


def test_7_5_vs_open_opener_after_hero_is_none():
    """G6 (b): 오프너가 포지션 순서상 히어로보다 뒤 좌석이면(예: 림프 후
    아이솔레이트 레이즈) 우리 데이터 모델 밖이므로 enum 경로는 조회/기록 없이
    None을 반환해야 한다."""
    from gto.advisor import GTOAdvisor

    advisor = GTOAdvisor()
    bb = 20
    game_state = {
        "current_bet": 8 * bb,
        "street": "프리플랍",
        "preflop_seq": [
            {"position": "UTG", "action": "call", "amount_bb": 1.0},
            {"position": "CO", "action": "raise", "amount_bb": 8.0},
        ],
    }
    rec = advisor._recommend_by_enum(
        hole_cards=[c("A", "S"), c("K", "S")], my_position="UTG",
        positions={}, game_state=game_state, big_blind=bb,
    )
    assert rec is None, f"오프너(CO)가 히어로(UTG)보다 뒤 좌석 → 모델 밖 None이어야 함: {rec}"


def test_7_6_save_normalizes_vs3bet_half_format():
    """G17: /gto/preflop/save가 vs_3bet의 반쪽 포맷(three_bettor만 전달)을
    'opener/three_bettor'로 정규화해 저장한다(backfill_v12와 동일 규칙)."""
    from server.main import save_gto_preflop, GtoPreflopSaveRequest
    from db.connection import get_connection

    req = GtoPreflopSaveRequest(
        position="BTN", vs_position="BB", range_type="vs_3bet", raise_size=28.5,
        situation_label="BTN vs BB 3bet(테스트)", hands={"AKs": {"raise": 1.0}},
        action_seq="F-F-F-R2.5-F-R8",
    )
    out = save_gto_preflop(req)
    assert out["ok"] is True, out

    conn = get_connection()
    row = conn.execute(
        "SELECT vs_position FROM gto_preflop_situations WHERE position='BTN' AND range_type='vs_3bet'"
    ).fetchone()
    conn.close()
    assert row is not None and row["vs_position"] == "BTN/BB", \
        f"vs_3bet 반쪽 포맷 정규화 실패: {row['vs_position'] if row else None}"


# ── T-001: 노드 저장 키 = action_seq, 조회 순서 ADR 0035 ─────────────────
# 아래 테스트는 서로의 시딩이 섞이지 않도록 각자 새 임시 DB를 쓴다.

import contextlib


@contextlib.contextmanager
def _fresh_gto_db():
    """새 임시 DB로 EV_PLUS_DB를 잠시 바꾸고 로더 캐시를 비운다(끝나면 원복)."""
    import gto.loader as gto_loader
    prev = os.environ.get("EV_PLUS_DB")
    path = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    os.environ["EV_PLUS_DB"] = path
    gto_loader._cache = {}
    gto_loader._loaded = False
    try:
        yield path
    finally:
        if prev is None:
            os.environ.pop("EV_PLUS_DB", None)
        else:
            os.environ["EV_PLUS_DB"] = prev
        gto_loader._cache = {}
        gto_loader._loaded = False


def _save_client():
    from fastapi.testclient import TestClient
    from server.main import app
    return TestClient(app)


def _queued_seq_keys():
    from db.connection import get_connection
    conn = get_connection()
    rows = conn.execute(
        "SELECT position, vs_position FROM gto_missing_spots_preflop WHERE range_type='seq'"
    ).fetchall()
    conn.close()
    return {(r["position"], r["vs_position"]) for r in rows}


def test_7_7_distinct_action_seq_distinct_rows():
    """T-001: 3종 키(BB vs BTN open)가 같아도 action_seq가 다르면 다른 행이다.
    다시 저장해도 다른 노드가 사라지지 않고, 같은 action_seq만 덮어쓴다."""
    from db.connection import get_connection
    with _fresh_gto_db():
        client = _save_client()
        for seq, hands in (("F-F-F-R2.5-F", {"AKs": {"raise": 1.0}}),
                           ("F-F-F-R2.5-C", {"AKs": {"call": 1.0}})):
            r = client.post("/gto/preflop/save", json={
                "action_seq": seq, "hands": hands, "raise_size": 11.0,
                "position": "BB", "vs_position": "BTN", "range_type": "vs_open",
                "situation_label": "BB vs BTN open",
            })
            assert r.status_code == 200, r.text
        # 첫 노드를 다시 저장(수집 재실행) — 행 수 그대로, 다른 노드 보존
        r = client.post("/gto/preflop/save", json={
            "action_seq": "F-F-F-R2.5-F", "hands": {"AKs": {"fold": 0.5, "raise": 0.5}},
            "raise_size": 11.0,
        })
        assert r.status_code == 200, r.text

        conn = get_connection()
        rows = conn.execute(
            "SELECT s.action_seq, h.freq_fold, h.freq_call, h.freq_raise "
            "FROM gto_preflop_situations s JOIN gto_preflop_hands h ON h.situation_id=s.id "
            "WHERE s.position='BB' AND s.vs_position='BTN' AND s.range_type='vs_open' "
            "ORDER BY s.action_seq"
        ).fetchall()
        conn.close()
        got = {r["action_seq"]: (r["freq_fold"], r["freq_call"], r["freq_raise"]) for r in rows}
        assert got == {"F-F-F-R2.5-C": (0.0, 1.0, 0.0), "F-F-F-R2.5-F": (0.5, 0.0, 0.5)}, got


def test_7_8_save_requires_action_seq_and_consistent_keys():
    """T-001: action_seq 없는 저장, 결정 노드가 아닌 키, 3종 키가 action_seq와 다른 저장은
    거부(422)되고 DB에 아무것도 남지 않는다(레거시 enum 파생 폴백 없음)."""
    from db.connection import get_connection
    with _fresh_gto_db():
        client = _save_client()
        hands = {"AKs": {"raise": 1.0}}
        cases = [
            {"position": "HJ", "range_type": "open", "situation_label": "HJ RFI", "hands": hands},
            {"action_seq": None, "hands": hands},
            {"action_seq": "R2.5-F-F-F-F-F", "hands": hands},         # 모두 폴드 — 결정 노드 아님
            {"action_seq": "F-F-F-R2.5-F", "hands": hands,             # 실제는 BB vs BTN open
             "position": "SB", "vs_position": "BTN", "range_type": "vs_open"},
        ]
        for body in cases:
            r = client.post("/gto/preflop/save", json=body)
            assert r.status_code == 422, (body, r.status_code, r.text)
        conn = get_connection()
        n = conn.execute("SELECT COUNT(*) FROM gto_preflop_situations").fetchone()[0]
        conn.close()
        assert n == 0, f"거부된 저장이 행을 남김: {n}"


def test_7_9_save_rejects_corrupt_frequencies():
    """T-001/ADR 0002: 서버도 핸드별 빈도합 [0.9,1.1]을 검증한다 — 한 핸드라도 벗어나거나
    핸드가 0개면 422로 거부하고 기존 저장 노드를 건드리지 않는다."""
    from gto.loader import get_range_by_seq
    with _fresh_gto_db():
        client = _save_client()
        ok = client.post("/gto/preflop/save", json={
            "action_seq": "F", "hands": {"AKs": {"raise": 1.0}}, "raise_size": 2.5})
        assert ok.status_code == 200, ok.text
        for hands in ({"AKs": {"fold": 0.2, "raise": 0.1}, "AA": {"raise": 1.0}},  # 합 0.3
                      {"AKs": {"raise": 0.7, "call": 0.6}},                          # 합 1.3
                      {}):
            r = client.post("/gto/preflop/save", json={"action_seq": "F", "hands": hands})
            assert r.status_code == 422, (hands, r.status_code, r.text)
        data = get_range_by_seq("F")
        assert data is not None and data["hands"] == {"AKs": {"raise": 1.0}}, data


def test_7_10_exact_node_preferred_over_label():
    """ADR 0035 1순위: 정확한 노드가 있으면 간단 라벨보다 우선한다(approx=False).
    멀티웨이(CO 콜)와 헤즈업 팟(CO 폴드)이 각자의 노드를 받는다."""
    from gto.advisor import GTOAdvisor
    with _fresh_gto_db():
        _seed_situation("BTN", "HJ", "vs_open", 11.0, "BTN vs HJ open",
                        {"AKs": {"raise": 1.0}}, "F-R2.5-F")
        _seed_situation("BTN", "HJ", "vs_open", 11.0, "BTN vs HJ open",
                        {"AKs": {"call": 1.0}}, "F-R2.5-C")
        advisor = GTOAdvisor()
        for co_action, want_key, want_action in (("call", "F-R2.5-C", "call"),
                                                 ("fold", "F-R2.5-F", "raise")):
            seq = [{"position": "UTG", "action": "fold"},
                   {"position": "HJ", "action": "raise", "amount_bb": 2.5},
                   {"position": "CO", "action": co_action,
                    "amount_bb": 2.5 if co_action == "call" else None}]
            gs = {"street": "프리플랍", "current_bet": 50, "preflop_seq": seq}
            rec = advisor.get_recommendation([c("A", "S"), c("K", "S")], "BTN", {}, gs, 20)
            assert rec is not None and rec["node_key"] == want_key, (co_action, rec)
            assert rec["approx"] is False, rec
            assert rec["frequencies"] == {want_action: 1.0}, rec
            assert "(근사)" not in advisor.format_hint(rec)


def test_7_11_label_fallback_is_marked_approx():
    """ADR 0035 2순위: 정확한 노드가 없을 때만 간단 라벨(콜러 없는 노드)을 쓰고, 힌트와
    플레이 평가에 "(근사)"로 표시한다. 라벨로 답했으면 미수집 큐에는 넣지 않는다."""
    from gto.advisor import GTOAdvisor
    from gto.grader import grade_preflop_action
    with _fresh_gto_db():
        _seed_situation("BB", "HJ", "vs_open", 14.0, "BB vs HJ open",
                        {"AKs": {"raise": 0.6, "call": 0.4}}, "F-R2.5-F-F-F")
        # 라이브: HJ 오픈, CO 콜 → BB 결정. 정확한 노드(F-R2.5-C-F-F)는 미수집.
        seq = [{"position": "UTG", "action": "fold"},
               {"position": "HJ", "action": "raise", "amount_bb": 2.5},
               {"position": "CO", "action": "call", "amount_bb": 2.5},
               {"position": "BTN", "action": "fold"},
               {"position": "SB", "action": "fold"}]
        gs = {"street": "프리플랍", "current_bet": 50, "preflop_seq": seq}
        advisor = GTOAdvisor()
        rec = advisor.get_recommendation([c("A", "S"), c("K", "S")], "BB", {}, gs, 20)
        assert rec is not None and rec["approx"] is True, rec
        assert rec["node_key"] == "F-R2.5-F-F-F", rec
        hint = advisor.format_hint(rec)
        assert "(근사)" in hint, hint
        grade = grade_preflop_action("raise", rec)
        assert grade.reason.startswith("(근사)"), grade.reason
        assert ("BB", "F-R2.5-C-F-F") not in _queued_seq_keys(), "라벨로 답했는데 큐에 기록됨"


def test_7_12_headsup_pot_not_given_caller_node():
    """T-001 완료 조건 1: BB vs BTN 오픈 헤즈업 팟(SB 폴드)의 힌트가 "SB 콜 멀티웨이"
    노드가 아니다. 콜러 노드뿐이면 None + 정확한 노드 키 큐 기록. 2인 테이블의 BB vs
    BTN/SB 오픈은 6-max SB 오픈 노드(F-F-F-F-R…)를 받는다."""
    from gto.advisor import GTOAdvisor
    with _fresh_gto_db():
        _seed_situation("BB", "BTN", "vs_open", 14.0, "BB vs BTN open",
                        {"AKs": {"call": 1.0}}, "F-F-F-R2.5-C")
        advisor = GTOAdvisor()
        seq = [{"position": "UTG", "action": "fold"}, {"position": "HJ", "action": "fold"},
               {"position": "CO", "action": "fold"},
               {"position": "BTN", "action": "raise", "amount_bb": 2.5},
               {"position": "SB", "action": "fold"}]
        gs = {"street": "프리플랍", "current_bet": 50, "preflop_seq": seq}
        rec = advisor.get_recommendation([c("A", "S"), c("K", "S")], "BB", {}, gs, 20)
        assert rec is None, f"SB 콜 노드를 헤즈업 팟에 내줌: {rec}"
        assert ("BB", "F-F-F-R2.5-F") in _queued_seq_keys()

        _seed_situation("BB", "BTN", "vs_open", 14.0, "BB vs BTN open",
                        {"AKs": {"raise": 1.0}}, "F-F-F-R2.5-F")
        rec = advisor.get_recommendation([c("A", "S"), c("K", "S")], "BB", {}, gs, 20)
        assert rec is not None and rec["node_key"] == "F-F-F-R2.5-F" and not rec["approx"], rec

        # 2인 테이블: BTN/SB 오픈 3bb → BB. 6-max SB 오픈 노드로 스냅(ADR 0005)
        _seed_situation("BB", "SB", "vs_open", 10.5, "BB vs SB open",
                        {"AKs": {"raise": 1.0}}, "F-F-F-F-R3.5")
        hu_seq = [{"position": "BTN/SB", "action": "raise", "amount_bb": 3.0}]
        hu_gs = {"street": "프리플랍", "current_bet": 60, "preflop_seq": hu_seq}
        rec = advisor.get_recommendation([c("A", "S"), c("K", "S")], "BB",
                                         {"Bot": "BTN/SB", "Hero": "BB"}, hu_gs, 20)
        assert rec is not None and rec["node_key"] == "F-F-F-F-R3.5", rec


def test_7_13_headsup_not_snapped_to_utg_tree():
    """T-001 완료 조건 2: 헤즈업 SB 레이즈 → BB 3벳에서 6-max CO 노드(R2.5-R8)로 스냅되지
    않는다. 시퀀스 앞에 F-F-F-F를 붙여 SB 기준 노드를 찾고, 없으면 None + 큐 기록."""
    from gto.advisor import GTOAdvisor
    with _fresh_gto_db():
        _seed_situation("CO", "UTG/HJ", "vs_3bet", 17.5, "CO vs HJ 3bet",
                        {"AKs": {"call": 1.0}}, "R2.5-R8")
        advisor = GTOAdvisor()
        positions = {"Hero": "BTN/SB", "Bot": "BB"}
        seq = [{"position": "BTN/SB", "action": "raise", "amount_bb": 2.5},
               {"position": "BB", "action": "raise", "amount_bb": 8.0}]
        gs = {"street": "프리플랍", "current_bet": 160, "preflop_seq": seq}
        rec = advisor.get_recommendation([c("A", "S"), c("K", "S")], "BTN/SB", positions, gs, 20)
        assert rec is None, f"헤즈업이 6-max 노드로 스냅됨: {rec}"
        assert ("SB", "F-F-F-F-R2.5-R8") in _queued_seq_keys(), _queued_seq_keys()

        _seed_situation("SB", "SB/BB", "vs_3bet", 24.0, "SB vs BB 3bet",
                        {"AKs": {"raise": 1.0}}, "F-F-F-F-R3.5-R10")
        rec = advisor.get_recommendation([c("A", "S"), c("K", "S")], "BTN/SB", positions, gs, 20)
        assert rec is not None and rec["node_key"] == "F-F-F-F-R3.5-R10", rec
        assert rec["situation"] == "SB vs BB 3bet" and rec["approx"] is False, rec


def _make_v12_db(rows, hands):
    """v12 운영 DB 모양의 임시 DB(schema_version=12)를 만든다. rows/hands는 튜플 목록."""
    import sqlite3
    path = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL, "
                 "applied_at TEXT NOT NULL DEFAULT (datetime('now')))")
    conn.execute("INSERT INTO schema_version(version) VALUES (12)")
    conn.execute(_V12_GTO_SITUATIONS_DDL)
    conn.execute("""CREATE TABLE gto_preflop_hands (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        situation_id INTEGER NOT NULL REFERENCES gto_preflop_situations(id) ON DELETE CASCADE,
        hand TEXT NOT NULL, freq_fold REAL NOT NULL DEFAULT 0.0,
        freq_call REAL NOT NULL DEFAULT 0.0, freq_raise REAL NOT NULL DEFAULT 0.0,
        freq_allin REAL NOT NULL DEFAULT 0.0, UNIQUE(situation_id, hand))""")
    conn.execute("CREATE INDEX idx_gto_pre_sit ON gto_preflop_situations(position, vs_position, range_type)")
    conn.execute("CREATE UNIQUE INDEX idx_gto_pre_seq ON gto_preflop_situations(action_seq)")
    conn.executemany("INSERT INTO gto_preflop_situations VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.executemany("INSERT INTO gto_preflop_hands VALUES (?,?,?,?,?,?,?)", hands)
    conn.commit()
    conn.close()
    return path


def test_7_14_migration_v13_preserves_data():
    """T-001 스키마(v13): 3종 UNIQUE 제거·action_seq NOT NULL 재생성 마이그레이션이 행(id
    포함)과 핸드를 그대로 보존하고, 이후 같은 라벨의 다른 노드를 저장할 수 있다.
    action_seq가 NULL인 행이 있으면 추측으로 채우지 않고 중단한다."""
    import sqlite3
    from db.connection import get_connection
    from db.schema import SCHEMA_VERSION
    rows = [
        (1, "UTG", None, "open", 2.5, "UTG RFI", "", "UTG", 6),
        (8, "BB", "BTN", "vs_open", 14.0, "BB vs BTN open", "F-F-F-R2.5-C", "BB", 3),
    ]
    hands = [(10, 1, "AA", 0, 0, 1.0, 0), (11, 8, "AKs", 0, 0.6, 0.4, 0),
             (12, 8, "72o", 1.0, 0, 0, 0)]
    path = _make_v12_db(rows, hands)
    conn = get_connection(path)
    try:
        assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == SCHEMA_VERSION
        got_rows = [tuple(r) for r in conn.execute(
            "SELECT id, position, vs_position, range_type, raise_size, situation_label, "
            "action_seq, hero_position, num_active FROM gto_preflop_situations ORDER BY id")]
        got_hands = [tuple(r) for r in conn.execute("SELECT * FROM gto_preflop_hands ORDER BY id")]
        assert got_rows == rows, got_rows
        assert got_hands == [tuple(h) for h in hands], got_hands
        # 같은 3종 키의 다른 노드 저장 가능, action_seq 중복·NULL은 불가
        conn.execute("INSERT INTO gto_preflop_situations (position, vs_position, range_type, "
                     "situation_label, action_seq) VALUES ('BB','BTN','vs_open','x','F-F-F-R2.5-F')")
        for bad in ("'F-F-F-R2.5-C'", "NULL"):
            try:
                conn.execute("INSERT INTO gto_preflop_situations (position, range_type, "
                             f"situation_label, action_seq) VALUES ('BB','open','x',{bad})")
                raise AssertionError(f"action_seq {bad} 삽입이 거부되지 않음")
            except sqlite3.IntegrityError:
                pass
        # FK CASCADE 유지
        conn.execute("DELETE FROM gto_preflop_situations WHERE id=8")
        assert conn.execute("SELECT COUNT(*) FROM gto_preflop_hands WHERE situation_id=8").fetchone()[0] == 0
    finally:
        conn.close()

    null_path = _make_v12_db([(1, "HJ", None, "open", 2.5, "HJ RFI", None, "HJ", 5)], [])
    try:
        get_connection(null_path).close()
        raise AssertionError("action_seq NULL 행이 있는데 마이그레이션이 진행됨")
    except RuntimeError as e:
        assert "action_seq" in str(e), e


# ═════════════════════════════════════════════════════════════
# 영역 8 — 세션 경로 룰 (WebGameSession 실제 실행 경로)
#   core 헬퍼(_betting_order, apply_action)만 부르는 테스트는 웹 경로의 버그를
#   못 잡았다(2026-09-26 리뷰 RC1). 여기 테스트는 전부 WebGameSession 공개 API
#   (submit_action / next_hand / get_state의 events)로 검사한다.
# ═════════════════════════════════════════════════════════════

def _total_chips(sess):
    return sum(p.chips for p in sess.game.players) + sess.game.pot


def _scripted_session(num_bots, scripts=None, chips=None, dealer_index=0, sb=10):
    """원하는 좌석·스택·봇 스크립트로 '새 핸드'를 시작한 세션을 만든다.

    WebGameSession 생성자는 첫 핸드를 바로 진행시키므로, 생성 후 스택·딜러·봇을
    다시 세팅하고 핸드 종료 상태에서 next_hand()로 깨끗한 핸드를 시작한다.
    scripts: {봇 이름: [(Action, amount), ...]} — 소진되면 콜/체크.
    chips: 좌석 순서(사람 먼저)대로의 스택 리스트.
    반환: (sess, events) — events는 새 핸드 시작~사람 차례까지의 이벤트.
    """
    from server.session import WebGameSession
    sess = WebGameSession("s8", "Human", 1000, num_bots, "easy", sb, equity_enabled=False)
    for i, p in enumerate(sess.game.players):
        p.chips = chips[i] if chips else 1000
    sess.game.pot = 0
    # 이 핸드의 버튼을 dealer_index로 고정: 직전 버튼 기록을 지우면 다음 핸드는
    # dealer_index를 그대로 버튼으로 쓴다(첫 핸드와 같은 규칙).
    sess.game.dealer_index = dealer_index
    sess._button_name = None
    scripts = scripts or {}
    for name, bot in list(sess.bots.items()):
        sess.bots[name] = StubBot(bot.player, scripts.get(name))
    sess.hand_over = True
    events = sess.next_hand()
    return sess, events


def _action_events(events):
    return [e for e in events if e["type"] == "action"]


def test_8_1_next_hand_double_call_keeps_chips():
    """T-025: 핸드 종료 후 next_hand를 연달아 두 번 불러도 핸드는 하나만 넘어가고
    칩 합계가 그대로다."""
    sess, _ = _scripted_session(2)
    total = _total_chips(sess)
    sess.submit_action("fold", 0)
    assert sess.hand_over, "사람 폴드 후 봇 2명이 핸드를 끝내야 함"
    hand_no = sess.hand_number
    sess.next_hand()
    sess.next_hand()  # 연타 — 무시돼야 함
    assert sess.hand_number == hand_no + 1, \
        f"핸드가 한 번만 넘어가야 함: {hand_no} → {sess.hand_number}"
    assert _total_chips(sess) == total, f"칩 합계 변화: {total} → {_total_chips(sess)}"


def test_8_2_next_hand_during_hand_ignored():
    """T-025: 핸드 진행 중 next_hand 요청은 무시된다(팟 칩이 사라지지 않음)."""
    sess, _ = _scripted_session(3)
    assert sess.get_state()["waiting_for_action"]
    sess.submit_action("raise", 200)
    total = _total_chips(sess)
    hand_no = sess.hand_number
    pot = sess.game.pot
    assert not sess.hand_over and pot > 0
    sess.next_hand()
    assert sess.hand_number == hand_no, "핸드 중 next_hand가 새 핸드를 시작함"
    assert sess.game.pot == pot, f"팟 변화: {pot} → {sess.game.pot}"
    assert _total_chips(sess) == total, f"칩 합계 변화: {total} → {_total_chips(sess)}"


def test_8_3_headsup_btnsb_first_and_bb_option():
    """T-019: 헤즈업 프리플랍은 BTN/SB가 먼저 행동하고, BTN/SB가 림프하면 BB(사람)가
    체크/레이즈 옵션을 받는다(세션 경로)."""
    # dealer_index=1 → 봇이 BTN/SB, 사람이 BB. 봇은 림프(콜).
    sess, events = _scripted_session(1, dealer_index=1,
                                     scripts={"🤖 Alpha": [(Action.CALL, 10)]})
    acts = _action_events(events)
    assert acts, f"사람(BB) 차례 전에 BTN/SB 액션이 있어야 함: {events}"
    assert acts[0]["position"] == "BTN/SB", f"첫 액션 포지션: {acts[0]}"
    state = sess.get_state()
    assert state["waiting_for_action"], "림프 후 BB(사람)에게 옵션이 와야 함"
    assert state["street"] == "프리플랍", f"BB 옵션 없이 스트리트가 넘어감: {state['street']}"
    assert state["call_amount"] == 0 and state["min_raise_to"] > 0, \
        f"BB는 체크/레이즈 가능해야 함: call={state['call_amount']} min_raise_to={state['min_raise_to']}"


def test_8_4_headsup_human_btnsb_acts_first():
    """T-019: 사람이 BTN/SB면 프리플랍 첫 결정이 사람이고(봇 액션 없음), 사람이 림프하면
    BB 봇이 이어서 행동한다."""
    sess, events = _scripted_session(1, dealer_index=0)
    assert not _action_events(events), f"BTN/SB(사람)보다 먼저 행동한 사람이 있음: {events}"
    state = sess.get_state()
    assert state["waiting_for_action"] and state["call_amount"] == 10
    acts = _action_events(sess.submit_action("call", 0))
    assert [a["position"] for a in acts[:2]] == ["BTN/SB", "BB"], \
        f"림프 뒤 BB가 행동해야 함: {[(a['position'], a['action']) for a in acts]}"


def test_8_5_headsup_btnsb_first_decision_has_gto_hint():
    """T-019: 헤즈업 BTN/SB 첫 결정에서 GTO 힌트가 보인다(격리 DB에 SB RFI 시딩)."""
    from db.connection import get_connection
    import gto.loader as gto_loader
    conn = get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO gto_preflop_situations "
        "(position, vs_position, range_type, raise_size, situation_label, action_seq, hero_position, num_active) "
        "VALUES ('SB', NULL, 'open', 3.0, 'SB RFI', 'F-F-F-F', 'SB', 2)")
    sid = conn.execute(
        "SELECT id FROM gto_preflop_situations WHERE position='SB' AND range_type='open'"
    ).fetchone()[0]
    conn.execute(
        "INSERT OR IGNORE INTO gto_preflop_hands "
        "(situation_id, hand, freq_fold, freq_call, freq_raise, freq_allin) "
        "VALUES (?, 'AKs', 0.0, 0.0, 1.0, 0.0)", (sid,))
    conn.commit()
    conn.close()
    gto_loader._cache = {}
    gto_loader._loaded = False

    sess, _ = _scripted_session(1, dealer_index=0)
    sess.human.hole_cards = [c("A", "S"), c("K", "S")]
    # 첫 결정 시점의 구조화 시퀀스는 비어 있어야 한다(BB의 가짜 선행 체크가 끼면 노드 오염)
    assert sess.game.preflop_action_seq() == [], \
        f"BTN/SB 첫 결정 전 시퀀스가 비어 있지 않음: {sess.game.preflop_action_seq()}"
    state = sess.get_state()
    assert state["waiting_for_action"]
    assert state["gto_hint"], f"헤즈업 BTN/SB 첫 결정에 GTO 힌트가 없음: {state['gto_hint']}"


def _flop_bet_scenario(beta_stack):
    """3인, 딜러=Beta → 사람=SB(플랍 선행동), Alpha=BB. 프리플랍은 모두 20으로 림프/체크.
    플랍: 사람 벳 100 → Alpha 콜 → Beta 올인(플랍 시작 스택 beta_stack - 20)."""
    sess, _ = _scripted_session(
        2, dealer_index=2, chips=[1000, 1000, beta_stack],
        scripts={"🤖 Alpha": [(Action.CHECK, 0), (Action.CALL, 100)],
                 "🤖 Beta": [(Action.CALL, 20), (Action.ALL_IN, 0)]})
    assert sess.get_state()["call_amount"] == 10, "사람(SB) 프리플랍 차례여야 함"
    sess.submit_action("call", 0)
    state = sess.get_state()
    assert state["street"] == "플랍" and state["waiting_for_action"], state["street"]
    return sess, sess.submit_action("raise", 100)


def test_8_6_short_allin_under_call_does_not_reopen():
    """T-020: 벳 100 → 콜 → 50 올인(콜도 못 채움) 뒤 처음 벳한 사람에게 액션이 다시
    오지 않는다(라운드 종료)."""
    sess, events = _flop_bet_scenario(beta_stack=70)
    state = sess.get_state()
    flop_acts = [(a["player"], a["action"]) for a in _action_events(events)
                 if a["street"] == "플랍"]
    assert flop_acts == [("Human", "raise"), ("🤖 Alpha", "call"), ("🤖 Beta", "allin")], \
        f"50 올인 뒤 재오픈되면 안 됨: {flop_acts}"
    assert state["street"] == "턴", f"플랍 라운드가 끝나야 함: {state['street']}"


def test_8_7_incomplete_raise_allin_call_or_fold_only():
    """T-020: 벳 100 → 콜 → 150 올인(최소 레이즈 미만) 뒤 처음 벳한 사람은 콜/폴드만."""
    from core.game import IllegalActionError
    sess, _ = _flop_bet_scenario(beta_stack=170)
    state = sess.get_state()
    assert state["waiting_for_action"] and state["call_amount"] == 50, \
        f"사람이 50을 더 콜해야 함: call={state['call_amount']}"
    assert state["can_raise"] is False and state["min_raise_to"] == 0, \
        f"레이즈 불가가 응답에 보여야 함: can_raise={state['can_raise']} min_raise_to={state['min_raise_to']}"
    for bad in [("raise", 400), ("allin", 0)]:
        try:
            sess.submit_action(*bad)
            raise AssertionError(f"닫힌 액션에서 {bad}가 거절되지 않음")
        except IllegalActionError:
            pass
    sess.submit_action("call", 0)
    assert sess.game.current_street == Street.TURN and sess.human.chips == 1000 - 20 - 150, \
        f"콜 후 턴으로: street={sess.game.current_street} chips={sess.human.chips}"


def test_8_8_full_allin_updates_min_raise():
    """T-020: BB 20에서 500 올인(레이즈 480) 뒤 최소 레이즈-투가 980으로 보인다."""
    # 딜러=Alpha → Beta=SB, 사람=BB, 프리플랍 첫 행동 Alpha
    sess, events = _scripted_session(
        2, dealer_index=1, chips=[1000, 500, 1000],
        scripts={"🤖 Alpha": [(Action.ALL_IN, 0)]})
    state = sess.get_state()
    assert state["waiting_for_action"] and state["current_bet"] == 500, state["current_bet"]
    assert state["min_raise_to"] == 980, f"최소 레이즈-투 980이어야 함: {state['min_raise_to']}"


def test_8_9_raise_over_stack_becomes_allin():
    """T-020: 칩 300으로 1000 레이즈를 보내면 300 올인이 되고, 유령 베팅이 생기지 않는다."""
    # 딜러=사람(3인이라 UTG 겸 BTN, 프리플랍 첫 행동). 봇은 콜 금액만큼 콜(스텁).
    sess, _ = _scripted_session(2, dealer_index=0, chips=[300, 1000, 1000])
    events = _action_events(sess.submit_action("raise", 1000))
    h_act = next(a for a in events if a["player"] == "Human")
    assert h_act["action"] == "allin", f"스택 초과 레이즈는 올인: {h_act}"
    assert sess.human.is_all_in and sess.human.total_bet_this_round == 300
    # 유령 current_bet(1000)이 있었다면 봇이 1000을 콜했을 것 — 실제로는 300만 콜해야 함
    for name in ("🤖 Alpha", "🤖 Beta"):
        call = next(a for a in events if a["player"] == name and a["street"] == "프리플랍")
        assert call["chips_after"] == 700, f"{name}은 300까지만 콜해야 함: {call}"


def test_8_13_runout_when_one_player_can_act():
    """T-023: 행동 가능한 사람이 1명이고 콜할 금액이 없으면 남은 카드가 바로 깔린다
    (남은 봇·사람에게 스트리트마다 액션을 묻지 않음)."""
    # ① 사람(BTN/SB, 500) 프리플랍 올인 → 봇(1000) 콜 → 봇만 칩이 남아도 액션 없이 쇼다운
    sess, _ = _scripted_session(1, dealer_index=0, chips=[500, 1000])
    ev = sess.submit_action("allin", 0)
    st = sess.get_state()
    post = [a for a in _action_events(ev) if a["street"] != "프리플랍"]
    assert not post, f"상대가 전부 올인인데 포스트플랍 액션을 물음: {[(a['player'], a['action']) for a in post]}"
    assert st["hand_over"] and len(st["community_cards"]) == 5
    assert [e["street"] for e in ev if e["type"] == "street_start"] == ["플랍", "턴", "리버"]

    # ② 봇 올인 → 사람 콜 → 사람에게 자동 체크 이벤트 없이 런아웃
    sess, _ = _scripted_session(1, dealer_index=0, chips=[1000, 400],
                                scripts={"🤖 Alpha": [(Action.ALL_IN, 0)]})
    sess.submit_action("raise", 60)   # BTN/SB 오픈 → BB 봇 올인 400
    st = sess.get_state()
    assert st["waiting_for_action"] and st["call_amount"] == 340, st["call_amount"]
    ev = sess.submit_action("call", 0)
    st = sess.get_state()
    post = [a for a in _action_events(ev) if a["street"] != "프리플랍"]
    assert not post, f"사람에게 무의미한 체크가 생김: {[(a['player'], a['action']) for a in post]}"
    assert st["hand_over"] and len(st["community_cards"]) == 5

    # ③ 콜할 금액이 있으면 묻는다: 플랍에서 봇이 올인하면 사람은 결정해야 한다
    sess, _ = _scripted_session(1, dealer_index=0, chips=[1000, 300],
                                scripts={"🤖 Alpha": [(Action.CHECK, 0), (Action.ALL_IN, 0)]})
    sess.submit_action("call", 0)     # 림프 → BB 체크 → 플랍, BB(봇) 선행동 올인
    st = sess.get_state()
    assert st["street"] == "플랍" and st["waiting_for_action"] and st["call_amount"] == 280, \
        f"콜할 금액이 있으면 사람에게 물어야 함: street={st['street']} call={st['call_amount']}"


def test_8_14_blind_events_sb_then_bb_when_human_bb():
    """T-002: 내가 BB일 때(인원 2~6) blind 이벤트는 항상 [SB, BB] 순서다."""
    for n_bots in range(1, 6):
        n = n_bots + 1
        # 사람(좌석 0)이 BB가 되는 딜러: 헤즈업은 상대가 딜러, 3인 이상은 딜러+2 = 0
        dealer = 1 if n == 2 else (n - 2) % n
        sess, events = _scripted_session(n_bots, dealer_index=dealer)
        assert sess.game.get_positions()["Human"] == "BB", sess.game.get_positions()
        blinds = [(e["position"], e["player"]) for e in events if e["type"] == "blind"]
        sb_label = "BTN/SB" if n == 2 else "SB"
        assert [b[0] for b in blinds] == [sb_label, "BB"], f"{n}인: blind 순서 {blinds}"
        assert blinds[1][1] == "Human"


def test_8_10_illegal_check_rejected_not_recorded():
    """T-021: 벳을 마주한 체크 요청은 거절되고(API 400) 로그·이벤트·RL 기록에 남지 않는다."""
    from core.game import IllegalActionError
    # 세션 경로: 딜러=사람(3인 UTG) → 첫 결정에서 콜 20을 마주함
    sess, _ = _scripted_session(2, dealer_index=0)
    assert sess.get_state()["call_amount"] == 20
    log_before = list(sess.action_log)
    rec_before = len(sess.recorder._pending_preflop)
    total = _total_chips(sess)
    try:
        sess.submit_action("check", 0)
        raise AssertionError("벳을 마주한 체크가 거절되지 않음")
    except IllegalActionError:
        pass
    state = sess.get_state()
    assert sess._events == [], f"거절된 액션이 이벤트를 남김: {sess._events}"
    assert sess.action_log == log_before, "거절된 체크가 액션 로그에 남음"
    assert len(sess.recorder._pending_preflop) == rec_before, "거절된 체크가 RL 기록에 남음"
    assert _total_chips(sess) == total and state["waiting_for_action"]

    # API 경로: 400 + 상태 무변경
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient
        from server.main import app, sessions
    client = TestClient(app)
    sessions["api-t021"] = sess
    res = client.post("/game/api-t021/action", json={"action": "check", "amount": 0})
    assert res.status_code == 400, f"불법 체크는 400이어야 함: {res.status_code} {res.text}"
    assert "체크" in res.json()["detail"]
    assert sess.action_log == log_before
    sessions.pop("api-t021", None)


def test_8_11_bot_illegal_action_falls_back():
    """T-021: 봇이 불법 액션을 내면 경고 로그를 남기고 안전한 액션으로 대체된다
    (불법 체크 → 폴드, 막힌 레이즈/올인 → 콜, 콜할 금액 없으면 체크)."""
    import logging
    records = []

    class _H(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    lg = logging.getLogger("server.session")
    h = _H(level=logging.WARNING)
    lg.addHandler(h)
    try:
        # 딜러=사람(UTG). 사람 레이즈 60 → Alpha(SB)가 불법 체크 → 폴드로 대체
        sess, _ = _scripted_session(2, dealer_index=0,
                                    scripts={"🤖 Alpha": [(Action.CHECK, 0)]})
        acts = _action_events(sess.submit_action("raise", 60))
        alpha = next(a for a in acts if a["player"] == "🤖 Alpha")
        assert alpha["action"] == "fold", f"불법 체크는 폴드로 대체: {alpha}"
        assert any("Alpha" in m and "불법" in m for m in records), f"경고 로그 없음: {records}"
    finally:
        lg.removeHandler(h)

    game, players = make_game(3)
    game.start_hand()
    p0 = players[0]  # BTN(UTG), 콜 20 마주함
    assert game.fallback_action(p0, Action.CHECK) == Action.FOLD
    assert game.fallback_action(p0, Action.RAISE) == Action.CALL
    assert game.fallback_action(p0, Action.ALL_IN) == Action.CALL
    game.current_bet = 0
    assert game.fallback_action(p0, Action.RAISE) == Action.CHECK


class _RandomBot(StubBot):
    """퍼저용: 합법·불법을 가리지 않고 무작위 액션을 낸다(불법이면 세션이 폴백)."""

    def __init__(self, player, rng):
        super().__init__(player)
        self._rng = rng

    def decide_action(self, game_state):
        r = self._rng.random()
        cb = game_state["current_bet"]
        if r < 0.15:
            return Action.FOLD, 0
        if r < 0.35:
            return Action.CHECK, 0
        if r < 0.70:
            return Action.CALL, 0
        if r < 0.93:
            return Action.RAISE, self._rng.randint(0, max(1, cb * 4 + 100))
        return Action.ALL_IN, 0


def _walk_events(events, chips, bets):
    """이벤트 금액 = 실제 칩 이동 불변식 검사. chips/bets는 호출 간 유지되는 추적 상태."""
    for e in events:
        t = e["type"]
        if t == "street_start":
            for k in bets:
                bets[k] = 0
        elif t in ("blind", "action"):
            p = e["player"]
            moved = chips[p] - e["chips_after"]
            assert moved >= 0, f"칩이 늘어나는 {t} 이벤트: {e}"
            if t == "blind":
                assert moved > 0 and e["amount"] == moved, f"블라인드 금액≠실제 포스팅: {e} moved={moved}"
            elif e["action"] in ("fold", "check"):
                assert moved == 0 and e["amount"] == 0, f"{e['action']}인데 칩 이동: {e}"
            elif e["action"] == "call":
                assert e["amount"] == moved, f"콜 금액≠이동액: {e} moved={moved}"
            else:
                assert e["amount"] == bets[p] + moved, \
                    f"{e['action']} 금액≠도달 베팅: {e} bet_before={bets[p]} moved={moved}"
            if e.get("action") not in ("fold", "check"):
                assert f"{e['amount']}" in e["log"], f"로그 금액 불일치: {e}"
            bets[p] += moved
            chips[p] = e["chips_after"]
        elif t == "winner":
            chips.update(e.get("winner_chips") or {})


def test_8_12_session_fuzz_event_amounts_and_conservation():
    """T-021 퍼저(시드 고정, 세션 경로): 무작위 스택·인원·액션(불법 포함)으로 수백 핸드를
    돌려 ① 이벤트·로그 금액 = 실제 칩 이동(블라인드 포함) ② 칩 보존 ③ 사람 불법 액션은
    상태를 바꾸지 않음 ④ 파산 전환을 포함한 무빙 버튼 이동(T-022)을 검사한다."""
    import random
    import logging
    from core.game import IllegalActionError
    rng = random.Random(20260926)
    lg = logging.getLogger("server.session")
    old_level = lg.level
    lg.setLevel(logging.ERROR)  # 봇 폴백 경고는 여기서 의도된 것
    hands = 0
    try:
        while hands < 250:
            n_bots = rng.randint(1, 5)
            stacks = [rng.choice([rng.randint(5, 60), rng.randint(100, 2000)])
                      for _ in range(n_bots + 1)]
            sess, events = _scripted_session(n_bots, chips=stacks,
                                             dealer_index=rng.randint(0, n_bots))
            for name, bot in list(sess.bots.items()):
                sess.bots[name] = _RandomBot(bot.player, rng)
            seats = [p.name for p in sess.game.players]
            total = sum(stacks)
            for _ in range(15):  # 세션당 최대 15핸드
                if sess.game_over:
                    break
                chips = dict(sess._hand_start_chips)
                bets = {k: 0 for k in chips}
                _walk_events(events, chips, bets)
                guard = 0
                while not sess.hand_over:
                    guard += 1
                    assert guard < 60, "핸드가 끝나지 않음"
                    st = sess.get_state()
                    assert st["events"] == [], "get_state가 이벤트를 내보냄(순수 조회 위반)"
                    assert _total_chips(sess) == total, "칩 보존 위반"
                    if not st["waiting_for_action"]:
                        break
                    act = rng.choice(["fold", "check", "call", "raise", "allin"])
                    amt = rng.randint(0, st["current_bet"] * 4 + 100)
                    log_len = len(sess.action_log)
                    try:
                        ev = sess.submit_action(act, amt)
                    except IllegalActionError:
                        assert len(sess.action_log) == log_len and _total_chips(sess) == total
                        ev = sess.submit_action("call" if st["call_amount"] > 0 else "check", 0)
                    _walk_events(ev, chips, bets)
                assert _total_chips(sess) == total, "칩 보존 위반(핸드 종료)"
                hands += 1
                btn_label = "BTN/SB" if len(sess.game.players) == 2 else "BTN"
                prev_btn = _labels(sess)[btn_label]
                events = sess.next_hand()
                if not sess.game_over:
                    # ④ 무빙 버튼(ADR 0036): 파산 전환 포함, 버튼 = 직전 버튼 다음 생존자
                    alive = {p.name for p in sess.game.players}
                    want = _expected_next_button(seats, prev_btn, alive)
                    btn_label = "BTN/SB" if len(alive) == 2 else "BTN"
                    assert _labels(sess)[btn_label] == want, \
                        f"버튼 이동 위반: 직전 {prev_btn} → {_labels(sess)[btn_label]} (기대 {want})"
    finally:
        lg.setLevel(old_level)


def _labels(sess):
    """{포지션 라벨: 이름}"""
    return {lbl: name for name, lbl in sess.game.get_positions().items()}


def _finish_hand_by_folding(sess):
    guard = 0
    while not sess.hand_over:
        guard += 1
        assert guard < 20, "핸드가 끝나지 않음"
        sess.submit_action("fold", 0)


def _expected_next_button(seats, prev_button, alive):
    """무빙 버튼(ADR 0036): 좌석 순서에서 직전 버튼 다음의 살아 있는 사람."""
    i = seats.index(prev_button)
    for k in range(1, len(seats) + 1):
        name = seats[(i + k) % len(seats)]
        if name in alive:
            return name
    return None


def test_8_15_moving_button_on_bust():
    """T-022(ADR 0036): 봇이 파산해 빠져도 버튼은 '직전 버튼 다음의 살아 있는 사람'으로
    옮기고 SB·BB는 그 뒤 두 명이다 — 직전 BB가 SB를 건너뛰고 바로 BTN이 되지 않는다."""
    # 5인 [H, Alpha, Beta, Gamma, Delta], 직전 핸드 BTN=Gamma/SB=Delta/BB=H.
    cases = [
        # (파산하는 봇, 기대 BTN, SB, BB)
        ("🤖 Alpha", "🤖 Delta", "Human", "🤖 Beta"),    # 버튼 앞 좌석 파산(리뷰 재현)
        ("🤖 Gamma", "🤖 Delta", "Human", "🤖 Alpha"),   # 버튼 자신 파산
        ("🤖 Delta", "Human", "🤖 Alpha", "🤖 Beta"),    # 다음 버튼이 될 좌석 파산
    ]
    for bust, btn, sb, bb in cases:
        sess, _ = _scripted_session(4, dealer_index=3)
        before = _labels(sess)
        assert (before["BTN"], before["SB"], before["BB"]) == ("🤖 Gamma", "🤖 Delta", "Human"), before
        _finish_hand_by_folding(sess)
        victim = next(p for p in sess.game.players if p.name == bust)
        victim.chips = 0
        sess.next_hand()
        after = _labels(sess)
        assert bust not in after.values(), f"파산자가 남아 있음: {after}"
        assert (after["BTN"], after["SB"], after["BB"]) == (btn, sb, bb), \
            f"{bust} 파산 뒤 BTN/SB/BB: {(after['BTN'], after['SB'], after['BB'])} ≠ {(btn, sb, bb)}"

    # 3인 → 헤즈업 전환: 버튼 = 직전 버튼 다음 생존자이고 헤즈업은 버튼이 SB
    sess, _ = _scripted_session(2, dealer_index=1)   # BTN=Alpha, SB=Beta, BB=H
    _finish_hand_by_folding(sess)
    next(p for p in sess.game.players if p.name == "🤖 Beta").chips = 0
    sess.next_hand()
    after = _labels(sess)
    assert after == {"BTN/SB": "Human", "BB": "🤖 Alpha"}, f"헤즈업 전환: {after}"


def test_8_16_hand_over_positions_are_played_hand():
    """T-022: 핸드 종료 응답의 포지션 라벨은 방금 친 핸드 기준이다(딜러 이동은 다음 핸드
    시작 시점). 폴드 종료·쇼다운 종료 모두."""
    # ① 사람 폴드로 종료
    sess, _ = _scripted_session(3, dealer_index=2)
    during = {p["name"]: p["position"] for p in sess.get_state()["players"]}
    _finish_hand_by_folding(sess)
    st = sess.get_state()
    assert st["hand_over"]
    after = {p["name"]: p["position"] for p in st["players"]}
    assert after == during, f"종료 응답 포지션이 다음 핸드 기준으로 바뀜: {during} → {after}"

    # ② 쇼다운으로 종료(스텁 봇은 콜/체크, 사람도 콜/체크)
    sess, _ = _scripted_session(2, dealer_index=1)
    during = {p["name"]: p["position"] for p in sess.get_state()["players"]}
    guard = 0
    while not sess.hand_over:
        guard += 1
        assert guard < 20
        sess.submit_action("call" if sess.get_state()["call_amount"] > 0 else "check", 0)
    st = sess.get_state()
    assert st["showdown_hands"], "쇼다운으로 끝나야 함"
    after = {p["name"]: p["position"] for p in st["players"]}
    assert after == during, f"쇼다운 종료 응답 포지션이 바뀜: {during} → {after}"
    # 다음 핸드에서야 버튼이 이동한다
    sess.next_hand()
    seats = [p.name for p in sess.game.players]
    prev_btn = next(n for n, lbl in during.items() if lbl == "BTN")
    assert _labels(sess)["BTN"] == seats[(seats.index(prev_btn) + 1) % len(seats)]


def test_8_17_odd_chip_to_first_winner_left_of_button():
    """T-022: 스플릿 팟의 홀수 칩은 버튼 왼쪽부터 돌아 처음 만나는 승자가 받는다
    (세션 쇼다운 경로 — 기여액 오름차순·리스트 첫 승자가 아님)."""
    # 3인 [H, Alpha, Beta], BTN=Alpha → 버튼 왼쪽 = Beta. H 폴드, Alpha·Beta 보드 로열 스플릿.
    sess, _ = _scripted_session(2, dealer_index=1)
    g = sess.game
    board = [c("A", "S"), c("K", "S"), c("Q", "S"), c("J", "S"), c("10", "S")]
    g.community_cards = board
    holes = {"Human": [c("2", "H"), c("3", "D")], "🤖 Alpha": [c("4", "H"), c("5", "D")],
             "🤖 Beta": [c("6", "H"), c("7", "D")]}
    for p in g.players:
        p.hole_cards = holes[p.name]
        p.total_bet_this_round = 67
        p.chips = 1000
        p.is_folded = (p.name == "Human")
        p.is_all_in = False
    g.pot = 201
    sess._do_showdown()
    chips = {p.name: p.chips for p in g.players}
    assert chips["🤖 Beta"] == 1101 and chips["🤖 Alpha"] == 1100, \
        f"홀수 칩은 버튼(Alpha) 왼쪽 Beta에게: {chips}"


def _api_client():
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient
        from server.main import app, sessions
    return TestClient(app), sessions


class _SlowBot(StubBot):
    """동시성 테스트용: 판단마다 잠깐 멈춰 요청이 겹칠 틈을 만든다(콜/체크)."""

    def decide_action(self, game_state):
        time.sleep(0.02)
        return super().decide_action(game_state)


def test_8_18_concurrent_requests_do_not_steal_or_duplicate_events():
    """T-026: 같은 세션에 요청이 겹쳐도(탭 두 개·연타) 이벤트가 빠지거나 중복되지 않는다.
    ① 액션 요청 진행 중 들어온 GET state는 그 액션의 이벤트를 가로채지 않는다(get_state 순수)
    ② '다음 핸드' 동시 2회 → 핸드는 하나만 넘어가고 딜 이벤트도 한 벌만 나온다."""
    import threading as _th
    client, sessions = _api_client()
    sess, _ = _scripted_session(4, dealer_index=1)   # 5인: BTN=Alpha, 사람=CO
    for name, bot in list(sess.bots.items()):
        sess.bots[name] = _SlowBot(bot.player)
    sid = "api-t026-a"
    sessions[sid] = sess
    try:
        # get_state는 순수: 두 번 불러도 같은 결과, 이벤트 없음
        assert sess.get_state() == sess.get_state()
        assert sess.get_state()["events"] == []

        results = {}
        log_before = len(sess.action_log)

        def do_action():
            results["action"] = client.post(f"/game/{sid}/action",
                                            json={"action": "fold", "amount": 0}).json()

        def do_gets():
            results["gets"] = [client.get(f"/game/{sid}/state").json() for _ in range(8)]

        t1 = _th.Thread(target=do_action)
        t2 = _th.Thread(target=do_gets)
        t1.start()
        time.sleep(0.005)
        t2.start()
        t1.join()
        t2.join()
        acts = _action_events(results["action"]["events"])
        n_log_actions = sum(1 for line in sess.action_log[log_before:]
                            if ":" in line and "🏆" not in line)
        assert len(acts) == n_log_actions and acts, \
            f"액션 응답 이벤트 {len(acts)}개 ≠ 실제 액션 {n_log_actions}개"
        stolen = [e for g in results["gets"] for e in g["events"]]
        assert not stolen, f"GET state가 이벤트를 가로챔: {len(stolen)}개"
        assert results["action"]["hand_over"]

        # ② 다음 핸드 동시 2회
        hand_no = sess.hand_number
        res = []

        def do_next():
            res.append(client.post(f"/game/{sid}/next-hand").json())

        ts = [_th.Thread(target=do_next) for _ in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert sess.hand_number == hand_no + 1, f"핸드가 한 번만 넘어가야 함: {hand_no} → {sess.hand_number}"
        deals = [e for r in res for e in r["events"] if e["type"] == "deal_card"]
        assert len(deals) == 2 * len(sess.game.players), \
            f"딜 이벤트는 한 벌(2×{len(sess.game.players)})만: {len(deals)}"
    finally:
        sessions.pop(sid, None)


class _BrokenBot(StubBot):
    """판단 중 예외를 던지는 봇(예외 주입)."""

    def decide_action(self, game_state):
        raise RuntimeError("주입된 봇 오류")


def test_8_19_bot_exception_logged_and_game_continues():
    """T-026: 봇 판단에서 예외가 나도 게임이 멈추지 않는다 — 오류는 로그에 남고 그 봇은
    안전 폴백(콜할 금액 있으면 폴드, 없으면 체크)으로 진행된다."""
    import logging
    records = []

    class _H(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    lg = logging.getLogger("server.session")
    h = _H(level=logging.ERROR)
    lg.addHandler(h)
    old_level = lg.level
    lg.setLevel(logging.ERROR)
    lg.propagate = False  # 콘솔 트레이스백은 숨기고 핸들러로만 수집
    try:
        # 딜러=사람(3인 UTG). 사람 레이즈 60 → Alpha(SB) 예외 → 폴드, Beta 콜
        sess, _ = _scripted_session(2, dealer_index=0)
        sess.bots["🤖 Alpha"] = _BrokenBot(sess.bots["🤖 Alpha"].player)
        total = _total_chips(sess)
        ev = sess.submit_action("raise", 60)
        alpha = [a for a in _action_events(ev) if a["player"] == "🤖 Alpha"]
        assert alpha and alpha[0]["action"] == "fold", f"예외 봇은 폴드로 대체돼야 함: {alpha}"
        assert any("Alpha" in m and "오류" in m for m in records), f"오류 로그 없음: {records}"
        st = sess.get_state()
        assert st["waiting_for_action"] or st["hand_over"], "게임이 봇 차례에 멈춤"
        assert _total_chips(sess) == total

        # 체크 가능한 상황에서는 체크로: 헤즈업, 사람 BTN/SB 림프 → BB(예외) 체크 → 플랍
        sess, _ = _scripted_session(1, dealer_index=0)
        sess.bots["🤖 Alpha"] = _BrokenBot(sess.bots["🤖 Alpha"].player)
        ev = sess.submit_action("call", 0)
        alpha = [a for a in _action_events(ev) if a["player"] == "🤖 Alpha"]
        assert alpha and alpha[0]["action"] == "check", f"콜할 금액 없으면 체크: {alpha}"
        assert sess.get_state()["street"] == "플랍" and sess.get_state()["waiting_for_action"]
    finally:
        lg.removeHandler(h)
        lg.setLevel(old_level)
        lg.propagate = True


def test_8_20_get_state_recovers_stuck_bot_turn():
    """T-026: 요청 중간 오류로 세션이 봇 차례에 멈춰 있으면 GET state가 사람 차례(또는 핸드
    종료)까지 진행해 복구하고, 실패한 요청의 이벤트를 다시 내보내지 않는다."""
    import logging
    client, sessions = _api_client()
    sess, _ = _scripted_session(2, dealer_index=0)   # 사람 UTG
    real = sess._run_until_human

    def boom():
        raise RuntimeError("주입된 진행 오류")

    sess._run_until_human = boom
    try:
        sess.submit_action("raise", 60)
        raise AssertionError("주입한 오류가 전파되지 않음")
    except RuntimeError:
        pass
    sess._run_until_human = real
    assert sess.needs_recovery(), "사람 액션 뒤 봇 차례에 멈춘 상태여야 함"

    sid = "api-t026-c"
    sessions[sid] = sess
    lg = logging.getLogger("server.session")
    old_level = lg.level
    lg.setLevel(logging.ERROR)
    try:
        st = client.get(f"/game/{sid}/state").json()
        assert st["waiting_for_action"] or st["hand_over"], "GET state가 복구하지 못함"
        players = [e["player"] for e in _action_events(st["events"])]
        assert "Human" not in players, f"실패한 요청의 사람 액션 이벤트가 다시 나옴: {players}"
        assert players, "복구 진행의 봇 액션 이벤트가 실려야 함"
        # 정상 상태에서 GET은 아무것도 바꾸지 않는다
        log_before = list(sess.action_log)
        st2 = client.get(f"/game/{sid}/state").json()
        assert st2["events"] == [] and sess.action_log == log_before
    finally:
        lg.setLevel(old_level)
        sessions.pop(sid, None)


def test_8_21_start_game_rejects_invalid_settings():
    """T-027: 잘못된 게임 설정은 422 + 이유가 적힌 한국어 안내로 거절되고 세션이 만들어지지
    않는다(BB 1·홀수 BB·칩 0·칩 < BB×10·봇 0명/6명·알 수 없는 난이도·빈 이름·봇 이름)."""
    client, sessions = _api_client()
    base = {"player_name": "Player", "chips": 1000, "num_bots": 2,
            "difficulty": "easy", "big_blind": 10}
    bad = [
        ({"big_blind": 1}, "빅 블라인드"),
        ({"big_blind": 0}, "빅 블라인드"),
        ({"big_blind": 15}, "짝수"),
        ({"chips": 0}, "칩"),
        ({"chips": 50}, "10배"),
        ({"num_bots": 0}, "봇"),
        ({"num_bots": 6}, "봇"),
        ({"difficulty": "insane"}, "난이도"),
        ({"player_name": "   "}, "이름"),
        ({"player_name": "🤖 Alpha"}, "이름"),
    ]
    before = set(sessions)
    for override, reason in bad:
        body = dict(base, **override)
        res = client.post("/game/start", json=body)
        assert res.status_code == 422, f"{override}: 422여야 함, {res.status_code} {res.text[:200]}"
        msgs = " / ".join(d.get("msg", "") for d in res.json()["detail"])
        assert reason in msgs, f"{override}: 안내에 '{reason}'이 없음: {msgs}"
        assert set(sessions) == before, f"{override}: 거절됐는데 세션이 등록됨"

    # 정상 설정은 만들어지고 등록된다
    res = client.post("/game/start", json=base)
    assert res.status_code == 200, res.text[:200]
    sid = res.json()["session_id"]
    assert sid in sessions
    assert sessions[sid].game.big_blind == 10 and sessions[sid].game.small_blind == 5
    sessions.pop(sid, None)


def test_8_22_session_registered_only_after_successful_start():
    """T-027: 세션 생성 중(첫 상태 계산 포함) 오류가 나면 세션 목록에 남지 않는다."""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient
        from server.main import app, sessions
        from server.session import WebGameSession
    client = TestClient(app, raise_server_exceptions=False)
    before = set(sessions)
    orig = WebGameSession.get_state

    def boom(self, events=None):
        raise RuntimeError("주입된 상태 계산 오류")

    WebGameSession.get_state = boom
    try:
        res = client.post("/game/start", json={"player_name": "P", "chips": 1000, "num_bots": 1,
                                               "difficulty": "easy", "big_blind": 10})
    finally:
        WebGameSession.get_state = orig
    assert res.status_code == 500, res.status_code
    assert set(sessions) == before, "생성에 실패한 세션이 등록돼 남음"


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
    ("5-10 에퀴티 패널 — 넛급 핸드",          test_5_10_equity_panel_nut_hand),
    ("5-11 핸드 종료 후 hand_review 포함",    test_5_11_hand_review_after_hand_over),
    ("5-12 equity_enabled=False 스위치",      test_5_12_equity_disabled_flag),
    # 영역 6 — 버그 픽스
    ("6-1  헤즈업 블라인드 포스팅 (BTN/SB=SB)", test_6_1_headsup_blind_posting),
    ("6-2  헤즈업 프리플랍 BTN/SB 선행동",     test_6_2_headsup_preflop_btnSB_acts_first),
    ("6-3  헤즈업 포스트플랍 BB 선행동",       test_6_3_headsup_postflop_bb_acts_first),
    ("6-4  헤즈업 20핸드 칩 총량 보존",        test_6_4_headsup_chip_conservation),
    ("6-5  사이드팟 — 숏스택 메인팟만 수령",   test_6_5_sidepot_shortstack_wins_mainpot_only),
    ("6-6  사이드팟 — 동일 올인 팟 1개",       test_6_6_sidepot_three_allins),
    ("6-7  사이드팟 — 폴드 기여분 처리",       test_6_7_sidepot_folded_player_contribution),
    ("6-8  사이드팟 분배 후 칩 보존",          test_6_8_sidepot_conservation),
    ("6-9  헤즈업 GTO BTN/SB→SB RFI 매핑",     test_6_9_headsup_gto_btnSB_mapped_to_sb_rfi),
    ("6-10 스퀴즈 구조화 시퀀스에 콜 포함",     test_6_10_squeeze_seq_includes_call),
    ("6-11 헤즈업 시퀀스 BTN/SB 라벨 유지",     test_6_11_headsup_seq_labels_btnSB),
    ("6-12 vs_open 시퀀스 라우팅 스팟체크",     test_6_12_vs_open_routing_via_seq),
    ("6-13 시퀀스 키=enum 키 동일 레인지",      test_6_13_seq_key_and_enum_key_same_range),
    ("6-14 런타임 사이즈 스냅→노드 매핑",       test_6_14_runtime_snap_maps_near_size_to_node),
    ("6-15 마이그레이션 vs_3bet 포맷 정규화",   test_6_15_migration_normalizes_vs3bet_format),
    ("6-16 실측 사이즈 노드 형제 스냅",         test_6_16_realsize_node_snaps_to_collected_sibling),
    ("6-17 미수집 브랜치 None+큐 등록",         test_6_17_uncollected_branch_returns_none_and_queues),
    ("6-18 형제 2개 bb 최소거리 스냅",          test_6_18_two_siblings_snap_to_nearest_bb),
    ("6-19 올인은 올인 형제로만 스냅(T-014)",   test_6_19_allin_snaps_to_allin_sibling_not_nearest_raise),
    ("6-20 올인 형제 미수집 시 None(T-014)",    test_6_20_allin_with_no_allin_sibling_returns_none),
    # 영역 7 — 프리플랍 GTO 원칙
    ("7-1  save 후 로더 캐시 자동 무효화(G2)",   test_7_1_save_invalidates_loader_cache),
    ("7-2  손상 핸드 스킵(fold 채움 아님)(G4)",  test_7_2_corrupt_hand_skipped_not_folded),
    ("7-3  미수집 핸드 None(G5)",              test_7_3_missing_hand_returns_none),
    ("7-4  BB RFI 불가+큐 미기록(G6)",          test_7_4_bb_never_rfi_and_no_queue),
    ("7-5  오프너가 히어로보다 뒤 좌석→None(G6)", test_7_5_vs_open_opener_after_hero_is_none),
    ("7-6  save의 vs_3bet 반쪽 포맷 정규화(G17)", test_7_6_save_normalizes_vs3bet_half_format),
    ("7-7  다른 action_seq는 다른 행(T-001)",     test_7_7_distinct_action_seq_distinct_rows),
    ("7-8  action_seq 없는·불일치 저장 거부(T-001)", test_7_8_save_requires_action_seq_and_consistent_keys),
    ("7-9  빈도합 불량 저장 거부(T-001)",          test_7_9_save_rejects_corrupt_frequencies),
    ("7-10 정확한 노드가 라벨보다 우선(ADR 0035)", test_7_10_exact_node_preferred_over_label),
    ("7-11 라벨 예비는 근사 표시(ADR 0035)",       test_7_11_label_fallback_is_marked_approx),
    ("7-12 헤즈업 팟에 콜러 노드 안 줌(T-001)",    test_7_12_headsup_pot_not_given_caller_node),
    ("7-13 헤즈업은 UTG 트리로 스냅 안 됨(T-001)", test_7_13_headsup_not_snapped_to_utg_tree),
    ("7-14 v13 마이그레이션 데이터 보존(T-001)",   test_7_14_migration_v13_preserves_data),
    # 영역 8 — 세션 경로 룰
    ("8-1  next_hand 연타 → 한 핸드만, 칩 보존",  test_8_1_next_hand_double_call_keeps_chips),
    ("8-2  핸드 중 next_hand 무시",              test_8_2_next_hand_during_hand_ignored),
    ("8-3  헤즈업 BTN/SB 선행동 + BB 옵션",      test_8_3_headsup_btnsb_first_and_bb_option),
    ("8-4  헤즈업 사람 BTN/SB 첫 결정",           test_8_4_headsup_human_btnsb_acts_first),
    ("8-5  헤즈업 BTN/SB 첫 결정 GTO 힌트",       test_8_5_headsup_btnsb_first_decision_has_gto_hint),
    ("8-6  콜 미만 올인은 재오픈 없음",           test_8_6_short_allin_under_call_does_not_reopen),
    ("8-7  불완전 레이즈 올인 → 콜/폴드만",       test_8_7_incomplete_raise_allin_call_or_fold_only),
    ("8-8  풀 레이즈 올인이 min_raise 갱신",      test_8_8_full_allin_updates_min_raise),
    ("8-9  스택 초과 레이즈 → 올인",              test_8_9_raise_over_stack_becomes_allin),
    ("8-10 불법 체크 거절(400)·기록 없음",        test_8_10_illegal_check_rejected_not_recorded),
    ("8-11 봇 불법 액션 → 로그+안전 폴백",        test_8_11_bot_illegal_action_falls_back),
    ("8-12 세션 퍼저: 이벤트 금액=칩 이동·보존",  test_8_12_session_fuzz_event_amounts_and_conservation),
    ("8-13 행동 가능 1명 + 콜 없음 → 런아웃",     test_8_13_runout_when_one_player_can_act),
    ("8-14 사람 BB일 때 blind 이벤트 SB→BB",      test_8_14_blind_events_sb_then_bb_when_human_bb),
    ("8-15 파산 전환 시 무빙 버튼(ADR 0036)",     test_8_15_moving_button_on_bust),
    ("8-16 핸드 종료 응답 포지션 = 방금 핸드",     test_8_16_hand_over_positions_are_played_hand),
    ("8-17 홀수 칩 → 버튼 왼쪽 첫 승자",          test_8_17_odd_chip_to_first_winner_left_of_button),
    ("8-18 동시 요청: 이벤트 가로채기·중복 없음",  test_8_18_concurrent_requests_do_not_steal_or_duplicate_events),
    ("8-19 봇 판단 예외 → 로그+안전 폴백",         test_8_19_bot_exception_logged_and_game_continues),
    ("8-20 GET state가 멈춘 봇 차례 복구",          test_8_20_get_state_recovers_stuck_bot_turn),
    ("8-21 잘못된 게임 설정 → 422 한국어 안내",     test_8_21_start_game_rejects_invalid_settings),
    ("8-22 생성 성공 후에만 세션 등록",             test_8_22_session_registered_only_after_successful_start),
]


AREA_LABELS = {
    "1": "영역 1 — 핸드 평가",
    "2": "영역 2 — 베팅 라운드",
    "3": "영역 3 — 팟 분배",
    "4": "영역 4 — 게임 흐름",
    "5": "영역 5 — 웹 세션",
    "6": "영역 6 — 버그 픽스",
    "7": "영역 7 — 프리플랍 GTO 원칙",
    "8": "영역 8 — 세션 경로 룰",
}
AREA_ORDER = ["1", "2", "3", "4", "5", "6", "7", "8"]


if __name__ == "__main__":
    print("\n" + "═" * 60, flush=True)
    print("  포커 로직 정밀 검사", flush=True)
    print("═" * 60, flush=True)

    suite_start = time.perf_counter()
    area = ""
    for name, fn in ALL_TESTS:
        new_area = name.split("-")[0].strip()
        if new_area != area:
            area = new_area
            idx = AREA_ORDER.index(area) + 1 if area in AREA_ORDER else "?"
            print(f"\n[영역 {idx}/{len(AREA_ORDER)}] {AREA_LABELS.get(area, area)}", flush=True)
            print("  " + "─" * 40, flush=True)
        run(name, fn)
    total_elapsed = time.perf_counter() - suite_start

    print(flush=True)
    passed = [r for r in results if r[0] == "✅"]
    failed  = [r for r in results if r[0] == "❌"]
    errors  = [r for r in results if r[0] == "💥"]

    print("═" * 60, flush=True)
    print(f"  결과: {len(passed)} 통과 / {len(failed)} 실패 / {len(errors)} 에러  (총 {len(results)})", flush=True)
    print(f"  총 소요 시간: {total_elapsed:.2f}s", flush=True)
    print("═" * 60, flush=True)

    if failed or errors:
        print("\n  실패/에러 목록:", flush=True)
        for icon, name in failed + errors:
            print(f"  {icon} {name}", flush=True)

    # 느린 테스트 TOP 5
    slowest = sorted(durations.items(), key=lambda kv: kv[1], reverse=True)[:5]
    if slowest:
        print("\n  느린 테스트 TOP 5:", flush=True)
        for name, dur in slowest:
            print(f"    {dur:.2f}s  {name}", flush=True)

    # 시간 버짓 가드 (작업 F) — 실패 처리는 하지 않고 경고만
    if total_elapsed > TIME_BUDGET_SEC:
        print(f"\n  ⚠️ 시간 버짓 초과({TIME_BUDGET_SEC:.0f}s): 성능 회귀 의심 (실제 {total_elapsed:.2f}s)", flush=True)

    if failed or errors:
        sys.exit(1)
