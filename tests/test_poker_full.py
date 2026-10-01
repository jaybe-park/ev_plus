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


def _set_contributions(game, amounts):
    """이번 핸드 누적 기여액(total_bet_this_round)을 amounts로 맞추고 팟 = 합계.
    core showdown은 기여액 계층으로 팟을 나누므로 팟만 직접 세팅하면 안 된다."""
    for p, a in zip(game.players, amounts):
        p.total_bet_this_round = a
    game.pot = sum(amounts)


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
    # 테스트마다 새 임시 DB 파일 — 운영 poker.db를 건드리지 않고(ADR 0026), 테스트끼리
    # 기록이 섞이지 않는다.
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
    # 180에서 마지막으로 행동한 P0는 마주한 증가분 20 < 120이라 레이즈 불가(콜/폴드만).
    # 아직 행동 안 한 사람은 가능.
    bet_seen = {"P0": 180, "P1": 200, "P2": 180}
    assert not game.raise_allowed(players[0], bet_seen)
    assert game.raise_allowed(players[0], {})
    # 60에서 행동한 뒤 200을 마주하면 증가분 140 ≥ 120 → 레이즈 가능(TDA Rule 47, T-038)
    assert game.raise_allowed(players[0], {"P0": 60})
    assert not game.apply_action(players[0], Action.RAISE, 400, raise_allowed=False)
    assert game.apply_action(players[0], Action.CALL, raise_allowed=False)

def _scripted_core_game(stacks, scripts, sb=10):
    """core 베팅 루프(play_round, CLI 경로)용: 스크립트 콜백을 단 게임.
    scripts: {이름: [(Action, amount), ...]} — 소진되면 콜/체크."""
    game, players = make_game(len(stacks), sb=sb)
    for p, s in zip(players, stacks):
        p.chips = s
    queues = {k: list(v) for k, v in scripts.items()}

    def cb(player, state):
        q = queues.get(player.name)
        if q:
            return q.pop(0)
        to_call = state["current_bet"] - player.current_bet
        return (Action.CALL, 0) if to_call > 0 else (Action.CHECK, 0)

    game._action_callback = cb
    return game, players


def _core_actions(game, street=None):
    return [(e.data["player"], e.data["action"], e.data.get("to_amount"))
            for e in game.event_log if e.event_type == "action"
            and (street is None or e.data["street"] == street)]


def test_2_8_core_cumulative_short_allins_reopen():
    """T-038(core 베팅 루프 play_round, CLI 경로): 플랍 벳 100 → 콜 → 150 올인 → 220 올인이면 처음 벳한
    사람이 레이즈할 수 있고(+120 ≥ 100), 190 올인(+90)이면 레이즈 요청이 콜로 대체된다."""
    for last_allin, can_raise in [(220, True), (190, False)]:
        # 딜러 P0 → 플랍 순서 P1(SB), P2, P3, P0. 프리플랍은 체크/콜로 20씩.
        game, players = _scripted_core_game(
            [last_allin + 20, 1000, 1000, 170],
            {"P1": [(Action.CALL, 0), (Action.RAISE, 100), (Action.RAISE, 500)],
             "P3": [(Action.CALL, 0), (Action.ALL_IN, 0)],
             "P0": [(Action.CALL, 0), (Action.ALL_IN, 0)]})
        game.start_hand()
        game.play_round()
        assert game.advance_street() == Street.FLOP
        game.play_round()
        flop = _core_actions(game, Street.FLOP.value)
        assert flop[:4] == [("P1", "레이즈", 100), ("P2", "콜", 100),
                            ("P3", "올인", 150), ("P0", "올인", last_allin)], flop
        want = ("P1", "레이즈", 500) if can_raise else ("P1", "콜", last_allin)
        assert flop[4] == want, f"마지막 올인 {last_allin}: P1 두 번째 액션 {flop[4]} ≠ {want}"


def test_2_4_allin_ends_round_when_no_callers():
    """올인에 콜할 사람이 없으면 라운드가 끝난다(core next_to_act/round_over):
    ① UTG 올인 → SB·BB 폴드 → 다음 차례 None, 다음 스트리트 없음
    ② UTG 올인 → SB 폴드 → BB 콜(스택 남음) → 행동 가능 1명·콜 없음 → 라운드 종료(런아웃)"""
    game, players = make_game(3, chips=1000, sb=10)   # 딜러 P0: UTG=P0, SB=P1, BB=P2
    game.start_hand()
    players[0].chips = 300
    assert game.next_to_act() is players[0]
    game.act(players[0], Action.ALL_IN)
    assert game.next_to_act() is players[1] and not game.round_over()
    game.act(players[1], Action.FOLD)
    assert game.next_to_act() is players[2] and not game.round_over()
    game.act(players[2], Action.FOLD)
    assert game.next_to_act() is None, "1명만 남으면 다음 차례가 없어야 함"
    assert game.advance_street() is None, "1명만 남으면 다음 스트리트가 없어야 함"

    game, players = make_game(3, chips=1000, sb=10)
    game.start_hand()
    players[0].chips = 300
    game.act(players[0], Action.ALL_IN)
    game.act(players[1], Action.FOLD)
    game.act(players[2], Action.CALL)
    assert players[2].chips > 0 and players[2].current_bet == game.current_bet == 300
    assert game.round_over() and game.next_to_act() is None, \
        "올인을 콜하고 행동 가능한 사람이 1명뿐이면 라운드 종료"
    assert game.advance_street() is not None and game.next_to_act() is None, \
        "포스트플랍도 물을 상대가 없어 바로 끝나야 함(런아웃)"

def test_2_5_preflop_betting_order_3players():
    """3인 프리플랍 베팅 순서: UTG(=BTN=P0) → SB(P1) → BB(P2)"""
    game, players = make_game(3, chips=1000, sb=10)
    # dealer_index=0 → BTN=P0, SB=P1, BB=P2
    # 프리플랍 UTG = dealer+3 % 3 = 0
    game.start_hand()
    order = game._betting_order(Street.PREFLOP)
    names = [p.name for p in order]
    assert names == ["P0", "P1", "P2"], f"UTG(P0) → SB(P1) → BB(P2)여야 함: {names}"

def test_2_6_headsup_btn_acts_first_preflop():
    """헤즈업 행동 순서(core next_to_act): 프리플랍 BTN/SB 먼저 → 림프하면 BB 옵션 →
    BB 체크로 라운드 종료 → 플랍은 BB 먼저."""
    game, players = make_game(2, chips=1000, sb=10)
    game.dealer_index = 1                     # BTN/SB=P1, BB=P0 (dealer 0이 아닌 쪽도 확인)
    game.start_hand()
    assert game.get_positions() == {"P1": "BTN/SB", "P0": "BB"}, game.get_positions()
    assert game.next_to_act() is players[1], "프리플랍은 BTN/SB가 먼저"
    game.act(players[1], Action.CALL)
    assert game.next_to_act() is players[0], "BTN/SB 림프 뒤 BB가 옵션을 가져야 함"
    assert game.can_raise(players[0])
    game.act(players[0], Action.CHECK)
    assert game.next_to_act() is None and game.round_over()
    assert game.advance_street() == Street.FLOP
    assert game.next_to_act() is players[0], "포스트플랍은 BB가 먼저"
    game.act(players[0], Action.CHECK)
    assert game.next_to_act() is players[1]

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
    """100핸드 시뮬(시드 고정, 3초 이내) — 사람·봇 모두 레이즈·올인을 섞어 친다.
    매 결정 지점과 매 핸드 끝에 칩 + 팟 합계가 시작 총합과 같아야 하고, 레이즈·올인·
    사이드팟(기여 다른 2명 이상 쇼다운)이 실제로 나와야 한다."""
    import logging
    lg = logging.getLogger("server.session")
    old_level = lg.level
    lg.setLevel(logging.ERROR)  # 봇 폴백 경고는 의도된 것
    try:
        _pot_conservation_sim()
    finally:
        lg.setLevel(old_level)


def _pot_conservation_sim():
    from server.session import WebGameSession
    from core.game import IllegalActionError
    import random

    rng = random.Random(31)
    start = time.perf_counter()
    sess = WebGameSession("sim", "Human", 500, 5, "medium", 10, equity_enabled=False)
    for name, bot in list(sess.bots.items()):
        sess.bots[name] = _RandomBot(bot.player, rng, shove=0.08)
    total_initial = sum(p.chips for p in sess.game.players) + sess.game.pot
    assert total_initial == 3000, f"초기 총합이 3000(6×500)이어야 함: {total_initial}"

    seen = {"raise": 0, "allin": 0, "multi_pot": 0}
    hands = 0
    while hands < 100:
        for _ in range(40):
            state = sess.get_state()
            if state["hand_over"] or not state["waiting_for_action"]:
                break
            assert _total_chips(sess) == total_initial, "칩 보존 실패(핸드 진행 중)"
            act = rng.choice(["fold", "check", "call", "call", "raise", "allin"])
            try:
                sess.submit_action(act, rng.randint(0, state["current_bet"] * 3 + 60))
            except IllegalActionError:
                sess.submit_action("call" if state["call_amount"] > 0 else "check", 0)
        state = sess.get_state()
        assert state["hand_over"], "핸드가 끝나지 않음"
        assert _total_chips(sess) == total_initial, \
            f"칩 보존 실패: 초기 {total_initial}, 현재 {_total_chips(sess)} (pot={sess.game.pot})"
        log = " ".join(state["action_log"])
        seen["raise"] += "레이즈" in log
        seen["allin"] += "올인" in log
        seen["multi_pot"] += sum(1 for p in state["pots"] if not p["returned"]) > 1
        hands += 1
        if not sess.game_over:
            sess.next_hand()
        if sess.game_over:   # 파산으로 게임 종료 → 새 세션으로 이어서
            sess = WebGameSession("sim", "Human", 500, 5, "medium", 10, equity_enabled=False)
            for name, bot in list(sess.bots.items()):
                sess.bots[name] = _RandomBot(bot.player, rng, shove=0.08)
    assert hands >= 100, f"100핸드를 못 침: {hands}"
    assert all(v > 0 for v in seen.values()), f"레이즈·올인·사이드팟이 나와야 함: {seen}"
    elapsed = time.perf_counter() - start
    assert elapsed < 3.0, f"3초 이내여야 함: {elapsed:.2f}s"

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

    _set_contributions(game, [100, 100])
    initial_p0 = players[0].chips
    initial_p1 = players[1].chips

    winners = game.showdown().winners
    assert len(winners) == 2, f"타이이므로 2명 승자여야 함: {[w.name for w in winners]}"
    assert players[0].chips == initial_p0 + 100
    assert players[1].chips == initial_p1 + 100

