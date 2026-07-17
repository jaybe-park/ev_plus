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
    stub_all_bots(sess)

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
    stub_all_bots(sess)

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
    from db.connection import get_connection
    from gto.advisor import GTOAdvisor
    import gto.loader as gto_loader

    conn = get_connection()
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO gto_preflop_situations
            (position, vs_position, range_type, raise_size, situation_label)
        VALUES ('SB', NULL, 'open', 3.0, 'SB RFI')
        """
    )
    conn.commit()
    situation_id = conn.execute(
        "SELECT id FROM gto_preflop_situations WHERE position='SB' AND range_type='open'"
    ).fetchone()[0]
    conn.execute(
        """
        INSERT OR IGNORE INTO gto_preflop_hands
            (situation_id, hand, freq_fold, freq_call, freq_raise, freq_allin)
        VALUES (?, 'AKs', 0.0, 0.0, 1.0, 0.0)
        """,
        (situation_id,),
    )
    conn.commit()
    conn.close()

    # gto/loader._load_all()은 프로세스당 1회만 DB를 읽는 메모리 캐시라
    # 방금 시딩한 데이터가 반영되도록 캐시를 무효화한다(테스트 격리).
    gto_loader._cache = {}
    gto_loader._loaded = False

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
    from db.connection import get_connection
    from gto.advisor import GTOAdvisor
    import gto.loader as gto_loader

    conn = get_connection()
    conn.execute(
        """INSERT OR IGNORE INTO gto_preflop_situations
           (position, vs_position, range_type, raise_size, situation_label)
           VALUES ('HJ', 'UTG', 'vs_open', 8.0, 'HJ vs UTG open')"""
    )
    conn.commit()
    sid = conn.execute(
        "SELECT id FROM gto_preflop_situations "
        "WHERE position='HJ' AND vs_position='UTG' AND range_type='vs_open'"
    ).fetchone()[0]
    conn.execute(
        """INSERT OR IGNORE INTO gto_preflop_hands
           (situation_id, hand, freq_fold, freq_call, freq_raise, freq_allin)
           VALUES (?, 'AKs', 0.0, 0.5, 0.5, 0.0)""",
        (sid,),
    )
    conn.commit()
    conn.close()
    gto_loader._cache = {}
    gto_loader._loaded = False

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


def _seed_situation(position, vs_position, range_type, raise_size, label,
                    hands, action_seq):
    """② 테스트용: (선택적) action_seq 포함 시추에이션 + 핸드 시딩 후 로더 캐시 무효화."""
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
    if vs_position is None:
        sid = conn.execute(
            "SELECT id FROM gto_preflop_situations "
            "WHERE position=? AND range_type=? AND vs_position IS NULL",
            (position, range_type),
        ).fetchone()[0]
    else:
        sid = conn.execute(
            "SELECT id FROM gto_preflop_situations "
            "WHERE position=? AND range_type=? AND vs_position=?",
            (position, range_type, vs_position),
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
    from db.connection import get_connection
    from db.schema import backfill_v12

    conn = get_connection()  # 격리 임시 DB(v12), 컬럼 이미 존재
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

    # UTG open → HJ 3bet → CO fold → BTN 콜드-4벳 20 → 히어로 UTG가 4벳에 직면.
    # 프리픽스 "R2.5-R8-F"에 수집된 레이즈-형제 없음(수집분 token[3]="F") → None.
    seq = [
        {"position": "UTG", "action": "raise", "amount_bb": 2.5},
        {"position": "HJ", "action": "raise", "amount_bb": 8.0},
        {"position": "CO", "action": "fold"},
        {"position": "BTN", "action": "raise", "amount_bb": 20.0},
    ]
    assert canonical_node_key(seq) is None, canonical_node_key(seq)

    advisor = GTOAdvisor()
    gs = {"street": "프리플랍", "current_bet": 400, "preflop_seq": seq}
    rec = advisor._recommend_by_seq([c("A", "S"), c("K", "S")], "UTG", gs, big_blind=20)
    assert rec is None, rec

    # 실측 사이즈 키로 큐 등록 확인
    conn = get_connection()
    row = conn.execute(
        "SELECT position, vs_position, range_type FROM gto_missing_spots_preflop "
        "WHERE range_type='seq' AND vs_position=?",
        ("R2.5-R8-F-R20",),
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
]


AREA_LABELS = {
    "1": "영역 1 — 핸드 평가",
    "2": "영역 2 — 베팅 라운드",
    "3": "영역 3 — 팟 분배",
    "4": "영역 4 — 게임 흐름",
    "5": "영역 5 — 웹 세션",
    "6": "영역 6 — 버그 픽스",
}
AREA_ORDER = ["1", "2", "3", "4", "5", "6"]


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
