from typing import List, Optional, Dict, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum
from .deck import Deck
from .player import Player
from .evaluator import HandEvaluator


class Street(Enum):
    PREFLOP = "프리플랍"
    FLOP    = "플랍"
    TURN    = "턴"
    RIVER   = "리버"
    SHOWDOWN = "쇼다운"


STREETS = [Street.PREFLOP, Street.FLOP, Street.TURN, Street.RIVER]


class Action(Enum):
    FOLD  = "fold"
    CHECK = "check"
    CALL  = "call"
    RAISE = "raise"
    ALL_IN = "allin"


class IllegalActionError(ValueError):
    """현재 상태에서 허용되지 않는 액션(예: 벳을 마주한 체크, 닫힌 액션에서의 레이즈)."""


@dataclass
class ActionResult:
    """execute_action()이 실제로 적용한 결과.

    action   : 실제 적용된 액션(스택을 넘는 RAISE는 ALL_IN, 콜할 금액 없는 CALL은 CHECK)
    moved    : 이번 액션으로 스택에서 팟으로 옮겨간 칩
    to_amount: 액션 후 이번 스트리트 누적 베팅(player.current_bet)
    reopens  : 이미 행동한 플레이어에게 레이즈 기회를 다시 여는가(풀 레이즈 이상일 때만)
    """
    action: "Action"
    moved: int
    to_amount: int
    reopens: bool


@dataclass
class PotShare:
    """팟 한 계층(메인/사이드)의 분배 결과.
    returned=True는 아무도 콜하지 않은 초과 베팅(본인 돈)을 돌려준 계층이다(eligible 1명)."""
    amount: int
    eligible: List[Player]
    winners: List[Player]
    returned: bool = False


@dataclass
class ShowdownResult:
    """showdown()의 결과.

    pot        : 분배한 총액(반환분 포함)
    winners    : 승자(초과 베팅 반환만 받은 사람은 제외, 버튼 왼쪽 순서 아님 — 팟 순서)
    pots       : 계층별 분배(메인 → 사이드 → 반환 순)
    evaluations: 쇼다운에 참여한 사람의 핸드 평가(전원 폴드로 끝나면 빈 dict)
    contested  : 2명 이상이 카드를 겨뤘는가(봇 카드 공개 조건)
    """
    pot: int
    winners: List[Player]
    pots: List[PotShare] = field(default_factory=list)
    evaluations: Dict[str, object] = field(default_factory=dict)
    contested: bool = False


class GameEvent:
    """웹앱 전환 시 이벤트 기반 통신에 활용"""
    def __init__(self, event_type: str, data: dict):
        self.event_type = event_type
        self.data = data

    def __repr__(self):
        return f"GameEvent({self.event_type}, {self.data})"


