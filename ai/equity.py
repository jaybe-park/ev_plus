"""
에퀴티(승률) 계산 엔진 — "내 홀카드 + 보드 vs 랜덤 핸드 상대 N명" (ADR 0034)

계산 경로 (`smart_equity` / `equity_detail`):
1. 프리플랍 — 상수 테이블(`ai/preflop_equity_table.py`, 169핸드 × 상대 1~5명, 각 100만 샘플).
2. 리버 상대 1명 — 전수조사(990조합, 약 3ms). 모든 난이도.
3. 그 밖 — 실시간 Monte Carlo. 기본은 적응형: 표준오차가 TARGET_SE(1%p)에
   도달하면 멈추고, 최대 MC_MAX_SAMPLES(최악 p=0.5에서도 SE ≤ 1%p가 되는 수)까지.
   호출자가 샘플 수를 고정하면(easy 봇, ADR 0014) 그 수만큼만 돈다.
레인지 반영 에퀴티(`ranged_equity`)도 같은 적응형 규칙을 쓴다.

결과를 DB에 저장하지 않는다 — equity_cache는 폐기됐다(ADR 0034).
"""

import bisect
import math
import random
from itertools import combinations
from typing import Dict, List, NamedTuple, Optional, Tuple

from core.card import Card, Suit, Rank
from core.evaluator import HandEvaluator, evaluate_rank
from ai.preflop_equity_table import PREFLOP_EQUITY, PREFLOP_SAMPLES

_FULL_DECK = [Card(r, s) for r in Rank for s in Suit]
_SUITS = [Suit.SPADES, Suit.HEARTS, Suit.DIAMONDS, Suit.CLUBS]
_RANK_BY_VALUE = {r.rank_value: r for r in Rank}

# 정밀도 목표: 봇·패널 에퀴티(vs 랜덤·레인지 반영)의 표준오차(1σ) ≤ 1%p (ADR 0045)
TARGET_SE = 0.01
# 적응형 MC: MC_BATCH 단위로 돌며 MC_MIN_SAMPLES 이후 SE ≤ TARGET_SE면 멈춘다.
# 샘플 1개의 지분 분산은 최대 0.25(p=0.5, 동률 없음)이므로
# MC_MAX_SAMPLES = 0.25 / TARGET_SE² = 2,500이면 어떤 스팟도 목표를 만족한다(상한 자체가 보장).
# MC_MIN_SAMPLES = 500: 표본분산 추정의 상대오차가 약 1/sqrt(2n) ≈ 3%라 조기 종료 판정이
# 믿을 만하고, 에퀴티가 극단적인 스팟(p=0.95 → 필요 n≈475)도 이 선에서 끝난다.
MC_MIN_SAMPLES = 500
MC_BATCH = 250
MC_MAX_SAMPLES = 2_500

_NOTE_CHAR = {2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8",
              9: "9", 10: "T", 11: "J", 12: "Q", 13: "K", 14: "A"}


def street_of(board: List[Card]) -> str:
    return {0: "preflop", 3: "flop", 4: "turn", 5: "river"}[len(board)]


def _check_cards(hole_cards: List[Card], board: List[Card]) -> None:
    """홀-보드 간 또는 보드 내부에 중복 카드가 있으면 잘못된 스팟이므로 ValueError."""
    all_cards = list(hole_cards) + list(board)
    if len(all_cards) != len(set(all_cards)):
        raise ValueError(f"에퀴티 계산: 중복 카드 — {all_cards}")


def preflop_notation(hole_cards: List[Card]) -> str:
    """홀카드 2장 → 'AA' / 'AKs' / 'AKo' (상수 테이블 키)."""
    a, b = hole_cards
    if a.rank.rank_value < b.rank.rank_value:
        a, b = b, a
    hi, lo = _NOTE_CHAR[a.rank.rank_value], _NOTE_CHAR[b.rank.rank_value]
    if hi == lo:
        return hi + lo
    return hi + lo + ("s" if a.suit == b.suit else "o")


# ──────────────────────────────────────────
# Monte Carlo 샘플링
# ──────────────────────────────────────────

