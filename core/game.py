from typing import List, Optional, Dict, Callable
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

    def apply_action(self, player: Player, action: Action, amount: int = 0) -> bool:
        """
        플레이어 액션 적용. 유효하면 True 반환.
        웹앱 전환 시 이 메서드를 HTTP endpoint에서 호출하면 됩니다.
        """
        if action == Action.FOLD:
            player.fold()
            self._emit("action", {"player": player.name, "action": "폴드"})

        elif action == Action.CHECK:
            if self.current_bet > player.current_bet:
                return False  # 체크 불가
            self._emit("action", {"player": player.name, "action": "체크"})

        elif action == Action.CALL:
            call_amount = self.current_bet - player.current_bet
            actual = player.place_bet(call_amount)
            self.pot += actual
            self._emit("action", {
                "player": player.name, "action": "콜", "amount": actual,
            })

        elif action == Action.RAISE:
            if amount < self.current_bet + self.min_raise:
                amount = self.current_bet + self.min_raise  # 최소 레이즈로 보정
            call_portion = self.current_bet - player.current_bet
            raise_portion = amount - self.current_bet
            total = call_portion + raise_portion
            actual = player.place_bet(total)
            self.pot += actual
            self.min_raise = raise_portion
            self.current_bet = amount
            self._emit("action", {
                "player": player.name, "action": "레이즈", "amount": amount,
            })

        elif action == Action.ALL_IN:
            actual = player.place_bet(player.chips + player.current_bet)
            self.pot += actual
            if player.current_bet > self.current_bet:
                self.current_bet = player.current_bet
            self._emit("action", {
                "player": player.name, "action": "올인", "amount": actual,
            })

        return True

    # ──────────────────────────────────────────
    # 내부 메서드
    # ──────────────────────────────────────────

    def _reset_hand(self):
        self.deck.reset()
        self.community_cards = []
        self.pot = 0
        self.current_bet = 0
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

        # 프리플랍: SB는 포스팅으로 acted 처리, BB는 레이즈 옵션이 있으므로 제외
        acted: set = set()
        if street == Street.PREFLOP:
            positions = self.get_positions()
            for p in self.players:
                pos = positions.get(p.name, "")
                # SB/BTN/SB만 acted에 포함 (BB는 아직 옵션 있음)
                if pos in ("SB", "BTN/SB") and p.current_bet > 0:
                    acted.add(p.name)

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
            self.apply_action(player, action, amount)
            acted.add(player.name)

            # 레이즈/올인 시: 본인만 acted에 남기고 다음 플레이어부터 다시 순회
            if action in (Action.RAISE, Action.ALL_IN):
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
            6: ["BTN", "SB", "BB", "UTG", "MP", "CO"],
            7: ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "CO"],
        }
        labels = labels_by_count.get(n, ["BTN", "SB", "BB"] + [f"P{i}" for i in range(n - 3)])
        positions = {}
        for i, label in enumerate(labels):
            idx = (self.dealer_index + i) % n
            positions[self.players[idx].name] = label
        return positions

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