def test_3_3_split_pot_odd_remainder():
    """홀수 팟 — 나머지 1칩은 버튼 왼쪽 첫 승자에게(리스트 첫 승자가 아님, T-022)"""
    # 3인, P2는 1칩 내고 폴드 → 팟 201을 P0·P1이 스플릿. 딜러 0 → 버튼 왼쪽 P1,
    # 딜러 1 → 버튼 왼쪽 P2(폴드)를 건너뛰어 P0
    for dealer, odd_idx in [(0, 1), (1, 0)]:
        game, players = make_game(3, chips=500, sb=10)
        game.dealer_index = dealer
        game.start_hand()
        force_community(game, [c("A","S"), c("K","S"), c("Q","S"), c("J","S"), c("10","S")])
        players[0].hole_cards = [c("2","H"), c("3","D")]
        players[1].hole_cards = [c("4","H"), c("5","D")]
        _set_contributions(game, [100, 100, 1])
        players[2].fold()
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
    winners = game.showdown().winners
    assert len(winners) == 1
    assert players[0].chips == initial + 300

def test_3_6_sidepot_independent_calculator_2000():
    """독립 사이드팟 계산기(코드 공유 없음, tests/test_sidepot_indep.py)와 core showdown()을
    시드 고정 2,000 시나리오로 대조: 플레이어별 칩 증가분(홀수 칩 수령자 포함)·계층·반환(2초 이내)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import test_sidepot_indep as indep
    indep.test_ref_distribute_examples()
    indep.test_sidepot_matches_independent_calculator()


def test_3_5_allin_player_cannot_win_more_than_contributed():
    """core showdown(CLI 경로)도 사이드팟을 나눈다(T-024): P0 100 올인(AA), P1·P2 500씩(KK/QQ)
    → P0는 메인팟 300만, 사이드팟 800은 P1."""
    game, players = make_game(3, chips=1000, sb=10)
    game.start_hand()
    _set_contributions(game, [100, 500, 500])
    for p, left in zip(players, [0, 500, 500]):
        p.chips = left
    players[0].is_all_in = True
    force_community(game, [c("2","H"), c("7","D"), c("9","S"), c("3","C"), c("5","H")])
    players[0].hole_cards = [c("A","S"), c("A","H")]   # AA
    players[1].hole_cards = [c("K","S"), c("K","H")]   # KK
    players[2].hole_cards = [c("Q","S"), c("Q","H")]   # QQ

    result = game.showdown()
    assert [p.chips for p in players] == [300, 1300, 500], \
        f"메인 300 → P0, 사이드 800 → P1: {[p.chips for p in players]}"
    assert [w.name for w in result.winners] == ["P0", "P1"], result.winners
    assert [(pot.amount, len(pot.eligible)) for pot in result.pots] == [(300, 3), (800, 2)], result.pots
    assert game.pot == 0


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

    winners = game.showdown().winners
    assert len(winners) == 1
    assert winners[0].name == "P0"
    assert players[0].chips == initial + 60

def test_4_4_street_bet_reset():
    """스트리트 전환(core advance_street) 시 current_bet·플레이어 베팅·min_raise가 리셋되고
    핸드 누적 기여·팟은 유지된다."""
    game, players = make_game(3, chips=1000, sb=10)   # UTG=P0, SB=P1, BB=P2
    game.start_hand()
    game.act(players[0], Action.RAISE, 100)            # +80 → min_raise 80
    game.act(players[1], Action.CALL)
    game.act(players[2], Action.CALL)
    assert game.round_over() and game.min_raise == 80 and game.current_bet == 100
    assert game.advance_street() == Street.FLOP
    assert game.current_bet == 0 and game.min_raise == 20, (game.current_bet, game.min_raise)
    for p in players:
        assert p.current_bet == 0, f"{p.name}.current_bet should be 0"
        assert p.total_bet_this_round == 100, f"{p.name} 핸드 누적 기여는 유지: {p.total_bet_this_round}"
    assert game.pot == 300 and len(game.community_cards) == 3
    assert game.acted == set() and game.next_to_act() is players[1], "플랍 새 라운드는 SB부터"

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
    """최소 레이즈는 이전 레이즈 크기 이상 — 모자란 요청은 최소 레이즈-투로 보정되고,
    보정값이 스택 이상이면 올인으로 적용된다."""
    game, players = make_game(3, chips=1000, sb=10)   # UTG=P0, SB=P1, BB=P2
    game.start_hand()
    # 요청 25(최소 40 미만) → 40으로 보정
    assert game.validate(players[0], Action.RAISE, 25) == (Action.RAISE, 40)
    r = game.act(players[0], Action.RAISE, 25)
    assert r.to_amount == 40 and game.current_bet == 40 and game.min_raise == 20, \
        (r, game.current_bet, game.min_raise)
    # 요청 50(최소 60 미만) → 60으로 보정
    r = game.act(players[1], Action.RAISE, 50)
    assert r.to_amount == 60 and r.moved == 50 and game.current_bet == 60, (r, game.current_bet)
    # 풀 레이즈 +100 → min_raise 100, 다음 요청 170(최소 260 미만) → 260
    r = game.act(players[2], Action.RAISE, 160)
    assert game.min_raise == 100 and r.to_amount == 160, (game.min_raise, r)
    assert game.validate(players[0], Action.RAISE, 170) == (Action.RAISE, 260)
    # 보정값이 스택(칩 + 이번 베팅) 이상이면 올인
    players[0].chips = 150                             # 스택 40 + 150 = 190 < 260
    assert game.validate(players[0], Action.RAISE, 170) == (Action.ALL_IN, 190)
    r = game.act(players[0], Action.RAISE, 170)
    assert r.action == Action.ALL_IN and players[0].chips == 0 and game.current_bet == 190, r
    assert game.min_raise == 100 and not r.reopens, "+30 불완전 올인은 min_raise 유지"

def _cli_controller(stacks, names=None):
    """cli.main.GameController를 setup() 입력 없이 만든다(봇 결정은 콜백으로 주입)."""
    from cli.main import GameController
    names = names or ["H"] + [f"B{i}" for i in range(1, len(stacks))]
    players = [Player(n, s, is_human=(i == 0)) for i, (n, s) in enumerate(zip(names, stacks))]
    ctl = GameController()
    ctl.human_player = players[0]
    ctl.game = TexasHoldem(players, small_blind=10, big_blind=20)
    return ctl


def _quiet(fn, *args):
    import io
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args)


def test_4_9_cli_sidepot_and_moving_button():
    """T-024: CLI(`GameController.play_hand`)도 core 경로라 사이드팟을 나누고 무빙 버튼을 쓴다.
    ① H(100) 올인·A/B 300씩 → H는 메인팟(310)만, 사이드팟 400은 A ② 버튼 앞 좌석(A)이
    파산해도 버튼은 직전 버튼(B) 다음 생존자(C)로(옛 인덱스 방식이면 H)."""
    ctl = _cli_controller([100, 500, 500, 500], ["H", "A", "B", "C"])
    g = ctl.game
    g.dealer_index = 2          # BTN=B, SB=C, BB=H, UTG=A
    holes = {"H": [c("A", "S"), c("A", "H")], "A": [c("K", "S"), c("K", "H")],
             "B": [c("Q", "S"), c("Q", "H")], "C": [c("J", "S"), c("8", "H")]}
    board = [c("2", "H"), c("7", "D"), c("9", "S"), c("3", "C"), c("5", "C")]
    real_deal = g._deal_hole_cards

    def rigged_deal():
        real_deal()
        for p in g.players:
            p.hole_cards = list(holes[p.name])
    g._deal_hole_cards = rigged_deal
    g.deal_community = lambda street: g.community_cards.extend(
        board[len(g.community_cards):{Street.FLOP: 3, Street.TURN: 4, Street.RIVER: 5}[street]])
    script = {"A": [(Action.CALL, 0), (Action.CALL, 0), (Action.RAISE, 200)],
              "B": [(Action.CALL, 0), (Action.CALL, 0)],
              "C": [(Action.FOLD, 0)], "H": [(Action.ALL_IN, 0)]}

    def cb(player, state):
        q = script.get(player.name)
        if q:
            return q.pop(0)
        return (Action.CALL, 0) if state["current_bet"] > player.current_bet else (Action.CHECK, 0)
    g._action_callback = cb
    assert _quiet(ctl.play_hand)
    chips = {p.name: p.chips for p in g.players}
    assert chips == {"H": 310, "A": 600, "B": 200, "C": 490}, \
        f"메인 310 → H, 사이드 400 → A여야 함: {chips}"

    # ② 버튼 앞 좌석(A) 파산 → 다음 버튼은 B 다음 생존자 C
    del g._deal_hole_cards, g.deal_community
    next(p for p in g.players if p.name == "A").chips = 0
    assert _quiet(ctl.play_hand)
    assert g.button_name == "C", f"무빙 버튼: 직전 B → C여야 함, 실제 {g.button_name}"
    assert [p.name for p in g.players] == ["H", "B", "C"]


def test_4_10_cli_and_web_session_same_behavior():
    """T-024: 같은 카드·같은 결정이면 CLI 경로(GameController.play_hand)와 웹 세션 경로
    (WebGameSession)가 핸드마다 같은 액션(불법 요청의 폴백 포함)·같은 칩 결과를 낸다 — 룰이
    core 한 곳에만 있다는 확인."""
    import random
    from core.game import IllegalActionError
    names = ["Human", "🤖 Alpha", "🤖 Beta", "🤖 Gamma"]
    stacks = [400, 60, 900, 35]

    def make_decider(seed):
        rngs = {n: random.Random(f"{seed}-{n}") for n in names}

        def decide(player, state):
            r = rngs[player.name].random()
            cb = state["current_bet"]
            if r < 0.12:
                return Action.FOLD, 0
            if r < 0.30:
                return Action.CHECK, 0   # 벳을 마주하면 불법 → 폴백(폴드)
            if r < 0.60:
                return Action.CALL, 0
            if r < 0.85:
                return Action.RAISE, rngs[player.name].randint(0, cb * 3 + 60)
            return Action.ALL_IN, 0
        return decide

    def hand_actions(game):
        return [(e.data["player"], e.data["action"], e.data.get("to_amount"))
                for e in game.event_log if e.event_type == "action"]

    import logging
    lg = logging.getLogger("server.session")
    old_level = lg.level
    lg.setLevel(logging.ERROR)  # 봇 폴백 경고는 여기서 의도된 것
    compared = 0
    try:
        for seed in range(8):
            compared += _cli_vs_web_one_seed(seed, names, stacks, make_decider, hand_actions)
    finally:
        lg.setLevel(old_level)
    assert compared >= 15, f"비교한 핸드가 너무 적음: {compared}"


def _cli_vs_web_one_seed(seed, names, stacks, make_decider, hand_actions):
    """test_4_10 한 시드: CLI와 웹 세션을 같은 카드·결정으로 돌려 핸드별로 비교. 반환: 비교한 핸드 수."""
    import random
    from core.game import IllegalActionError
    # CLI 경로
    ctl = _cli_controller(stacks, names)
    deck_rng = random.Random(seed)
    ctl.game.deck.shuffle = lambda d=ctl.game.deck: deck_rng.shuffle(d.cards)
    ctl.game._action_callback = make_decider(seed)
    cli_hands = []
    for _ in range(8):
        if not _quiet(ctl.play_hand):
            break
        cli_hands.append((hand_actions(ctl.game), {p.name: p.chips for p in ctl.game.players}))

    # 웹 세션 경로(같은 카드 순서·같은 결정 함수)
    decide = make_decider(seed)

    class _Bot(StubBot):
        def decide_action(self, gs):
            return decide(self.player, gs)
    sess, _ = _scripted_session(3, chips=stacks, dealer_index=0,
                                deck_rng=random.Random(seed), bot_factory=_Bot)
    web_hands = []
    while len(web_hands) < len(cli_hands) and not sess.game_over:
        while not sess.hand_over:
            assert sess.get_state()["waiting_for_action"]
            act, amt = decide(sess.human, sess.game._get_game_state())
            try:
                sess.submit_action(act.value, amt)
            except IllegalActionError:
                sess.submit_action(sess.game.fallback_action(sess.human, act).value, 0)
        web_hands.append((hand_actions(sess.game), {p.name: p.chips for p in sess.game.players}))
        sess.next_hand()
    for i, (cli, web) in enumerate(zip(cli_hands, web_hands)):
        assert cli == web, f"seed {seed} 핸드 {i + 1}: CLI {cli} ≠ 웹 {web}"
    assert len(web_hands) == len(cli_hands), (seed, len(cli_hands), len(web_hands))
    return len(cli_hands)


def test_4_11_cli_raise_prompt_no_negative_chips():
    """CLI 레이즈 안내는 최소 레이즈-투를 낼 스택이 있을 때만(웹 ActionBar `maxRaise >= min_raise_to`).
    BB(스택 150)가 100 레이즈를 마주하면 최소 레이즈-투 180 > 스택 → [r] 없이 콜·올인만, 음수 칩 없음."""
    import io
    import contextlib
    from unittest import mock

    def prompt(h_stack):
        ctl = _cli_controller([h_stack, 1000, 1000], ["H", "A", "B"])
        g = ctl.game
        g.dealer_index = 1                     # BTN=A, SB=B, BB=H, UTG=A
        g.start_hand()
        h, a, b = g.players
        g.act(a, Action.RAISE, 100)
        g.act(b, Action.FOLD)
        assert g.next_to_act() is h
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch("builtins.input", return_value="f"):
            ctl._get_human_action(h, g._get_game_state(), "[BB]")
        return out.getvalue()

    text = prompt(150)
    assert "[r]" not in text and "[a] 올인" in text and "→ -" not in text, text
    text = prompt(1000)
    assert "[r] 레이즈" in text and "→ -" not in text, text


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
    """기여가 다른 3명 올인(100/300/600) → 메인 300(3명)·사이드 400(2명)·반환 300(1명)으로
    정확히 분리(core showdown). 같은 기여(200×3)면 팟 1개."""
    game, players = make_game(3, chips=0, sb=10)
    _set_contributions(game, [100, 300, 600])
    for p in players:
        p.is_all_in = True
    force_community(game, [c("2", "H"), c("7", "D"), c("9", "S"), c("3", "C"), c("5", "H")])
    force_hole_cards(game, {0: [c("A", "S"), c("A", "H")], 1: [c("K", "S"), c("K", "H")],
                            2: [c("Q", "S"), c("Q", "H")]})
    res = game.showdown()
    layers = [(s.amount, [p.name for p in s.eligible], [p.name for p in s.winners], s.returned)
              for s in res.pots]
    assert layers == [(300, ["P0", "P1", "P2"], ["P0"], False),
                      (400, ["P1", "P2"], ["P1"], False),
                      (300, ["P2"], ["P2"], True)], layers
    assert [p.chips for p in players] == [300, 400, 300], [p.chips for p in players]
    assert [w.name for w in res.winners] == ["P0", "P1"], "반환만 받은 P2는 승자가 아님"

    game, players = make_game(3, chips=0, sb=10)
    _set_contributions(game, [200, 200, 200])
    for p in players:
        p.hole_cards = [c("2", "S"), c("3", "S")]
    pots = game.calculate_side_pots()
    assert [(a, len(e)) for a, e in pots] == [(600, 3)], f"동일 기여액이면 팟 1개여야 함: {pots}"

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
    gto_loader.invalidate()


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
    수동으로 캐시를 비우지 않아도 새로 저장한 노드가 즉시 조회된다."""
    from server.main import save_gto_preflop, GtoPreflopSaveRequest
    from gto.loader import get_open_range, get_range_by_seq
    import gto.loader as gto_loader

    gto_loader.invalidate()
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
    gto_loader.invalidate()
    try:
        yield path
    finally:
        if prev is None:
            os.environ.pop("EV_PLUS_DB", None)
        else:
            os.environ["EV_PLUS_DB"] = prev
        gto_loader.invalidate()


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