def _showdown_share(mine: tuple, opp_ranks: List[tuple]) -> Tuple[float, float]:
    """
    한 번의 쇼다운 결과를 (wins, ties) 증분으로 환산한다.

    카운트 스키마 (wins, ties, total)와 `_ratio` = (wins + 0.5*ties)/total을 그대로
    쓰기 위해, 나를 포함해 k명이 팟을 나누면 ties에 2/k를 더한다 → 지분 1/k.
    헤즈업(k=2)이면 기존과 같은 ties += 1.
    """
    best_opp = max(opp_ranks)
    if mine > best_opp:
        return 1.0, 0.0
    if mine < best_opp:
        return 0.0, 0.0
    k = 1 + sum(1 for r in opp_ranks if r == best_opp)
    return 0.0, 2.0 / k


def _mc_run(
    hole_cards: List[Card],
    board: List[Card],
    num_opponents: int,
    num_simulations: int,
) -> Tuple[float, float, float]:
    """MC 1회분: (wins, ties, 샘플별 지분 제곱합). 제곱합은 적응형 MC의 표준오차용."""
    known = set(hole_cards) | set(board)
    deck = [c for c in _FULL_DECK if c not in known]
    need = 5 - len(board)
    draw_count = need + 2 * num_opponents

    wins = 0.0
    ties = 0.0
    sq = 0.0
    for _ in range(num_simulations):
        drawn = random.sample(deck, draw_count)
        full = board + drawn[:need]
        mine = evaluate_rank(hole_cards + full)

        opp_ranks = [
            evaluate_rank(list(drawn[need + 2 * i:need + 2 * i + 2]) + full)
            for i in range(num_opponents)
        ]
        w, t = _showdown_share(mine, opp_ranks)
        wins += w
        ties += t
        share = w + 0.5 * t
        sq += share * share
    return wins, ties, sq


def mc_counts(
    hole_cards: List[Card],
    board: List[Card],
    num_opponents: int,
    num_simulations: int,
) -> Tuple[float, float, int]:
    """고정 샘플 MC: (wins, ties, total)."""
    w, t, _ = _mc_run(hole_cards, board, num_opponents, num_simulations)
    return w, t, num_simulations


def _adaptive(
    run,
    target_se: float = TARGET_SE,
    min_samples: int = MC_MIN_SAMPLES,
    max_samples: int = MC_MAX_SAMPLES,
    batch: int = MC_BATCH,
) -> Tuple[float, float, int, float]:
    """
    적응형 MC 공통 루프. run(n) → (wins, ties, 지분 제곱합).
    batch씩 돌며 min_samples 이후 표준오차 sqrt(표본분산/n)이 target_se 이하가 되면 멈춘다.
    max_samples에서 끝나도 지분 분산 ≤ 0.25라 기본값(2,500)이면 SE ≤ 1%p다.
    반환: (wins, ties, total, 표준오차)
    """
    wins = ties = sq = 0.0
    n = 0
    se = 0.5
    while n < max_samples:
        step = min(batch, max_samples - n)
        w, t, q = run(step)
        wins += w
        ties += t
        sq += q
        n += step
        mean = (wins + 0.5 * ties) / n
        var = max(0.0, sq / n - mean * mean)
        se = math.sqrt(var / n)
        if n >= min_samples and se <= target_se:
            break
    return wins, ties, n, se


def mc_adaptive(
    hole_cards: List[Card],
    board: List[Card],
    num_opponents: int,
    **kw,
) -> Tuple[float, float, int, float]:
    """vs 랜덤 적응형 MC: (wins, ties, total, 표준오차). kw는 _adaptive 인자."""
    return _adaptive(lambda n: _mc_run(hole_cards, board, num_opponents, n), **kw)


def calculate_equity(
    hole_cards: List[Card],
    community_cards: List[Card],
    num_opponents: int = 1,
    num_simulations: int = 200,
) -> float:
    """순수 고정 샘플 MC 승률 (0.0~1.0)."""
    if len(hole_cards) < 2:
        return 0.5
    w, t, n = mc_counts(hole_cards, community_cards, num_opponents, num_simulations)
    return (w + 0.5 * t) / n


