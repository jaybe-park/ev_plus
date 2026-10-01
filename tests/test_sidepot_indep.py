"""사이드팟 분배 독립 대조 — core `TexasHoldem.showdown()` vs 테스트 쪽 독립 계산기.

독립 계산기(`ref_distribute`)는 core 코드를 하나도 쓰지 않고 기여액·폴드 여부·핸드 강도 순위·
버튼 위치만으로 계층별 분배를 계산한다:
  1) 아무도 콜하지 않은 초과 베팅(최대 기여 − 두 번째 기여)은 그 사람에게 반환 계층으로 돌려준다.
  2) 나머지는 폴드하지 않은 사람의 기여 수준 오름차순으로 자른 계층마다, 그 수준까지 낸
     (폴드 안 한) 사람 중 강도 최고가 균등 분할하고, 홀수 칩은 버튼 왼쪽부터 시계 방향 첫 승자.
core 쪽은 핸드 평가기를 강도 순위 조회로 바꿔(분배만 검사) 같은 입력을 넣는다.

시나리오 2,000개(시드 고정): 주입 1,500(2~7인, 동률 잦은 기여액·폴드·강도) + 실제 액션 경로
500(core play_round + 무작위 콜백, 숏스택 올인 위주). 각 플레이어 칩 증가분(홀수 칩 수령자 포함)과
계층 목록(금액·eligible·승자·반환 여부)을 대조한다.

단독 실행: python3 tests/test_sidepot_indep.py
"""
import os
import random
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("EV_PLUS_DB", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

import core.game as core_game  # noqa: E402
from core.card import Card, Rank, Suit  # noqa: E402
from core.game import Action, TexasHoldem  # noqa: E402
from core.player import Player  # noqa: E402

SEED = 4242
N_INJECTED = 1500
N_PLAYED = 500
TIME_LIMIT_SEC = 2.0
DECK = [Card(r, s) for s in Suit for r in Rank]


# ── 독립 계산기 (core 코드 공유 없음) ─────────────────────────────

def ref_distribute(seats, contrib, folded, strength, dealer):
    """seats: 좌석 순서 이름, contrib: {이름: 이번 핸드 기여}, folded: 폴드한 이름 집합,
    strength: {이름: 강도(클수록 강함)}, dealer: 버튼 좌석 인덱스.
    반환: (gain {이름: 받은 칩}, layers [(금액, eligible 집합, 승자 집합, 반환 여부)])."""
    n = len(seats)
    live = [p for p in seats if p not in folded]
    gain = {p: 0 for p in seats}
    left = dict(contrib)
    layers = []
    if len(live) == 1:
        total = sum(contrib.values())
        gain[live[0]] = total
        return gain, [(total, {live[0]}, {live[0]}, False)]

    # 1) 콜되지 않은 초과 베팅 반환
    ranked = sorted(seats, key=lambda p: left[p], reverse=True)
    returned = None
    if left[ranked[0]] > left[ranked[1]]:
        top = ranked[0]
        extra = left[top] - left[ranked[1]]
        left[top] -= extra
        gain[top] += extra
        returned = (extra, {top}, {top}, True)

    # 2) 살아 있는 사람의 기여 수준으로 자른 계층
    def clockwise_from_button_left(names):
        return sorted(names, key=lambda p: (seats.index(p) - dealer - 1) % n)

    prev = 0
    for lv in sorted({left[p] for p in live if left[p] > 0}):
        amount = sum(max(0, min(left[p], lv) - prev) for p in seats)
        eligible = {p for p in live if left[p] >= lv}
        best = max(strength[p] for p in eligible)
        winners = {p for p in eligible if strength[p] == best}
        each, odd = divmod(amount, len(winners))
        for w in winners:
            gain[w] += each
        if odd:
            gain[clockwise_from_button_left(winners)[0]] += odd
        layers.append((amount, eligible, winners, False))
        prev = lv
    leftover = sum(max(0, left[p] - prev) for p in seats)
    assert leftover == 0, f"살아 있는 최고 기여보다 많이 낸 폴드 기여(실전 불가): {contrib} {folded}"
    if returned:
        layers.append(returned)
    return gain, layers


# ── core 실행 (평가기를 강도 조회로 대체) ──────────────────────────

class _StrengthEvaluator:
    """core.game.HandEvaluator 대용: 홀카드 두 장(첫 두 원소)으로 미리 정한 강도를 돌려준다."""
    table = {}

    @classmethod
    def evaluate(cls, cards):
        return cls.table[(str(cards[0]), str(cards[1]))]


def _core_showdown(game, strength):
    _StrengthEvaluator.table = {(str(p.hole_cards[0]), str(p.hole_cards[1])): strength[p.name]
                                for p in game.players}
    before = {p.name: p.chips for p in game.players}
    res = game.showdown()
    gain = {p.name: p.chips - before[p.name] for p in game.players}
    layers = [(s.amount, {p.name for p in s.eligible}, {p.name for p in s.winners}, s.returned)
              for s in res.pots]
    return gain, layers, res


def _check(game, seats, contrib, folded, strength, label):
    want_gain, want_layers = ref_distribute(seats, contrib, folded, strength, game.dealer_index)
    gain, layers, res = _core_showdown(game, strength)
    ctx = f"{label}: seats={seats} dealer={game.dealer_index} contrib={contrib} folded={folded} strength={strength}"
    assert gain == want_gain, f"칩 분배 불일치 {ctx}\n  core={gain}\n  ref ={want_gain}"
    assert layers == want_layers, f"계층 불일치 {ctx}\n  core={layers}\n  ref ={want_layers}"
    assert sum(gain.values()) == sum(contrib.values()) and game.pot == 0, f"팟 보존 실패 {ctx}"
    want_winners = set().union(*[w for _, _, w, ret in want_layers if not ret])
    assert {w.name for w in res.winners} == want_winners, f"승자 목록 불일치 {ctx}"


def _injected(rng):
    n = rng.randint(2, 7)
    players = [Player(f"P{i}", 0, is_human=(i == 0)) for i in range(n)]
    game = TexasHoldem(players, 10, 20)
    game.dealer_index = rng.randrange(n)
    cards = rng.sample(DECK, 2 * n)
    levels = rng.sample(range(1, 400), rng.randint(1, 4))   # 같은 기여액(동률 계층)이 잦게
    contrib = {p.name: (rng.choice(levels) if rng.random() < 0.85 else rng.randint(0, 400))
               for p in players}
    folded = {p.name for p in players if rng.random() < 0.3}
    if len(folded) == n:
        folded.discard(players[rng.randrange(n)].name)
    live_max = max(contrib[p] for p in contrib if p not in folded)
    for p in folded:                       # 실전에서 폴드한 사람은 살아 있는 최고 기여를 넘지 못한다
        contrib[p] = min(contrib[p], live_max)
    strength = {p.name: rng.randint(1, 4) for p in players}   # 동률(스플릿)이 잦게
    for i, p in enumerate(players):
        p.hole_cards = cards[2 * i:2 * i + 2]
        p.total_bet_this_round = contrib[p.name]
        p.chips = 1000
        p.is_folded = p.name in folded
    game.pot = sum(contrib.values())
    _check(game, [p.name for p in players], contrib, folded, strength, "주입")


def _played(rng):
    n = rng.randint(2, 7)
    stacks = [rng.choice([rng.randint(5, 60), rng.randint(100, 1500)]) for _ in range(n)]
    players = [Player(f"P{i}", stacks[i], is_human=(i == 0)) for i in range(n)]
    game = TexasHoldem(players, 10, 20)
    game.dealer_index = rng.randrange(n)

    def cb(player, state):
        r = rng.random()
        shove = 0.5 if player.chips + player.current_bet <= 100 else 0.12
        if r < shove:
            return Action.ALL_IN, 0
        if r < shove + 0.15:
            return Action.FOLD, 0
        if r < shove + 0.35:
            return Action.CHECK, 0
        if r < shove + 0.7:
            return Action.CALL, 0
        return Action.RAISE, rng.randint(0, state["current_bet"] * 3 + 100)

    game._action_callback = cb
    game.start_hand()
    game.play_round()
    while game.advance_street() is not None:
        game.play_round()
    contrib = {p.name: p.total_bet_this_round for p in players}
    folded = {p.name for p in players if p.is_folded}
    strength = {p.name: rng.randint(1, 4) for p in players}
    assert game.pot == sum(contrib.values())
    _check(game, [p.name for p in players], contrib, folded, strength, "실제 경로")


def test_sidepot_matches_independent_calculator():
    """시나리오 2,000개(시드 고정)에서 core showdown()과 독립 계산기의 칩 분배·계층이 같다(2초 이내)."""
    rng = random.Random(SEED)
    real = core_game.HandEvaluator
    core_game.HandEvaluator = _StrengthEvaluator
    start = time.perf_counter()
    try:
        for _ in range(N_INJECTED):
            _injected(rng)
        for _ in range(N_PLAYED):
            _played(rng)
    finally:
        core_game.HandEvaluator = real
    elapsed = time.perf_counter() - start
    assert elapsed < TIME_LIMIT_SEC, f"2,000 시나리오가 {elapsed:.2f}s (한도 {TIME_LIMIT_SEC}s)"


def test_ref_distribute_examples():
    """독립 계산기 자체의 손 계산 예: 100/300/600 올인(강도 3>2>1) → 메인 300·사이드 400·반환 300."""
    seats = ["A", "B", "C"]
    gain, layers = ref_distribute(seats, {"A": 100, "B": 300, "C": 600}, set(),
                                  {"A": 3, "B": 2, "C": 1}, 0)
    assert gain == {"A": 300, "B": 400, "C": 300}, gain
    assert layers == [(300, {"A", "B", "C"}, {"A"}, False), (400, {"B", "C"}, {"B"}, False),
                      (300, {"C"}, {"C"}, True)], layers
    # 폴드한 C의 돈이 든 계층은 반환이 아니라 A가 이긴 팟: A 600, B 100 올인, C 300 폴드
    gain, layers = ref_distribute(seats, {"A": 600, "B": 100, "C": 300}, {"C"},
                                  {"A": 1, "B": 2, "C": 9}, 0)
    assert gain == {"A": 700, "B": 300, "C": 0}, gain
    assert layers == [(300, {"A", "B"}, {"B"}, False), (400, {"A"}, {"A"}, False),
                      (300, {"A"}, {"A"}, True)], layers


if __name__ == "__main__":
    ok = True
    for fn in (test_ref_distribute_examples, test_sidepot_matches_independent_calculator):
        t = time.perf_counter()
        try:
            fn()
            print(f"  ✅ {fn.__name__} ({time.perf_counter() - t:.2f}s)", flush=True)
        except AssertionError as e:
            ok = False
            print(f"  ❌ {fn.__name__} → {e}", flush=True)
    sys.exit(0 if ok else 1)
