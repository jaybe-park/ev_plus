"""
에퀴티(승률) 계산 엔진

세 가지 계산 경로:
1. Monte Carlo 샘플링 — 실시간용. 샘플 수가 봇 난이도를 결정한다.
2. 전수조사(exact) — 리버/턴/플랍의 1:1 상황은 모든 조합을 열거해 정확값 산출.
3. equity_cache DB — 계산 결과를 수트 정규화 키로 누적 저장.
   봇이 플레이 중 만난 스팟은 자동으로 큐에 쌓이고,
   scripts/equity_worker.py 가 시간 날 때마다 정확값으로 바꿔간다.

수트 정규화(canonical key): A♥K♥와 A♠K♠는 같은 스팟이므로
24가지 수트 치환 중 사전순 최소 키를 대표로 쓴다.
"""

import atexit
import random
from itertools import combinations, permutations
from typing import List, Optional, Tuple

from core.card import Card, Suit, Rank
from core.evaluator import HandEvaluator, evaluate_rank

_FULL_DECK = [Card(r, s) for r in Rank for s in Suit]
_SUITS = [Suit.SPADES, Suit.HEARTS, Suit.DIAMONDS, Suit.CLUBS]

# 랭크 2~14 → 정렬 가능한 1글자 코드
_RANK_CODE = {2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8",
              9: "9", 10: "a", 11: "b", 12: "c", 13: "d", 14: "e"}
_CODE_RANK = {v: k for k, v in _RANK_CODE.items()}
_RANK_BY_VALUE = {r.rank_value: r for r in Rank}

# 캐시 신뢰 기준: 이 샘플 수를 넘으면 재계산 없이 캐시값 사용 (±0.35%)
HIGH_PRECISION_SAMPLES = 20_000

# 테스트에서 임시 DB로 교체 가능. None이면 기본 poker.db
DB_PATH: Optional[str] = None


# ──────────────────────────────────────────
# 수트 정규화 키
# ──────────────────────────────────────────

def street_of(board: List[Card]) -> str:
    return {0: "preflop", 3: "flop", 4: "turn", 5: "river"}[len(board)]


def _encode(cards: List[Card], smap: dict, sort: bool) -> str:
    toks = [_RANK_CODE[c.rank.rank_value] + str(smap[c.suit]) for c in cards]
    if sort:
        toks.sort(reverse=True)
    return "".join(toks)


def canonical_key(hole_cards: List[Card], board: List[Card]) -> str:
    """
    수트 치환에 불변인 스팟 키.
    형식: "홀|플랍|턴|리버" (턴/리버는 순서 유지 — 스트리트 경계가 의미 있음)
    """
    flop, turn, river = board[:3], board[3:4], board[4:5]
    best = None
    for perm in permutations(range(4)):
        smap = dict(zip(_SUITS, perm))
        key = "|".join([
            _encode(hole_cards, smap, True),
            _encode(flop, smap, True),
            _encode(turn, smap, False),
            _encode(river, smap, False),
        ])
        if best is None or key < best:
            best = key
    return best


def decode_key(spot_key: str) -> Tuple[List[Card], List[Card]]:
    """canonical key → (홀카드, 보드). 워커가 계산 대상 복원에 사용."""
    parts = spot_key.split("|")

    def dec(s: str) -> List[Card]:
        return [
            Card(_RANK_BY_VALUE[_CODE_RANK[s[i]]], _SUITS[int(s[i + 1])])
            for i in range(0, len(s), 2)
        ]

    hole = dec(parts[0])
    board = dec(parts[1]) + dec(parts[2]) + dec(parts[3])
    return hole, board


# ──────────────────────────────────────────
# Monte Carlo 샘플링
# ──────────────────────────────────────────

def mc_counts(
    hole_cards: List[Card],
    board: List[Card],
    num_opponents: int,
    num_simulations: int,
) -> Tuple[float, float, int]:
    """(wins, ties, total) 카운트 반환 — 누적 저장용."""
    known = set(hole_cards) | set(board)
    deck = [c for c in _FULL_DECK if c not in known]
    need = 5 - len(board)
    draw_count = need + 2 * num_opponents

    wins = 0.0
    ties = 0.0
    for _ in range(num_simulations):
        drawn = random.sample(deck, draw_count)
        full = board + drawn[:need]
        mine = evaluate_rank(hole_cards + full)

        best_opp = None
        for i in range(num_opponents):
            start = need + 2 * i
            opp = evaluate_rank(list(drawn[start:start + 2]) + full)
            if best_opp is None or opp > best_opp:
                best_opp = opp

        if mine > best_opp:
            wins += 1.0
        elif mine == best_opp:
            ties += 1.0
    return wins, ties, num_simulations


