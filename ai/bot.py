import random
from enum import Enum
from typing import Tuple, Optional, List, Dict

from core.game import Action
from core.player import Player
from core.card import Card, Suit
from core.pot_odds import effective_call_pot, pot_odds as calc_pot_odds
from gto.advisor import GTOAdvisor
from gto.loader import get_raise_range, get_call_range, get_vs_open_range
from ai.equity import smart_equity, made_hand_rank, ranged_equity, RangeSampler

_gto_advisor = GTOAdvisor()

# 난이도별 GTO 준수율 (프리플랍)
GTO_COMPLIANCE = {
    "easy":   0.40,
    "medium": 0.70,
    "hard":   0.95,
}

# 난이도별 포스트플랍 프로파일
# sims: equity MC 샘플 수 = 판단 해상도(vs 랜덤·레인지 반영 공통). None이면 적응형 MC
#   (표준오차 ≤ 1%p, ADR 0045). easy만 40으로 고정해 ±8% 오차로 자연스럽게 실수한다(ADR 0014).
#   리버 1:1 전수조사·프리플랍 상수 테이블은 난이도와 무관하게 smart_equity가 쓴다.
# call_margin: equity가 (팟오즈 + margin)을 넘어야 콜. 음수면 콜링스테이션 성향.
POSTFLOP_PROFILES = {
    "easy": {
        "sims": 40,   "use_ranges": False,
        "call_margin": -0.06, "raise_eq": 0.72, "value_bet_eq": 0.62,
        "semibluff_freq": 0.10, "bluff_freq": 0.04, "trap_freq": 0.05,
        "aggression_margin": 0.0,
    },
    "medium": {
        "sims": None, "use_ranges": False,
        "call_margin": 0.0,   "raise_eq": 0.65, "value_bet_eq": 0.55,
        "semibluff_freq": 0.40, "bluff_freq": 0.13, "trap_freq": 0.10,
        "aggression_margin": 0.06,
    },
    "hard": {
        "sims": None, "use_ranges": True,
        "call_margin": 0.02,  "raise_eq": 0.62, "value_bet_eq": 0.52,
        "semibluff_freq": 0.55, "bluff_freq": 0.22, "trap_freq": 0.14,
        "aggression_margin": 0.08,
    },
}

# 봇 페르소나: 난이도 프로파일 위에 얹는 성향 보정
# (call_margin/raise_eq/value_eq는 가산, *_mult는 빈도·사이즈 배율)
PERSONAS = {
    "balanced":   {},
    "tight":      {"call_margin": +0.05, "value_eq": +0.03, "bluff_mult": 0.7},
    "loose":      {"call_margin": -0.05, "value_eq": -0.04, "bluff_mult": 1.1},
    "aggressive": {"raise_eq": -0.04, "bluff_mult": 1.6, "semibluff_mult": 1.5,
                   "size_mult": 1.25},
    "passive":    {"raise_eq": +0.05, "bluff_mult": 0.5, "semibluff_mult": 0.6,
                   "size_mult": 0.85},
}

# 포스트플랍 액션 순서 (SB 먼저, BTN 마지막; 헤즈업은 BB 먼저 → BTN/SB 마지막)
_POSTFLOP_ORDER = {"SB": 0, "BB": 1, "UTG": 2, "HJ": 3, "CO": 4, "BTN": 6, "BTN/SB": 6}


class BotDifficulty(Enum):
    EASY   = "easy"
    MEDIUM = "medium"
    HARD   = "hard"


def _range_pos(pos: str) -> str:
    """GTO 레인지 조회용 포지션. 헤즈업 딜러 라벨 BTN/SB는 6-max SB 데이터를 쓴다(ADR 0005)."""
    return "SB" if pos == "BTN/SB" else pos


_EPS = 1e-9


