#!/usr/bin/env python3
"""
봇 vs 봇 아레나 — AI 개선 검증 도구

서로 다른 봇 프로파일을 같은 테이블에 앉혀 N핸드 돌리고 bb/100 승률을 비교한다.
매 핸드 종료 후 전원 스택을 100bb로 리셋 (캐시게임 방식) → 파산 없음, 공정한 비교.
딜러 버튼이 자동 로테이션되므로 포지션 유불리는 장기적으로 상쇄된다.

사용법:
  python3 scripts/bot_arena.py --hands 300 --seats hard,medium,easy,legacy,legacy,legacy
  python3 scripts/bot_arena.py --hands 200 --seats hard,legacy --seed 42

프로파일:
  easy / medium / hard : 현재 equity 기반 봇 난이도
  legacy               : 개선 전 핸드랭크 휴리스틱 봇 (베이스라인)
"""

import argparse
import random
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.game import Action
from ai.bot import PokerBot, BotDifficulty
from server.session import WebGameSession


# ──────────────────────────────────────────
# 레거시 봇 (개선 전 포스트플랍 휴리스틱 재현)
# ──────────────────────────────────────────

class LegacyBot(PokerBot):
    """프리플랍 GTO는 동일, 포스트플랍만 구버전 핸드랭크 휴리스틱"""

    def _postflop_decision(self, state):
        strength = self._legacy_strength(state)
        call_amount = max(0, state["current_bet"] - self.player.current_bet)
        pot = state["pot"]
        pot_odds = call_amount / (pot + call_amount) if (pot + call_amount) > 0 else 0

        if strength > 0.75:
            return self._raise_action(state, pot_frac=random.uniform(0.5, 0.8))
        elif strength > pot_odds + 0.1:
            if call_amount == 0:
                if strength > 0.55:
                    return self._raise_action(state, pot_frac=0.5)
                return Action.CHECK, 0
            return Action.CALL, call_amount
        elif strength > pot_odds and random.random() < 0.2:
            return self._raise_action(state, pot_frac=0.5)
        else:
            if call_amount == 0:
                return Action.CHECK, 0
            return Action.FOLD, 0

    def _legacy_strength(self, state) -> float:
        """구버전: 핸드 랭크 / 10 (+ 키커 보정)"""
        from core.evaluator import HandEvaluator
        hole = self.player.hole_cards
        community = self._parse_community_cards(state.get("community_cards", []))
        if len(hole) < 2 or len(community) < 3:
            return self._preflop_strength(hole) if len(hole) >= 2 else 0.5
        result = HandEvaluator.evaluate(hole + community)
        rank_val = result.hand_rank.rank_value
        if rank_val >= 2 and result.tiebreakers:
            sub = min(result.tiebreakers[0] / 14.0, 1.0) * 0.09
            return min(rank_val / 10.0 + sub, 1.0)
        return rank_val / 10.0


PROFILE_MAP = {
    "easy": BotDifficulty.EASY,
    "medium": BotDifficulty.MEDIUM,
    "hard": BotDifficulty.HARD,
}


def parse_seat(spec: str):
    """
    시트 문법: "hard" | "hard:persona=aggressive" | "hard:aggression_margin=0.12+bluff_freq=0.3"
    반환: (base_profile, persona, overrides)
    """
    if ":" not in spec:
        return spec, "balanced", {}
    base, opts = spec.split(":", 1)
    persona = "balanced"
    overrides = {}
    for kv in opts.split("+"):
        k, v = kv.split("=")
        if k == "persona":
            persona = v
        else:
            overrides[k] = float(v)
    return base, persona, overrides


def make_driver(spec: str, player) -> PokerBot:
    base, persona, overrides = parse_seat(spec)
    if base == "legacy":
        return LegacyBot(player, BotDifficulty.MEDIUM, persona=persona)
    return PokerBot(player, PROFILE_MAP[base], persona=persona, overrides=overrides)


