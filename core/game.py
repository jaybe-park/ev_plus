from typing import List, Optional, Dict, Callable
from dataclasses import dataclass
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


class GameEvent:
    """웹앱 전환 시 이벤트 기반 통신에 활용"""
    def __init__(self, event_type: str, data: dict):
        self.event_type = event_type
        self.data = data

    def __repr__(self):
        return f"GameEvent({self.event_type}, {self.data})"


class TexasHoldem:
    def __init__(self, players: List[Player], small_blind: int = 10, big_blind: int = 20):
        if len(players) < 2:
            raise ValueError("최소 2명의 플레이어가 필요합니다.")
        self.players = players
        self.small_blind = small_blind
        self.big_blind = big_blind

        self.deck = Deck()
        self.community_cards: List = []
        self.pot: int = 0
        self.side_pots: List[Dict] = []
        self.current_street: Street = Street.PREFLOP
        self.dealer_index: int = 0
        self.current_bet: int = 0          # 현재 라운드 최고 베팅액
        self.min_raise: int = big_blind
        self.event_log: List[GameEvent] = []

        # 액션 콜백 (웹앱 전환 시 override)
        self._action_callback: Optional[Callable] = None

    # ──────────────────────────────────────────
    # 공개 API
    # ──────────────────────────────────────────

    def start_hand(self):
        """한 핸드(게임) 시작"""
        self._reset_hand()
        self._post_blinds()
        self._deal_hole_cards()
        self._emit("hand_started", {
            "players": [p.name for p in self.players],
            "dealer": self.players[self.dealer_index].name,
        })

    def run_street(self, street: Street):
        """특정 스트리트 진행"""
        self.current_street = street
        self.min_raise = self.big_blind

        if street == Street.PREFLOP:
            # 블라인드가 이미 포스팅된 상태 유지 — current_bet, player.current_bet 리셋 안 함
            pass
        else:
            self.current_bet = 0
            for p in self.players:
                p.reset_for_street()

        # 커뮤니티 카드 딜은 외부(CLI/웹)에서 deal_community()를 직접 호출하거나
        # run_hand()를 통해 진행. run_street()는 딜하지 않음.
        self._emit("street_started", {
            "street": street.value,
            "community_cards": [str(c) for c in self.community_cards],
        })
        self._betting_round(street)

    def deal_community(self, street: Street):
        """스트리트에 맞게 커뮤니티 카드 딜 (외부에서 직접 호출)"""
        if street == Street.FLOP:
            self.community_cards += self.deck.deal(3)
        elif street in (Street.TURN, Street.RIVER):
            self.community_cards += self.deck.deal(1)

    def run_hand(self) -> Optional[List[Player]]:
        """프리플랍부터 쇼다운까지 한 핸드 완전 진행. 승자 리스트 반환."""
        self.start_hand()

        streets = [Street.PREFLOP, Street.FLOP, Street.TURN, Street.RIVER]
        for street in streets:
            if self._count_active() <= 1:
                break
            self.deal_community(street)
            self.run_street(street)

        return self.showdown()

    def showdown(self) -> List[Player]:
        """쇼다운 처리 및 팟 분배. 승자 리스트 반환."""
        contenders = [p for p in self.players if not p.is_folded]

        if len(contenders) == 1:
            winner = contenders[0]
            winner.chips += self.pot
            self._emit("winner", {
                "winners": [winner.name],
                "pot": self.pot,
                "reason": "상대방 폴드",
            })
            self.pot = 0
            self._advance_dealer()
            return [winner]

        # 핸드 평가
        evaluations = {}
        for p in contenders:
            all_cards = p.hole_cards + self.community_cards
            evaluations[p.name] = HandEvaluator.evaluate(all_cards)

        best_result = max(evaluations.values())
        winners = [p for p in contenders if evaluations[p.name] == best_result]

        # 팟 분배 (동률 시 균등 분배)
        share = self.pot // len(winners)
        remainder = self.pot % len(winners)
        for w in winners:
            w.chips += share
        if remainder and winners:
            winners[0].chips += remainder  # 나머지는 딜러 왼쪽 플레이어에게

        showdown_info = {p.name: str(evaluations[p.name]) for p in contenders}
        self._emit("showdown", {
            "hands": showdown_info,
            "winners": [w.name for w in winners],
            "pot": self.pot,
        })
        self.pot = 0
        self._advance_dealer()
        return winners

    def apply_action(self, player: Player, action: Action, amount: int = 0,
                     raise_allowed: bool = True) -> bool:
        """execute_action()의 bool 래퍼(CLI·기존 호출용). 불법 액션이면 아무것도 바꾸지 않고 False."""
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
        - raise_allowed=False(불완전 올인만 마주해 액션이 닫힌 플레이어)면 current_bet을
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
                    "레이즈할 수 없습니다 — 불완전 올인 뒤에는 콜 또는 폴드만 가능합니다.")
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

    def execute_action(self, player: Player, action: Action, amount: int = 0,
                       raise_allowed: bool = True) -> ActionResult:
        """플레이어 액션을 검증·적용하고 실제 결과를 돌려준다. 불법이면 IllegalActionError.

        레이즈·올인 규칙(표준 불완전 레이즈 규칙):
        - 레이즈 증가분(새 current_bet − 이전 current_bet)이 min_raise 이상이면 풀 레이즈:
          min_raise를 그 증가분으로 갱신하고 액션을 다시 연다(reopens=True).
        - 증가분이 0보다 크지만 min_raise 미만인 올인은 current_bet만 올린다. 이미 행동한
          플레이어는 콜/폴드만 할 수 있다(reopens=False, min_raise 유지).
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
            if action == Action.RAISE:
                target = max(amount, prev_bet + self.min_raise)
                moved = player.place_bet(target - player.current_bet)
            else:
                moved = player.place_bet(player.chips)
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

    @staticmethod
    def raise_allowed(player: Player, acted: set) -> bool:
        """마지막 풀 레이즈 이후 아직 행동하지 않은 플레이어만 레이즈할 수 있다."""
        return player.name not in acted

    def _is_round_over(self, acted: set) -> bool:
        """모든 액티브 플레이어가 액션했고 베팅액이 균등하면 True"""
        active = [p for p in self.players if not p.is_folded and not p.is_all_in]
        if not active:
            return True
        return all(p.name in acted and p.current_bet == self.current_bet for p in active)

    def _betting_round(self, street: Street):
        """베팅 라운드 진행"""
        order = self._betting_order(street)
        n = len(order)
        # acted = 마지막 풀 레이즈 이후 행동한 플레이어. 여기 없는 사람만 레이즈할 수 있다.
        # 블라인드 포스팅은 행동이 아니다(SB도 자기 차례에 레이즈 가능, BB는 옵션 보유).
        acted: set = set()

        i = 0
        while True:
            if self._count_active() <= 1:
                break
            if self._is_round_over(acted):
                break

            player = order[i % n]
            i += 1

            if player.is_folded or player.is_all_in:
                continue
            if player.name in acted and player.current_bet == self.current_bet:
                continue

            action, amount = self._get_player_action(player)
            can_raise = self.raise_allowed(player, acted)
            try:
                result = self.execute_action(player, action, amount, raise_allowed=can_raise)
            except IllegalActionError:
                result = self.execute_action(player, self.fallback_action(player, action), 0,
                                             raise_allowed=can_raise)
            acted.add(player.name)

            # 풀 레이즈(재오픈) 시: 본인만 acted에 남기고 다음 플레이어부터 다시 순회.
            # 불완전 올인은 재오픈하지 않는다 — 이미 행동한 사람은 콜/폴드만.
            if result.reopens:
                acted = {player.name}
                i = (order.index(player) + 1) % n

    def _get_player_action(self, player: Player):
        """액션 콜백 또는 기본 요청"""
        if self._action_callback:
            return self._action_callback(player, self._get_game_state())
        # 콜백 없으면 외부(CLI/웹)에서 override
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
            # SB부터 (딜러+1)
            start = (self.dealer_index + 1) % n
        return [self.players[(start + i) % n] for i in range(n)]

    def _count_active(self) -> int:
        return sum(1 for p in self.players if not p.is_folded)

    def _advance_dealer(self):
        self.dealer_index = (self.dealer_index + 1) % len(self.players)

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