def _preflop_roles(preflop_seq: list) -> Tuple[Optional[str], Dict[str, int], set, int]:
    """
    구조화 프리플랍 시퀀스(`core/game.py::preflop_action_seq`, ADR 0007)에서 레이즈 구조를 뽑는다.
    반환: (오프너 포지션, {포지션: 그 사람이 처음 올린 레이즈 번호(1=오픈, 2=3벳, ...)},
           콜러 포지션 집합, 레이즈 횟수)

    - 레이즈 = `raise`, 또는 지금까지의 최고 베팅(시작 1bb)보다 높은 `allin`. 최고 베팅 이하의
      `allin`(숏스택이 콜도 다 못 낸 올인)은 콜로 본다.
    - 콜러 = 오픈이 나온 뒤에 콜(또는 콜 성격 올인)한 사람. 오픈 전 콜(림프)만 한 사람은 콜러가 아니다.
    - 포지션 라벨은 원본 그대로(헤즈업 "BTN/SB"). 레인지 조회용 치환은 호출자가 `_range_pos`로 한다.
    """
    level = 1.0  # 빅 블라인드
    n_raises = 0
    opener: Optional[str] = None
    first_raise: Dict[str, int] = {}
    callers: set = set()
    for a in preflop_seq:
        pos = a.get("position", "")
        act = a.get("action")
        amt = a.get("amount_bb")
        if act == "raise" or (act == "allin" and (amt is None or amt > level + _EPS)):
            n_raises += 1
            if amt is not None:
                level = max(level, amt)
            if opener is None:
                opener = pos
            first_raise.setdefault(pos, n_raises)
        elif act in ("call", "allin") and opener is not None:
            callers.add(pos)
    return opener, first_raise, callers, n_raises


def _count_preflop_raises(preflop_seq: list) -> int:
    """프리플랍 레이즈 횟수(오픈 = 1). 최고 베팅을 올린 올인도 센다(`_preflop_roles`와 같은 기준)."""
    return _preflop_roles(preflop_seq)[3]


def _three_bet_range(my_pos: str, opener_pos: str) -> Optional[dict]:
    """오프너에게 3벳한 사람의 핸드 분포: "my_pos vs opener_pos open"(vs_open) 노드의
    레이즈(+올인) 빈도 가중, 빈도 ≤ 2% 제외(RFI·콜 레인지와 같은 기준). 노드가 없으면 None."""
    data = get_vs_open_range(my_pos, opener_pos)
    if data is None:
        return None
    weights = {}
    for hand, freqs in data.get("hands", {}).items():
        w = freqs.get("raise", 0.0) + freqs.get("allin", 0.0)
        if w > 0.02:
            weights[hand] = w
    return weights or None


def opponent_range_info(state: dict, opponents: list) -> list:
    """
    구조화 프리플랍 시퀀스(state["preflop_seq"])로 살아있는 상대들의 핸드 레인지 추정(ADR 0007).
    반환: opponents 순서대로 [(RangeSampler|None, role)] — role: raiser|caller|unknown
    오프너(첫 레이즈)      → 그 포지션의 RFI 레이즈 레인지
    3벳터(두 번째 레이즈) → "3벳터 vs 오프너 open" vs_open 노드의 레이즈 레인지
    4벳 이상을 처음 올린 사람 → 데이터 없음(unknown, 랜덤)
    콜러(오픈 뒤 콜)      → 오프너에 대한 콜 레인지
    정보 없음(블라인드 체크·림프 팟 등) → sampler=None (랜덤 핸드)
    이름→포지션은 state["players"][].position(없으면 state["positions"]).
    봇(hard)과 세션 에퀴티 패널이 공용으로 사용 — CLI·웹이 같은 core 상태를 넘긴다.
    """
    pos_of: Dict[str, str] = {
        p["name"]: p.get("position", "") for p in state.get("players", []) if "name" in p
    }
    for name, pos in (state.get("positions") or {}).items():
        if not pos_of.get(name):
            pos_of[name] = pos

    opener, first_raise, callers, _ = _preflop_roles(state.get("preflop_seq") or [])
    opener_pos = _range_pos(opener) if opener else None

    result = []
    for opp in opponents:
        raw_pos = pos_of.get(opp["name"], "")
        pos = _range_pos(raw_pos)
        weights = None
        role = "unknown"
        n = first_raise.get(raw_pos) if raw_pos else None
        if n is not None:
            role = "raiser"
            if n == 1:
                weights = get_raise_range(pos)
            elif n == 2 and opener_pos:
                weights = _three_bet_range(pos, opener_pos)
        elif raw_pos and raw_pos in callers and opener_pos:
            weights = get_call_range(pos, opener_pos)
            role = "caller"
        if not weights:
            # 레인지 데이터가 없으면 랜덤 핸드로 본다 — 화면(EquityPanel)이 role을 그대로 보이므로
            # "caller"/"raiser"로 남기면 레인지를 반영한 것처럼 보인다.
            role = "unknown"
        result.append((RangeSampler(weights) if weights else None, role))
    return result


