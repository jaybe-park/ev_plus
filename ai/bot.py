import random
from enum import Enum
from typing import Tuple, Optional, List

from core.game import Action
from core.player import Player
from core.card import Card
from gto.advisor import GTOAdvisor
from gto.loader import get_raise_range, get_call_range
from ai.equity import smart_equity, made_hand_rank, ranged_equity, RangeSampler

_gto_advisor = GTOAdvisor()

# 난이도별 GTO 준수율 (프리플랍)
GTO_COMPLIANCE = {
    "easy":   0.40,
    "medium": 0.70,
    "hard":   0.95,
}

# 난이도별 포스트플랍 프로파일
# sims: MC 샘플 수 = 판단 해상도. easy는 ±8% 오차로 자연스럽게 실수한다.
# call_margin: equity가 (팟오즈 + margin)을 넘어야 콜. 음수면 콜링스테이션 성향.
# exact_river: 리버 1:1에서 전수조사(정확값) 사용 여부
POSTFLOP_PROFILES = {
    "easy": {
        "sims": 40,   "use_cache": False, "exact_river": False, "use_ranges": False,
        "call_margin": -0.06, "raise_eq": 0.72, "value_bet_eq": 0.62,
        "semibluff_freq": 0.10, "bluff_freq": 0.04, "trap_freq": 0.05,
        "aggression_margin": 0.0,
    },
    "medium": {
        "sims": 300,  "use_cache": True,  "exact_river": False, "use_ranges": False,
        "call_margin": 0.0,   "raise_eq": 0.65, "value_bet_eq": 0.55,
        "semibluff_freq": 0.40, "bluff_freq": 0.13, "trap_freq": 0.10,
        "aggression_margin": 0.06,
    },
    "hard": {
        "sims": 1200, "use_cache": True,  "exact_river": True, "use_ranges": True,
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


def opponent_range_info(state: dict, opponents: list) -> list:
    """
    프리플랍 액션 로그로 살아있는 상대들의 핸드 레인지 추정.
    반환: opponents 순서대로 [(RangeSampler|None, role)] — role: raiser|caller|unknown
    레이저 → 그 포지션의 RFI 레이즈 레인지
    콜러  → 오프너에 대한 콜 레인지
    정보 없음(블라인드 체크 등) → sampler=None (랜덤 핸드)
    봇(hard)과 세션 에퀴티 패널이 공용으로 사용.
    """
    positions = state.get("positions", {})
    preflop_log = []
    for entry in state.get("action_log", []):
        if "──" in entry:
            break
        preflop_log.append(entry)

    raisers, callers = [], []
    for entry in preflop_log:
        for name, pos in positions.items():
            if name in entry:
                if "레이즈" in entry or "올인" in entry:
                    raisers.append((name, pos))
                elif "콜" in entry:
                    callers.append((name, pos))
                break

    opener_pos = raisers[0][1] if raisers else None
    raiser_names = {n for n, _ in raisers}
    caller_names = {n for n, _ in callers}

    result = []
    for opp in opponents:
        name = opp["name"]
        pos = positions.get(name, "")
        weights = None
        role = "unknown"
        if name in raiser_names:
            weights = get_raise_range(pos)
            role = "raiser"
        elif name in caller_names and opener_pos:
            weights = get_call_range(pos, opener_pos)
            role = "caller"
        result.append((RangeSampler(weights) if weights else None, role))
    return result


def estimate_opponent_ranges(state: dict, opponents: list) -> Optional[list]:
    """상대 레인지 샘플러 목록 (공용 opponent_range_info의 얇은 래퍼).
    PokerBot._opponent_ranges와 server/session.py에서 공용으로 사용."""
    return [s for s, _ in opponent_range_info(state, opponents)]


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
        self.last_equity = None  # 직전 결정의 equity (기록용, 프리플랍은 None)

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
        raise_size = gto_result.get("raise_size", "3x")
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

        return None

    def _preflop_raise(self, state: dict, raise_count: int, raise_size: str) -> Tuple[Action, int]:
        """
        프리플랍 레이즈 사이즈 계산.
        - RFI (raise_count=0): 2.5bb 오픈
        - 3벳 (raise_count=1): 오픈의 3x
        - 4벳 (raise_count=2): 3벳의 2.5x (또는 올인)
        """
        current_bet = state["current_bet"]
        big_blind = state.get("big_blind", 20)
        min_raise = state.get("min_raise", big_blind)
        max_chips = self.player.chips + self.player.current_bet

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
        call_amount = state["current_bet"] - self.player.current_bet
        pot = state["pot"]
        pot_odds = call_amount / (pot + call_amount) if call_amount > 0 else 0.0

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
        """action_log에서 프리플랍 레이즈 횟수"""
        count = 0
        for entry in game_state.get("action_log", []):
            if "──" in entry:
                break
            if "레이즈" in entry:
                count += 1
        return count

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
        call_amount = max(0, state["current_bet"] - self.player.current_bet)
        pot = state["pot"]
        street = state["street"]  # "플랍" | "턴" | "리버"

        # 레인지 반영 (hard): 프리플랍 액션으로 상대 핸드 분포를 좁혀 시뮬레이션
        samplers = None
        if prof["use_ranges"]:
            samplers = self._opponent_ranges(state, opponents)
            if samplers and not any(samplers):
                samplers = None  # 정보 없음 → 캐시 활용 가능한 랜덤 equity

        if samplers:
            equity = ranged_equity(hole, community, samplers, prof["sims"])
        else:
            equity = smart_equity(
                hole, community, n_opps, prof["sims"],
                use_cache=prof["use_cache"], contribute=True,
                exact_river=prof["exact_river"],
            )
        self.last_equity = round(equity, 4)
        made = made_hand_rank(hole, community)
        # 드로우: 지금은 하이카드지만 equity가 살아있는 핸드 (리버 제외)
        is_draw = street != "리버" and made <= 1 and equity >= 0.30
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

    def _facing_bet(
        self, state, prof, equity, is_draw, pos, wet,
        call_amount, pot, street, multiway_penalty,
    ) -> Tuple[Action, int]:
        pot_odds = call_amount / (pot + call_amount)

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
        bet_ratio = call_amount / max(pot - call_amount, 1)
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