# ──────────────────────────────────────────
# 전수조사 (vs 상대 1명)
# ──────────────────────────────────────────

def exact_counts_river(hole: List[Card], board: List[Card]) -> Tuple[float, float, int]:
    """리버: 상대 홀카드 C(45,2)=990 조합 전부 판정. <1초."""
    known = set(hole) | set(board)
    deck = [c for c in _FULL_DECK if c not in known]
    mine = evaluate_rank(hole + board)

    wins = ties = 0.0
    total = 0
    for opp_pair in combinations(deck, 2):
        opp = evaluate_rank(list(opp_pair) + board)
        if mine > opp:
            wins += 1
        elif mine == opp:
            ties += 1
        total += 1
    return wins, ties, total


def exact_counts_turn(hole: List[Card], board: List[Card]) -> Tuple[float, float, int]:
    """턴: 리버 46장 × 상대 C(44,2) ≈ 4.6만 조합. ~10초."""
    known = set(hole) | set(board)
    deck = [c for c in _FULL_DECK if c not in known]

    wins = ties = 0.0
    total = 0
    for river in deck:
        full = board + [river]
        mine = evaluate_rank(hole + full)
        rest = [c for c in deck if c != river]
        for opp_pair in combinations(rest, 2):
            opp = evaluate_rank(list(opp_pair) + full)
            if mine > opp:
                wins += 1
            elif mine == opp:
                ties += 1
            total += 1
    return wins, ties, total


def exact_counts_flop(hole: List[Card], board: List[Card]) -> Tuple[float, float, int]:
    """플랍: 턴/리버 C(47,2) × 상대 C(45,2) ≈ 107만 조합. 2~5분."""
    known = set(hole) | set(board)
    deck = [c for c in _FULL_DECK if c not in known]

    wins = ties = 0.0
    total = 0
    for tr in combinations(deck, 2):
        full = board + list(tr)
        mine = evaluate_rank(hole + full)
        tr_set = set(tr)
        rest = [c for c in deck if c not in tr_set]
        for opp_pair in combinations(rest, 2):
            opp = evaluate_rank(list(opp_pair) + full)
            if mine > opp:
                wins += 1
            elif mine == opp:
                ties += 1
            total += 1
    return wins, ties, total


def board_rank_table(board: List[Card]) -> dict:
    """
    보드 B(5장) 공유 리버 스팟들을 위한 랭크 테이블.

    B와 겹치지 않는 47장에서 만들 수 있는 모든 2장 조합(C(47,2)=1081개)의
    "보드+그 2장" 핸드 랭크를 한 번만 계산해 정렬 리스트(bisect용)와
    카드별 부분 리스트(블로커 보정용)로 반환한다.
    """
    known = set(board)
    deck = [c for c in _FULL_DECK if c not in known]

    full_sorted: List[tuple] = []
    card_ranks: Dict[Card, List[tuple]] = {c: [] for c in deck}
    pair_rank: Dict[frozenset, tuple] = {}

    for c1, c2 in combinations(deck, 2):
        r = evaluate_rank([c1, c2] + board)
        full_sorted.append(r)
        card_ranks[c1].append(r)
        card_ranks[c2].append(r)
        pair_rank[frozenset((c1, c2))] = r

    full_sorted.sort()
    return {
        "board": list(board),
        "deck": deck,
        "full_sorted": full_sorted,
        "card_ranks": card_ranks,
        "pair_rank": pair_rank,
    }


