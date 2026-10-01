"""
독립 홀덤 평가기 — 프로젝트 코드를 import하지 않는 브루트포스 기준 구현.

`ai/equity.py`·`core/evaluator.py`가 맞는지 다른 알고리즘으로 대조하려고 둔다
(`tests/test_equity_verify.py`). 프로젝트 모듈을 import하면 같은 버그를 공유하므로
이 파일은 표준 라이브러리만 쓴다.

카드 = 정수 0..51, 랭크 = 2 + (c >> 2) (2..14), 수트 = c & 3.
rank7(cards) → (카테고리 1..10, 타이브레이크 튜플) — `core.evaluator.evaluate_rank`와
같은 비교 포맷이라 값 자체로 동일성을 비교할 수 있다(계산 방식은 따로 작성).
"""
import random
from itertools import combinations

RANK_OF = [2 + (c >> 2) for c in range(52)]
SUIT_OF = [c & 3 for c in range(52)]
DECK = list(range(52))

# 스트레이트 패턴: 비트 r = 랭크 r 존재 (A=14, 휠을 위해 A를 1로도 센다)
_STRAIGHT_MASKS = [(sum(1 << (h - i) for i in range(5)), h) for h in range(14, 4, -1)]


def _straight_high(mask):
    if mask & (1 << 14):
        mask |= 1 << 1
    for m, h in _STRAIGHT_MASKS:
        if mask & m == m:
            return h
    return 0


def rank7(cards):
    """5~7장 카드의 최고 핸드 랭크 (카테고리, 타이브레이크)."""
    cnt = [0] * 15
    by_suit = [[], [], [], []]
    mask = 0
    for c in cards:
        r = RANK_OF[c]
        cnt[r] += 1
        by_suit[SUIT_OF[c]].append(r)
        mask |= 1 << r
    flush = None
    for s in range(4):
        if len(by_suit[s]) >= 5:
            flush = sorted(by_suit[s], reverse=True)
            break
    if flush is not None:
        fm = 0
        for r in flush:
            fm |= 1 << r
        sh = _straight_high(fm)
        if sh == 14:
            return (10, (14,))
        if sh:
            return (9, (sh,))
    groups = sorted(((n, r) for r, n in enumerate(cnt) if n), reverse=True)  # (장수, 랭크) 내림차순
    if groups[0][0] == 4:
        q = groups[0][1]
        kicker = max(r for r in range(2, 15) if cnt[r] and r != q)
        return (8, (q, kicker))
    if groups[0][0] == 3 and groups[1][0] >= 2:
        return (7, (groups[0][1], groups[1][1]))
    if flush is not None:
        return (6, tuple(flush[:5]))
    sh = _straight_high(mask)
    if sh:
        return (5, (sh,))
    if groups[0][0] == 3:
        t = groups[0][1]
        ks = sorted((r for r in range(2, 15) if cnt[r] and r != t), reverse=True)[:2]
        return (4, (t,) + tuple(ks))
    if groups[0][0] == 2 and groups[1][0] == 2:
        p1, p2 = groups[0][1], groups[1][1]
        k = max(r for r in range(2, 15) if cnt[r] and r not in (p1, p2))
        return (3, (p1, p2, k))
    if groups[0][0] == 2:
        p = groups[0][1]
        ks = sorted((r for r in range(2, 15) if cnt[r] and r != p), reverse=True)[:3]
        return (2, (p,) + tuple(ks))
    highs = sorted((r for r in range(2, 15) if cnt[r]), reverse=True)[:5]
    return (1, tuple(highs))


def share(mine, opp_ranks):
    """내 지분: 이기면 1, 지면 0, 나 포함 k명 동률이면 1/k."""
    best = max(opp_ranks)
    if mine > best:
        return 1.0
    if mine < best:
        return 0.0
    k = 1 + sum(1 for r in opp_ranks if r == best)
    return 1.0 / k


