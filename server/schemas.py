from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError
from typing import Optional, List, Dict, Any, Literal

# 게임 설정 한계 (T-027). 위반 시 422 — detail[].msg는 설정 화면에 그대로 보이는 한국어 안내.
MIN_BIG_BLIND = 2            # SB = BB/2 가 1 이상이어야 한다
MIN_STACK_IN_BB = 10         # 시작 칩 ≥ BB × 10 (블라인드 몇 번에 파산하는 게임 방지)
MAX_CHIPS = 10_000_000
MAX_BOTS = 5                 # 봇 이름·페르소나가 5개
MAX_NAME_LEN = 20
BOT_NAME_PREFIX = "🤖"       # 봇 이름 접두사 — 사람 이름과 겹치면 이름 기준 좌석·버튼이 깨진다


def _invalid(code: str, msg: str) -> PydanticCustomError:
    # PydanticCustomError는 msg를 접두사("Value error, ") 없이 그대로 내보낸다
    return PydanticCustomError(code, msg)


class StartGameRequest(BaseModel):
    player_name: str = Field("Player", description=f"1~{MAX_NAME_LEN}자, '{BOT_NAME_PREFIX}'로 시작 불가")
    chips: int = Field(1000, description=f"시작 칩, BB×{MIN_STACK_IN_BB} 이상 {MAX_CHIPS:,} 이하")
    num_bots: int = Field(5, description=f"봇 수 1~{MAX_BOTS}")
    difficulty: str = Field("medium", description="easy / medium / hard")
    big_blind: int = Field(10, description=f"{MIN_BIG_BLIND} 이상 짝수(SB = BB/2)")

    @field_validator("player_name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise _invalid("name_empty", "플레이어 이름을 입력하세요.")
        if len(v) > MAX_NAME_LEN:
            raise _invalid("name_long", f"플레이어 이름은 {MAX_NAME_LEN}자 이하여야 합니다.")
        if v.startswith(BOT_NAME_PREFIX):
            raise _invalid("name_bot", f"플레이어 이름은 '{BOT_NAME_PREFIX}'로 시작할 수 없습니다(봇 이름과 겹침).")
        return v

    @field_validator("num_bots")
    @classmethod
    def _check_bots(cls, v: int) -> int:
        if not 1 <= v <= MAX_BOTS:
            raise _invalid("num_bots", f"AI 봇 수는 1~{MAX_BOTS}명이어야 합니다.")
        return v

    @field_validator("difficulty")
    @classmethod
    def _check_difficulty(cls, v: str) -> str:
        if v not in ("easy", "medium", "hard"):
            raise _invalid("difficulty", "난이도는 easy / medium / hard 중 하나여야 합니다.")
        return v

    @field_validator("big_blind")
    @classmethod
    def _check_bb(cls, v: int) -> int:
        if v < MIN_BIG_BLIND:
            raise _invalid("bb_small", f"빅 블라인드는 {MIN_BIG_BLIND} 이상이어야 합니다(스몰 블라인드 = BB/2).")
        if v % 2:
            raise _invalid("bb_odd", "빅 블라인드는 짝수여야 합니다(스몰 블라인드 = BB/2).")
        return v

    @field_validator("chips")
    @classmethod
    def _check_chips(cls, v: int) -> int:
        if v <= 0:
            raise _invalid("chips_nonpositive", "시작 칩은 1 이상이어야 합니다.")
        if v > MAX_CHIPS:
            raise _invalid("chips_large", f"시작 칩은 {MAX_CHIPS:,} 이하여야 합니다.")
        return v

    @model_validator(mode="after")
    def _check_stack_depth(self):
        if self.chips < self.big_blind * MIN_STACK_IN_BB:
            raise _invalid(
                "chips_shallow",
                f"시작 칩은 빅 블라인드의 {MIN_STACK_IN_BB}배({self.big_blind * MIN_STACK_IN_BB}) 이상이어야 합니다.")
        return self


class ActionRequest(BaseModel):
    action: Literal["fold", "check", "call", "raise", "allin"]
    amount: int = Field(0, ge=0)


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
    vs_range: float           # 그 스트리트 첫 결정의 vs_range (패널과 같은 기준, T-006)


class EquityInfo(BaseModel):
    vs_random: float                    # 랜덤 핸드 대비 승률 — 화면 비표시(ADR 0022/0034), 평가·기록용
    vs_range: float                     # 상대 레인지 반영 종합 승률 — 패널이 보여주는 값
    range_applied: bool = False         # 레인지 정보가 있는 상대가 하나라도 있나(없으면 vs_range = vs_random)
    pot_odds: float = 0.0                # 유효 콜 / (유효 팟 + 유효 콜), 벳 없으면 0
    call_ev_bb: Optional[float] = None  # vs_range 기준 콜 EV (bb), 벳 직면 시만
    source: str                         # vs_range를 만든 경로: preflop-table | exact | mc:N
    samples: int                        # 그 계산의 샘플 수(테이블 1,000,000 / 전수 990 / MC N)
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


class GtoPanelInfo(BaseModel):
    """GTO 패널 — advisor 추천 하나에서 만든다(T-013). 레인지는 node_key로 /gto/preflop/range 조회."""
    found: bool                                   # 추천(정확한 노드 또는 라벨 예비)이 있나
    position: str = ""                            # 히어로 포지션(게임 라벨, 헤즈업은 BTN/SB)
    node_key: Optional[str] = None                # 쓰인 노드의 action_seq (UTG RFI는 "")
    approx: bool = False                          # 간단 라벨 예비 결과 → "(근사)" (ADR 0035)
    situation: str = ""                           # "BTN RFI" 등
    hand: Optional[str] = None                    # "AKs"
    frequencies: Optional[Dict[str, float]] = None  # 내 패의 액션 빈도


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
    action_log: List[str] = []
    call_amount: int = 0
    min_raise_to: int = 0             # 레이즈 불가(액션 닫힘·스택 부족)면 0
    can_raise: bool = False           # 사람이 지금 레이즈/올인-레이즈를 할 수 있는가
    events: List[GameEvent] = []   # 이번 응답에서 발생한 이벤트 목록
    gto: Optional[GtoPanelInfo] = None        # GTO 패널 (프리플랍 사람 차례일 때, advisor 추천에서)
    equity: Optional[EquityInfo] = None       # 에퀴티 패널 (waiting_for_action=true일 때)
    hand_review: Optional[List[HandReviewEntry]] = None  # 플레이 평가 (hand_over=true일 때)