def has_draw(hole: List[Card], board: List[Card]) -> bool:
    """
    아웃 기반 드로우 판정(순수 함수). 내 홀카드가 최소 1장 들어가는 드로우만 센다 —
    플러시 드로우 = 같은 수트 4장 중 내 카드가 있음, 스트레이트 드로우(OESD·거트샷) = 없는 랭크
    하나를 더하면 내 홀카드를 포함한 5연속이 생김. 보드만으로 생기는 드로우(홀카드 무관)는
    아웃이 0이라 드로우가 아니다. 백도어(두 장이 더 필요)도 아니다. 리버 제외·메이드 핸드
    (페어 이상) 제외는 호출자가 한다.
    """
    all_cards = list(hole) + list(board)
    if len(all_cards) < 5:
        return False

    suit_counts: Dict[Suit, int] = {}
    for card in all_cards:
        suit_counts[card.suit] = suit_counts.get(card.suit, 0) + 1
    hole_suits = {c.suit for c in hole}
    if any(n == 4 and s in hole_suits for s, n in suit_counts.items()):
        return True

    def bits(cards_):
        m = 0
        for card in cards_:
            v = card.rank.rank_value
            m |= 1 << v
            if v == 14:
                m |= 1 << 1  # 에이스는 로우(휠)로도 센다
        return m

    mask = bits(all_cards)
    hole_mask = bits(hole)
    straight_windows = [0b11111 << lo for lo in range(1, 11)]  # A-5 ~ T-A
    if any(mask & w == w for w in straight_windows):
        return False  # 이미 스트레이트(메이드)
    for v in range(2, 15):
        if mask & (1 << v):
            continue
        extra = (1 << v) | ((1 << 1) if v == 14 else 0)
        m2 = mask | extra
        # 완성될 5연속 창에 내 홀카드 랭크가 들어가야 내 드로우다
        if any(m2 & w == w and hole_mask & w for w in straight_windows):
            return True
    return False


def estimate_opponent_ranges(state: dict, opponents: list) -> Optional[list]:
    """상대 레인지 샘플러 목록 (공용 opponent_range_info의 얇은 래퍼).
    PokerBot._opponent_ranges와 server/session.py에서 공용으로 사용."""
    return [s for s, _ in opponent_range_info(state, opponents)]


def facing_bet_ratio(pot: int, current_bet: int, street_bets: List[int]) -> float:
    """
    받은 벳/레이즈의 크기 ÷ 그 공격자가 액션하기 직전 팟 (어그레션 마진용, ADR 0015).

    - 크기 = 공격자의 이번 스트리트 총 벳(current_bet). 공격자가 이 스트리트 첫 액션이라고 본다.
    - 직전 팟 = 팟 − 이번 스트리트에 current_bet만큼 넣은 사람들(공격자 + 그 뒤 콜러)의 벳.
      current_bet보다 적게 넣은 사람(나의 벳, 먼저 벳했다가 레이즈당한 사람)은 공격자 이전 액션이므로 포함.
    예: 팟 100에 내가 50 벳, 상대 150으로 레이즈 → 150 / (300 − 150) = 1.0.
    (이전 공식 콜/(팟−콜)은 100/200 = 0.5로 레이즈를 절반 크기로 봤다.)
    """
    if current_bet <= 0:
        return 0.0
    matched = sum(b for b in street_bets if b >= current_bet)
    return current_bet / max(pot - matched, 1)


def board_wetness(board: List[Card]) -> float:
    """
    보드 텍스처 0.0(드라이) ~ 1.0(웻).
    플러시/스트레이트 가능성이 높을수록 웻 → 밸류벳을 키워 드로우에 값을 청구.
    """
    if len(board) < 3:
        return 0.5
    score = 0.0

    suits = [c.suit for c in board]
    max_suit = max(suits.count(s) for s in set(suits))
    if max_suit >= 4:
        score += 0.8
    elif max_suit == 3:
        score += 0.5
    elif max_suit == 2 and len(board) == 3:
        score += 0.25

    ranks = sorted(set(c.rank.rank_value for c in board))
    for i in range(len(ranks) - 2):
        if ranks[i + 2] - ranks[i] <= 4:  # 4갭 안에 3장 = 스트레이트 코디네이션
            score += 0.35
            break

    if len(ranks) < len(board):  # 페어 보드는 드로우가 죽음
        score -= 0.1

    return max(0.0, min(1.0, score))


