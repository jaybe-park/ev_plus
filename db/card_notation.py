"""
카드 표기 변환 유틸리티
내부 표기(A♠) → DB 저장 표기(As)
"""

from core.card import Card, Suit, Rank

# 수트 변환
_SUIT_TO_CHAR = {
    Suit.SPADES:   's',
    Suit.HEARTS:   'h',
    Suit.DIAMONDS: 'd',
    Suit.CLUBS:    'c',
}

# 랭크 변환 (10 → T)
_RANK_TO_CHAR = {
    Rank.TWO:   '2',
    Rank.THREE: '3',
    Rank.FOUR:  '4',
    Rank.FIVE:  '5',
    Rank.SIX:   '6',
    Rank.SEVEN: '7',
    Rank.EIGHT: '8',
    Rank.NINE:  '9',
    Rank.TEN:   'T',
    Rank.JACK:  'J',
    Rank.QUEEN: 'Q',
    Rank.KING:  'K',
    Rank.ACE:   'A',
}

# 역변환 (DB → Card 객체)
_CHAR_TO_SUIT = {v: k for k, v in _SUIT_TO_CHAR.items()}
_CHAR_TO_RANK = {v: k for k, v in _RANK_TO_CHAR.items()}


def card_to_str(card: Card) -> str:
    """Card 객체 → DB 저장 문자열 (예: As, Kd, Tc, 9h)"""
    return _RANK_TO_CHAR[card.rank] + _SUIT_TO_CHAR[card.suit]


def str_to_card(s: str) -> Card:
    """DB 문자열 → Card 객체 (예: As → Card(ACE, SPADES))"""
    if len(s) != 2:
        raise ValueError(f"잘못된 카드 표기: {s!r}")
    rank = _CHAR_TO_RANK.get(s[0])
    suit = _CHAR_TO_SUIT.get(s[1])
    if rank is None or suit is None:
        raise ValueError(f"잘못된 카드 표기: {s!r}")
    return Card(rank, suit)


def cards_to_str(cards: list[Card]) -> list[str]:
    """Card 리스트 → 문자열 리스트"""
    return [card_to_str(c) for c in cards]


def str_to_cards(strings: list[str]) -> list[Card]:
    """문자열 리스트 → Card 리스트"""
    return [str_to_card(s) for s in strings]
