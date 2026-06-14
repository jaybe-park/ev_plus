from enum import Enum
from dataclasses import dataclass


class Suit(Enum):
    SPADES   = ("♠", "spades")
    HEARTS   = ("♥", "hearts")
    DIAMONDS = ("♦", "diamonds")
    CLUBS    = ("♣", "clubs")

    def __init__(self, symbol: str, name: str):
        self.symbol = symbol
        self.suit_name = name

    def __str__(self):
        return self.symbol


class Rank(Enum):
    TWO   = (2,  "2")
    THREE = (3,  "3")
    FOUR  = (4,  "4")
    FIVE  = (5,  "5")
    SIX   = (6,  "6")
    SEVEN = (7,  "7")
    EIGHT = (8,  "8")
    NINE  = (9,  "9")
    TEN   = (10, "10")
    JACK  = (11, "J")
    QUEEN = (12, "Q")
    KING  = (13, "K")
    ACE   = (14, "A")

    def __init__(self, rank_value: int, symbol: str):
        self.rank_value = rank_value
        self.symbol = symbol

    def __str__(self):
        return self.symbol

    def __lt__(self, other):
        return self.rank_value < other.rank_value


@dataclass(frozen=True)
class Card:
    rank: Rank
    suit: Suit

    def __str__(self):
        return f"{self.rank.symbol}{self.suit.symbol}"

    def __repr__(self):
        return self.__str__()

    def __lt__(self, other):
        return self.rank.rank_value < other.rank.rank_value