class PokerBot:

    def __init__(
        self,
        player: Player,
        difficulty: BotDifficulty = BotDifficulty.MEDIUM,
        persona: str = "balanced",
        overrides: Optional[dict] = None,
    ):
        self.player = player
        self.difficulty = difficulty
        self.persona = persona if persona in PERSONAS else "balanced"
        self.overrides = overrides or {}  # 프로파일 수치 직접 덮어쓰기 (튜닝용)
        self.last_equity = None  # 직전 결정의 equity (진단·테스트용, 프리플랍은 None)

    def _effective_profile(self) -> dict:
        """난이도 프로파일 + 페르소나 보정 합성"""
        prof = dict(POSTFLOP_PROFILES[self.difficulty.value])
        p = PERSONAS[self.persona]
        prof["call_margin"] += p.get("call_margin", 0.0)
        prof["raise_eq"] += p.get("raise_eq", 0.0)
        prof["value_bet_eq"] += p.get("value_eq", 0.0)
        prof["bluff_freq"] *= p.get("bluff_mult", 1.0)
        prof["semibluff_freq"] *= p.get("semibluff_mult", 1.0)
        prof["size_mult"] = p.get("size_mult", 1.0)
        prof.update(self.overrides)  # 튜닝 오버라이드가 최우선
        return prof

    def decide_action(self, game_state: dict) -> Tuple[Action, int]:
        action, amount = self._decide(game_state)
        # 오픈 폴드 금지: 콜할 금액이 없으면 폴드 대신 체크한다(공짜 카드를 버리지 않는다).
        if action == Action.FOLD:
            call_amount = max(0, game_state.get("current_bet", 0) - self.player.current_bet)
            if call_amount == 0:
                return Action.CHECK, 0
        return action, amount

    def _decide(self, game_state: dict) -> Tuple[Action, int]:
        if game_state.get("street") == "프리플랍":
            self.last_equity = None
            gto_result = self._try_gto_action(game_state)
            if gto_result is not None:
                return gto_result
            return self._preflop_fallback(game_state)
        return self._postflop_decision(game_state)

    # ──────────────────────────────────────────
    # 프리플랍: GTO 레인지 우선
    # ──────────────────────────────────────────

    def _try_gto_action(self, game_state: dict) -> Optional[Tuple[Action, int]]:
        """GTO 레인지 기반 액션. 데이터 없으면 None 반환."""
        compliance = GTO_COMPLIANCE.get(self.difficulty.value, 0.7)
        positions = game_state.get("positions", {})
        my_pos = positions.get(self.player.name, "")
        big_blind = game_state.get("big_blind", 20)

        gto_result = _gto_advisor.get_bot_action(
            self.player.hole_cards, my_pos, positions,
            game_state, big_blind, compliance
        )
        if gto_result is None:
            # GTO 데이터 없는 상황 (vs_4bet 등)
            # 4벳+ 이상이면 폴드 또는 올인만 허용
            raise_count = self._count_raises(game_state)
            if raise_count >= 3:
                return self._four_bet_plus_response(game_state)
            return None

        action_str = gto_result["action"]
        raise_count = gto_result.get("raise_count", 0)
        raise_size = gto_result.get("raise_size")  # 실측 bb(REAL) 또는 None
        call_amount = game_state["current_bet"] - self.player.current_bet

        if action_str == "fold":
            if call_amount == 0:
                return Action.CHECK, 0
            return Action.FOLD, 0

        elif action_str == "call":
            if call_amount == 0:
                return Action.CHECK, 0
            return Action.CALL, call_amount

        elif action_str == "raise":
            return self._preflop_raise(game_state, raise_count, raise_size)

        elif action_str == "allin":
            # 샘플된 GTO 액션이 allin이면 그대로 실행한다(레이즈로 뭉개거나
            # 휴리스틱으로 떨어지지 않음 — ADR 0002 "화면 그대로만" 원칙).
            return Action.ALL_IN, 0

        return None

    def _preflop_raise(
        self, state: dict, raise_count: int, raise_size: Optional[float]
    ) -> Tuple[Action, int]:
        """
        프리플랍 레이즈 사이즈 계산.
        raise_size: GTO 어드바이저가 반환한 실측 bb 단위 raise-to 값(REAL).
        수집된 값이 없으면(None/0) 폴백 공식을 사용한다 — 폴백은 근거 없는
        추측이라는 점을 명확히 구분해서만 사용 (GTO 실측값이 항상 우선).
        """
        current_bet = state["current_bet"]
        big_blind = state.get("big_blind", 20)
        min_raise = state.get("min_raise", big_blind)
        max_chips = self.player.chips + self.player.current_bet

        if raise_size:
            # GTO 실측값 사용: raise_size는 bb 단위 raise-to 금액
            raise_to = int(raise_size * big_blind)
            if raise_count >= 2 and raise_to >= max_chips * 0.7:
                return Action.ALL_IN, 0
        else:
            # 폴백 (GTO 데이터 없음 — 근거 없는 추측 공식, 데이터 수집되면 대체됨)
            if raise_count == 0:
                raise_to = int(big_blind * 2.5)
            elif raise_count == 1:
                raise_to = int(current_bet * 3)
            else:
                raise_to = int(current_bet * 2.5)
                if raise_to >= max_chips * 0.7:
                    return Action.ALL_IN, 0

        raise_to = max(raise_to, current_bet + min_raise)
        raise_to = min(raise_to, max_chips)

        if raise_to >= max_chips:
            return Action.ALL_IN, 0

        return Action.RAISE, raise_to

    def _four_bet_plus_response(self, state: dict) -> Tuple[Action, int]:
        """4벳+ 상황 (GTO 데이터 없음): 강한 패만 올인, 나머지 폴드"""
        call_amount = state["current_bet"] - self.player.current_bet
        strength = self._preflop_strength(self.player.hole_cards) \
            if len(self.player.hole_cards) >= 2 else 0.5

        if strength > 0.85 or (strength > 0.75 and random.random() < 0.3):
            return Action.ALL_IN, 0

        if call_amount == 0:
            return Action.CHECK, 0
        return Action.FOLD, 0

    def _preflop_fallback(self, state: dict) -> Tuple[Action, int]:
        """GTO 데이터 없는 프리플랍 스팟: 핸드 강도 휴리스틱"""
        strength = self._preflop_strength(self.player.hole_cards) \
            if len(self.player.hole_cards) >= 2 else 0.5
        call_amount, pot = self._effective_call_pot(state)
        pot_odds = calc_pot_odds(call_amount, pot)

        if strength > 0.75:
            return self._raise_action(state, pot_frac=0.75)
        if call_amount == 0:
            if strength > 0.6 and random.random() < 0.5:
                return self._raise_action(state, pot_frac=0.6)
            return Action.CHECK, 0
        if strength > pot_odds + 0.1:
            return Action.CALL, call_amount
        return Action.FOLD, 0

    def _count_raises(self, game_state: dict) -> int:
        """구조화 프리플랍 시퀀스의 레이즈 횟수(올인 포함, ADR 0007)"""
        return _count_preflop_raises(game_state.get("preflop_seq") or [])

    # ──────────────────────────────────────────
    # 포스트플랍: equity 기반 의사결정
    # ──────────────────────────────────────────

    def _postflop_decision(self, state: dict) -> Tuple[Action, int]:
        prof = self._effective_profile()
        hole = self.player.hole_cards
        community = self._parse_community_cards(state.get("community_cards", []))
        if len(hole) < 2 or len(community) < 3:
            return self._check_or_fold(state)

        opponents = [
            p for p in state.get("players", [])
            if p["name"] != self.player.name and not p["is_folded"]
        ]
        n_opps = max(1, len(opponents))
        # 숏스택 캡: 팟오즈는 유효 콜·유효 팟 기준
        call_amount, pot = self._effective_call_pot(state)
        street = state["street"]  # "플랍" | "턴" | "리버"

        # 레인지 반영 (hard): 프리플랍 액션으로 상대 핸드 분포를 좁혀 시뮬레이션
        samplers = None
        if prof["use_ranges"]:
            samplers = self._opponent_ranges(state, opponents)
            if samplers and not any(samplers):
                samplers = None  # 정보 없음 → 랜덤 핸드 equity

        if samplers:
            equity = ranged_equity(hole, community, samplers, prof["sims"])
        else:
            equity = smart_equity(hole, community, n_opps, prof["sims"])
        self.last_equity = round(equity, 4)
        made = made_hand_rank(hole, community)
        # 드로우: 아직 하이카드인데 내 홀카드가 관여하는 아웃이 있는 핸드(리버 제외) — ADR 0049
        is_draw = street != "리버" and made <= 1 and has_draw(hole, community)
        pos = self._position_score(state)   # 0.0(첫 액션) ~ 1.0(마지막 액션)
        wet = board_wetness(community)

        # 멀티웨이일수록 밸류 기준 상향 (equity 자체도 이미 낮아지지만 추가 보수화)
        multiway_penalty = 0.04 * (n_opps - 1)

        if call_amount > 0:
            return self._facing_bet(
                state, prof, equity, is_draw, pos, wet,
                call_amount, pot, street, multiway_penalty,
            )
        return self._no_bet(
            state, prof, equity, is_draw, pos, wet, street, n_opps, multiway_penalty,
        )

    def _effective_call_pot(self, state: dict) -> Tuple[int, int]:
        """
        (유효 콜, 유효 팟) — core/pot_odds 공용 함수. game_state에는 이번 스트리트 기여
        (players[].current_bet)만 있으므로 스트리트 기준으로 넘긴다(액션 중인 플레이어는
        이전 스트리트를 모두 맞췄으므로 정확 — core/pot_odds 모듈 설명).
        """
        raw_call = max(0, state["current_bet"] - self.player.current_bet)
        others = [p.get("current_bet", 0) for p in state.get("players", [])
                  if p["name"] != self.player.name]
        return effective_call_pot(
            state["pot"], raw_call, self.player.chips, self.player.current_bet, others,
        )

    def _facing_bet(
        self, state, prof, equity, is_draw, pos, wet,
        call_amount, pot, street, multiway_penalty,
    ) -> Tuple[Action, int]:
        """call_amount/pot은 유효 콜·유효 팟(숏스택 캡 적용)."""
        pot_odds = calc_pot_odds(call_amount, pot)

        size_mult = prof.get("size_mult", 1.0)

        # 강한 밸류: 레이즈 (가끔 슬로우플레이 콜)
        if equity >= prof["raise_eq"] + multiway_penalty:
            if random.random() < 1.0 - prof["trap_freq"]:
                return self._raise_action(state, pot_frac=(0.66 + 0.4 * wet) * size_mult)
            return Action.CALL, call_amount

        # 세미블러프 레이즈: 드로우 + 포지션 보정
        if is_draw and random.random() < prof["semibluff_freq"] * (0.5 + 0.5 * pos):
            return self._raise_action(state, pot_frac=0.7 * size_mult)

        # 콜/폴드: equity vs 팟 오즈
        margin = prof["call_margin"]
        # 어그레션 마진: 상대가 벳했다 = 랜덤보다 강한 레인지.
        # 벳이 클수록 equity(vs 랜덤)의 과대평가가 심해지므로 기준 상향.
        # (벳 크기 신호는 캡하지 않은 원래 금액 기준 — 레이즈를 받아도 실제 레이즈 크기)
        bet_ratio = facing_bet_ratio(
            state["pot"], state["current_bet"],
            [p.get("current_bet", 0) for p in state.get("players", [])],
        )
        margin += prof["aggression_margin"] * min(bet_ratio, 1.2)
        if is_draw:
            margin -= 0.04  # 임플라이드 오즈 (뜨면 더 딸 수 있음)
        if equity >= pot_odds + margin:
            return Action.CALL, call_amount
        return Action.FOLD, 0

    def _no_bet(
        self, state, prof, equity, is_draw, pos, wet, street, n_opps, multiway_penalty,
    ) -> Tuple[Action, int]:
        value_eq = prof["value_bet_eq"] + multiway_penalty
        size_mult = prof.get("size_mult", 1.0)

        # 넛급: 크게 벳 (가끔 트랩 체크)
        if equity >= 0.85:
            if random.random() < prof["trap_freq"]:
                return Action.CHECK, 0
            return self._raise_action(state, pot_frac=(0.75 + 0.35 * wet) * size_mult)

        # 일반 밸류: 드라이 보드는 스몰벳(33%), 웻 보드는 크게(66~85%)
        if equity >= value_eq:
            if random.random() < 0.30:  # 팟 컨트롤 체크 믹스
                return Action.CHECK, 0
            frac = 0.33 if wet < 0.4 else 0.66 + 0.2 * wet
            return self._raise_action(state, pot_frac=frac * size_mult)

        # 세미블러프: 드로우로 벳
        if is_draw and random.random() < prof["semibluff_freq"] * (0.4 + 0.6 * pos):
            return self._raise_action(state, pot_frac=0.6 * size_mult)

        # 순수 블러프: 포지션·상대 수 반영 (멀티웨이 블러프는 자살행위)
        bluff_f = prof["bluff_freq"] * (0.4 + 0.6 * pos) / n_opps
        if street == "리버":
            bluff_f *= 1.2  # 리버는 폴드 에퀴티가 전부
        if equity < 0.30 and random.random() < bluff_f:
            return self._raise_action(state, pot_frac=0.6 * size_mult)

        return Action.CHECK, 0

    def _opponent_ranges(self, state: dict, opponents: list) -> Optional[list]:
        """상대 레인지 샘플러 목록 (모듈 레벨 estimate_opponent_ranges의 얇은 래퍼)"""
        return estimate_opponent_ranges(state, opponents)

    def _check_or_fold(self, state: dict) -> Tuple[Action, int]:
        call_amount = max(0, state["current_bet"] - self.player.current_bet)
        if call_amount == 0:
            return Action.CHECK, 0
        return Action.FOLD, 0

    def _position_score(self, state: dict) -> float:
        """살아있는 플레이어 중 내 포스트플랍 액션 순서. 0.0=첫 액션, 1.0=마지막."""
        positions = state.get("positions", {})
        alive = [p["name"] for p in state.get("players", []) if not p["is_folded"]]
        if self.player.name not in alive:
            alive.append(self.player.name)
        order = sorted(_POSTFLOP_ORDER.get(positions.get(n, ""), 2) for n in alive)
        mine = _POSTFLOP_ORDER.get(positions.get(self.player.name, ""), 2)
        if len(order) <= 1:
            return 1.0
        return order.index(mine) / (len(order) - 1)

    # ──────────────────────────────────────────
    # 헬퍼
    # ──────────────────────────────────────────

    def _preflop_strength(self, hole_cards) -> float:
        r1 = hole_cards[0].rank.rank_value
        r2 = hole_cards[1].rank.rank_value
        suited = hole_cards[0].suit == hole_cards[1].suit
        paired = r1 == r2
        high, low = max(r1, r2), min(r1, r2)

        score = (high + low) / 28.0
        if paired: score += 0.2
        if suited:  score += 0.05
        if abs(r1 - r2) <= 2: score += 0.03
        return min(score, 1.0)

    def _parse_community_cards(self, card_strings):
        from core.card import Card, Suit, Rank as CardRank
        suit_map = {"♠": Suit.SPADES, "♥": Suit.HEARTS, "♦": Suit.DIAMONDS, "♣": Suit.CLUBS}
        rank_map = {r.symbol: r for r in CardRank}
        cards = []
        for s in card_strings:
            rank_sym, suit_sym = s[:-1], s[-1]
            if rank_sym in rank_map and suit_sym in suit_map:
                cards.append(Card(rank_map[rank_sym], suit_map[suit_sym]))
        return cards

    def _raise_action(self, state: dict, pot_frac: float = 0.5) -> Tuple[Action, int]:
        """팟 비율 기준 벳/레이즈"""
        pot = state["pot"]
        current_bet = state["current_bet"]
        min_raise = state.get("min_raise", state.get("big_blind", 20))
        max_chips = self.player.chips + self.player.current_bet

        bet_size = max(int(pot * pot_frac), min_raise)
        raise_to = current_bet + bet_size
        raise_to = min(raise_to, max_chips)

        if raise_to >= max_chips:
            return Action.ALL_IN, 0
        return Action.RAISE, raise_to
