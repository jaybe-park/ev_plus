import random
from enum import Enum
from typing import Tuple, Optional
from core.game import Action
from core.player import Player
from gto.advisor import GTOAdvisor

_gto_advisor = GTOAdvisor()

# 난이도별 GTO 준수율
GTO_COMPLIANCE = {
    "easy":   0.40,
    "medium": 0.70,
    "hard":   0.95,
}


class BotDifficulty(Enum):
    EASY   = "easy"
    MEDIUM = "medium"
    HARD   = "hard"


class PokerBot:

    def __init__(self, player: Player, difficulty: BotDifficulty = BotDifficulty.MEDIUM):
        self.player = player
        self.difficulty = difficulty

    def decide_action(self, game_state: dict) -> Tuple[Action, int]:
        # 프리플랍: GTO 레인지 우선 적용
        if game_state.get("street") == "프리플랍":
            gto_result = self._try_gto_action(game_state)
            if gto_result is not None:
                return gto_result

        hand_strength = self._evaluate_hand_strength(game_state)
        if self.difficulty == BotDifficulty.EASY:
            return self._easy_strategy(game_state, hand_strength)
        elif self.difficulty == BotDifficulty.MEDIUM:
            return self._medium_strategy(game_state, hand_strength)
        else:
            return self._hard_strategy(game_state, hand_strength)

    def _try_gto_action(self, game_state: dict) -> Optional[Tuple[Action, int]]:
        """GTO 레인지 기반 액션. 데이터 없으면 None 반환."""
        compliance = GTO_COMPLIANCE.get(self.difficulty.value, 0.7)
        positions = game_state.get("positions", {})
        my_pos = positions.get(self.player.name, "")
        big_blind = game_state.get("big_blind", 20)

        gto_result = _gto_advisor.get_bot_action(
            self.player.hole_cards, my_pos, positions,
            game_state, big_blind, compliance
        )
        if gto_result is None:
            # GTO 데이터 없는 상황 (vs_4bet 등)
            # 4벳+ 이상이면 폴드 또는 올인만 허용
            raise_count = self._count_raises(game_state)
            if raise_count >= 3:
                return self._four_bet_plus_response(game_state)
            return None

        action_str = gto_result["action"]
        raise_count = gto_result.get("raise_count", 0)
        raise_size = gto_result.get("raise_size", "3x")
        call_amount = game_state["current_bet"] - self.player.current_bet

        if action_str == "fold":
            if call_amount == 0:
                return Action.CHECK, 0
            return Action.FOLD, 0

        elif action_str == "call":
            if call_amount == 0:
                return Action.CHECK, 0
            return Action.CALL, call_amount

        elif action_str == "raise":
            return self._preflop_raise(game_state, raise_count, raise_size)

        return None

    def _preflop_raise(self, state: dict, raise_count: int, raise_size: str) -> Tuple[Action, int]:
        """
        프리플랍 레이즈 사이즈 계산.
        - RFI (raise_count=0): 2.5bb 오픈
        - 3벳 (raise_count=1): 오픈의 3x
        - 4벳 (raise_count=2): 3벳의 2.5x (또는 올인)
        """
        current_bet = state["current_bet"]
        big_blind = state.get("big_blind", 20)
        min_raise = state.get("min_raise", big_blind)
        max_chips = self.player.chips + self.player.current_bet

        if raise_count == 0:
            # RFI: 2.5bb
            raise_to = int(big_blind * 2.5)
        elif raise_count == 1:
            # 3벳: 오픈의 3x (일반적인 3벳 사이즈)
            raise_to = int(current_bet * 3)
        else:
            # 4벳: 3벳의 2.5x, 스택 작으면 올인
            raise_to = int(current_bet * 2.5)
            if raise_to >= max_chips * 0.7:
                return Action.ALL_IN, 0

        # 최솟값 보정
        raise_to = max(raise_to, current_bet + min_raise)
        raise_to = min(raise_to, max_chips)

        if raise_to >= max_chips:
            return Action.ALL_IN, 0

        return Action.RAISE, raise_to

    def _four_bet_plus_response(self, state: dict) -> Tuple[Action, int]:
        """4벳+ 상황 (GTO 데이터 없음): 강한 패만 올인, 나머지 폴드"""
        call_amount = state["current_bet"] - self.player.current_bet
        hand_strength = self._evaluate_hand_strength(state)

        # 5% 확률로 올인 블러프, 아니면 강한 패만 올인
        if hand_strength > 0.85 or (hand_strength > 0.75 and random.random() < 0.3):
            return Action.ALL_IN, 0

        if call_amount == 0:
            return Action.CHECK, 0
        return Action.FOLD, 0

    def _count_raises(self, game_state: dict) -> int:
        """action_log에서 프리플랍 레이즈 횟수"""
        count = 0
        for entry in game_state.get("action_log", []):
            if "──" in entry:
                break
            if "레이즈" in entry:
                count += 1
        return count

    # ──────────────────────────────────────────
    # 포스트플랍 전략 (기존 유지)
    # ──────────────────────────────────────────

    def _easy_strategy(self, state: dict, strength: float) -> Tuple[Action, int]:
        call_amount = state["current_bet"] - self.player.current_bet
        if strength > 0.7:
            return self._raise_action(state, pot_frac=0.5)
        elif strength > 0.4:
            if call_amount == 0:
                return Action.CHECK, 0
            return Action.CALL, call_amount
        else:
            if call_amount == 0:
                return Action.CHECK, 0
            if random.random() < 0.25:
                return Action.CALL, call_amount
            return Action.FOLD, 0

    def _medium_strategy(self, state: dict, strength: float) -> Tuple[Action, int]:
        call_amount = state["current_bet"] - self.player.current_bet
        pot = state["pot"]
        pot_odds = call_amount / (pot + call_amount) if (pot + call_amount) > 0 else 0

        if strength > 0.75:
            return self._raise_action(state, pot_frac=random.uniform(0.5, 0.8))
        elif strength > pot_odds + 0.1:
            if call_amount == 0:
                if strength > 0.55:
                    return self._raise_action(state, pot_frac=0.5)
                return Action.CHECK, 0
            return Action.CALL, call_amount
        elif strength > pot_odds and random.random() < 0.2:
            return self._raise_action(state, pot_frac=0.5)
        else:
            if call_amount == 0:
                return Action.CHECK, 0
            return Action.FOLD, 0

    def _hard_strategy(self, state: dict, strength: float) -> Tuple[Action, int]:
        call_amount = state["current_bet"] - self.player.current_bet
        pot = state["pot"]
        street = state["street"]
        pot_odds = call_amount / (pot + call_amount) if (pot + call_amount) > 0 else 0
        bluff_freq = {"플랍": 0.25, "턴": 0.20, "리버": 0.12}.get(street, 0.15)

        if strength > 0.8:
            return self._raise_action(state, pot_frac=random.uniform(0.6, 1.0))
        elif strength > 0.6:
            if call_amount == 0:
                return self._raise_action(state, pot_frac=random.uniform(0.4, 0.7))
            if strength > pot_odds + 0.15:
                return Action.CALL, call_amount
            return Action.FOLD, 0
        elif strength > 0.4:
            if call_amount == 0:
                if random.random() < 0.35:
                    return self._raise_action(state, pot_frac=0.4)
                return Action.CHECK, 0
            if strength > pot_odds:
                return Action.CALL, call_amount
            return Action.FOLD, 0
        else:
            if call_amount == 0 and random.random() < bluff_freq:
                return self._raise_action(state, pot_frac=random.uniform(0.4, 0.7))
            if call_amount > 0 and random.random() < bluff_freq * 0.4:
                return Action.CALL, call_amount
            if call_amount == 0:
                return Action.CHECK, 0
            return Action.FOLD, 0

    # ──────────────────────────────────────────
    # 핸드 강도 평가
    # ──────────────────────────────────────────

    def _evaluate_hand_strength(self, state: dict) -> float:
        hole_cards = self.player.hole_cards
        community = state.get("community_cards", [])

        if not hole_cards:
            return 0.5

        if not community:
            return self._preflop_strength(hole_cards)

        try:
            from core.evaluator import HandEvaluator
            comm_cards = self._parse_community_cards(state["community_cards"])
            all_cards = hole_cards + comm_cards
            result = HandEvaluator.evaluate(all_cards)
            # 핸드 랭크(1~10) 기반이지만 키커 정보도 반영
            rank_val = result.hand_rank.rank_value
            # 투페어 이상은 tiebreaker 최댓값으로 세분화
            if rank_val >= 2 and result.tiebreakers:
                sub = min(result.tiebreakers[0] / 14.0, 1.0) * 0.09
                return min(rank_val / 10.0 + sub, 1.0)
            return rank_val / 10.0
        except Exception:
            return self._preflop_strength(hole_cards)

    def _preflop_strength(self, hole_cards) -> float:
        r1 = hole_cards[0].rank.rank_value
        r2 = hole_cards[1].rank.rank_value
        suited = hole_cards[0].suit == hole_cards[1].suit
        paired = r1 == r2
        high, low = max(r1, r2), min(r1, r2)

        score = (high + low) / 28.0
        if paired: score += 0.2
        if suited:  score += 0.05
        if abs(r1 - r2) <= 2: score += 0.03
        return min(score, 1.0)

    def _parse_community_cards(self, card_strings):
        from core.card import Card, Suit, Rank as CardRank
        suit_map = {"♠": Suit.SPADES, "♥": Suit.HEARTS, "♦": Suit.DIAMONDS, "♣": Suit.CLUBS}
        rank_map = {r.symbol: r for r in CardRank}
        cards = []
        for s in card_strings:
            rank_sym, suit_sym = s[:-1], s[-1]
            if rank_sym in rank_map and suit_sym in suit_map:
                cards.append(Card(rank_map[rank_sym], suit_map[suit_sym]))
        return cards

    def _raise_action(self, state: dict, pot_frac: float = 0.5) -> Tuple[Action, int]:
        """포스트플랍 레이즈: 팟 비율 기준"""
        pot = state["pot"]
        current_bet = state["current_bet"]
        min_raise = state.get("min_raise", state.get("big_blind", 20))
        max_chips = self.player.chips + self.player.current_bet

        bet_size = max(int(pot * pot_frac), min_raise)
        raise_to = current_bet + bet_size
        raise_to = min(raise_to, max_chips)

        if raise_to >= max_chips:
            return Action.ALL_IN, 0
        return Action.RAISE, raise_to
