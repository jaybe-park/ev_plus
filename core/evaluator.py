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


# ─────────────────────────────────────────────────────────────
# 고속 7카드 평가 (equity 계산 전용)
#
# HandEvaluator.evaluate()는 C(7,5)=21개 부분집합을 전부 평가하는
# 브루트포스라 정확하지만 느리다 (~60μs/회). 아래는 랭크 카운트와
# 수트 비트마스크로 5~7장을 직접 판정한다 (~6~12μs, 등가성 테스트로 검증).
#
# 반환: (핸드랭크 1~10, 타이브레이커 튜플) — 튜플 비교가 HandResult
# 비교와 동일한 순서를 보장한다. best_cards가 필요한 표시용(쇼다운)은
# 계속 HandEvaluator.evaluate()를 쓸 것.
# ─────────────────────────────────────────────────────────────

from .card import Suit as _Suit

_SUIT_INDEX = {_Suit.SPADES: 0, _Suit.HEARTS: 1, _Suit.DIAMONDS: 2, _Suit.CLUBS: 3}
_ACE_BIT = 1 << 14


def _straight_high_from_bits(bits: int) -> int:
    """랭크 비트마스크(bit r = 랭크 r 존재)에서 가장 높은 스트레이트 탑. 없으면 0."""
    if bits & _ACE_BIT:
        bits |= 1 << 1  # A를 1로도 취급 (휠)
    run = 0
    high = 0
    for r in range(1, 15):
        if bits & (1 << r):
            run += 1
            if run >= 5:
                high = r
        else:
            run = 0
    return high


def evaluate_rank(cards) -> Tuple[int, Tuple]:
    """5~7장 카드의 (랭크값, 타이브레이커) 직접 판정."""
    counts: dict = {}
    suit_bits = [0, 0, 0, 0]
    suit_cnt = [0, 0, 0, 0]
    rank_bits = 0
    for c in cards:
        r = c.rank.rank_value
        counts[r] = counts.get(r, 0) + 1
        si = _SUIT_INDEX[c.suit]
        suit_bits[si] |= 1 << r
        suit_cnt[si] += 1
        rank_bits |= 1 << r

    # 스트레이트 플러시 / 로열
    flush_suit = -1
    for i in range(4):
        if suit_cnt[i] >= 5:
            flush_suit = i
            break
    if flush_suit >= 0:
        sf_high = _straight_high_from_bits(suit_bits[flush_suit])
        if sf_high == 14:
            return (10, (14,))
        if sf_high:
            return (9, (sf_high,))

    ranks_desc = sorted(counts, reverse=True)
    quads = [r for r in ranks_desc if counts[r] == 4]
    trips = [r for r in ranks_desc if counts[r] == 3]
    pairs = [r for r in ranks_desc if counts[r] == 2]

    if quads:
        q = quads[0]
        kicker = max(r for r in counts if r != q)
        return (8, (q, kicker))

    if trips and (pairs or len(trips) >= 2):
        t = trips[0]
        p = max(pairs + trips[1:])
        return (7, (t, p))

    if flush_suit >= 0:
        fb = suit_bits[flush_suit]
        top5 = []
        for r in range(14, 1, -1):
            if fb & (1 << r):
                top5.append(r)
                if len(top5) == 5:
                    break
        return (6, tuple(top5))

    s_high = _straight_high_from_bits(rank_bits)
    if s_high:
        return (5, (s_high,))

    if trips:
        t = trips[0]
        ks = sorted((r for r in counts if r != t), reverse=True)[:2]
        return (4, (t,) + tuple(ks))

    if len(pairs) >= 2:
        p1, p2 = pairs[0], pairs[1]
        kicker = max(r for r in counts if r != p1 and r != p2)
        return (3, (p1, p2, kicker))

    if pairs:
        p = pairs[0]
        ks = sorted((r for r in counts if r != p), reverse=True)[:3]
        return (2, (p,) + tuple(ks))

    return (1, tuple(ranks_desc[:5]))
