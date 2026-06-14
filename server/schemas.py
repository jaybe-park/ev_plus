from pydantic import BaseModel
from typing import Optional, List, Dict


class StartGameRequest(BaseModel):
    player_name: str = "Player"
    chips: int = 1000
    num_bots: int = 5
    difficulty: str = "medium"  # easy / medium / hard
    small_blind: int = 10


class ActionRequest(BaseModel):
    action: str   # fold / check / call / raise / allin
    amount: int = 0


class PlayerState(BaseModel):
    name: str
    chips: int
    current_bet: int
    is_folded: bool
    is_all_in: bool
    is_human: bool
    position: str
    hole_cards: Optional[List[str]] = None


class GameStateResponse(BaseModel):
    session_id: str
    hand_number: int
    street: str
    pot: int
    current_bet: int
    min_raise: int
    big_blind: int
    community_cards: List[str]
    players: List[PlayerState]
    waiting_for_action: bool
    hand_over: bool
    game_over: bool
    winners: List[str] = []
    showdown_hands: Dict[str, str] = {}
    gto_hint: Optional[str] = None
    action_log: List[str] = []
    call_amount: int = 0
    min_raise_to: int = 0