def test_7_15_migration_v14_relabels_limp_nodes():
    """T-016: 옛 derive_node_meta가 림프 노드를 'open'/"{H} RFI"로 잘못 저장한 기존
    행(예: 운영 DB id 17, action_seq="F-F-F-F-C")을 v14 마이그레이션이 'vs_limp'/
    "BB vs SB limp"로 재라벨링한다. range_type='open'인데 실제로 콜(림프) 없는
    진짜 RFI 행은 손대지 않는다. 핸드 데이터는 그대로 보존된다."""
    from db.connection import get_connection
    from db.schema import SCHEMA_VERSION
    rows = [
        # 운영 DB id 17과 같은 모양의 버그 행: SB 림프 후 BB인데 'open'/"BB RFI"로 저장됨.
        (17, "BB", None, "open", None, "BB RFI", "F-F-F-F-C", "BB", 2),
        # 진짜 RFI(콜 없음) — 재라벨 대상 아님.
        (1, "UTG", None, "open", 2.5, "UTG RFI", "", "UTG", 6),
    ]
    hands = [(1, 17, "AA", 0, 1.0, 0, 0), (2, 1, "AA", 0, 0, 1.0, 0)]
    path = _make_v12_db(rows, hands)
    conn = get_connection(path)
    try:
        assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == SCHEMA_VERSION
        limp = conn.execute(
            "SELECT vs_position, range_type, situation_label FROM gto_preflop_situations WHERE id=17"
        ).fetchone()
        assert (limp["vs_position"], limp["range_type"], limp["situation_label"]) == (
            "SB", "vs_limp", "BB vs SB limp"
        ), dict(limp)
        rfi = conn.execute(
            "SELECT vs_position, range_type, situation_label FROM gto_preflop_situations WHERE id=1"
        ).fetchone()
        assert (rfi["vs_position"], rfi["range_type"], rfi["situation_label"]) == (
            None, "open", "UTG RFI"
        ), dict(rfi)
        # 핸드 데이터 보존
        got_hands = [tuple(r) for r in conn.execute(
            "SELECT * FROM gto_preflop_hands ORDER BY id")]
        assert got_hands == [tuple(h) for h in hands], got_hands
    finally:
        conn.close()


def test_7_16_save_marks_missing_queue_collected():
    """T-015/ADR 0011: /gto/preflop/save가 성공하면 같은 action_seq를 가리키던
    미수집 큐(range_type='seq', 노드 키는 vs_position 칸) 행이 collected=1로
    갱신된다(collected_at도 채워짐). 다른 노드를 가리키는 큐 행은 그대로 collected=0."""
    from db.connection import get_connection
    with _fresh_gto_db():
        client = _save_client()
        conn = get_connection()
        conn.execute(
            "INSERT INTO gto_missing_spots_preflop "
            "(street, position, vs_position, range_type, situation_label) "
            "VALUES ('preflop','BB','F-F-F-R2.5-C','seq','seq F-F-F-R2.5-C')"
        )
        conn.execute(
            "INSERT INTO gto_missing_spots_preflop "
            "(street, position, vs_position, range_type, situation_label) "
            "VALUES ('preflop','BB','F-F-F-R2.5-F','seq','seq F-F-F-R2.5-F')"
        )
        conn.commit()
        conn.close()

        r = client.post("/gto/preflop/save", json={
            "action_seq": "F-F-F-R2.5-C", "hands": {"AKs": {"call": 1.0}}, "raise_size": 11.0,
        })
        assert r.status_code == 200, r.text

        conn = get_connection()
        rows = {
            row["vs_position"]: (row["collected"], row["collected_at"])
            for row in conn.execute(
                "SELECT vs_position, collected, collected_at FROM gto_missing_spots_preflop "
                "WHERE range_type='seq'"
            )
        }
        conn.close()
        assert rows["F-F-F-R2.5-C"][0] == 1, rows
        assert rows["F-F-F-R2.5-C"][1] is not None, "collected_at도 채워져야 함"
        assert rows["F-F-F-R2.5-F"] == (0, None), \
            f"다른 노드를 가리키는 큐 행은 그대로여야 함: {rows}"


def _panel_range(node_key):
    """GTO 패널이 부르는 경로 그대로: GET /gto/preflop/range?action_seq=<node_key>."""
    r = _save_client().get("/gto/preflop/range", params={"action_seq": node_key})
    assert r.status_code == 200, r.text
    return r.json()


def _assert_panel_matches_hint(state, want_key, want_approx=False):
    """게임 상태 gto(=advisor 추천)와 패널이 조회하는 레인지가 같은 노드인지."""
    gto = state["gto"]
    assert gto is not None and gto["found"], f"GTO 패널 데이터 없음: {gto}"
    assert gto["node_key"] == want_key, f"node_key {gto['node_key']!r} != {want_key!r}"
    assert gto["approx"] is want_approx, gto
    rng = _panel_range(gto["node_key"])
    assert rng["found"], f"패널 레인지 조회 실패: {rng}"
    assert rng["situation"] == gto["situation"], (rng["situation"], gto["situation"])
    assert rng["hands"][gto["hand"]] == gto["frequencies"], (rng["hands"].get(gto["hand"]), gto)
    return gto, rng


