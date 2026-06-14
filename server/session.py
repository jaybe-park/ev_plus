"""
웹 게임 세션 — 한 번에 한 액션씩 처리하는 스텝 방식
HTTP 요청마다: 사람 액션 적용 → 봇들 자동 처리 → 다음 사람 차례까지 진행
이벤트 목록을 함께 반환해 프론트엔드 애니메이션에 활용
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import List, Optional, Dict

from core.game import TexasHoldem, Action, Street
from core.player import Player
from ai.bot import PokerBot, BotDifficulty
from gto.advisor import GTOAdvisor

STREETS = [Street.PREFLOP, Street.FLOP, Street.TURN, Street.RIVER]


class WebGameSession:
    def __init__(
        self,
        session_id: str,
        human_name: str,
        chips: int,
        num_bots: int,
        difficulty: str,
        small_blind: int,
    ):
        self.session_id = session_id
        diff_map = {
            "easy": BotDifficulty.EASY,
            "medium": BotDifficulty.MEDIUM,
            "hard": BotDifficulty.HARD,
        }
        difficulty_enum = diff_map.get(difficulty, BotDifficulty.MEDIUM)

        self.human = Player(human_name, chips, is_human=True)
        bot_names = ["🤖 Alpha", "🤖 Beta", "🤖 Gamma", "🤖 Delta", "🤖 Epsilon"]
        bot_players = [Player(bot_names[i], chips, is_human=False) for i in range(min(num_bots, 5))]

        all_players = [self.human] + bot_players
        self.game = TexasHoldem(all_players, small_blind=small_blind, big_blind=small_blind * 2)
        self.bots: Dict[str, PokerBot] = {
            p.name: PokerBot(p, difficulty_enum) for p in bot_players
        }
        self.gto = GTOAdvisor()

        # 베팅 라운드 상태
        self._order: List[Player] = []
        self._acted: set = set()
        self._round_i: int = 0
        self.street_index: int = 0

        # 핸드/게임 상태
        self.hand_number: int = 0
        self.hand_over: bool = False
        self.game_over: bool = False
        self.winners: List[str] = []
        self.showdown_hands: Dict[str, str] = {}
        self.action_log: List[str] = []

        # 애니메이션 이벤트 큐
        self._events: List[dict] = []

        self._start_new_hand()

    # ──────────────────────────────────────────
    # 공개 API
    # ──────────────────────────────────────────

    def submit_action(self, action_str: str, amount: int) -> None:
        if self.hand_over or self.game_over:
            return

        action_map = {
            "fold": Action.FOLD,
            "check": Action.CHECK,
            "call": Action.CALL,
            "raise": Action.RAISE,
            "allin": Action.ALL_IN,
        }
        action = action_map.get(action_str)
        if action is None:
            return

        player = self._next_to_act()
        if player is None or not player.is_human:
            return

        self._events = []  # 새 액션마다 이벤트 초기화
        self._apply(player, action, amount)
        self._run_until_human()

    def next_hand(self) -> None:
        if self.game_over:
            return
        self._events = []
        self._start_new_hand()

    def get_state(self) -> dict:
        positions = self.game.get_positions()
        next_player = self._next_to_act() if not self.hand_over else None
        waiting = next_player is not None and next_player.is_human

        call_amount = 0
        min_raise_to = 0
        if waiting:
            call_amount = max(0, self.game.current_bet - self.human.current_bet)
            min_raise_to = self.game.current_bet + self.game.min_raise

        players_out = []
        for p in self.game.players:
            # 봇 카드는 실제 쇼다운(여러 명 대결)이 있었을 때만 공개
            # 모두 폴드 → 1명 남은 경우는 카드 비공개
            had_showdown = bool(self.showdown_hands)
            reveal = p.is_human or (self.hand_over and not p.is_folded and had_showdown)
            players_out.append({
                "name": p.name,
                "chips": p.chips,
                "current_bet": p.current_bet,
                "is_folded": p.is_folded,
                "is_all_in": p.is_all_in,
                "is_human": p.is_human,
                "position": positions.get(p.name, ""),
                "hole_cards": [str(c) for c in p.hole_cards] if reveal else None,
            })

        # 이벤트를 반환하고 초기화 (한 번만 소비)
        events = list(self._events)
        self._events = []

        return {
            "session_id": self.session_id,
            "hand_number": self.hand_number,
            "street": self.game.current_street.value,
            "pot": self.game.pot,
            "current_bet": self.game.current_bet,
            "min_raise": self.game.min_raise,
            "big_blind": self.game.big_blind,
            "community_cards": [str(c) for c in self.game.community_cards],
            "players": players_out,
            "waiting_for_action": waiting,
            "hand_over": self.hand_over,
            "game_over": self.game_over,
            "winners": self.winners,
            "showdown_hands": self.showdown_hands,
            "gto_hint": self._get_gto_hint() if waiting else None,
            "action_log": self.action_log[-30:],
            "call_amount": call_amount,
            "min_raise_to": min_raise_to,
            "events": events,
        }

    # ──────────────────────────────────────────
    # 이벤트 발행 헬퍼
    # ──────────────────────────────────────────

    def _emit(self, event: dict) -> None:
        self._events.append(event)

    # ──────────────────────────────────────────
    # 핸드 시작
    # ──────────────────────────────────────────

    def _start_new_hand(self) -> None:
        self.hand_over = False
        self.winners = []
        self.showdown_hands = {}
        self.action_log = []

        # 파산 플레이어 제거
        self.game.players = [p for p in self.game.players if p.chips > 0]
        if len(self.game.players) < 2 or self.human not in self.game.players:
            self.game_over = True
            return
        self.game.dealer_index = self.game.dealer_index % len(self.game.players)

        self.hand_number += 1
        self.game.start_hand()
        self.game.current_street = Street.PREFLOP
        self.street_index = 0

        positions = self.game.get_positions()

        # 1. 카드 딜 이벤트 먼저 — SB부터 시작해서 2라운드 딜링
        n = len(self.game.players)
        dealing_order = [
            self.game.players[(self.game.dealer_index + 1 + i) % n]
            for i in range(n)
        ]
        for deal_round in range(1, 3):
            for p in dealing_order:
                self._emit({
                    "type": "deal_card",
                    "player": p.name,
                    "position": positions.get(p.name, ""),
                    "round": deal_round,
                    "street": "프리플랍",
                })

        # 2. 블라인드 이벤트 + 로그 (딜링 이후)
        for p in self.game.players:
            pos = positions.get(p.name, "")
            if pos in ("SB", "BTN/SB") and p.current_bet > 0:
                log_text = f"[{pos}] {p.name}: 스몰 블라인드 ({self.game.small_blind})"
                self.action_log.append(log_text)
                self._emit({
                    "type": "blind", "player": p.name, "position": pos,
                    "amount": self.game.small_blind, "street": "프리플랍",
                    "log": log_text, "chips_after": p.chips,
                })
            elif pos == "BB" and p.current_bet > 0:
                log_text = f"[{pos}] {p.name}: 빅 블라인드 ({self.game.big_blind})"
                self.action_log.append(log_text)
                self._emit({
                    "type": "blind", "player": p.name, "position": pos,
                    "amount": self.game.big_blind, "street": "프리플랍",
                    "log": log_text, "chips_after": p.chips,
                })

        self._setup_round(Street.PREFLOP)
        self._run_until_human()

    # ──────────────────────────────────────────
    # 베팅 라운드 관리
    # ──────────────────────────────────────────

    def _setup_round(self, street: Street) -> None:
        n = len(self.game.players)
        start = (self.game.dealer_index + 3) % n if street == Street.PREFLOP else (self.game.dealer_index + 1) % n
        self._order = [self.game.players[(start + i) % n] for i in range(n)]
        self._acted = set()
        self._round_i = 0

        # 프리플랍: SB는 이미 액션한 것으로 처리
        if street == Street.PREFLOP:
            positions = self.game.get_positions()
            for p in self.game.players:
                if positions.get(p.name, "") in ("SB", "BTN/SB") and p.current_bet > 0:
                    self._acted.add(p.name)

    def _is_round_over(self) -> bool:
        active = [p for p in self.game.players if not p.is_folded and not p.is_all_in]
        if not active:
            return True
        return all(
            p.name in self._acted and p.current_bet == self.game.current_bet
            for p in active
        )

    def _next_to_act(self) -> Optional[Player]:
        n = len(self._order)
        if not self._order:
            return None
        checked = 0
        while checked < n * 3:
            if self.game._count_active() <= 1:
                return None
            if self._is_round_over():
                return None
            p = self._order[self._round_i % n]
            if p.is_folded or p.is_all_in:
                self._round_i += 1
                checked += 1
                continue
            if p.name in self._acted and p.current_bet == self.game.current_bet:
                self._round_i += 1
                checked += 1
                continue
            return p
        return None

    def _apply(self, player: Player, action: Action, amount: int) -> None:
        positions = self.game.get_positions()
        street = self.game.current_street.value

        # 콜 금액은 apply_action 전에 계산
        call_amt = max(0, self.game.current_bet - player.current_bet)

        self.game.apply_action(player, action, amount)
        self._acted.add(player.name)
        if action in (Action.RAISE, Action.ALL_IN):
            self._acted = {player.name}
            idx = self._order.index(player)
            self._round_i = (idx + 1) % len(self._order)
        else:
            self._round_i += 1

        log_text = self._fmt_log(player, action, call_amt, amount)
        self.action_log.append(log_text)

        # 액션 이벤트 발행
        event_amount = amount if action in (Action.RAISE,) else call_amt
        self._emit({
            "type": "action",
            "player": player.name,
            "position": positions.get(player.name, ""),
            "action": action.value,
            "amount": event_amount,
            "street": street,
            "log": log_text,
            "chips_after": player.chips,
        })

    def _run_until_human(self) -> None:
        while True:
            player = self._next_to_act()
            if player is None:
                self._advance_street()
                return
            if player.is_human:
                return
            bot = self.bots.get(player.name)
            if bot:
                action, amount = bot.decide_action(self.game._get_game_state())
                self._apply(player, action, amount)
            else:
                self._apply(player, Action.CHECK, 0)

    def _advance_street(self) -> None:
        if self.game._count_active() <= 1 or self.street_index >= 3:
            self._do_showdown()
            return

        self.street_index += 1
        street = STREETS[self.street_index]
        self.game.deal_community(street)
        self.game.current_street = street
        self.game.current_bet = 0
        self.game.min_raise = self.game.big_blind
        for p in self.game.players:
            if not p.is_folded:
                p.reset_for_street()

        street_log = f"── {street.value} ──"
        self.action_log.append(street_log)

        # 스트리트 전환 이벤트
        self._emit({
            "type": "street_start",
            "street": street.value,
            "log": street_log,
        })

        # 커뮤니티 카드 이벤트 (장별로 분리)
        comm = self.game.community_cards
        if street == Street.FLOP:
            for card in comm[-3:]:
                self._emit({"type": "community_card", "card": str(card), "street": street.value})
        else:
            self._emit({"type": "community_card", "card": str(comm[-1]), "street": street.value})

        self._setup_round(street)
        self._run_until_human()

    def _calculate_side_pots(self) -> list:
        all_players = self.game.players
        contenders = [
            p for p in all_players
            if not p.is_folded and len(p.hole_cards) >= 2
        ]
        if not contenders:
            return []

        sorted_contenders = sorted(contenders, key=lambda p: p.total_bet_this_round)
        pots = []
        processed = {p.name: 0 for p in all_players}
        prev_level = 0

        for i, c in enumerate(sorted_contenders):
            level = c.total_bet_this_round
            if level <= prev_level:
                continue
            delta = level - prev_level

            pot_amount = 0
            for p in all_players:
                take = min(p.total_bet_this_round - processed[p.name], delta)
                pot_amount += take
                processed[p.name] += take

            eligible = sorted_contenders[i:]
            if pot_amount > 0:
                pots.append((pot_amount, eligible))
            prev_level = level

        remainder = sum(p.total_bet_this_round - processed[p.name] for p in all_players)
        if remainder > 0 and pots:
            pots[-1] = (pots[-1][0] + remainder, pots[-1][1])

        return pots

    def _do_showdown(self) -> None:
        from core.evaluator import HandEvaluator

        contenders = [p for p in self.game.players if not p.is_folded]

        if len(contenders) == 1:
            winner = contenders[0]
            winner.chips += self.game.pot
            self.winners = [winner.name]
            win_log = f"🏆 {winner.name} 승리 (상대 폴드)"
            self.action_log.append(win_log)
            self._emit({
                "type": "winner", "winners": [winner.name],
                "pot": self.game.pot, "log": win_log,
                "winner_chips": {winner.name: winner.chips},
            })
        else:
            contenders = [p for p in contenders if len(p.hole_cards) >= 2]
            if not contenders:
                self.game.pot = 0
                self.game._advance_dealer()
                self.hand_over = True
                return

            evals = {
                p.name: HandEvaluator.evaluate(p.hole_cards + self.game.community_cards)
                for p in contenders
            }

            # 쇼다운 이벤트 — 봇 카드 공개
            self._emit({
                "type": "showdown",
                "hands": {
                    p.name: [str(c) for c in p.hole_cards]
                    for p in contenders if not p.is_human
                },
            })

            pots = self._calculate_side_pots()
            all_winners: set = set()

            for pot_amount, eligible in pots:
                best = max(evals[p.name] for p in eligible)
                pot_winners = [p for p in eligible if evals[p.name] == best]
                share = pot_amount // len(pot_winners)
                remainder = pot_amount % len(pot_winners)
                for w in pot_winners:
                    w.chips += share
                    all_winners.add(w.name)
                if remainder:
                    pot_winners[0].chips += remainder

            self.winners = list(all_winners)
            self.showdown_hands = {p.name: str(evals[p.name]) for p in contenders}
            win_log = f"🏆 {', '.join(self.winners)} 승리"
            self.action_log.append(win_log)

            self._emit({
                "type": "winner",
                "log": win_log,
                "winners": self.winners,
                "pot": self.game.pot,
                "winner_chips": {w.name: w.chips
                                 for w in self.game.players
                                 if w.name in all_winners},
            })

        self.game.pot = 0
        self.game._advance_dealer()
        self.hand_over = True

        if self.human.chips <= 0 or sum(1 for p in self.game.players if p.chips > 0) < 2:
            self.game_over = True

    # ──────────────────────────────────────────
    # 헬퍼
    # ──────────────────────────────────────────

    def _fmt_log(self, player: Player, action: Action, call_amt: int, amount: int) -> str:
        positions = self.game.get_positions()
        pos = positions.get(player.name, "")
        pos_str = f"[{pos}]" if pos else ""
        if action == Action.FOLD:
            return f"{pos_str} {player.name}: 폴드"
        elif action == Action.CHECK:
            return f"{pos_str} {player.name}: 체크"
        elif action == Action.CALL:
            return f"{pos_str} {player.name}: 콜 ({call_amt})"
        elif action == Action.RAISE:
            return f"{pos_str} {player.name}: 레이즈 → {amount}"
        elif action == Action.ALL_IN:
            return f"{pos_str} {player.name}: 올인!"
        return f"{pos_str} {player.name}: {action.value}"

    def _get_gto_hint(self) -> Optional[str]:
        if self.human.is_folded or self.game.current_street != Street.PREFLOP:
            return None
        state = self.game._get_game_state()
        positions = state.get("positions", {})
        my_pos = positions.get(self.human.name, "")
        rec = self.gto.get_recommendation(
            self.human.hole_cards, my_pos, positions, state, self.game.big_blind
        )
        return self.gto.format_hint(rec)