def mc_random(hole, board, n_opp, n, rng=None):
    """vs 랜덤 n_opp명 MC. 반환 (평균 지분, 지분 제곱 평균)."""
    rng = rng or random.Random()
    known = set(hole) | set(board)
    deck = [c for c in DECK if c not in known]
    need = 5 - len(board)
    tot = 0.0
    sq = 0.0
    for _ in range(n):
        d = rng.sample(deck, need + 2 * n_opp)
        full = list(board) + d[:need]
        mine = rank7(list(hole) + full)
        opps = [rank7(d[need + 2 * i: need + 2 * i + 2] + full) for i in range(n_opp)]
        s = share(mine, opps)
        tot += s
        sq += s * s
    return tot / n, sq / n


def exact_river_1(hole, board):
    """리버 vs 1명 전수: (지분 평균, 조합 수 990)."""
    known = set(hole) | set(board)
    deck = [c for c in DECK if c not in known]
    mine = rank7(list(hole) + list(board))
    tot = 0.0
    n = 0
    for a, b in combinations(deck, 2):
        tot += share(mine, [rank7([a, b] + list(board))])
        n += 1
    return tot / n, n


def _pairings(cards):
    """카드 2k장을 k쌍으로 나누는 모든 방법."""
    if not cards:
        yield []
        return
    a = cards[0]
    for i in range(1, len(cards)):
        rest = cards[1:i] + cards[i + 1:]
        for p in _pairings(rest):
            yield [(a, cards[i])] + p


def exact_ranged(hole, board, ranges, n_random=0):
    """
    레인지 상대 결합분포 Π wᵢ(hᵢ)·[카드 비중복] × 랜덤 상대 × 런아웃 전수로 낸 내 지분 기댓값.
    ranges: [{표기: 가중치}, ...]. 작은 레인지·리버/턴에서만 현실적인 속도다.
    """
    known = set(hole) | set(board)
    lists = []
    for r in ranges:
        lst = []
        for note, w in r.items():
            for a, b in notation_combos(note):
                if a not in known and b not in known:
                    lst.append(((a, b), w))
        lists.append(lst)
    deck = [c for c in DECK if c not in known]
    need = 5 - len(board)
    num = den = 0.0

    def rec(i, used, w, picks):
        nonlocal num, den
        if i == len(lists):
            rest = [c for c in deck if c not in used]
            sub_tot = 0.0
            sub_n = 0
            for extra in combinations(rest, 2 * n_random + need):
                for board_part in combinations(extra, need):
                    opp_part = [c for c in extra if c not in board_part]
                    full = list(board) + list(board_part)
                    mine = rank7(list(hole) + full)
                    fixed = [rank7(list(p) + full) for p in picks]
                    for pairing in _pairings(opp_part):
                        rks = fixed + [rank7(list(p) + full) for p in pairing]
                        sub_tot += share(mine, rks)
                        sub_n += 1
            num += w * sub_tot
            den += w * sub_n
            return
        for (a, b), wi in lists[i]:
            if a in used or b in used:
                continue
            rec(i + 1, used | {a, b}, w * wi, picks + [(a, b)])

    rec(0, frozenset(), 1.0, [])
    return num / den


# ── 카드 표기 ('As' ↔ 정수) ──
RANK_CHARS = "23456789TJQKA"
SUIT_CHARS = "shdc"


def parse(spec):
    """'As' → 정수"""
    return RANK_CHARS.index(spec[0]) * 4 + SUIT_CHARS.index(spec[1])


def to_spec(c):
    return RANK_CHARS[c >> 2] + SUIT_CHARS[c & 3]


def notation_combos(note):
    """'AKs' → 정수 콤보 4개, 'AKo' → 12개, 'AA' → 6개"""
    r1 = RANK_CHARS.index(note[0])
    r2 = RANK_CHARS.index(note[1])
    out = []
    if r1 == r2:
        for s1 in range(4):
            for s2 in range(s1 + 1, 4):
                out.append((r1 * 4 + s1, r2 * 4 + s2))
    elif note.endswith("s"):
        for s in range(4):
            out.append((r1 * 4 + s, r2 * 4 + s))
    else:
        for s1 in range(4):
            for s2 in range(4):
                if s1 != s2:
                    out.append((r1 * 4 + s1, r2 * 4 + s2))
    return out