def equity_via_board_table(
    hole: List[Card], board: List[Card], table: dict,
) -> Tuple[float, float, int]:
    """
    board_rank_table 결과를 이용한 리버 equity 계산.
    exact_counts_river와 동일한 반환 형식 (wins, ties, total=990).

    아이디어: 1081개 전체 조합 중 "나보다 약한/타이" 개수를 이진탐색으로 구하고,
    내 홀카드 2장을 포함하는 91개 조합(상대가 실제로 만들 수 없는 조합)의
    약한/타이 개수를 빼서 정확한 990조합 기준값을 만든다.
    """
    a, b = hole
    mine = evaluate_rank(list(hole) + list(board))

    full_sorted = table["full_sorted"]
    lo = bisect.bisect_left(full_sorted, mine)
    hi = bisect.bisect_right(full_sorted, mine)
    full_weaker = lo
    full_tie = hi - lo

    ab_rank = table["pair_rank"][frozenset((a, b))]
    excluded = list(table["card_ranks"][a]) + list(table["card_ranks"][b])
    excluded.remove(ab_rank)  # a·b 조합 자체는 두 리스트에 각 1회씩 중복 → 1회만 제거

    exc_weaker = sum(1 for r in excluded if r < mine)
    exc_tie = sum(1 for r in excluded if r == mine)

    wins = float(full_weaker - exc_weaker)
    ties = float(full_tie - exc_tie)
    total = 990
    return wins, ties, total


def _ratio(wins: float, ties: float, total: int) -> float:
    return (wins + 0.5 * ties) / total if total > 0 else 0.5


# ──────────────────────────────────────────
# 스마트 에퀴티 (봇·패널 진입점)
# ──────────────────────────────────────────

class EquityResult(NamedTuple):
    equity: float
    source: str    # "preflop-table" | "exact" | "mc:N" | "none"
    samples: int   # 테이블 샘플 수 / 전수 조합 수 / MC 샘플 수


def equity_detail(
    hole_cards: List[Card],
    board: List[Card],
    num_opponents: int = 1,
    num_simulations: Optional[int] = None,
) -> EquityResult:
    """
    vs 랜덤 핸드 에퀴티와 그 계산 경로 (ADR 0034).

    - 프리플랍(상대 1~5명): 상수 테이블. num_simulations와 무관.
    - 리버 상대 1명: 전수조사(990조합). num_simulations와 무관(모든 난이도).
    - 그 밖: num_simulations가 None이면 적응형 MC(SE ≤ TARGET_SE),
      정수면 그 수만큼 고정 MC(easy 봇처럼 해상도를 일부러 낮출 때 — ADR 0014).
    DB에 읽거나 쓰지 않는다.
    """
    if len(hole_cards) < 2:
        return EquityResult(0.5, "none", 0)
    _check_cards(hole_cards, board)
    street = street_of(board)

    if street == "preflop" and 1 <= num_opponents <= 5:
        vals = PREFLOP_EQUITY[preflop_notation(hole_cards)]
        return EquityResult(vals[num_opponents - 1], "preflop-table", PREFLOP_SAMPLES)

    if street == "river" and num_opponents == 1:
        w, t, n = exact_counts_river(hole_cards, board)
        return EquityResult(_ratio(w, t, n), "exact", n)

    if num_simulations is None:
        w, t, n, _se = mc_adaptive(hole_cards, board, num_opponents)
    else:
        w, t, n = mc_counts(hole_cards, board, num_opponents, num_simulations)
    return EquityResult(_ratio(w, t, n), f"mc:{n}", n)


def standard_error(result: EquityResult) -> float:
    """에퀴티 추정의 표준오차(1σ, 0~1 단위) — Play Grader 경계 판정용(ADR 0039).

    - 전수(`exact`)·프리플랍 상수 테이블(`preflop-table`)·`none`: 0 (정확값으로 취급)
    - MC(`mc:N`): sqrt(p(1−p)/N). 한 샘플의 지분(0·1/k·1) 분산은 p(1−p) 이하라 이 값은
      실제 표준오차의 상한이다(동률이 있으면 약간 크게 잡힌다 — 경계를 넓히는 쪽).
    """
    if not result.source.startswith("mc:") or result.samples <= 0:
        return 0.0
    p = result.equity
    return math.sqrt(max(0.0, p * (1.0 - p)) / result.samples)


def smart_equity(
    hole_cards: List[Card],
    board: List[Card],
    num_opponents: int = 1,
    num_simulations: Optional[int] = None,
) -> float:
    """equity_detail의 에퀴티 값만 (0.0~1.0)."""
    return equity_detail(hole_cards, board, num_opponents, num_simulations).equity


