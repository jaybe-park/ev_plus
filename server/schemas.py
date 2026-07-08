from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class StartGameRequest(BaseModel):
    player_name: str = "Player"
    chips: int = 1000
    num_bots: int = 5
    difficulty: str = "medium"  # easy / medium / hard
    big_blind: int = 10


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


class EquityOpponent(BaseModel):
    name: str
    position: str
    role: str                          # raiser | caller | unknown
    equity: Optional[float] = None     # 나 vs 이 상대 1:1 레인지 에퀴티


class EquityHistoryEntry(BaseModel):
    street: str               # 프리플랍 / 플랍 / 턴 / 리버
    vs_random: float


class EquityInfo(BaseModel):
    vs_random: float                    # 랜덤 핸드 대비 승률 (캐시/MC)
    vs_range: float                     # 상대 레인지 반영 종합 승률
    pot_odds: float = 0.0                # call / (pot + call), 벳 없으면 0
    call_ev_bb: Optional[float] = None  # 콜 EV (bb), 벳 직면 시만
    source: str                         # exact | mc:N
    samples: int                        # 계산에 쓰인 샘플 수
    num_opponents: int
    opponents: List[EquityOpponent] = []
    history: List[EquityHistoryEntry] = []


class HandReviewEntry(BaseModel):
    street: str
    action: str
    grade: str                          # ✅ 🟡 🟠 🔴 ⬜ ⚠️
    reason: str
    ev_loss_bb: Optional[float] = None
    pot_odds: Optional[float] = None
    equity: Optional[float] = None
    gto_freq: Optional[float] = None   # 선택한 액션의 GTO 빈도 (프리플랍만)


class SessionReviewResponse(BaseModel):
    """세션 전체 누적 플레이 평가 요약 (GET /session/{id}/review)"""
    total_actions: int
    grade_counts: Dict[str, int]              # 등급 기호 → 개수
    total_ev_loss_bb: float
    gto_match_rate: Optional[float] = None    # 프리플랍 GTO 데이터 있는 액션 중 최선(✅) 비율


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
    gto_key: Optional[Dict[str, Any]] = None  # GTO 레인지 조회용 키 {position, vs_position, range_type}
    equity: Optional[EquityInfo] = None       # 에퀴티 패널 (waiting_for_action=true일 때)
    hand_review: Optional[List[HandReviewEntry]] = None  # 플레이 평가 (hand_over=true일 때)
