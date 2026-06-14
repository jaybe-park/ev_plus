import random
from enum import Enum
from typing import Tuple, List, Optional
from core.game import Action
from core.player import Player
from core.card import Rank
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
    """
    Texas Hold'em AI 봇
    - EASY:   랜덤 + 기본 핸드 강도 판단
    - MEDIUM: 핸드 강도 + 팟 오즈 계산
    - HARD:   포지션 + 블러핑 + 핸드 레인지
    """

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

        gto_action_str = _gto_advisor.get_bot_action(
            self.player.hole_cards, my_pos, positions,
            game_state, big_blind, compliance
        )
        if gto_action_str is None:
            return None

        call_amount = game_state["current_bet"] - self.player.current_bet

        if gto_action_str == "fold":
            if call_amount == 0:
                return Action.CHECK, 0  # 폴드 대신 체크 (공짜면)
            return Action.FOLD, 0
        elif gto_action_str == "call":
            if call_amount == 0:
                return Action.CHECK, 0
            return Action.CALL, call_amount
        elif gto_action_str == "raise":
            return self._raise_action(game_state, multiplier=2.5)
        return None

    # ──────────────────────────────────────────
    # 전략
    # ──────────────────────────────────────────

    def _easy_strategy(self, state: dict, strength: float) -> Tuple[Action, int]:
        """단순 확률 기반 전략"""
        call_amount = state["current_bet"] - self.player.current_bet

        if strength > 0.7:
            return self._raise_action(state, multiplier=2)
        elif strength > 0.4:
            if call_amount == 0:
                return Action.CHECK, 0
            return Action.CALL, call_amount
        else:
            if call_amount == 0:
                return Action.CHECK, 0
            if random.random() < 0.3:  # 30% 확률로 블러프 콜
                return Action.CALL, call_amount
            return Action.FOLD, 0

    def _medium_strategy(self, state: dict, strength: float) -> Tuple[Action, int]:
        """팟 오즈 고려 전략"""
        call_amount = state["current_bet"] - self.player.current_bet
        pot = state["pot"]

        pot_odds = call_amount / (pot + call_amount) if (pot + call_amount) > 0 else 0

        if strength > 0.75:
            return self._raise_action(state, multiplier=random.uniform(2, 3))
        elif strength > pot_odds + 0.1:
            if call_amount == 0:
                # 베팅 기회
                if strength > 0.55:
                    return self._raise_action(state, multiplier=1.5)
                return Action.CHECK, 0
            return Action.CALL, call_amount
        elif strength > pot_odds and random.random() < 0.2:  # 세미 블러프
            return self._raise_action(state, multiplier=1.5)
        else:
            if call_amount == 0:
                return Action.CHECK, 0
            return Action.FOLD, 0

    def _hard_strategy(self, state: dict, strength: float) -> Tuple[Action, int]:
        """포지션 + 블러핑 + 다양한 베팅 사이즈"""
        call_amount = state["current_bet"] - self.player.current_bet
        pot = state["pot"]
        street = state["street"]

        pot_odds = call_amount / (pot + call_amount) if (pot + call_amount) > 0 else 0
        bluff_freq = self._bluff_frequency(street)

        if strength > 0.8:
            # 밸류 베팅: 다양한 사이즈
            multiplier = random.uniform(2.5, 4)
            return self._raise_action(state, multiplier=multiplier)

        elif strength > 0.6:
            if call_amount == 0:
                return self._raise_action(state, multiplier=random.uniform(1.5, 2.5))
            if strength > pot_odds + 0.15:
                return Action.CALL, call_amount
            return Action.FOLD, 0

        elif strength > 0.4:
            if call_amount == 0:
                # 세미 블러프 베팅
                if random.random() < 0.4:
                    return self._raise_action(state, multiplier=1.5)
                return Action.CHECK, 0
            if strength > pot_odds:
                return Action.CALL, call_amount
            return Action.FOLD, 0

        else:
            # 블러프
            if call_amount == 0 and random.random() < bluff_freq:
                return self._raise_action(state, multiplier=random.uniform(1.5, 2.5))
            if call_amount > 0 and random.random() < bluff_freq * 0.5:
                return Action.CALL, call_amount
            if call_amount == 0:
                return Action.CHECK, 0
            return Action.FOLD, 0

    # ──────────────────────────────────────────
    # 핸드 강도 평가 (0.0 ~ 1.0)
    # ──────────────────────────────────────────

    def _evaluate_hand_strength(self, state: dict) -> float:
        """홀 카드 + 커뮤니티 카드 기반 핸드 강도 추정"""
        hole_cards = self.player.hole_cards
        community = state.get("community_cards", [])

        if not hole_cards:
            return 0.5

        # 프리플랍: 홀 카드만으로 평가
        if not community:
            return self._preflop_strength(hole_cards)

        # 포스트플랍: 간단한 핸드 강도 계산
        from core.evaluator import HandEvaluator, HandRank
        from core.card import Card, Suit, Rank as CardRank

        try:
            # community_cards가 문자열 리스트일 경우 Card 객체로 변환
            comm_cards = self._parse_community_cards(state["community_cards"])
            all_cards = hole_cards + comm_cards
            result = HandEvaluator.evaluate(all_cards)
            rank_value = result.hand_rank.rank_value  # 1~10
            return min(rank_value / 10.0, 1.0)
        except Exception:
            return self._preflop_strength(hole_cards)

    def _preflop_strength(self, hole_cards) -> float:
        """프리플랍 홀 카드 강도 (0~1)"""
        if len(hole_cards) < 2:
            return 0.3

        r1 = hole_cards[0].rank.rank_value
        r2 = hole_cards[1].rank.rank_value
        suited = hole_cards[0].suit == hole_cards[1].suit
        paired = r1 == r2

        high = max(r1, r2)
        low  = min(r1, r2)

        score = (high + low) / 28.0  # 최대 14+14=28

        if paired:
            score += 0.2
        if suited:
            score += 0.05
        if abs(r1 - r2) <= 2:  # 커넥터
            score += 0.03

        return min(score, 1.0)

    def _parse_community_cards(self, card_strings: List[str]):
        """문자열 리스트를 Card 객체로 변환"""
        from core.card import Card, Suit, Rank as CardRank

        suit_map = {"♠": Suit.SPADES, "♥": Suit.HEARTS,
                    "♦": Suit.DIAMONDS, "♣": Suit.CLUBS}
        rank_map = {r.symbol: r for r in CardRank}

        cards = []
        for s in card_strings:
            rank_sym = s[:-1]
            suit_sym = s[-1]
            if rank_sym in rank_map and suit_sym in suit_map:
                cards.append(Card(rank_map[rank_sym], suit_map[suit_sym]))
        return cards

    def _bluff_frequency(self, street: str) -> float:
        """스트리트별 블러프 빈도"""
        return {"프리플랍": 0.15, "플랍": 0.25, "턴": 0.20, "리버": 0.15}.get(street, 0.15)

    def _raise_action(self, state: dict, multiplier: float) -> Tuple[Action, int]:
        """레이즈 액션 계산"""
        pot = state["pot"]
        min_raise = state.get("min_raise", 20)
        current_bet = state["current_bet"]

        raise_to = int(current_bet + max(pot * multiplier * 0.33, min_raise))
        raise_to = min(raise_to, self.player.chips + self.player.current_bet)

        if raise_to >= self.player.chips + self.player.current_bet:
            return Action.ALL_IN, 0

        return Action.RAISE, raise_to