# ──────────────────────────────────────────
# 레인지 기반 샘플링 (B단계)
# ──────────────────────────────────────────

_NOTATION_RANK = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8,
                  "9": 9, "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14}


def _notation_combos(notation: str) -> List[Tuple[Card, Card]]:
    """'AKs' → 4콤보, 'AKo' → 12콤보, 'AA' → 6콤보"""
    r1 = _RANK_BY_VALUE[_NOTATION_RANK[notation[0]]]
    r2 = _RANK_BY_VALUE[_NOTATION_RANK[notation[1]]]
    combos = []
    if r1 == r2:  # 페어
        for i in range(4):
            for j in range(i + 1, 4):
                combos.append((Card(r1, _SUITS[i]), Card(r2, _SUITS[j])))
    elif notation.endswith("s"):
        for s in _SUITS:
            combos.append((Card(r1, s), Card(r2, s)))
    else:  # 오프수트
        for s1 in _SUITS:
            for s2 in _SUITS:
                if s1 != s2:
                    combos.append((Card(r1, s1), Card(r2, s2)))
    return combos


class RangeSampler:
    """
    가중 레인지에서 홀카드 콤보를 샘플링.
    weights: {"AKs": 0.8, "QQ": 1.0, ...} — GTO 액션 빈도가 가중치.
    """

    def __init__(self, weights: dict):
        import bisect
        self._bisect = bisect
        self.combos: List[Tuple[Card, Card]] = []
        self.cum: List[float] = []
        total = 0.0
        for notation, w in weights.items():
            try:
                for combo in _notation_combos(notation):
                    total += w
                    self.combos.append(combo)
                    self.cum.append(total)
            except (KeyError, IndexError):
                continue
        self.total = total

    def restricted(self, blocked: set) -> Optional["RangeSampler"]:
        """blocked 카드와 겹치는 콤보를 뺀 새 샘플러(가중치 유지). 남는 콤보가 없으면 None."""
        sub = RangeSampler({})
        total = 0.0
        prev = 0.0
        for combo, cum in zip(self.combos, self.cum):
            w = cum - prev
            prev = cum
            if combo[0] in blocked or combo[1] in blocked or w <= 0:
                continue
            total += w
            sub.combos.append(combo)
            sub.cum.append(total)
        sub.total = total
        return sub if sub.combos else None

    def draw(self) -> Tuple[Card, Card]:
        """가중치대로 콤보 1개 (블로커 무시 — 호출자가 거절 판단)."""
        i = self._bisect.bisect_left(self.cum, random.random() * self.total)
        return self.combos[min(i, len(self.combos) - 1)]

    def sample(self, blocked: set) -> Optional[Tuple[Card, Card]]:
        """blocked와 겹치지 않는 콤보 샘플. 30회 실패 시 None (랜덤 폴백)."""
        if not self.combos:
            return None
        for _ in range(30):
            i = self._bisect.bisect_left(self.cum, random.random() * self.total)
            c1, c2 = self.combos[min(i, len(self.combos) - 1)]
            if c1 not in blocked and c2 not in blocked:
                return c1, c2
        return None


_JOINT_MAX_TRIES = 200


