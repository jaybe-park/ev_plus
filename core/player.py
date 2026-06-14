from typing import List, Optional
from .card import Card


class Player:
    def __init__(self, name: str, chips: int = 1000, is_human: bool = True):
        self.name = name
        self.chips = chips
        self.is_human = is_human
        self.hole_cards: List[Card] = []
        self.current_bet: int = 0
        self.is_folded: bool = False
        self.is_all_in: bool = False
        self.total_bet_this_round: int = 0  # 현재 라운드 총 베팅액

    def reset_for_hand(self):
        """새 핸드 시작 시 초기화"""
        self.hole_cards = []
        self.current_bet = 0
        self.is_folded = False
        self.is_all_in = False
        self.total_bet_this_round = 0

    def reset_for_street(self):
        """새 스트리트(베팅 라운드) 시작 시 초기화"""
        self.current_bet = 0

    def receive_cards(self, cards: List[Card]):
        self.hole_cards.extend(cards)

    def place_bet(self, amount: int) -> int:
        """실제 베팅 금액을 반환 (올인 처리 포함)"""
        actual = min(amount, self.chips)
        self.chips -= actual
        self.current_bet += actual
        self.total_bet_this_round += actual
        if self.chips == 0:
            self.is_all_in = True
        return actual

    def fold(self):
        self.is_folded = True

    @property
    def is_active(self) -> bool:
        """아직 게임에 참여 중인지 (폴드/올인 아님)"""
        return not self.is_folded and not self.is_all_in

    def __repr__(self):
        status = ""
        if self.is_folded:
            status = " [폴드]"
        elif self.is_all_in:
            status = " [올인]"
        return f"{self.name}(칩:{self.chips}{status})"
