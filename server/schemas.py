from pydantic import BaseModel
from typing import Optional, List, Dict, Any


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


class GameEvent(BaseModel):
    """프론트엔드 애니메이션용 구조화 이벤트"""
    type: str          # blind | deal_card | action | street_start | community_card | showdown | winner
    player: Optional[str] = None      # 관련 플레이어 이름
    position: Optional[str] = None    # BTN / SB / BB / ...
    action: Optional[str] = None      # fold / check / call / raise / allin
    amount: Optional[int] = None      # 베팅 금액
    street: Optional[str] = None      # 프리플랍 / 플랍 / 턴 / 리버
    card: Optional[str] = None        # 커뮤니티 카드 한 장 (community_card 이벤트)
    cards: Optional[List[str]] = None # 홀카드 또는 여러 장
    hands: Optional[Dict[str, List[str]]] = None  # 쇼다운 핸드 공개
    winners: Optional[List[str]] = None
    pot: Optional[int] = None
    round: Optional[int] = None                      # deal_card: 1 or 2
    log: Optional[str] = None                        # 액션 로그 텍스트
    chips_after: Optional[int] = None                # action/blind: 액션 후 플레이어 잔여 칩
    winner_chips: Optional[Dict[str, int]] = None    # winner: 승자별 최종 칩


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
    events: List[GameEvent] = []   # 이번 응답에서 발생한 이벤트 목록