def run_arena(seats: list, hands: int, big_blind: int, seed=None, verbose=False):
    if seed is not None:
        random.seed(seed)

    start_chips = big_blind * 100  # 100bb
    session = WebGameSession(
        session_id="arena",
        human_name="Seat0",
        chips=start_chips,
        num_bots=len(seats) - 1,
        difficulty="medium",
        small_blind=big_blind // 2,
    )

    # 좌석별 프로파일 배정
    all_players = session.game.players           # [human, bots...]
    drivers = {}                                 # name → 사람 좌석 드라이버
    seat_profile = {}                            # name → profile 문자열
    for i, player in enumerate(all_players):
        profile = seats[i]
        seat_profile[player.name] = profile
        if player.is_human:
            drivers[player.name] = make_driver(profile, player)
        else:
            session.bots[player.name] = make_driver(profile, player)

    profit = {p.name: 0 for p in all_players}    # 누적 칩 손익
    t0 = time.time()

    for h in range(hands):
        # 사람 좌석 차례를 드라이버 봇으로 진행
        guard = 0
        while not session.hand_over and not session.game_over:
            player = session._next_to_act()
            if player is None or not player.is_human:
                break  # 방어적 탈출 (정상 흐름에선 발생 안 함)
            gs = session.game._get_game_state()
            gs["action_log"] = session.action_log
            action, amount = drivers[player.name].decide_action(gs)
            session.submit_action(action.value, amount)
            guard += 1
            if guard > 100:
                raise RuntimeError("핸드가 끝나지 않음 (무한 루프 감지)")

        # 칩 총량 보존 검증 (엔진 퍼징) — 팟 분배 후 총합은 불변이어야 함
        total = sum(p.chips for p in session.game.players)
        expected = start_chips * len(session.game.players)
        assert total == expected, (
            f"칩 보존 위반! 핸드 {h+1}: 총 {total} != {expected} "
            f"({ {p.name: p.chips for p in session.game.players} })")

        # 손익 기록 + 스택 리셋
        for p in session.game.players:
            profit[p.name] += p.chips - start_chips
            p.chips = start_chips

        if verbose or (h + 1) % 50 == 0:
            elapsed = time.time() - t0
            print(f"  {h+1}/{hands} 핸드 ({elapsed:.0f}s)")

        session.game_over = False  # 리셋했으므로 계속
        session.next_hand()

    return profit, seat_profile


def report(profit: dict, seat_profile: dict, hands: int, big_blind: int):
    print(f"\n{'='*56}")
    print(f"  아레나 결과  ({hands}핸드, BB={big_blind})")
    print(f"{'='*56}")

    print(f"\n  [좌석별]")
    for name, chips in sorted(profit.items(), key=lambda x: -x[1]):
        bb100 = chips / big_blind / hands * 100
        print(f"    {name:12s} ({seat_profile[name]:6s}) "
              f"{chips:+8,d}칩  {bb100:+7.1f} bb/100")

    # 프로파일별 집계 (같은 프로파일 여러 좌석 → 평균)
    agg = {}
    for name, chips in profit.items():
        agg.setdefault(seat_profile[name], []).append(chips)
    print(f"\n  [프로파일별 평균]")
    for prof, chip_list in sorted(agg.items(),
                                  key=lambda x: -sum(x[1]) / len(x[1])):
        avg = sum(chip_list) / len(chip_list)
        bb100 = avg / big_blind / hands * 100
        print(f"    {prof:8s} × {len(chip_list)}좌석  "
              f"평균 {avg:+9,.0f}칩  {bb100:+7.1f} bb/100")
    print()


def main():
    parser = argparse.ArgumentParser(description="봇 vs 봇 아레나")
    parser.add_argument("--hands", type=int, default=200)
    parser.add_argument("--seats", type=str,
                        default="hard,medium,easy,legacy,legacy,legacy",
                        help="쉼표 구분 프로파일 (2~6개)")
    parser.add_argument("--bb", type=int, default=20, help="빅 블라인드")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    seats = [s.strip() for s in args.seats.split(",")]
    if not 2 <= len(seats) <= 6:
        sys.exit("좌석은 2~6개")
    for s in seats:
        base = s.split(":")[0]
        if base not in ("easy", "medium", "hard", "legacy"):
            sys.exit(f"알 수 없는 프로파일: {base}")

    print(f"아레나 시작: {seats}, {args.hands}핸드")
    profit, seat_profile = run_arena(
        seats, args.hands, args.bb, seed=args.seed, verbose=args.verbose)
    report(profit, seat_profile, args.hands, args.bb)


if __name__ == "__main__":
    main()