def _ranged_runner(
    hole_cards: List[Card],
    board: List[Card],
    samplers: List[Optional[RangeSampler]],
):
    """
    상대별 레인지 샘플러를 적용한 MC 러너 run(n) → (wins, ties, 지분 제곱합).
    samplers의 None은 랜덤 핸드. 레인지 조건부 분포다. 블로커 제거는 한 번만 한다.

    상대 홀카드는 결합분포 Π w_i(h_i)·[카드 비중복]에서 뽑는다(T-034):
    1) 각 레인지에서 내 홀·보드와 겹치는 콤보를 미리 뺀다(남는 게 없으면 랜덤 상대).
    2) 레인지 상대 전원을 독립으로 한 번에 뽑고, 서로 겹치면 전체를 다시 뽑는다(결합 거절 샘플링).
    3) 랜덤 상대는 남은 카드에서 균등하게 뽑는다(균등 가중이라 조건부도 균등 — 정확).
    상대를 한 명씩 차례로 뽑으면(이전 방식) 결합분포가 아니어서 좁은 레인지끼리 편향된다.
    거절이 _JOINT_MAX_TRIES번 연속이면(레인지끼리 거의 전부 겹침) 그 샘플만 순차 방식으로 대체한다.
    """
    known = set(hole_cards) | set(board)
    deck = [c for c in _FULL_DECK if c not in known]
    need = 5 - len(board)

    restricted = [s.restricted(known) if s else None for s in samplers]
    ranged = [s for s in restricted if s is not None]
    n_random = len(restricted) - len(ranged)

    def run(num_simulations: int) -> Tuple[float, float, float]:
        wins = ties = sq = 0.0
        for _ in range(num_simulations):
            opp_holes = None
            for _try in range(_JOINT_MAX_TRIES):
                holes = [s.draw() for s in ranged]
                cards_used = {c for pair in holes for c in pair}
                if len(cards_used) == 2 * len(holes):
                    opp_holes = holes
                    break
            if opp_holes is None:  # 드문 폴백: 순차 샘플링
                opp_holes = []
                cards_used = set()
                for s in ranged:
                    pair = s.sample(known | cards_used)
                    if pair is None:
                        pair = tuple(random.sample(
                            [c for c in deck if c not in cards_used], 2))
                    opp_holes.append(pair)
                    cards_used.update(pair)

            blocked = known | cards_used
            avail = [c for c in deck if c not in blocked]
            if n_random:
                rnd = random.sample(avail, 2 * n_random)
                opp_holes = opp_holes + [(rnd[2 * i], rnd[2 * i + 1]) for i in range(n_random)]
                blocked = blocked | set(rnd)
                avail = [c for c in avail if c not in blocked]
            board_fill = random.sample(avail, need) if need else []
            full = board + board_fill

            mine = evaluate_rank(hole_cards + full)
            w, t = _showdown_share(mine, [evaluate_rank(list(pair) + full) for pair in opp_holes])
            wins += w
            ties += t
            share = w + 0.5 * t
            sq += share * share
        return wins, ties, sq

    return run


def mc_counts_ranged(
    hole_cards: List[Card],
    board: List[Card],
    samplers: List[Optional[RangeSampler]],
    num_simulations: int,
) -> Tuple[float, float, int]:
    """레인지 반영 고정 샘플 MC: (wins, ties, total)."""
    w, t, _ = _ranged_runner(hole_cards, board, samplers)(num_simulations)
    return w, t, num_simulations


def mc_adaptive_ranged(
    hole_cards: List[Card],
    board: List[Card],
    samplers: List[Optional[RangeSampler]],
    **kw,
) -> Tuple[float, float, int, float]:
    """레인지 반영 적응형 MC: (wins, ties, total, 표준오차). kw는 _adaptive 인자."""
    return _adaptive(_ranged_runner(hole_cards, board, samplers), **kw)


def ranged_equity(
    hole_cards: List[Card],
    board: List[Card],
    samplers: List[Optional[RangeSampler]],
    num_simulations: Optional[int] = None,
) -> float:
    """
    레인지 반영 equity (조건부 분포). num_simulations가 None이면 적응형 MC
    (SE ≤ TARGET_SE, ADR 0045), 정수면 그 수만큼 고정 MC.
    """
    if len(hole_cards) < 2 or not samplers:
        return 0.5
    if num_simulations is None:
        w, t, n, _se = mc_adaptive_ranged(hole_cards, board, samplers)
    else:
        w, t, n = mc_counts_ranged(hole_cards, board, samplers, num_simulations)
    return _ratio(w, t, n)


def made_hand_rank(hole_cards: List[Card], community_cards: List[Card]) -> int:
    """
    현재 보드 기준 '완성된' 핸드 랭크 (1=하이카드 ~ 10=로열플러시).
    equity는 높은데 made rank가 낮으면 드로우 → 세미블러프 후보.
    """
    if len(hole_cards) < 2 or len(community_cards) < 3:
        return 1
    return evaluate_rank(hole_cards + community_cards)[0]
