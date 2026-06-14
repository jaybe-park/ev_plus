from itertools import combinations
from typing import List, Tuple
from enum import Enum
from .card import Card, Rank


class HandRank(Enum):
    HIGH_CARD       = (1, "하이 카드")
    ONE_PAIR        = (2, "원 페어")
    TWO_PAIR        = (3, "투 페어")
    THREE_OF_A_KIND = (4, "트리플")
    STRAIGHT        = (5, "스트레이트")
    FLUSH           = (6, "플러시")
    FULL_HOUSE      = (7, "풀 하우스")
    FOUR_OF_A_KIND  = (8, "포카드")
    STRAIGHT_FLUSH  = (9, "스트레이트 플러시")
    ROYAL_FLUSH     = (10, "로열 플러시")

    def __init__(self, value: int, korean: str):
        self.rank_value = value
        self.korean = korean

    def __lt__(self, other):
        return self.rank_value < other.rank_value

    def __le__(self, other):
        return self.rank_value <= other.rank_value

    def __gt__(self, other):
        return self.rank_value > other.rank_value

    def __ge__(self, other):
        return self.rank_value >= other.rank_value


class HandResult:
    def __init__(self, hand_rank: HandRank, best_cards: List[Card], tiebreakers: Tuple):
        self.hand_rank = hand_rank
        self.best_cards = best_cards
        self.tiebreakers = tiebreakers  # tuple of rank values for tie-breaking

    def __gt__(self, other):
        if self.hand_rank != other.hand_rank:
            return self.hand_rank > other.hand_rank
        return self.tiebreakers > other.tiebreakers

    def __lt__(self, other):
        if self.hand_rank != other.hand_rank:
            return self.hand_rank < other.hand_rank
        return self.tiebreakers < other.tiebreakers

    def __eq__(self, other):
        return self.hand_rank == other.hand_rank and self.tiebreakers == other.tiebreakers

    def __repr__(self):
        cards_str = " ".join(str(c) for c in self.best_cards)
        return f"{self.hand_rank.korean} [{cards_str}]"


class HandEvaluator:

    @staticmethod
    def evaluate(cards: List[Card]) -> HandResult:
        """7장(또는 5장) 중 가장 강한 5장 핸드를 평가합니다."""
        if len(cards) < 5:
            raise ValueError("최소 5장의 카드가 필요합니다.")

        best: HandResult = None
        for combo in combinations(cards, 5):
            result = HandEvaluator._evaluate_five(list(combo))
            if best is None or result > best:
                best = result
        return best

    @staticmethod
    def _evaluate_five(cards: List[Card]) -> HandResult:
        cards_sorted = sorted(cards, key=lambda c: c.rank.rank_value, reverse=True)
        ranks = [c.rank.rank_value for c in cards_sorted]
        suits = [c.suit for c in cards_sorted]

        is_flush = len(set(suits)) == 1
        is_straight, straight_high = HandEvaluator._check_straight(ranks)

        rank_counts = {}
        for r in ranks:
            rank_counts[r] = rank_counts.get(r, 0) + 1

        counts = sorted(rank_counts.values(), reverse=True)
        count_ranks = sorted(rank_counts.keys(),
                             key=lambda r: (rank_counts[r], r), reverse=True)

        # Royal Flush
        if is_flush and is_straight and straight_high == 14:
            return HandResult(HandRank.ROYAL_FLUSH, cards_sorted, (14,))

        # Straight Flush
        if is_flush and is_straight:
            return HandResult(HandRank.STRAIGHT_FLUSH, cards_sorted, (straight_high,))

        # Four of a Kind
        if counts[0] == 4:
            quad_rank = count_ranks[0]
            kicker = count_ranks[1]
            return HandResult(HandRank.FOUR_OF_A_KIND, cards_sorted, (quad_rank, kicker))

        # Full House
        if counts[0] == 3 and counts[1] == 2:
            trips_rank = count_ranks[0]
            pair_rank  = count_ranks[1]
            return HandResult(HandRank.FULL_HOUSE, cards_sorted, (trips_rank, pair_rank))

        # Flush
        if is_flush:
            return HandResult(HandRank.FLUSH, cards_sorted, tuple(ranks))

        # Straight
        if is_straight:
            return HandResult(HandRank.STRAIGHT, cards_sorted, (straight_high,))

        # Three of a Kind
        if counts[0] == 3:
            trips_rank = count_ranks[0]
            kickers    = sorted([r for r in ranks if r != trips_rank], reverse=True)
            return HandResult(HandRank.THREE_OF_A_KIND, cards_sorted,
                              (trips_rank,) + tuple(kickers))

        # Two Pair
        if counts[0] == 2 and counts[1] == 2:
            pair1, pair2 = sorted([count_ranks[0], count_ranks[1]], reverse=True)
            kicker = [r for r in ranks if r != pair1 and r != pair2][0]
            return HandResult(HandRank.TWO_PAIR, cards_sorted, (pair1, pair2, kicker))

        # One Pair
        if counts[0] == 2:
            pair_rank = count_ranks[0]
            kickers   = sorted([r for r in ranks if r != pair_rank], reverse=True)
            return HandResult(HandRank.ONE_PAIR, cards_sorted,
                              (pair_rank,) + tuple(kickers))

        # High Card
        return HandResult(HandRank.HIGH_CARD, cards_sorted, tuple(ranks))

    @staticmethod
    def _check_straight(ranks: List[int]) -> Tuple[bool, int]:
        unique = sorted(set(ranks), reverse=True)
        # A-2-3-4-5 (wheel)
        if set([14, 2, 3, 4, 5]).issubset(set(ranks)):
            return True, 5
        if len(unique) >= 5:
            for i in range(len(unique) - 4):
                window = unique[i:i+5]
                if window[0] - window[4] == 4 and len(set(window)) == 5:
                    return True, window[0]
        return False, 0
