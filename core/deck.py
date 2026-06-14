import random
from typing import List
from .card import Card, Suit, Rank


class Deck:
    def __init__(self):
        self.cards: List[Card] = []
        self.reset()

    def reset(self):
        self.cards = [Card(rank, suit) for suit in Suit for rank in Rank]
        self.shuffle()

    def shuffle(self):
        random.shuffle(self.cards)

    def deal(self, count: int = 1) -> List[Card]:
        if count > len(self.cards):
            raise ValueError(f"덱에 카드가 부족합니다. (남은 카드: {len(self.cards)}장)")
        dealt = self.cards[:count]
        self.cards = self.cards[count:]
        return dealt

    def deal_one(self) -> Card:
        return self.deal(1)[0]

    def __len__(self):
        return len(self.cards)

    def __repr__(self):
        return f"Deck({len(self.cards)} cards remaining)"
