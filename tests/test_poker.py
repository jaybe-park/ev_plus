"""
포커 시뮬레이터 유닛 테스트
실행: python -m pytest tests/test_poker.py -v
또는: python tests/test_poker.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.card import Card, Suit, Rank
from core.deck import Deck
from core.evaluator import HandEvaluator, HandRank
from core.player import Player
from core.game import TexasHoldem, Action


def make_card(rank_sym: str, suit_sym: str) -> Card:
    rank_map = {r.symbol: r for r in Rank}
    suit_map = {"S": Suit.SPADES, "H": Suit.HEARTS, "D": Suit.DIAMONDS, "C": Suit.CLUBS}
    return Card(rank_map[rank_sym], suit_map[suit_sym])


def test_royal_flush():
    cards = [make_card(r, "H") for r in ["A", "K", "Q", "J", "10"]]
    result = HandEvaluator.evaluate(cards)
    assert result.hand_rank == HandRank.ROYAL_FLUSH, f"Expected Royal Flush, got {result}"
    print("✅ Royal Flush 판정 OK")


def test_straight_flush():
    cards = [make_card(r, "S") for r in ["9", "8", "7", "6", "5"]]
    result = HandEvaluator.evaluate(cards)
    assert result.hand_rank == HandRank.STRAIGHT_FLUSH
    print("✅ Straight Flush 판정 OK")


def test_four_of_a_kind():
    cards = [make_card("A", s) for s in ["S", "H", "D", "C"]] + [make_card("K", "S")]
    result = HandEvaluator.evaluate(cards)
    assert result.hand_rank == HandRank.FOUR_OF_A_KIND
    print("✅ Four of a Kind 판정 OK")


def test_full_house():
    cards = [make_card("K", s) for s in ["S", "H", "D"]] + \
            [make_card("Q", s) for s in ["S", "H"]]
    result = HandEvaluator.evaluate(cards)
    assert result.hand_rank == HandRank.FULL_HOUSE
    print("✅ Full House 판정 OK")


def test_flush():
    cards = [make_card(r, "D") for r in ["A", "10", "7", "4", "2"]]
    result = HandEvaluator.evaluate(cards)
    assert result.hand_rank == HandRank.FLUSH
    print("✅ Flush 판정 OK")


def test_straight():
    cards = [
        make_card("9", "S"), make_card("8", "H"), make_card("7", "D"),
        make_card("6", "C"), make_card("5", "S")
    ]
    result = HandEvaluator.evaluate(cards)
    assert result.hand_rank == HandRank.STRAIGHT
    print("✅ Straight 판정 OK")


def test_wheel_straight():
    """A-2-3-4-5 스트레이트 (Wheel)"""
    cards = [
        make_card("A", "S"), make_card("2", "H"), make_card("3", "D"),
        make_card("4", "C"), make_card("5", "S")
    ]
    result = HandEvaluator.evaluate(cards)
    assert result.hand_rank == HandRank.STRAIGHT
    assert result.tiebreakers == (5,), f"Wheel should have high=5, got {result.tiebreakers}"
    print("✅ Wheel Straight (A-2-3-4-5) 판정 OK")


def test_three_of_a_kind():
    cards = [make_card("J", s) for s in ["S", "H", "D"]] + \
            [make_card("A", "S"), make_card("K", "S")]
    result = HandEvaluator.evaluate(cards)
    assert result.hand_rank == HandRank.THREE_OF_A_KIND
    print("✅ Three of a Kind 판정 OK")


def test_two_pair():
    cards = [
        make_card("A", "S"), make_card("A", "H"),
        make_card("K", "S"), make_card("K", "H"),
        make_card("Q", "S")
    ]
    result = HandEvaluator.evaluate(cards)
    assert result.hand_rank == HandRank.TWO_PAIR
    print("✅ Two Pair 판정 OK")


def test_one_pair():
    cards = [
        make_card("A", "S"), make_card("A", "H"),
        make_card("K", "S"), make_card("Q", "H"), make_card("J", "S")
    ]
    result = HandEvaluator.evaluate(cards)
    assert result.hand_rank == HandRank.ONE_PAIR
    print("✅ One Pair 판정 OK")


def test_high_card():
    cards = [
        make_card("A", "S"), make_card("K", "H"),
        make_card("Q", "D"), make_card("J", "C"), make_card("9", "S")
    ]
    result = HandEvaluator.evaluate(cards)
    assert result.hand_rank == HandRank.HIGH_CARD
    print("✅ High Card 판정 OK")


def test_hand_comparison():
    flush = HandEvaluator.evaluate([make_card(r, "H") for r in ["A", "10", "7", "4", "2"]])
    straight = HandEvaluator.evaluate([
        make_card("9", "S"), make_card("8", "H"), make_card("7", "D"),
        make_card("6", "C"), make_card("5", "S")
    ])
    assert flush > straight
    print("✅ 핸드 비교 (Flush > Straight) OK")


def test_deck():
    deck = Deck()
    assert len(deck) == 52
    cards = deck.deal(5)
    assert len(cards) == 5
    assert len(deck) == 47
    print("✅ Deck deal OK")


def test_best_hand_from_7():
    """7장 중 최고 핸드 선택"""
    cards = [
        make_card("A", "S"), make_card("A", "H"),  # 페어
        make_card("K", "S"), make_card("K", "H"),  # 페어
        make_card("A", "D"),                        # 트리플 완성
        make_card("2", "C"), make_card("3", "D"),
    ]
    result = HandEvaluator.evaluate(cards)
    assert result.hand_rank == HandRank.FULL_HOUSE  # AAA + KK
    print("✅ 7장 중 최고 핸드 선택 OK")


if __name__ == "__main__":
    tests = [
        test_royal_flush, test_straight_flush, test_four_of_a_kind,
        test_full_house, test_flush, test_straight, test_wheel_straight,
        test_three_of_a_kind, test_two_pair, test_one_pair, test_high_card,
        test_hand_comparison, test_deck, test_best_hand_from_7,
    ]

    passed = 0
    failed = 0
    print("\n" + "=" * 50)
    print("  포커 시뮬레이터 유닛 테스트")
    print("=" * 50 + "\n")

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"❌ {test.__name__} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"💥 {test.__name__} ERROR: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"  결과: {passed} 통과 / {failed} 실패")
    print("=" * 50)