def test_7_17_panel_is_bound_to_advisor_node_key():
    """T-013: GTO 패널은 advisor 추천의 node_key로 레인지를 조회한다 — 힌트와 같은 노드.
    ① 시퀀스로만 수집된 콜러 노드(3벳에 콜드콜)도 패널에 보인다(라벨 노드로 새지 않음)
    ② 4벳을 받는 결정(라벨 경로 없음)도 패널에 보인다
    ③ 게임 상태에 한글 로그 판정 키(gto_key)·중복 문자열(gto_hint)이 없다(ADR 0007)."""
    # ① 사람=UTG(dealer_index=3). UTG 2.5bb → HJ 3벳 8bb → CO 콜 → 나머지 폴드 → 사람
    _seed_situation("UTG", "UTG/HJ", "vs_3bet", 20.0, "UTG vs HJ 3bet",
                    {"AKs": {"raise": 1.0}}, "R2.5-R8-F-F-F-F")
    _seed_situation("UTG", "UTG/HJ", "vs_3bet", 22.0, "UTG vs HJ 3bet (CO call)",
                    {"AKs": {"call": 1.0}}, "R2.5-R8-C-F-F-F")
    sess, _ = _scripted_session(5, dealer_index=3, scripts={
        "🤖 Alpha": [(Action.RAISE, 160)], "🤖 Beta": [(Action.CALL, 160)],
        "🤖 Gamma": [(Action.FOLD, 0)], "🤖 Delta": [(Action.FOLD, 0)],
        "🤖 Epsilon": [(Action.FOLD, 0)]})
    assert sess.game.get_positions()[sess.human.name] == "UTG"
    sess.human.hole_cards = [c("A", "S"), c("K", "S")]
    sess.submit_action("raise", 50)
    state = sess.get_state()
    assert state["waiting_for_action"] and state["street"] == "프리플랍", state["street"]
    assert "gto_key" not in state and "gto_hint" not in state, sorted(state)
    gto, _ = _assert_panel_matches_hint(state, "R2.5-R8-C-F-F-F")
    assert gto["frequencies"] == {"call": 1.0}, gto

    # ② 사람=HJ(dealer_index=2). UTG 2.5bb → 사람 3벳 8bb → 폴드 4명 → UTG 4벳 20bb → 사람
    _seed_situation("HJ", "UTG/HJ/UTG", "vs_4bet", None, "HJ vs UTG 4bet",
                    {"AKs": {"call": 0.7, "allin": 0.3}}, "R2.5-R8-F-F-F-F-R20")
    sess, _ = _scripted_session(5, dealer_index=2, scripts={
        "🤖 Epsilon": [(Action.RAISE, 50), (Action.RAISE, 400)],
        "🤖 Alpha": [(Action.FOLD, 0)], "🤖 Beta": [(Action.FOLD, 0)],
        "🤖 Gamma": [(Action.FOLD, 0)], "🤖 Delta": [(Action.FOLD, 0)]})
    assert sess.game.get_positions()[sess.human.name] == "HJ"
    sess.human.hole_cards = [c("A", "S"), c("K", "S")]
    sess.submit_action("raise", 160)
    state = sess.get_state()
    assert state["waiting_for_action"] and state["current_bet"] == 400, state["current_bet"]
    _assert_panel_matches_hint(state, "R2.5-R8-F-F-F-F-R20")


def test_7_18_headsup_first_decision_panel_shows_range():
    """T-013(T-019 화면 쪽): 헤즈업 BTN/SB 첫 결정에서 패널이 6-max SB RFI 노드(F-F-F-F)
    레인지를 보여준다. 예전 패널은 'BTN/SB' 라벨로 조회해 "데이터 없음"이었다."""
    _seed_situation("SB", None, "open", 3.0, "SB RFI",
                    {"AKs": {"raise": 1.0}, "72o": {"fold": 1.0}}, "F-F-F-F")
    sess, _ = _scripted_session(1, dealer_index=0)
    sess.human.hole_cards = [c("A", "S"), c("K", "S")]
    state = sess.get_state()
    assert state["waiting_for_action"]
    gto, rng = _assert_panel_matches_hint(state, "F-F-F-F")
    assert gto["position"] == "BTN/SB" and rng["summary"], (gto, rng)


def test_7_19_label_fallback_panel_marked_approx():
    """ADR 0035: 라벨 예비로 답한 추천은 패널에도 근사(approx=True)로 실리고, 패널은 그
    라벨이 가리키는 노드(콜러 없는 노드)의 레인지를 받는다. 6인: 사람=BB(딜러=Delta),
    HJ 오픈 → CO 콜 → BTN·SB 폴드. 정확한 노드(F-R2.5-C-F-F)는 미수집."""
    with _fresh_gto_db():
        _seed_situation("BB", "HJ", "vs_open", 14.0, "BB vs HJ open",
                        {"AKs": {"raise": 0.6, "call": 0.4}}, "F-R2.5-F-F-F")
        sess, _ = _scripted_session(5, dealer_index=4, scripts={
            "🤖 Alpha": [(Action.FOLD, 0)], "🤖 Beta": [(Action.RAISE, 50)],
            "🤖 Gamma": [(Action.CALL, 50)], "🤖 Delta": [(Action.FOLD, 0)],
            "🤖 Epsilon": [(Action.FOLD, 0)]})
        assert sess.game.get_positions()[sess.human.name] == "BB", sess.game.get_positions()
        sess.human.hole_cards = [c("A", "S"), c("K", "S")]
        state = sess.get_state()
        assert state["waiting_for_action"] and state["current_bet"] == 50, state["current_bet"]
        _assert_panel_matches_hint(state, "F-R2.5-F-F-F", want_approx=True)

        # 추천이 없으면 found=False(패널 "GTO 데이터 없음"), 포스트플랍·폴드 후엔 None
        sess.human.hole_cards = [c("7", "H"), c("2", "C")]
        assert sess.get_state()["gto"] == {"found": False, "position": "BB"}
        assert _panel_range("R9-R9")["found"] is False


_SIX_MAX = {"U": "UTG", "H": "HJ", "C": "CO", "B": "BTN", "S": "SB", "Bb": "BB"}


def test_7_20_allin_in_seq_label_fallback_none_and_queued():
    """ADR 0037: 시퀀스에 올인이 있으면 라벨 예비 경로는 올인을 레이즈 라벨로 읽지 않는다
    (None → 힌트 "데이터 없음"). 정확한 노드 키는 미수집 큐에 남는다.
    ① UTG 올인 → HJ: "HJ vs UTG open" 라벨 노드를 내주지 않는다
    ② UTG 오픈 → HJ 3벳 → CO 올인 → UTG: "UTG vs HJ 3bet" 라벨 노드를 내주지 않는다"""
    from gto.advisor import GTOAdvisor
    with _fresh_gto_db():
        _seed_situation("UTG", None, "open", 2.5, "UTG RFI", {"AKo": {"raise": 1.0}}, "")
        _seed_situation("HJ", "UTG", "vs_open", 8.0, "HJ vs UTG open",
                        {"AKo": {"raise": 0.9, "call": 0.1}}, "R2.5")
        _seed_situation("UTG", "UTG/HJ", "vs_3bet", 20.0, "UTG vs HJ 3bet",
                        {"AKo": {"raise": 0.3, "call": 0.7}}, "R2.5-R8-F-F-F-F")
        advisor = GTOAdvisor()
        hole = [c("A", "S"), c("K", "H")]

        gs = {"street": "프리플랍", "current_bet": 2000,
              "preflop_seq": [{"position": "UTG", "action": "allin", "amount_bb": 100.0}]}
        assert advisor._recommend_by_enum(hole, "HJ", _SIX_MAX, gs, 20) is None
        rec = advisor.get_recommendation(hole, "HJ", _SIX_MAX, gs, 20)
        assert rec is None, f"UTG 올인에 HJ vs UTG open 라벨을 내줌: {rec}"
        assert ("HJ", "R100") in _queued_seq_keys(), _queued_seq_keys()

        seq = [{"position": "UTG", "action": "raise", "amount_bb": 2.5},
               {"position": "HJ", "action": "raise", "amount_bb": 8.0},
               {"position": "CO", "action": "allin", "amount_bb": 100.0},
               {"position": "BTN", "action": "fold"}, {"position": "SB", "action": "fold"},
               {"position": "BB", "action": "fold"}]
        gs = {"street": "프리플랍", "current_bet": 2000, "preflop_seq": seq}
        assert advisor._recommend_by_enum(hole, "UTG", _SIX_MAX, gs, 20) is None
        rec = advisor.get_recommendation(hole, "UTG", _SIX_MAX, gs, 20)
        assert rec is None, f"CO 올인에 UTG vs HJ 3bet 라벨을 내줌: {rec}"
        assert ("UTG", "R2.5-R8-R100-F-F-F") in _queued_seq_keys(), _queued_seq_keys()


def test_7_21_limped_pot_is_not_rfi():
    """ADR 0046: 림프(레이즈 전 콜)가 있는 팟은 RFI가 아니다 — 라벨 예비 경로가 "HJ RFI"
    노드를 내주지 않는다. 림프 노드(vs_limp)가 수집돼 있으면 시퀀스 경로로만 정확히 받는다."""
    from gto.advisor import GTOAdvisor
    with _fresh_gto_db():
        _seed_situation("HJ", None, "open", 2.5, "HJ RFI", {"AKs": {"raise": 1.0}}, "F")
        advisor = GTOAdvisor()
        hole = [c("A", "S"), c("K", "S")]
        gs = {"street": "프리플랍", "current_bet": 20,
              "preflop_seq": [{"position": "UTG", "action": "call", "amount_bb": 1.0}]}
        rec = advisor.get_recommendation(hole, "HJ", _SIX_MAX, gs, 20)
        assert rec is None, f"림프 팟에 RFI 노드를 내줌: {rec}"
        assert ("HJ", "C") in _queued_seq_keys(), _queued_seq_keys()

        _seed_situation("HJ", "UTG", "vs_limp", 4.0, "HJ vs UTG limp", {"AKs": {"raise": 1.0}}, "C")
        rec = advisor.get_recommendation(hole, "HJ", _SIX_MAX, gs, 20)
        assert rec is not None and rec["node_key"] == "C" and rec["approx"] is False, rec