def calculate_equity(
    hole_cards: List[Card],
    community_cards: List[Card],
    num_opponents: int = 1,
    num_simulations: int = 200,
) -> float:
    """순수 MC 승률 (0.0~1.0). 캐시 없이 즉석 계산."""
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


EXACT_FUNCS = {
    "river": exact_counts_river,
    "turn": exact_counts_turn,
    "flop": exact_counts_flop,
}


# ──────────────────────────────────────────
# DB 캐시 연동
# ──────────────────────────────────────────

def _db():
    from db.connection import get_connection, _DEFAULT_DB_PATH
    return get_connection(DB_PATH or _DEFAULT_DB_PATH)


def cache_lookup(spot_key: str, num_opponents: int) -> Optional[dict]:
    try:
        conn = _db()
        row = conn.execute(
            "SELECT wins, ties, total, exact FROM equity_cache "
            "WHERE spot_key = ? AND num_opponents = ?",
            (spot_key, num_opponents),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        return dict(row)
    except Exception:
        return None


# MC 기여분 메모리 버퍼: (street, key, n_opp) → [wins, ties, total]
# 봇 결정마다 커밋하면 그라인드에서 쓰기 락 경합이 나므로 배치 플러시한다.
_contrib_buffer: dict = {}
_CONTRIB_FLUSH_AT = 25  # 스팟 25개 쌓이면 플러시


def _flush_contributions() -> None:
    if not _contrib_buffer:
        return
    items = list(_contrib_buffer.items())
    _contrib_buffer.clear()
    try:
        conn = _db()
        for (street, key, n_opp), (w, t, n) in items:
            cur = conn.execute(
                """
                INSERT INTO equity_cache(street, spot_key, num_opponents, wins, ties, total, exact)
                VALUES(?,?,?,?,?,?,0)
                ON CONFLICT(spot_key, num_opponents) DO UPDATE SET
                    wins = equity_cache.wins + excluded.wins,
                    ties = equity_cache.ties + excluded.ties,
                    total = equity_cache.total + excluded.total,
                    updated_at = datetime('now')
                WHERE equity_cache.exact = 0
                """,
                (street, key, n_opp, w, t, n),
            )
            cur.close()
        conn.commit()
        conn.close()
    except Exception:
        pass


atexit.register(lambda: _flush_contributions())


def cache_contribute(
    street: str, spot_key: str, num_opponents: int,
    wins: float, ties: float, total: int, exact: bool = False,
) -> None:
    """계산 결과를 캐시에 누적. MC 기여는 버퍼링 후 배치 플러시."""
    if not exact:
        buf = _contrib_buffer.setdefault((street, spot_key, num_opponents), [0.0, 0.0, 0])
        buf[0] += wins; buf[1] += ties; buf[2] += total
        if len(_contrib_buffer) >= _CONTRIB_FLUSH_AT:
            _flush_contributions()
        return
    try:
        conn = _db()
        if exact:
            cur = conn.execute(
                """
                INSERT INTO equity_cache(street, spot_key, num_opponents, wins, ties, total, exact)
                VALUES(?,?,?,?,?,?,1)
                ON CONFLICT(spot_key, num_opponents) DO UPDATE SET
                    wins = excluded.wins, ties = excluded.ties,
                    total = excluded.total, exact = 1,
                    updated_at = datetime('now')
                """,
                (street, spot_key, num_opponents, wins, ties, total),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO equity_cache(street, spot_key, num_opponents, wins, ties, total, exact)
                VALUES(?,?,?,?,?,?,0)
                ON CONFLICT(spot_key, num_opponents) DO UPDATE SET
                    wins = equity_cache.wins + excluded.wins,
                    ties = equity_cache.ties + excluded.ties,
                    total = equity_cache.total + excluded.total,
                    updated_at = datetime('now')
                WHERE equity_cache.exact = 0
                """,
                (street, spot_key, num_opponents, wins, ties, total),
            )
        cur.close()
        conn.commit()
        conn.close()
    except Exception:
        pass  # DB 문제 시 조용히 무시 (equity 계산 자체는 유효)


def _ratio(wins: float, ties: float, total: int) -> float:
    return (wins + 0.5 * ties) / total if total > 0 else 0.5


# ──────────────────────────────────────────
# 스마트 에퀴티 (봇 런타임 진입점)
# ──────────────────────────────────────────

def smart_equity(
    hole_cards: List[Card],
    board: List[Card],
    num_opponents: int = 1,
    num_simulations: int = 300,
    use_cache: bool = True,
    contribute: bool = True,
    exact_river: bool = False,
) -> float:
    """
    캐시 → 전수조사 → MC 순으로 최선의 equity 반환.

    - use_cache: 정확값/고정밀 누적값이 있으면 그대로 사용 (hard 봇용)
    - contribute: MC 결과를 캐시에 누적 → 봇이 칠수록 DB가 똑똑해짐.
      처음 만난 스팟은 자동으로 워커 큐에 등록되는 효과.
    - exact_river: 리버 1:1이면 전수조사(990조합, <1초)로 정확값 계산
    """
    if len(hole_cards) < 2:
        return 0.5

    street = street_of(board)
    key = None
    row = None
    if use_cache or contribute:
        key = canonical_key(hole_cards, board)
        row = cache_lookup(key, num_opponents)

    if use_cache and row:
        if row["exact"] or row["total"] >= HIGH_PRECISION_SAMPLES:
            return _ratio(row["wins"], row["ties"], row["total"])

    if exact_river and street == "river" and num_opponents == 1:
        w, t, n = exact_counts_river(hole_cards, board)
        if contribute and key:
            cache_contribute(street, key, 1, w, t, n, exact=True)
        return _ratio(w, t, n)

    w, t, n = mc_counts(hole_cards, board, num_opponents, num_simulations)
    if contribute and key:
        cache_contribute(street, key, num_opponents, w, t, n)

    # 캐시에 부분 누적이 있으면 합쳐서 더 정확한 추정치 사용
    if use_cache and row and not row["exact"] and row["total"] > 0:
        return _ratio(row["wins"] + w, row["ties"] + t, row["total"] + n)
    return _ratio(w, t, n)


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


def mc_counts_ranged(
    hole_cards: List[Card],
    board: List[Card],
    samplers: List[Optional[RangeSampler]],
    num_simulations: int,
) -> Tuple[float, float, int]:
    """
    상대별 레인지 샘플러를 적용한 MC. samplers의 None은 랜덤 핸드.
    레인지 조건부 분포라 equity_cache에는 저장하지 않는다.
    """
    known = set(hole_cards) | set(board)
    deck = [c for c in _FULL_DECK if c not in known]
    need = 5 - len(board)

    wins = ties = 0.0
    for _ in range(num_simulations):
        blocked = set(known)
        opp_holes = []
        for sampler in samplers:
            pair = sampler.sample(blocked) if sampler else None
            if pair is None:
                # 랜덤 폴백 (블록 카드와 겹치면 재시도 — 블록이 적어 드묾)
                while True:
                    c1, c2 = random.sample(deck, 2)
                    if c1 not in blocked and c2 not in blocked:
                        pair = (c1, c2)
                        break
            opp_holes.append(pair)
            blocked.add(pair[0])
            blocked.add(pair[1])

        avail = [c for c in deck if c not in blocked]
        board_fill = random.sample(avail, need) if need else []
        full = board + board_fill

        mine = evaluate_rank(hole_cards + full)
        best_opp = None
        for pair in opp_holes:
            opp = evaluate_rank(list(pair) + full)
            if best_opp is None or opp > best_opp:
                best_opp = opp

        if mine > best_opp:
            wins += 1.0
        elif mine == best_opp:
            ties += 1.0
    return wins, ties, num_simulations


def ranged_equity(
    hole_cards: List[Card],
    board: List[Card],
    samplers: List[Optional[RangeSampler]],
    num_simulations: int = 300,
) -> float:
    """레인지 반영 equity. 캐시 미사용 (조건부 분포)."""
    if len(hole_cards) < 2 or not samplers:
        return 0.5
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