class TexasHoldem:
    """텍사스 홀덤 룰 엔진 — 웹 세션(server/session.py)·CLI(cli/main.py)·테스트가 같은 경로를 쓴다.

    한 핸드의 흐름(모두 이 클래스의 공개 메서드):
      seat_for_next_hand() → start_hand() → [next_to_act() → validate() → act()]* →
      advance_street() → ... → showdown()
    콜백 방식(CLI·아레나 드라이버)은 play_round()가 위 루프를 대신 돈다.
    """

    def __init__(self, players: List[Player], small_blind: int = 10, big_blind: int = 20):
        if len(players) < 2:
            raise ValueError("최소 2명의 플레이어가 필요합니다.")
        self.players = players
        # 고정 좌석 순서(이름). 파산으로 players에서 빠져도 이 순서는 유지된다 — 무빙 버튼 기준
        self.seat_names: List[str] = [p.name for p in players]
        self.small_blind = small_blind
        self.big_blind = big_blind

        self.deck = Deck()
        self.community_cards: List = []
        self.pot: int = 0
        self.current_street: Street = Street.PREFLOP
        self.dealer_index: int = 0
        # 이번 핸드 버튼 보유자(이름). 다음 핸드의 무빙 버튼 기준(ADR 0036). None = 첫 핸드
        self.button_name: Optional[str] = None
        self.current_bet: int = 0          # 현재 라운드 최고 베팅액
        self.min_raise: int = big_blind
        self.event_log: List[GameEvent] = []
        self.blind_posts: List[tuple] = []  # [(SB 플레이어, 낸 칩), (BB 플레이어, 낸 칩)]

        # 베팅 라운드 상태 (begin_round가 초기화)
        #   order   : 이번 스트리트 행동 순서
        #   acted   : 마지막 풀 레이즈 이후 행동한 플레이어(라운드 종료 판정용)
        #   bet_seen: 각자 마지막 행동 직후의 current_bet(레이즈 권한 판정용, TDA Rule 47)
        #   turn_i  : order에서 다음에 볼 위치
        self.order: List[Player] = []
        self.acted: set = set()
        self.bet_seen: Dict[str, int] = {}
        self.turn_i: int = 0

        # 액션 콜백 (play_round/run_hand용 — CLI·아레나 드라이버)
        self._action_callback: Optional[Callable] = None

    # ──────────────────────────────────────────
    # 핸드 진행
    # ──────────────────────────────────────────

    def seat_for_next_hand(self) -> None:
        """다음 핸드 좌석 정리: 칩 0 이하 플레이어 제거 + 무빙 버튼(ADR 0036).

        버튼 = 고정 좌석 순서(seat_names)에서 직전 버튼 보유자(button_name) 다음의 살아 있는
        사람. SB·BB는 그 뒤 두 명(헤즈업은 버튼 = SB). button_name이 None이면(첫 핸드)
        dealer_index를 그대로 쓴다. 인덱스가 아니라 이름으로 찾으므로 버튼 앞 좌석이 빠져도
        버튼이 한 칸 더 건너뛰지 않는다. 생존자가 2명 미만이면 버튼은 그대로."""
        self.players = [p for p in self.players if p.chips > 0]
        if len(self.players) < 2:
            return
        prev = self.button_name
        if prev is None or prev not in self.seat_names:
            self.dealer_index %= len(self.players)
            return
        index_of = {p.name: i for i, p in enumerate(self.players)}
        start = self.seat_names.index(prev)
        n = len(self.seat_names)
        for k in range(1, n + 1):
            name = self.seat_names[(start + k) % n]
            if name in index_of:
                self.dealer_index = index_of[name]
                return

    def start_hand(self):
        """한 핸드 시작: 리셋 → 블라인드 → 홀카드 → 프리플랍 베팅 라운드 준비.
        버튼은 dealer_index 그대로(이동은 seat_for_next_hand가 한다)."""
        self._reset_hand()
        self.button_name = self.players[self.dealer_index].name
        self._post_blinds()
        self._deal_hole_cards()
        self._emit("hand_started", {
            "players": [p.name for p in self.players],
            "dealer": self.button_name,
        })
        self.begin_round(Street.PREFLOP)

    def begin_round(self, street: Street) -> None:
        """베팅 라운드 준비. 프리플랍은 블라인드 포스팅을 유지하고, 그 뒤 스트리트는
        current_bet·플레이어별 베팅을 0으로. 블라인드 포스팅은 행동이 아니다(acted 비어 있음)."""
        self.current_street = street
        self.min_raise = self.big_blind
        if street != Street.PREFLOP:
            self.current_bet = 0
            for p in self.players:
                p.reset_for_street()
        self.order = self._betting_order(street)
        self.acted = set()
        self.bet_seen = {}
        self.turn_i = 0
        self._emit("street_started", {
            "street": street.value,
            "community_cards": [str(c) for c in self.community_cards],
        })

    def advance_street(self) -> Optional[Street]:
        """베팅이 끝난 뒤 다음 스트리트로: 커뮤니티 카드를 깔고 라운드를 준비해 그 스트리트를
        돌려준다. 1명만 남았거나 리버가 끝났으면 None(다음은 showdown())."""
        if self._count_active() <= 1 or self.current_street not in STREETS[:-1]:
            return None
        street = STREETS[STREETS.index(self.current_street) + 1]
        self.deal_community(street)
        self.begin_round(street)
        return street

    def deal_community(self, street: Street):
        """스트리트에 맞게 커뮤니티 카드 딜 (advance_street가 호출)"""
        if street == Street.FLOP:
            self.community_cards += self.deck.deal(3)
        elif street in (Street.TURN, Street.RIVER):
            self.community_cards += self.deck.deal(1)

    def next_to_act(self) -> Optional[Player]:
        """이번 라운드에서 다음에 행동할 플레이어. 라운드가 끝났으면 None."""
        n = len(self.order)
        if not n:
            return None
        for _ in range(n * 3):
            if self._count_active() <= 1 or self.round_over():
                return None
            p = self.order[self.turn_i % n]
            if p.is_folded or p.is_all_in or (
                    p.name in self.acted and p.current_bet == self.current_bet):
                self.turn_i += 1
                continue
            return p
        return None

    def round_over(self) -> bool:
        """모든 액티브 플레이어가 액션했고 베팅액이 균등하면 True.
        행동 가능한(폴드·올인 아닌) 플레이어가 1명뿐이고 그가 콜할 금액이 없으면 더 물을
        상대가 없으므로 True(런아웃)."""
        active = [p for p in self.players if not p.is_folded and not p.is_all_in]
        if not active:
            return True
        if len(active) == 1 and active[0].current_bet >= self.current_bet:
            return True
        return all(p.name in self.acted and p.current_bet == self.current_bet for p in active)

    def can_raise(self, player: Player) -> bool:
        """이번 라운드에서 player의 레이즈 권한(TDA Rule 47, raise_allowed 참고)."""
        return self.raise_allowed(player, self.bet_seen)

    def validate(self, player: Player, action: Action, amount: int = 0) -> Tuple[Action, int]:
        """(실제로 적용될 액션, 도달 베팅). 상태는 바꾸지 않는다. 불법이면 IllegalActionError."""
        action = self.normalize_action(player, action, amount, self.can_raise(player))
        return action, self.bet_target(player, action, amount)

    def validate_or_fallback(self, player: Player, action: Action, amount: int = 0
                             ) -> Tuple[Action, int, Optional[IllegalActionError]]:
        """validate()와 같되 불법이면 fallback_action으로 대체한다(봇·CLI 콜백용).
        반환: (액션, 도달 베팅, 대체했다면 원래 오류 아니면 None)."""
        try:
            act, amt = self.validate(player, action, amount)
            return act, amt, None
        except IllegalActionError as e:
            act, amt = self.validate(player, self.fallback_action(player, action), 0)
            return act, amt, e

    def act(self, player: Player, action: Action, amount: int = 0) -> ActionResult:
        """player의 액션을 적용하고 라운드 상태(acted/bet_seen/차례)를 갱신한다.
        불법이면 아무것도 바꾸지 않고 IllegalActionError."""
        result = self.execute_action(player, action, amount, self.can_raise(player))
        self.acted.add(player.name)
        self.bet_seen[player.name] = self.current_bet
        if result.reopens:
            # 풀 레이즈만 액션을 다시 연다: 본인만 acted에 남기고 다음 사람부터 다시 돈다.
            # 불완전 올인은 acted를 비우지 않는다 — 레이즈 권한은 bet_seen 누적으로 판정.
            self.acted = {player.name}
            self.turn_i = (self.order.index(player) + 1) % len(self.order)
        else:
            self.turn_i += 1
        return result

    def play_round(self) -> None:
        """콜백(_action_callback)으로 이번 베팅 라운드를 끝까지 진행한다(CLI·run_hand).
        불법 액션은 fallback_action으로 대체된다."""
        while True:
            player = self.next_to_act()
            if player is None:
                return
            action, amount = self._get_player_action(player)
            action, amount, _ = self.validate_or_fallback(player, action, amount)
            self.act(player, action, amount)

    def run_hand(self) -> ShowdownResult:
        """콜백으로 프리플랍부터 쇼다운까지 한 핸드를 진행한다(좌석 정리 포함)."""
        self.seat_for_next_hand()
        self.start_hand()
        self.play_round()
        while self.advance_street() is not None:
            self.play_round()
        return self.showdown()

    # ──────────────────────────────────────────
    # 팟 분배
    # ──────────────────────────────────────────

    def calculate_side_pots(self) -> List[Tuple[int, List[Player]]]:
        """[(금액, eligible 플레이어들)] — total_bet_this_round 오름차순 계층.
        각 계층은 그 금액을 낸(폴드하지 않은) 플레이어끼리만 나눈다. 폴드한 사람의 기여도
        계층별로 들어간다. eligible이 1명인 계층 = 초과 베팅 반환."""
        all_players = self.players
        contenders = [p for p in all_players if not p.is_folded and len(p.hole_cards) >= 2]
        if not contenders:
            return []

        sorted_contenders = sorted(contenders, key=lambda p: p.total_bet_this_round)
        pots = []
        processed = {p.name: 0 for p in all_players}
        prev_level = 0

        for i, c in enumerate(sorted_contenders):
            level = c.total_bet_this_round
            if level <= prev_level:
                continue
            delta = level - prev_level

            pot_amount = 0
            for p in all_players:
                take = min(p.total_bet_this_round - processed[p.name], delta)
                pot_amount += take
                processed[p.name] += take

            eligible = sorted_contenders[i:]
            if pot_amount > 0:
                pots.append((pot_amount, eligible))
            prev_level = level

        remainder = sum(p.total_bet_this_round - processed[p.name] for p in all_players)
        if remainder > 0 and pots:
            pots[-1] = (pots[-1][0] + remainder, pots[-1][1])

        return pots

    def showdown(self) -> ShowdownResult:
        """쇼다운·팟 분배(사이드팟 포함). 버튼은 옮기지 않는다(다음 핸드 seat_for_next_hand).

        - 1명만 남으면 팟 전액.
        - 아니면 calculate_side_pots() 계층마다 eligible 중 최강 핸드가 나눠 갖고, 홀수 칩은
          버튼 왼쪽부터 돌아 처음 만나는 승자에게.
        - 아무도 콜하지 않은 초과 베팅(최대 기여 − 두 번째 기여)은 returned 계층으로 따로
          돌려주고, 그 사람은 반환만으로는 승자가 아니다. eligible 1명이지만 폴드한 사람의
          돈이 든 계층은 반환이 아니라 그 사람이 이긴 팟이다.
        """
        total = self.pot
        contenders = [p for p in self.players if not p.is_folded]

        if len(contenders) == 1:
            winner = contenders[0]
            winner.chips += total
            self.pot = 0
            self._emit("winner", {"winners": [winner.name], "pot": total, "reason": "상대방 폴드"})
            return ShowdownResult(pot=total, winners=[winner],
                                  pots=[PotShare(total, [winner], [winner])])

        contenders = [p for p in contenders if len(p.hole_cards) >= 2]
        if not contenders:
            self.pot = 0
            return ShowdownResult(pot=total, winners=[])

        evaluations = {
            p.name: HandEvaluator.evaluate(p.hole_cards + self.community_cards)
            for p in contenders
        }
        pots: List[PotShare] = []
        winners: List[Player] = []
        layers = self.calculate_side_pots()
        uncalled = 0
        if layers and len(layers[-1][1]) == 1:
            top = layers[-1][1][0]
            others = max((p.total_bet_this_round for p in self.players if p is not top), default=0)
            uncalled = max(0, min(layers[-1][0], top.total_bet_this_round - others))
            if uncalled == layers[-1][0]:
                layers = layers[:-1]
            else:
                layers[-1] = (layers[-1][0] - uncalled, layers[-1][1])
        for amount, eligible in layers:
            best = max(evaluations[p.name] for p in eligible)
            pot_winners = [p for p in eligible if evaluations[p.name] == best]
            share, remainder = divmod(amount, len(pot_winners))
            for w in pot_winners:
                w.chips += share
            if remainder:
                self.order_from_button_left(pot_winners)[0].chips += remainder
            pots.append(PotShare(amount, eligible, pot_winners))
            winners.extend(w for w in pot_winners if w not in winners)
        if uncalled > 0:
            top.chips += uncalled
            pots.append(PotShare(uncalled, [top], [top], returned=True))

        self.pot = 0
        self._emit("showdown", {
            "hands": {name: str(ev) for name, ev in evaluations.items()},
            "winners": [w.name for w in winners],
            "pot": total,
        })
        return ShowdownResult(pot=total, winners=winners, pots=pots,
                              evaluations=evaluations, contested=True)

    # ──────────────────────────────────────────
    # 액션 판정 (ADR 0038, 0048)
    # ──────────────────────────────────────────

    def apply_action(self, player: Player, action: Action, amount: int = 0,
                     raise_allowed: bool = True) -> bool:
        """execute_action()의 bool 래퍼(기존 호출용). 불법 액션이면 아무것도 바꾸지 않고 False.
        라운드 상태(acted/bet_seen/차례)는 갱신하지 않는다 — 라운드 진행은 act()."""
        try:
            self.execute_action(player, action, amount, raise_allowed)
        except IllegalActionError:
            return False
        return True

    def normalize_action(self, player: Player, action: Action, amount: int = 0,
                         raise_allowed: bool = True) -> Action:
        """액션을 검증하고 실제로 적용될 액션을 돌려준다(상태는 바꾸지 않음).

        - 폴드했거나 올인한 플레이어는 행동할 수 없다.
        - 벳을 마주한 CHECK는 불법.
        - 콜할 금액이 없는 CALL은 CHECK로 적용된다.
        - RAISE 금액이 최소 레이즈-투(current_bet + min_raise) 미만이면 그 값으로 올리고,
          그 결과가 스택(chips + current_bet) 이상이면 ALL_IN으로 적용된다.
        - raise_allowed=False(레이즈 권한 없음, raise_allowed() 참고)면 current_bet을
          넘기는 RAISE/ALL_IN은 불법이다. 스택이 콜 이하인 올인(=콜)은 허용.
        불법이면 IllegalActionError.
        """
        if player.is_folded or player.is_all_in:
            raise IllegalActionError("이미 폴드했거나 올인한 플레이어입니다.")
        to_call = self.current_bet - player.current_bet
        max_to = player.chips + player.current_bet

        if action == Action.FOLD:
            return Action.FOLD
        if action == Action.CHECK:
            if to_call > 0:
                raise IllegalActionError(f"체크할 수 없습니다 — 콜 금액 {to_call}이 있습니다.")
            return Action.CHECK
        if action == Action.CALL:
            return Action.CHECK if to_call <= 0 else Action.CALL
        if action == Action.RAISE:
            target = max(amount, self.current_bet + self.min_raise)
            action = Action.ALL_IN if target >= max_to else Action.RAISE
        if action in (Action.RAISE, Action.ALL_IN):
            if not raise_allowed and max_to > self.current_bet:
                raise IllegalActionError(
                    "레이즈할 수 없습니다 — 불완전 올인 뒤이거나 콜할 상대가 없어 콜 또는 폴드만 가능합니다.")
            return action
        raise IllegalActionError(f"알 수 없는 액션: {action}")

    def fallback_action(self, player: Player, action: Action) -> Action:
        """불법 액션을 대신할 안전한 액션(봇·CLI 콜백용).
        공격(RAISE/ALL_IN)이 막히면 의도에 가장 가까운 콜(콜할 금액이 없으면 체크),
        불법 체크는 칩을 더 넣지 않는 폴드. 결과는 항상 합법이다."""
        to_call = self.current_bet - player.current_bet
        if action in (Action.RAISE, Action.ALL_IN):
            return Action.CALL if to_call > 0 else Action.CHECK
        return Action.CHECK if to_call <= 0 else Action.FOLD

    def raise_allowed(self, player: Player, bet_seen: Dict[str, int]) -> bool:
        """레이즈 권한(TDA Rule 47). bet_seen = 이번 라운드에서 각 플레이어가 마지막으로
        행동한 직후의 current_bet. 아직 행동하지 않았거나, 그 뒤로 오른 금액의 합계
        (current_bet − 그 값)가 풀 레이즈(min_raise) 이상이면 레이즈할 수 있다 — 불완전
        올인 여러 개의 합이 풀 레이즈가 되면 재오픈된다.
        나 외에 행동 가능한(폴드·올인 아닌) 플레이어가 없으면 레이즈를 콜할 사람이 없으므로
        레이즈할 수 없다(콜·폴드만)."""
        if not any(p is not player and not p.is_folded and not p.is_all_in for p in self.players):
            return False
        seen = bet_seen.get(player.name)
        return seen is None or self.current_bet - seen >= self.min_raise

    def bet_target(self, player: Player, action: Action, amount: int = 0) -> int:
        """정규화된 액션이 실제로 도달할 이번 스트리트 베팅(to_amount). 상태는 바꾸지 않는다.
        RAISE = max(요청, 최소 레이즈-투), ALL_IN = 스택 전부, CALL = 콜(스택 한도), 그 외 현재 베팅."""
        max_to = player.chips + player.current_bet
        if action == Action.RAISE:
            return min(max(amount, self.current_bet + self.min_raise), max_to)
        if action == Action.ALL_IN:
            return max_to
        if action == Action.CALL:
            return min(self.current_bet, max_to)
        return player.current_bet

    def execute_action(self, player: Player, action: Action, amount: int = 0,
                       raise_allowed: bool = True) -> ActionResult:
        """플레이어 액션을 검증·적용하고 실제 결과를 돌려준다. 불법이면 IllegalActionError.
        라운드 상태(acted/bet_seen/차례)는 act()가 갱신한다.

        레이즈·올인 규칙:
        - 레이즈 증가분(새 current_bet − 이전 current_bet)이 min_raise 이상이면 풀 레이즈:
          min_raise를 그 증가분으로 갱신하고 액션을 다시 연다(reopens=True).
        - 증가분이 0보다 크지만 min_raise 미만인 올인은 current_bet만 올린다(reopens=False,
          min_raise 유지). 이미 행동한 사람의 레이즈 권한은 raise_allowed()가 누적으로 판정.
        - 콜도 못 채우는 올인은 current_bet을 바꾸지 않는다.

        각 "action" 이벤트에는 position/street/to_amount(해당 라운드에서
        플레이어가 도달한 총 베팅액; fold/check는 None)가 함께 기록된다.
        이 필드들이 preflop_action_seq()의 구조화 시퀀스 재구성 기반이 된다.
        """
        action = self.normalize_action(player, action, amount, raise_allowed)
        pos = self.get_positions().get(player.name, "")
        street = self.current_street.value
        moved = 0
        reopens = False

        if action == Action.FOLD:
            player.fold()
            self._emit("action", {
                "player": player.name, "action": "폴드",
                "position": pos, "street": street, "to_amount": None,
            })

        elif action == Action.CHECK:
            self._emit("action", {
                "player": player.name, "action": "체크",
                "position": pos, "street": street, "to_amount": None,
            })

        elif action == Action.CALL:
            moved = player.place_bet(self.current_bet - player.current_bet)
            self.pot += moved
            self._emit("action", {
                "player": player.name, "action": "콜", "amount": moved,
                "position": pos, "street": street, "to_amount": player.current_bet,
            })

        else:  # RAISE / ALL_IN
            prev_bet = self.current_bet
            moved = player.place_bet(self.bet_target(player, action, amount) - player.current_bet)
            self.pot += moved
            raise_by = player.current_bet - prev_bet
            if raise_by > 0:
                self.current_bet = player.current_bet
                if raise_by >= self.min_raise:
                    self.min_raise = raise_by
                    reopens = True
            self._emit("action", {
                "player": player.name,
                "action": "레이즈" if action == Action.RAISE else "올인",
                "amount": moved,
                "position": pos, "street": street, "to_amount": player.current_bet,
            })

        return ActionResult(action=action, moved=moved,
                            to_amount=player.current_bet, reopens=reopens)

    # ──────────────────────────────────────────
    # 내부 메서드
    # ──────────────────────────────────────────

    def _reset_hand(self):
        self.deck.reset()
        self.community_cards = []
        self.pot = 0
        self.current_bet = 0
        self.min_raise = self.big_blind  # 매 핸드 초기화 (이전 핸드 레이즈 값 잔류 방지)
        self.event_log = []
        for p in self.players:
            p.reset_for_hand()

    def _post_blinds(self):
        n = len(self.players)
        if n == 2:
            # 헤즈업: 딜러(BTN/SB)가 스몰 블라인드, 상대가 빅 블라인드
            sb_player = self.players[self.dealer_index]
            bb_player = self.players[(self.dealer_index + 1) % n]
        else:
            active = self._active_players_from_dealer()
            sb_player = active[0]
            bb_player = active[1]

        sb_actual = sb_player.place_bet(self.small_blind)
        self.pot += sb_actual
        bb_actual = bb_player.place_bet(self.big_blind)
        self.pot += bb_actual
        self.current_bet = self.big_blind
        # 포스팅 순서(SB → BB)와 실제로 낸 칩. 웹 세션·CLI가 블라인드 로그를 이 순서로 남긴다.
        self.blind_posts = [(sb_player, sb_actual), (bb_player, bb_actual)]

        self._emit("blinds", {
            "small_blind": {"player": sb_player.name, "amount": sb_actual},
            "big_blind":   {"player": bb_player.name, "amount": bb_actual},
        })

    def _deal_hole_cards(self):
        for _ in range(2):
            for p in self.players:
                p.receive_cards(self.deck.deal(1))
        self._emit("hole_cards_dealt", {
            p.name: [str(c) for c in p.hole_cards] for p in self.players
        })

    def _get_player_action(self, player: Player):
        """액션 콜백 또는 기본 요청"""
        if self._action_callback:
            return self._action_callback(player, self._get_game_state())
        raise NotImplementedError("_action_callback이 설정되지 않았습니다.")

    def _active_players_from_dealer(self) -> List[Player]:
        n = len(self.players)
        return [self.players[(self.dealer_index + 1 + i) % n] for i in range(n)]

    def _betting_order(self, street: Street) -> List[Player]:
        n = len(self.players)
        if street == Street.PREFLOP:
            if n == 2:
                # 헤즈업: BTN/SB(딜러)가 프리플랍 선행동
                start = self.dealer_index
            else:
                # UTG부터 (딜러+3)
                start = (self.dealer_index + 3) % n
        else:
            # SB부터 (딜러+1) — 헤즈업은 딜러+1 = BB
            start = (self.dealer_index + 1) % n
        return [self.players[(start + i) % n] for i in range(n)]

    def _count_active(self) -> int:
        return sum(1 for p in self.players if not p.is_folded)

    def order_from_button_left(self, players: List[Player]) -> List[Player]:
        """players를 버튼 왼쪽(SB 자리)부터 시계 방향 순서로 정렬(홀수 칩 수령 순서)."""
        n = len(self.players)
        idx = {p.name: i for i, p in enumerate(self.players)}
        return sorted(players, key=lambda p: (idx[p.name] - self.dealer_index - 1) % n)

    def _emit(self, event_type: str, data: dict):
        event = GameEvent(event_type, data)
        self.event_log.append(event)

    def get_positions(self) -> dict:
        """플레이어별 포지션 반환 (이름 → 포지션 레이블)"""
        n = len(self.players)
        labels_by_count = {
            2: ["BTN/SB", "BB"],
            3: ["BTN", "SB", "BB"],
            4: ["BTN", "SB", "BB", "UTG"],
            5: ["BTN", "SB", "BB", "UTG", "CO"],
            6: ["BTN", "SB", "BB", "UTG", "HJ", "CO"],
            7: ["BTN", "SB", "BB", "UTG", "UTG+1", "HJ", "CO"],
        }
        labels = labels_by_count.get(n, ["BTN", "SB", "BB"] + [f"P{i}" for i in range(n - 3)])
        positions = {}
        for i, label in enumerate(labels):
            idx = (self.dealer_index + i) % n
            positions[self.players[idx].name] = label
        return positions

    # 한글 액션 라벨 → 구조화 액션 키
    _ACTION_KR_TO_EN = {
        "폴드": "fold", "체크": "check", "콜": "call",
        "레이즈": "raise", "올인": "allin",
    }

    def preflop_action_seq(self) -> List[dict]:
        """프리플랍 자발적 액션(블라인드 제외) 구조화 시퀀스.

        반환: [{"position": str, "action": "fold"|"call"|"raise"|"allin"|"check",
                "amount_bb": float|None}] (행동 순서대로).

        - position은 get_positions() 라벨(헤즈업은 "BTN/SB" 원본 유지 — advisor가
          조회 시점에 6-max "SB"로 국소 매핑).
        - amount_bb = 해당 라운드 도달 총 베팅액 / big_blind (call/raise/allin).
          fold/check는 None.
        - 블라인드(SB/BB 강제 베팅)는 "blinds" 이벤트라 "action" 필터에서 자연히
          제외됨 → GTO Wizard preflop_actions 포맷(자발적 액션만)과 동일.
        - "프리플랍" = current_street가 PREFLOP인 동안 발행된 action 이벤트.
          event_log는 핸드 시작 시 리셋되고 스트리트 정보가 이벤트에 박혀 있으므로
          플랍 이후 액션은 street 필터로 걸러진다.
        """
        seq: List[dict] = []
        for event in self.event_log:
            if event.event_type != "action":
                continue
            data = event.data
            if data.get("street") != Street.PREFLOP.value:
                continue
            act = self._ACTION_KR_TO_EN.get(data.get("action"))
            if act is None:
                continue
            to_amount = data.get("to_amount")
            amount_bb = (
                to_amount / self.big_blind
                if (to_amount is not None and self.big_blind)
                else None
            )
            seq.append({
                "position": data.get("position", ""),
                "action": act,
                "amount_bb": amount_bb,
            })
        return seq

    def _get_game_state(self) -> dict:
        positions = self.get_positions()
        return {
            "street": self.current_street.value,
            "pot": self.pot,
            "current_bet": self.current_bet,
            "min_raise": self.min_raise,
            "big_blind": self.big_blind,
            "community_cards": [str(c) for c in self.community_cards],
            "positions": positions,
            # 프리플랍 구조화 액션 시퀀스 (advisor가 콜/순서/참여인원 판별에 사용)
            "preflop_seq": self.preflop_action_seq(),
            "players": [
                {
                    "name": p.name,
                    "chips": p.chips,
                    "current_bet": p.current_bet,
                    "is_folded": p.is_folded,
                    "is_all_in": p.is_all_in,
                    "is_human": p.is_human,
                    "position": positions.get(p.name, ""),
                }
                for p in self.players
            ],
        }