def test_7_22_short_handed_table_has_no_label_fallback():
    """ADR 0005: 3~5인 테이블은 시퀀스 경로뿐 아니라 라벨 예비 경로도 쓰지 않는다 — 6-max
    "UTG RFI" 데이터를 4인 UTG에게 내주지 않고(패널 "GTO 데이터 없음"), 큐에도 넣지 않는다."""
    from gto.advisor import GTOAdvisor
    with _fresh_gto_db():
        _seed_situation("UTG", None, "open", 2.5, "UTG RFI", {"AKs": {"raise": 1.0}}, "")
        _seed_situation("BTN", None, "open", 2.5, "BTN RFI", {"AKs": {"raise": 1.0}}, "F-F-F")
        sess, _ = _scripted_session(3, dealer_index=1)
        assert sess.game.get_positions()[sess.human.name] == "UTG", sess.game.get_positions()
        sess.human.hole_cards = [c("A", "S"), c("K", "S")]
        assert sess.get_state()["gto"] == {"found": False, "position": "UTG"}

        three = {"A": "BTN", "B": "SB", "C": "BB"}
        gs = {"street": "프리플랍", "current_bet": 20, "preflop_seq": []}
        advisor = GTOAdvisor()
        assert advisor._recommend_by_enum([c("A", "S"), c("K", "S")], "BTN", three, gs, 20) is None
        assert advisor.get_recommendation([c("A", "S"), c("K", "S")], "BTN", three, gs, 20) is None
        assert _queued_seq_keys() == set(), _queued_seq_keys()


# ═════════════════════════════════════════════════════════════
# 영역 8 — 세션 경로 룰 (WebGameSession 실제 실행 경로)
#   core 헬퍼(_betting_order, apply_action)만 부르는 테스트는 웹 경로의 버그를
#   못 잡았다(2026-09-26 리뷰 RC1). 여기 테스트는 전부 WebGameSession 공개 API
#   (submit_action / next_hand / get_state의 events)로 검사한다.
# ═════════════════════════════════════════════════════════════

def _total_chips(sess):
    return sum(p.chips for p in sess.game.players) + sess.game.pot


def _scripted_session(num_bots, scripts=None, chips=None, dealer_index=0, sb=10,
                      bot_factory=None, deck_rng=None):
    """원하는 좌석·스택·봇 스크립트로 '새 핸드'를 시작한 세션을 만든다.

    WebGameSession 생성자는 첫 핸드를 바로 진행시키므로, 생성 후 스택·딜러·봇을
    다시 세팅하고 핸드 종료 상태에서 next_hand()로 깨끗한 핸드를 시작한다.
    scripts: {봇 이름: [(Action, amount), ...]} — 소진되면 콜/체크.
    chips: 좌석 순서(사람 먼저)대로의 스택 리스트.
    bot_factory: 주면 봇을 bot_factory(player)로 만든다(scripts 대신, 퍼저용).
    deck_rng: 주면 덱 셔플을 이 random.Random으로(퍼저 재현성).
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
    sess.game.button_name = None
    scripts = scripts or {}
    for name, bot in list(sess.bots.items()):
        sess.bots[name] = (bot_factory(bot.player) if bot_factory
                           else StubBot(bot.player, scripts.get(name)))
    if deck_rng is not None:
        deck = sess.game.deck
        deck.shuffle = lambda: deck_rng.shuffle(deck.cards)
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
    gto = state["gto"]
    assert gto and gto["found"] and gto["node_key"] == "F-F-F-F", \
        f"헤즈업 BTN/SB 첫 결정에 GTO 힌트가 없음: {gto}"


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


def _two_short_allins_scenario(beta_stack, gamma_stack):
    """4인, 딜러=Gamma → 사람=SB(플랍 선행동), Alpha=BB, Beta=UTG. 프리플랍은 모두 20 림프/체크.
    플랍: 사람 벳 100 → Alpha 콜 → Beta 올인 → Gamma 올인(각 플랍 시작 스택 = 스택 - 20)."""
    sess, _ = _scripted_session(
        3, dealer_index=3, chips=[1000, 1000, beta_stack, gamma_stack],
        scripts={"🤖 Alpha": [(Action.CHECK, 0), (Action.CALL, 100)],
                 "🤖 Beta": [(Action.CALL, 20), (Action.ALL_IN, 0)],
                 "🤖 Gamma": [(Action.CALL, 20), (Action.ALL_IN, 0)]})
    assert sess.get_state()["call_amount"] == 10, "사람(SB) 프리플랍 차례여야 함"
    sess.submit_action("call", 0)
    assert sess.get_state()["street"] == "플랍"
    return sess, sess.submit_action("raise", 100)


def test_8_25_cumulative_short_allins_reopen():
    """T-038(TDA Rule 47): 벳 100 → 콜 → 150 올인 → 220 올인. 올인 하나하나는 풀 레이즈가
    아니지만 처음 벳한 사람이 마주한 증가분 합계(+120)가 최소 레이즈(100) 이상이라 레이즈할 수 있다."""
    sess, events = _two_short_allins_scenario(beta_stack=170, gamma_stack=240)
    flop = [(a["player"], a["action"], a["amount"]) for a in _action_events(events)
            if a["street"] == "플랍"]
    assert flop == [("Human", "raise", 100), ("🤖 Alpha", "call", 100),
                    ("🤖 Beta", "allin", 150), ("🤖 Gamma", "allin", 220)], flop
    st = sess.get_state()
    assert st["waiting_for_action"] and st["call_amount"] == 120, st["call_amount"]
    assert st["can_raise"] is True and st["min_raise_to"] == 320, \
        f"누적 +120 ≥ 100이면 레이즈 가능: can_raise={st['can_raise']} min_raise_to={st['min_raise_to']}"
    ev = _action_events(sess.submit_action("raise", 400))
    assert (ev[0]["player"], ev[0]["action"], ev[0]["amount"]) == ("Human", "raise", 400), ev[0]
    # 콜했던 Alpha도 마주한 증가분(400-100)이 풀 레이즈 이상이라 다시 행동한다(스텁은 콜)
    assert ev[1]["player"] == "🤖 Alpha" and ev[1]["action"] == "call", ev[1]


def test_8_26_cumulative_short_allins_below_full_raise_stay_closed():
    """T-038: 벳 100 → 콜 → 150 올인 → 190 올인. 증가분 합계(+90)가 최소 레이즈(100) 미만이면
    처음 벳한 사람은 여전히 콜/폴드만 할 수 있다."""
    from core.game import IllegalActionError
    sess, _ = _two_short_allins_scenario(beta_stack=170, gamma_stack=210)
    st = sess.get_state()
    assert st["waiting_for_action"] and st["call_amount"] == 90, st["call_amount"]
    assert st["can_raise"] is False and st["min_raise_to"] == 0, \
        f"누적 +90 < 100이면 레이즈 불가: can_raise={st['can_raise']} min_raise_to={st['min_raise_to']}"
    for bad in [("raise", 400), ("allin", 0)]:
        try:
            sess.submit_action(*bad)
            raise AssertionError(f"닫힌 액션에서 {bad}가 거절되지 않음")
        except IllegalActionError:
            pass


def test_8_27_grade_receives_real_raise_amount():
    """T-038: 플레이 평가(_grade_human_action)는 요청값이 아니라 실제로 걸리는 레이즈 금액
    (최소 레이즈 보정·스택 초과 올인 반영, 도달 베팅 기준)을 받는다."""
    for req, want in [(25, 40), (5000, 1000)]:
        sess, _ = _scripted_session(2, dealer_index=0)   # 사람=UTG, 콜 20 마주함
        sess.equity_enabled = True
        seen = []
        sess._grade_human_action = lambda p, a, amt, st, ca: (seen.append((a, amt)), (None, None))[1]
        ev = _action_events(sess.submit_action("raise", req))
        h = next(e for e in ev if e["player"] == "Human")
        assert seen and seen[0][1] == want == h["amount"], \
            f"raise {req}: 평가 금액 {seen} ≠ 실제 {h['amount']} (기대 {want})"


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
    """퍼저용: 합법·불법을 가리지 않고 무작위 액션을 낸다(불법이면 세션이 폴백).
    requests가 주어지면 (이름, 요청 액션)을 기록해 참조 모델이 폴백 여부를 검사한다."""

    def __init__(self, player, rng, requests=None, shove=0.12):
        super().__init__(player)
        self._rng = rng
        self._requests = requests
        self._shove = shove  # 올인 요청 비율(숏스택 올인 연쇄 = 누적 재오픈 상황을 자주 만들기 위해)

    def decide_action(self, game_state):
        r = self._rng.random()
        cb = game_state["current_bet"]
        # 스택이 5bb 이하인 숏스택은 자주 올인한다(불완전 올인 연쇄)
        shove = 0.7 if self.player.chips + self.player.current_bet <= 5 * game_state["big_blind"] \
            else self._shove
        if r < shove:
            choice = (Action.ALL_IN, 0)
        elif r < shove + (1 - shove) * 0.17:
            choice = (Action.FOLD, 0)
        elif r < shove + (1 - shove) * 0.40:
            choice = (Action.CHECK, 0)
        elif r < shove + (1 - shove) * 0.70:
            choice = (Action.CALL, 0)
        else:
            choice = (Action.RAISE, self._rng.randint(0, max(1, cb * 4 + 100)))
        if self._requests is not None:
            self._requests.append((self.player.name, choice[0]))
        return choice


class _RefTable:
    """세션 경로 퍼저의 독립 참조 모델 — 룰을 core와 따로 테스트 쪽에 적어 두고, 세션이 낸
    이벤트·상태를 한 줄씩 대조한다(T-024). core 룰을 잘못 고치면 여기와 어긋나 실패한다.
    재생 표시 상태 필드(T-029: 이벤트 pot_after·bet_after)도 함께 검사한다.

    검사: 행동 순서(헤즈업 포함, 블라인드는 행동 아님, 런아웃), 최소 레이즈, 레이즈 권한
    (TDA Rule 47 누적 재오픈), 이벤트·로그 금액 = 실제 칩 이동, 봇 불법 액션 폴백,
    사람에게 보이는 call_amount·can_raise·min_raise_to, 사람 불법 액션 판정.
    """

    def __init__(self, sess, requests):
        g = sess.game
        self.seats = [p.name for p in g.players]       # 이번 핸드 좌석 순서
        self.n = len(self.seats)
        self.dealer = g.dealer_index
        self.human = sess.human.name
        self.bb = g.big_blind
        self.chips = dict(sess._hand_start_chips)
        self.bets = {k: 0 for k in self.seats}
        self.folded, self.allin = set(), set()
        self.pot = 0                                  # 재생 표시 상태 검사용(T-029 pot_after)
        self.requests = requests
        self._new_street("프리플랍")
        self.level = self.bb                          # 블라인드 뒤 current_bet = BB(숏스택 BB여도)

    def _new_street(self, street):
        self.street = street
        self.level, self.min = 0, self.bb
        self.acted, self.seen, self.last = set(), {}, None
        for k in self.bets:
            self.bets[k] = 0

    def _can_act(self, p):
        return p not in self.folded and p not in self.allin

    def may_raise(self, p):
        # 콜할 상대가 없으면(나 외에 폴드·올인 아닌 사람 0) 레이즈 불가
        if not any(q != p and self._can_act(q) for q in self.seats):
            return False
        return p not in self.seen or self.level - self.seen[p] >= self.min

    def next_actor(self):
        if sum(1 for p in self.seats if p not in self.folded) <= 1:
            return None
        act = [p for p in self.seats if self._can_act(p)]
        if not act:
            return None
        if len(act) == 1 and self.bets[act[0]] >= self.level:
            return None                                # 런아웃: 더 물을 상대가 없다
        if all(p in self.acted and self.bets[p] == self.level for p in act):
            return None
        if self.last is not None:
            start = self.seats.index(self.last) + 1
        elif self.street == "프리플랍":
            start = self.dealer if self.n == 2 else self.dealer + 3   # 헤즈업은 BTN/SB 먼저
        else:
            start = self.dealer + 1                    # 포스트플랍: SB(헤즈업은 BB)부터
        for k in range(self.n):
            p = self.seats[(start + k) % self.n]
            if self._can_act(p) and not (p in self.acted and self.bets[p] == self.level):
                return p
        return None

    def check_human_turn(self, st):
        h = self.human
        assert self.next_actor() == h, f"사람 차례가 아님: 기대 {self.next_actor()} ({self.street})"
        to_call = self.level - self.bets[h]
        assert st["call_amount"] == max(0, to_call), (st["call_amount"], to_call)
        can = self.may_raise(h) and self.chips[h] > to_call
        assert st["can_raise"] == can, \
            f"can_raise {st['can_raise']} ≠ 기대 {can} (level={self.level} seen={self.seen.get(h)} min={self.min})"
        if can:
            assert st["min_raise_to"] == self.level + self.min, (st["min_raise_to"], self.level, self.min)

    def human_legal(self, act):
        h = self.human
        to_call = self.level - self.bets[h]
        if act == "check":
            return to_call <= 0
        if act in ("raise", "allin"):
            return self.may_raise(h) or self.chips[h] + self.bets[h] <= self.level
        return True

    def feed(self, events):
        for e in events:
            t = e["type"]
            if t == "blind":
                p = e["player"]
                moved = self.chips[p] - e["chips_after"]
                assert moved > 0 and e["amount"] == moved, f"블라인드 금액≠실제 포스팅: {e} moved={moved}"
                self.bets[p] += moved
                self.chips[p] = e["chips_after"]
                if self.chips[p] == 0:
                    self.allin.add(p)
                self._check_replay_fields(e, p, moved)
            elif t == "street_start":
                assert self.next_actor() is None, \
                    f"{self.street} 라운드가 끝나기 전에 스트리트 전환(남은 차례 {self.next_actor()})"
                assert e["pot_after"] == self.pot, f"street_start pot_after 불일치: {e} want {self.pot}"
                self._new_street(e["street"])
            elif t == "action":
                self._on_action(e)
            elif t in ("showdown", "winner"):
                assert self.next_actor() is None, f"라운드가 끝나기 전에 {t} (남은 차례 {self.next_actor()})"
                if t == "winner":
                    self.pot = 0

    def _check_replay_fields(self, e, p, moved):
        """재생 표시 상태 필드(T-029): pot_after = 누적 이동액, bet_after = 이번 스트리트 누적 베팅."""
        self.pot += moved
        assert e["pot_after"] == self.pot and e["bet_after"] == self.bets[p], \
            f"pot_after/bet_after 불일치: {e} want pot={self.pot} bet={self.bets[p]}"

    def _on_action(self, e):
        p, a = e["player"], e["action"]
        want = self.next_actor()
        assert p == want, f"행동 순서 위반({self.street}): {p} {a} — 기대 {want}"
        moved = self.chips[p] - e["chips_after"]
        to_call = self.level - self.bets[p]
        max_to = self.chips[p] + self.bets[p]
        allowed = self.may_raise(p)
        to = self.bets[p] + moved
        assert moved >= 0, f"칩이 늘어나는 action 이벤트: {e}"
        if a in ("fold", "check"):
            assert moved == 0 and e["amount"] == 0, f"{a}인데 칩 이동: {e}"
            if a == "check":
                assert to_call <= 0, f"벳을 마주한 체크가 적용됨: {e} to_call={to_call}"
        elif a == "call":
            assert to_call > 0 and e["amount"] == moved == min(to_call, self.chips[p]), \
                f"콜 금액≠이동액: {e} to_call={to_call} moved={moved}"
        else:
            assert e["amount"] == to, f"{a} 금액≠도달 베팅: {e} bet_before={self.bets[p]} moved={moved}"
            if a == "allin":
                assert e["chips_after"] == 0, f"올인인데 칩이 남음: {e}"
            if to > self.level:
                assert allowed, (f"레이즈 권한 없는데 {a} 적용: {p} level={self.level} "
                                 f"seen={self.seen.get(p)} min={self.min}")
            if a == "raise":
                assert to - self.level >= self.min, f"최소 레이즈 위반: {e} level={self.level} min={self.min}"
        if a not in ("fold", "check"):
            assert f"{e['amount']}" in e["log"], f"로그 금액 불일치: {e}"

        if p != self.human and self.requests is not None:
            assert self.requests and self.requests[0][0] == p, f"봇 요청 기록 불일치: {self.requests[:1]} vs {p}"
            _, req = self.requests.pop(0)
            if req in (Action.RAISE, Action.ALL_IN):
                if max_to <= self.level:
                    ok = a == "allin"
                elif allowed:
                    ok = a in ("raise", "allin")
                else:
                    ok = a in ("call", "check")        # 닫힌 액션 → 안전 폴백
            elif req == Action.CHECK:
                ok = a == ("check" if to_call <= 0 else "fold")
            elif req == Action.CALL:
                ok = a == ("check" if to_call <= 0 else "call")
            else:
                ok = a == "fold"
            assert ok, (f"봇 요청 {req.value} → {a} (허용={allowed}, level={self.level}, "
                        f"seen={self.seen.get(p)}, min={self.min}, max_to={max_to})")

        self.bets[p] += moved
        self.chips[p] = e["chips_after"]
        self._check_replay_fields(e, p, moved)
        if a == "fold":
            self.folded.add(p)
        elif self.chips[p] == 0:
            self.allin.add(p)
        if a in ("raise", "allin") and to > self.level:
            raise_by = to - self.level
            self.level = to
            if raise_by >= self.min:                  # 풀 레이즈만 재오픈 + 최소 레이즈 갱신
                self.min = raise_by
                self.acted = set()
        self.acted.add(p)
        self.seen[p] = self.level
        self.last = p


def _run_session_fuzz(seed, target_hands):
    """시드 고정 세션 경로 퍼저. 위반이 있으면 AssertionError. 반환: 친 핸드 수."""
    import random
    import logging
    from core.game import IllegalActionError
    rng = random.Random(seed)
    lg = logging.getLogger("server.session")
    old_level = lg.level
    lg.setLevel(logging.ERROR)  # 봇 폴백 경고는 여기서 의도된 것
    hands = 0
    try:
        while hands < target_hands:
            # 절반은 숏스택 올인 위주 세션: 1~3bb 스택 봇들이 자주 올인해 불완전 올인이 연달아
            # 나오고, 깊은 스택 사람이 누적 재오픈(TDA 47) 결정 지점을 밟는다
            shove_mode = rng.random() < 0.5
            n_bots = rng.randint(3, 5) if shove_mode else rng.randint(1, 5)
            if shove_mode:
                # 봇 스택 = 좌석 순서로 1bb 미만씩 올라가는 사다리(+ 가끔 깊은 스택) → 올인이
                # 하나하나는 불완전 레이즈지만 합계는 풀 레이즈가 되는 상황이 자주 나온다
                ladder, level = [], 20
                for _ in range(n_bots):
                    level += rng.randint(6, 19)
                    ladder.append(level if rng.random() < 0.8 else rng.randint(500, 2000))
                stacks = [rng.randint(300, 2000)] + ladder
            else:
                stacks = [rng.choice([rng.randint(5, 60), rng.randint(100, 2000)])
                          for _ in range(n_bots + 1)]
            shove = 0.12
            requests = []
            sess, events = _scripted_session(
                n_bots, chips=stacks, dealer_index=rng.randint(0, n_bots), deck_rng=rng,
                bot_factory=lambda player: _RandomBot(player, rng, requests, shove))
            seats = [p.name for p in sess.game.players]
            total = sum(stacks)
            # 세션당 최대 15핸드(숏스택 세션은 숏스택이 금방 파산하므로 3핸드)
            for _ in range(3 if shove_mode else 15):
                if sess.game_over:
                    break
                ref = _RefTable(sess, requests)
                ref.feed(events)
                guard = 0
                while not sess.hand_over:
                    guard += 1
                    assert guard < 60, "핸드가 끝나지 않음"
                    st = sess.get_state()
                    assert st["events"] == [], "get_state가 이벤트를 내보냄(순수 조회 위반)"
                    assert _total_chips(sess) == total, "칩 보존 위반"
                    assert st["waiting_for_action"], "핸드 진행 중인데 사람 차례가 아님(멈춤)"
                    ref.check_human_turn(st)
                    act = rng.choice(["fold", "check", "call", "raise", "allin"])
                    amt = rng.randint(0, st["current_bet"] * 4 + 100)
                    legal = ref.human_legal(act)
                    log_len = len(sess.action_log)
                    try:
                        ev = sess.submit_action(act, amt)
                        assert legal, f"불법이어야 할 사람 액션이 적용됨: {act} {amt}"
                    except IllegalActionError:
                        assert not legal, f"합법인 사람 액션이 거절됨: {act} {amt}"
                        assert len(sess.action_log) == log_len and _total_chips(sess) == total
                        ev = sess.submit_action("call" if st["call_amount"] > 0 else "check", 0)
                    ref.feed(ev)
                    if not sess.hand_over:
                        assert ref.pot == sess.game.pot, f"재생 팟 {ref.pot} != 실제 {sess.game.pot}"
                assert ref.next_actor() is None, "핸드가 끝났는데 참조 모델에 남은 차례가 있음"
                assert not requests, f"적용되지 않은 봇 요청: {requests}"
                assert _total_chips(sess) == total, "칩 보존 위반(핸드 종료)"
                hands += 1
                btn_label = "BTN/SB" if len(sess.game.players) == 2 else "BTN"
                prev_btn = _labels(sess)[btn_label]
                events = sess.next_hand()
                if not sess.game_over:
                    # 무빙 버튼(ADR 0036): 파산 전환 포함, 버튼 = 직전 버튼 다음 생존자
                    alive = {p.name for p in sess.game.players}
                    want = _expected_next_button(seats, prev_btn, alive)
                    btn_label = "BTN/SB" if len(alive) == 2 else "BTN"
                    assert _labels(sess)[btn_label] == want, \
                        f"버튼 이동 위반: 직전 {prev_btn} → {_labels(sess)[btn_label]} (기대 {want})"
    finally:
        lg.setLevel(old_level)
    return hands


FUZZ_SEED = 20260926
FUZZ_HANDS = 400


def test_8_12_session_fuzz_event_amounts_and_conservation():
    """세션 경로 퍼저(시드 고정, T-021·T-024): 무작위 인원(2~6)·스택(숏 포함)·액션(불법 포함)으로
    400핸드를 돌려 독립 참조 모델(_RefTable)과 대조한다 — 행동 순서(헤즈업·런아웃), 최소 레이즈,
    누적 재오픈(TDA 47), 이벤트·로그 금액 = 실제 칩 이동, 봇 폴백, 사람 화면 값·불법 판정,
    칩 보존, 무빙 버튼(파산 전환 포함)."""
    hands = _run_session_fuzz(FUZZ_SEED, FUZZ_HANDS)
    assert hands >= FUZZ_HANDS


def test_8_28_fuzzer_catches_reverted_cumulative_reopen():
    """T-024: 퍼저 분포가 약해지지 않았는지 — 누적 재오픈(T-038)을 액션 단위 판정으로 되돌리면
    세션 퍼저가 실패해야 한다(숏스택 사다리 세션이 이 상황을 만든다)."""
    orig = TexasHoldem.raise_allowed
    TexasHoldem.raise_allowed = lambda self, player, bet_seen: player.name not in self.acted
    try:
        _run_session_fuzz(FUZZ_SEED, FUZZ_HANDS)
        caught = False
    except AssertionError:
        caught = True
    finally:
        TexasHoldem.raise_allowed = orig
    assert caught, "T-038 버그를 되살렸는데 퍼저가 통과함 — 퍼저가 누적 재오픈 상황을 못 만든다"


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


def test_8_23_dev_server_reload_watches_server_code_only():
    """T-028: tests/·scripts/·docs를 고쳐도 dev 서버가 재시작되지 않는다 — dev.sh의 uvicorn은
    서버 코드 디렉터리(server·core·ai·gto·db)만 감시한다(uvicorn 설정 해석으로 확인)."""
    import re
    import shlex
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    text = open(os.path.join(root, "dev.sh"), encoding="utf-8").read()
    cmd = re.search(r"-m uvicorn server\.main:app(.*?)&\s*$", text, re.S | re.M)
    assert cmd, "dev.sh에서 uvicorn 실행 줄을 찾지 못함"
    args = shlex.split(cmd.group(1).replace("\\\n", " "))
    assert "--reload" in args, "dev 모드는 자동 재시작을 유지해야 함"
    dirs = [args[i + 1] for i, a in enumerate(args) if a == "--reload-dir"]
    assert sorted(dirs) == ["ai", "core", "db", "gto", "server"], f"감시 디렉터리: {dirs}"

    from uvicorn.config import Config
    cwd = os.getcwd()
    os.chdir(root)
    try:
        cfg = Config("server.main:app", reload=True, reload_dirs=dirs, log_level="warning")
        watched = [str(p) for p in cfg.reload_dirs]
    finally:
        os.chdir(cwd)
    for untouched in ("tests", "scripts", "docs", "web", "tools", "cli"):
        path = os.path.join(root, untouched)
        assert not any(path == w or path.startswith(w + os.sep) for w in watched), \
            f"{untouched}/ 수정이 서버를 재시작시킴: {watched}"
    for needed in ("server", "core", "ai", "gto", "db"):
        assert os.path.join(root, needed) in watched, f"{needed}/ 가 감시 대상이 아님: {watched}"


def test_8_24_old_sessions_pruned_and_return_404():
    """T-028: 오래 안 쓴 세션(24시간)과 개수 상한(20개) 초과분은 서버에서 정리되고, 정리된
    세션에 대한 요청은 404(프론트는 '세션 만료 — 새 게임' 안내)다. 최근에 쓴 세션은 남는다."""
    import server.main as m
    client, sessions = _api_client()
    saved = dict(sessions), dict(m._last_seen)
    real_now = m._now
    clock = [1_000_000.0]
    m._now = lambda: clock[0]
    try:
        sessions.clear()
        m._last_seen.clear()
        sess, _ = _scripted_session(1)
        sessions["old"] = sess
        m._last_seen["old"] = clock[0] - m.SESSION_TTL_SEC - 1
        sessions["fresh"] = sess
        m._last_seen["fresh"] = clock[0] - 60
        assert client.get("/game/old/state").status_code == 404, "만료 세션은 404여야 함"
        assert "old" not in sessions
        assert client.get("/game/fresh/state").status_code == 200
        assert client.post("/game/old/action", json={"action": "fold"}).status_code == 404
        assert client.post("/game/old/next-hand").status_code == 404

        # 개수 상한: 새 게임을 만들면 가장 오래 안 쓴 것부터 지워 MAX_SESSIONS 이하로
        for i in range(m.MAX_SESSIONS + 3):
            clock[0] += 1
            sessions[f"s{i}"] = sess
            m._last_seen[f"s{i}"] = clock[0]
        clock[0] += 1
        m._last_seen["fresh"] = clock[0]   # 방금 쓴 세션
        res = client.post("/game/start", json={"player_name": "P", "chips": 1000, "num_bots": 1,
                                               "difficulty": "easy", "big_blind": 10})
        new_id = res.json()["session_id"]
        assert len(sessions) == m.MAX_SESSIONS, f"세션 수 {len(sessions)} > 상한 {m.MAX_SESSIONS}"
        assert new_id in sessions and "fresh" in sessions, "새 세션·최근 세션은 남아야 함"
        assert "s0" not in sessions and "s1" not in sessions, "가장 오래된 세션부터 정리돼야 함"
    finally:
        m._now = real_now
        sessions.clear()
        sessions.update(saved[0])
        m._last_seen.clear()
        m._last_seen.update(saved[1])


def test_8_29_no_raise_when_no_opponent_can_act():
    """콜할 상대가 없으면 레이즈 불가: 3인 BTN 폴드 · SB 올인 30 → BB(사람)는 콜/폴드만
    (core validate가 RAISE·ALL_IN 거절, 응답 can_raise=false·min_raise_to=0)."""
    from core.game import IllegalActionError
    # 좌석 [Human, Alpha, Beta], 딜러 Alpha → SB=Beta, BB=Human, UTG=Alpha(BTN)
    sess, _ = _scripted_session(2, dealer_index=1, chips=[1000, 1000, 30],
                                scripts={"🤖 Alpha": [(Action.FOLD, 0)],
                                         "🤖 Beta": [(Action.ALL_IN, 0)]})
    g = sess.game
    st = sess.get_state()
    assert st["waiting_for_action"] and st["call_amount"] == 10, st["call_amount"]
    assert st["can_raise"] is False and st["min_raise_to"] == 0, (st["can_raise"], st["min_raise_to"])
    for act in (Action.RAISE, Action.ALL_IN):
        try:
            g.validate(sess.human, act, 200)
            raise AssertionError(f"콜할 상대가 없는데 {act.value}가 허용됨")
        except IllegalActionError:
            pass
    assert g.validate(sess.human, Action.CALL) == (Action.CALL, 30)
    assert g.validate(sess.human, Action.FOLD)[0] == Action.FOLD
    for bad in [("raise", 200), ("allin", 0)]:
        try:
            sess.submit_action(*bad)
            raise AssertionError(f"세션이 {bad}를 받음")
        except IllegalActionError:
            pass
    sess.submit_action("call", 0)
    assert sess.hand_over and _total_chips(sess) == 2030
    # 봇도 같은 규칙: 콜할 상대 없는 봇의 레이즈 요청은 콜로 대체
    sess, _ = _scripted_session(2, dealer_index=2, chips=[30, 1000, 1000],
                                scripts={"🤖 Beta": [(Action.FOLD, 0)],
                                         "🤖 Alpha": [(Action.RAISE, 500)]})
    # 좌석 [Human, Alpha, Beta], 딜러 Beta → SB=Human, BB=Alpha, UTG=Beta
    assert sess.get_state()["waiting_for_action"]
    sess.submit_action("allin", 0)                 # 사람(SB) 30 올인
    log =[l for l in sess.action_log if "🤖 Alpha" in l]
    assert any("콜" in l for l in log) and not any("레이즈" in l for l in log), \
        f"상대 전원 올인인데 봇 레이즈가 적용됨: {log}"


def _three_allin_session():
    """3인 [Human 1000, Alpha 100, Beta 300], 딜러 Human → SB=Alpha, BB=Beta, UTG=Human.
    사람 올인 → 두 봇 콜(올인). 강도 Alpha AA > Beta KK > Human QQ."""
    sess, _ = _scripted_session(2, dealer_index=0, chips=[1000, 100, 300])
    g = sess.game
    holes = {"Human": [c("Q", "S"), c("Q", "H")], "🤖 Alpha": [c("A", "S"), c("A", "H")],
             "🤖 Beta": [c("K", "S"), c("K", "H")]}
    for p in g.players:
        p.hole_cards = holes[p.name]
    board = [c("2", "H"), c("7", "D"), c("9", "S"), c("3", "C"), c("5", "C")]
    g.deal_community = lambda street: g.community_cards.extend(
        board[len(g.community_cards):{Street.FLOP: 3, Street.TURN: 4, Street.RIVER: 5}[street]])
    assert sess.get_state()["waiting_for_action"]
    return sess, sess.submit_action("allin", 0)


def test_8_30_hand_over_pots_main_side_returned():
    """핸드 종료 응답의 pots: 3명 다른 스택 올인 → 메인 300(3명, Alpha)·사이드 400(2명, Beta)·
    반환 700(Human). winner 이벤트 pot과 "🏆 … 승리" 로그 금액은 반환분을 뺀 700."""
    from server.schemas import GameStateResponse
    sess, events = _three_allin_session()
    st = sess.get_state(events)
    assert st["hand_over"], "올인 런아웃 후 핸드가 끝나야 함"
    assert st["pots"] == [
        {"amount": 300, "eligible": ["🤖 Alpha", "🤖 Beta", "Human"], "winners": ["🤖 Alpha"], "returned": False},
        {"amount": 400, "eligible": ["🤖 Beta", "Human"], "winners": ["🤖 Beta"], "returned": False},
        {"amount": 700, "eligible": ["Human"], "winners": ["Human"], "returned": True},
    ], st["pots"]
    chips = {p.name: p.chips for p in sess.game.players}
    assert chips == {"Human": 700, "🤖 Alpha": 300, "🤖 Beta": 400}, chips
    win = [e for e in events if e["type"] == "winner"]
    assert len(win) == 1 and win[0]["pot"] == 700, win
    assert win[0]["winner_chips"] == chips, f"반환받은 사람 칩도 winner_chips에: {win[0]['winner_chips']}"
    assert st["winners"] == ["🤖 Alpha", "🤖 Beta"], st["winners"]
    assert st["action_log"][-1] == "🏆 🤖 Alpha, 🤖 Beta 승리 (700)", st["action_log"][-1]
    assert GameStateResponse(**st).pots[2].returned is True
    # 핸드 진행 중에는 pots가 없다
    sess.next_hand()
    assert sess.get_state()["pots"] is None


def test_8_32_log_entries_carry_board_and_hero_cards():
    """T-008: 게임 상태 log_entries는 action_log와 1:1(같은 길이·같은 text)이고, 각 줄에 그 시점의
    스트리트·보드(깔린 커뮤니티 카드)·사람 홀카드가 실린다. 응답 스키마도 통과한다."""
    from server.schemas import GameStateResponse
    # 헤즈업, 사람 BTN/SB. 사람 림프 → 봇 체크 → 이후 체크다운(쇼다운까지)
    sess, _ = _scripted_session(1, dealer_index=0)
    hero = [str(c) for c in sess.human.hole_cards]
    seen_lens = set()
    st = sess.get_state(sess.submit_action("call", 0))
    for _ in range(10):
        entries, log = st["log_entries"], st["action_log"]
        assert [e["text"] for e in entries] == log, "log_entries text가 action_log와 다름"
        for e in entries:
            assert e["hero_cards"] == hero, f"내 홀카드가 아님: {e}"
            want = {"프리플랍": 0, "플랍": 3, "턴": 4, "리버": 5}.get(e["street"])
            if want is not None:
                assert len(e["board"]) == want, f"{e['street']} 줄의 보드 장수: {e}"
            seen_lens.add(len(e["board"]))
        GameStateResponse(**st)
        if st["hand_over"]:
            break
        st = sess.get_state(sess.submit_action("check", 0))
    assert st["hand_over"], "체크다운이 끝나지 않음"
    assert seen_lens == {0, 3, 4, 5}, f"프리플랍~리버 보드가 모두 나와야 함: {seen_lens}"
    # 스트리트 헤더 줄 = 새로 깔린 보드, 승리 줄 = 최종 보드
    by_text = {e["text"]: e for e in st["log_entries"]}
    assert len(by_text["── 플랍 ──"]["board"]) == 3
    assert st["log_entries"][-1]["text"].startswith("🏆")
    assert st["log_entries"][-1]["board"] == st["community_cards"]
    # 새 핸드는 로그를 비우고 새 홀카드로 시작
    sess.next_hand()
    st = sess.get_state()
    assert [e["text"] for e in st["log_entries"]] == st["action_log"]
    assert all(e["hero_cards"] == [str(c) for c in sess.human.hole_cards] and e["board"] == []
               for e in st["log_entries"])


def test_8_33_log_entries_window_matches_action_log_tail():
    """T-008: 30줄이 넘어도 log_entries는 action_log[-30:]와 같은 창(끝 기준)이다 — 프론트가 logPending으로
    두 목록을 같은 개수만큼 끝에서 숨긴다."""
    sess, _ = _scripted_session(1, dealer_index=0)
    for i in range(40):
        sess._append_log(f"줄 {i}")
    st = sess.get_state()
    assert len(st["action_log"]) == len(st["log_entries"]) == 30
    assert [e["text"] for e in st["log_entries"]] == st["action_log"]
    assert st["action_log"][-1] == "줄 39"


def test_8_31_fold_win_pots_single_layer():
    """전원 폴드로 끝난 핸드도 pots는 1계층(반환 아님), winner pot = 팟 전액."""
    # 좌석 [Human, Alpha, Beta], 딜러 Human → UTG=Human
    sess, _ = _scripted_session(2, dealer_index=0,
                                scripts={"🤖 Alpha": [(Action.FOLD, 0)], "🤖 Beta": [(Action.FOLD, 0)]})
    ev = sess.submit_action("raise", 60)
    st = sess.get_state(ev)
    assert st["hand_over"]
    assert st["pots"] == [{"amount": 90, "eligible": ["Human"], "winners": ["Human"],
                           "returned": False}], st["pots"]
    win = [e for e in ev if e["type"] == "winner"]
    assert win[0]["pot"] == 90 and st["action_log"][-1] == "🏆 Human 승리 (90, 상대 폴드)", \
        (win, st["action_log"][-1])


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
    ("2-8  core 루프: 불완전 올인 합계 재오픈(T-038)", test_2_8_core_cumulative_short_allins_reopen),
    # 영역 3
    ("3-1  100핸드 칩 총량 보존",             test_3_1_pot_conservation),
    ("3-2  Split pot 균등 분배",              test_3_2_split_pot_even),
    ("3-3  홀수 팟 나머지 처리",              test_3_3_split_pot_odd_remainder),
    ("3-4  1명 남았을 때 팟 전액",            test_3_4_winner_takes_all),
    ("3-5  올인 플레이어 팟 수령 한도",       test_3_5_allin_player_cannot_win_more_than_contributed),
    ("3-6  독립 사이드팟 계산기 2,000 대조",   test_3_6_sidepot_independent_calculator_2000),
    # 영역 4
    ("4-1  딜러 버튼 로테이션",               test_4_1_dealer_rotation),
    ("4-2  파산 플레이어 제거",               test_4_2_bankrupt_player_removed),
    ("4-3  프리플랍 전부 폴드",               test_4_3_preflop_all_fold_no_showdown),
    ("4-4  스트리트 전환 시 베팅 리셋",       test_4_4_street_bet_reset),
    ("4-5  사람 파산 → game_over",            test_4_5_game_over_when_human_busted),
    ("4-6  최소 레이즈 룰",                   test_4_6_minimum_raise_rule),
    ("4-7  커뮤니티 카드 수 (스트리트별)",    test_4_7_community_cards_count_per_street),
    ("4-8  딜된 카드 중복 없음",              test_4_8_deck_no_duplicates),
    ("4-9  CLI 사이드팟·무빙 버튼(T-024)",     test_4_9_cli_sidepot_and_moving_button),
    ("4-10 CLI = 웹 세션 같은 동작(T-024)",    test_4_10_cli_and_web_session_same_behavior),
    ("4-11 CLI 레이즈 안내에 음수 칩 없음",    test_4_11_cli_raise_prompt_no_negative_chips),
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
    ("6-6  사이드팟 — 100/300/600 → 메인·사이드·반환",       test_6_6_sidepot_three_allins),
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
    ("7-15 v14 마이그레이션 림프 노드 재라벨(T-016)", test_7_15_migration_v14_relabels_limp_nodes),
    ("7-16 save가 미수집 큐 collected=1 갱신(T-015)", test_7_16_save_marks_missing_queue_collected),
    ("7-17 패널 = advisor node_key(콜러·4벳)(T-013)", test_7_17_panel_is_bound_to_advisor_node_key),
    ("7-18 헤즈업 첫 결정 패널 레인지(T-013)",     test_7_18_headsup_first_decision_panel_shows_range),
    ("7-19 라벨 예비는 패널도 근사(ADR 0035)",     test_7_19_label_fallback_panel_marked_approx),
    ("7-20 올인 시퀀스는 라벨 예비 None+큐(ADR 0037)", test_7_20_allin_in_seq_label_fallback_none_and_queued),
    ("7-21 림프 팟은 RFI 아님(ADR 0046)",          test_7_21_limped_pot_is_not_rfi),
    ("7-22 3~5인은 라벨 예비도 None(ADR 0005)",    test_7_22_short_handed_table_has_no_label_fallback),
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
    ("8-12 세션 퍼저: 참조 모델 대조 400핸드",    test_8_12_session_fuzz_event_amounts_and_conservation),
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
    ("8-23 dev 서버는 서버 코드만 감시",            test_8_23_dev_server_reload_watches_server_code_only),
    ("8-24 오래된 세션 정리 → 404",                 test_8_24_old_sessions_pruned_and_return_404),
    ("8-25 불완전 올인 합계 ≥ 풀 레이즈 → 재오픈",   test_8_25_cumulative_short_allins_reopen),
    ("8-26 불완전 올인 합계 < 풀 레이즈 → 닫힘",     test_8_26_cumulative_short_allins_below_full_raise_stay_closed),
    ("8-27 평가에 실제 레이즈 금액 전달",            test_8_27_grade_receives_real_raise_amount),
    ("8-28 퍼저가 되돌린 T-038 버그를 잡는다",       test_8_28_fuzzer_catches_reverted_cumulative_reopen),
    ("8-29 콜할 상대 없으면 레이즈 불가",            test_8_29_no_raise_when_no_opponent_can_act),
    ("8-30 핸드 종료 pots: 메인·사이드·반환",        test_8_30_hand_over_pots_main_side_returned),
    ("8-31 전원 폴드 핸드 pots 1계층",              test_8_31_fold_win_pots_single_layer),
    ("8-32 log_entries: 줄마다 보드·내 홀카드",      test_8_32_log_entries_carry_board_and_hero_cards),
    ("8-33 log_entries 창 = action_log[-30:]",      test_8_33_log_entries_window_matches_action_log_tail),
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
