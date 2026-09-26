"""
웹 게임 세션 — 한 번에 한 액션씩 처리하는 스텝 방식
HTTP 요청마다: 사람 액션 적용 → 봇들 자동 처리 → 다음 사람 차례까지 진행
이벤트 목록을 함께 반환해 프론트엔드 애니메이션에 활용
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from typing import List, Optional, Dict

from core.game import TexasHoldem, Action, Street, IllegalActionError
from core.player import Player
from core.pot_odds import effective_call_pot, pot_odds as calc_pot_odds, call_ev as calc_call_ev
from ai.bot import PokerBot, BotDifficulty, opponent_range_info
from ai.equity import smart_equity, ranged_equity
from gto.advisor import GTOAdvisor
from gto.grader import (
    grade_preflop_action, grade_postflop_call, grade_postflop_fold,
    grade_postflop_bet_or_raise,
)
from db.recorder import GameRecorder

STREETS = [Street.PREFLOP, Street.FLOP, Street.TURN, Street.RIVER]

logger = logging.getLogger(__name__)


class WebGameSession:
    def __init__(
        self,
        session_id: str,
        human_name: str,
        chips: int,
        num_bots: int,
        difficulty: str,
        small_blind: int,
        equity_enabled: bool = True,
    ):
        self.session_id = session_id
        # 에퀴티/플레이 평가 계산 스위치. 아레나처럼 순수 시뮬레이션 성능이 중요한
        # 경우 False로 꺼서 사람 액션당 추가 MC 계산을 건너뛴다.
        self.equity_enabled = equity_enabled

        diff_map = {
            "easy": BotDifficulty.EASY,
            "medium": BotDifficulty.MEDIUM,
            "hard": BotDifficulty.HARD,
        }
        difficulty_enum = diff_map.get(difficulty, BotDifficulty.MEDIUM)

        self.human = Player(human_name, chips, is_human=True)
        bot_names = ["🤖 Alpha", "🤖 Beta", "🤖 Gamma", "🤖 Delta", "🤖 Epsilon"]
        # 봇별 고정 페르소나 — 성향이 달라야 상대별 대응 재미가 생김
        bot_personas = ["tight", "loose", "aggressive", "passive", "balanced"]
        bot_players = [Player(bot_names[i], chips, is_human=False) for i in range(min(num_bots, 5))]

        all_players = [self.human] + bot_players
        self.game = TexasHoldem(all_players, small_blind=small_blind, big_blind=small_blind * 2)
        self.bots: Dict[str, PokerBot] = {
            p.name: PokerBot(p, difficulty_enum, persona=bot_personas[i])
            for i, p in enumerate(bot_players)
        }
        self.gto = GTOAdvisor()
        self.recorder = GameRecorder(big_blind=small_blind * 2)
        self._hand_start_chips: Dict[str, int] = {}

        # 에퀴티 패널 (Feature A): 스트리트+current_bet 단위 캐시(재계산 방지), 스트리트별 history
        self._equity_cache: Dict[tuple, dict] = {}
        self.equity_history: List[dict] = []
        self._equity_history_streets: set = set()

        # 플레이 평가 (Feature B): 방금 끝난 핸드의 평가(get_state용) + 세션 전체 누적(요약 API용)
        self.hand_reviews: List[dict] = []
        self.session_reviews: List[dict] = []

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

        # 사람의 불법 액션은 상태를 바꾸기 전에 거절한다(API는 400으로 응답).
        self.game.normalize_action(player, action, amount, self._can_raise(player))

        self._events = []  # 새 액션마다 이벤트 초기화
        self._apply(player, action, amount)
        self._run_until_human()

    def next_hand(self) -> None:
        # 핸드 진행 중(hand_over=False) 호출은 무시한다. 가드가 없으면 팟에 들어간 칩이
        # _reset_hand()로 사라진다("다음 핸드" 연타·중복 요청 — T-025).
        if self.game_over or not self.hand_over:
            return
        self._events = []
        self._start_new_hand()

    def get_state(self) -> dict:
        positions = self.game.get_positions()
        next_player = self._next_to_act() if not self.hand_over else None
        waiting = next_player is not None and next_player.is_human

        call_amount = 0
        min_raise_to = 0
        can_raise = False
        if waiting:
            call_amount = max(0, self.game.current_bet - self.human.current_bet)
            # 불완전 올인만 마주해 액션이 닫혔거나 스택이 콜 이하면 레이즈 불가 → min_raise_to=0
            # (프론트 ActionBar는 min_raise_to=0이면 레이즈 UI를 끈다)
            can_raise = (self._can_raise(self.human)
                         and self.human.chips > call_amount)
            if can_raise:
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
            "gto_key": self._get_gto_key() if waiting else None,
            "action_log": self.action_log[-30:],
            "call_amount": call_amount,
            "min_raise_to": min_raise_to,
            "can_raise": can_raise,
            "events": events,
            "equity": self._get_equity_info() if (waiting and self.equity_enabled) else None,
            "hand_review": self.hand_reviews if self.hand_over else None,
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

        # 에퀴티/평가 상태 초기화 (새 핸드마다 리셋)
        self._equity_cache = {}
        self.equity_history = []
        self._equity_history_streets = set()
        self.hand_reviews = []

        # 파산 플레이어 제거
        self.game.players = [p for p in self.game.players if p.chips > 0]
        if len(self.game.players) < 2 or self.human not in self.game.players:
            self.game_over = True
            return
        self.game.dealer_index = self.game.dealer_index % len(self.game.players)

        self.hand_number += 1
        self._hand_start_chips = {p.name: p.chips for p in self.game.players}
        self.game.start_hand()
        self.game.current_street = Street.PREFLOP
        self.street_index = 0

        positions = self.game.get_positions()

        # RL 학습 데이터: 핸드 기록 시작
        try:
            dealer_pos = positions.get(
                self.game.players[self.game.dealer_index].name, "BTN")
            self.recorder.start_hand(
                self.game.players, dealer_pos,
                {positions[p.name]: p.hole_cards for p in self.game.players},
                small_blind=self.game.small_blind,
            )
        except Exception:
            pass  # 기록 실패가 게임을 막지 않음

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

        # 2. 블라인드 이벤트 + 로그 (딜링 이후). core가 포스팅한 순서(SB → BB) 그대로 발행하고,
        #    금액은 실제로 낸 칩(숏스택이면 블라인드보다 적음)
        for (p, posted), kind in zip(self.game.blind_posts, ("스몰", "빅")):
            if posted <= 0:
                continue
            pos = positions.get(p.name, "")
            log_text = f"[{pos}] {p.name}: {kind} 블라인드 ({posted})"
            self.action_log.append(log_text)
            self._emit({
                "type": "blind", "player": p.name, "position": pos,
                "amount": posted, "street": "프리플랍",
                "log": log_text, "chips_after": p.chips,
            })

        self._setup_round(Street.PREFLOP)
        self._run_until_human()

    # ──────────────────────────────────────────
    # 베팅 라운드 관리
    # ──────────────────────────────────────────

    def _setup_round(self, street: Street) -> None:
        # 행동 순서는 core 규칙을 그대로 쓴다(헤즈업 프리플랍 BTN/SB 선행동 포함).
        # _acted = 마지막 풀 레이즈 이후 행동한 플레이어(core _betting_round와 같은 의미).
        # 블라인드 포스팅은 행동이 아니다 — SB도 자기 차례에 레이즈할 수 있고 BB는 옵션 보유.
        self._order = self.game._betting_order(street)
        self._acted = set()
        self._round_i = 0

    def _can_raise(self, player: Player) -> bool:
        return self.game.raise_allowed(player, self._acted)

    def _is_round_over(self) -> bool:
        # core 규칙 그대로(행동 가능 1명 + 콜할 금액 없음 → 라운드 종료, 런아웃 포함)
        return self.game._is_round_over(self._acted)

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
        can_raise = self._can_raise(player)

        # 검증: 사람은 submit_action에서 이미 거절됐다. 봇의 불법 액션은 로그를 남기고
        # core의 안전 폴백(공격→콜/체크, 불법 체크→폴드)으로 대체한다.
        try:
            action = self.game.normalize_action(player, action, amount, can_raise)
        except IllegalActionError as e:
            if player.is_human:
                raise
            fallback = self.game.fallback_action(player, action)
            logger.warning("봇 불법 액션 대체: %s %s(%s) → %s (%s)",
                           player.name, action.value, amount, fallback.value, e)
            action, amount = self.game.normalize_action(player, fallback, 0, can_raise), 0

        # 콜 금액은 apply_action 전에 계산
        call_amt = max(0, self.game.current_bet - player.current_bet)

        # RL 학습 데이터: 결정 직전 상태 캡처
        import json as _json
        _ctx = {
            "pot": self.game.pot,
            "current_bet": self.game.current_bet,
            "stack_before": player.chips,
        }
        _players_state = _json.dumps([
            {"pos": positions.get(p.name, ""), "chips": p.chips,
             "bet": p.current_bet, "folded": p.is_folded, "allin": p.is_all_in}
            for p in self.game.players
        ])
        _bot = self.bots.get(player.name)
        _profile = (f"{_bot.difficulty.value}/{_bot.persona}"
                    if _bot else "human")
        _equity = _bot.last_equity if _bot else None
        _gto_for_record = None

        # 사람 액션: 적용 전 equity 계산 + 플레이 평가 (Feature B)
        # (equity_enabled=False인 아레나 등에서는 건너뛰어 성능을 지킨다)
        if player is self.human and self.equity_enabled:
            _equity, _gto_for_record = self._grade_human_action(
                player, action, amount, self.game.current_street, call_amt,
            )

        result = self.game.execute_action(player, action, amount, can_raise)
        action = result.action
        # 로그·이벤트·RL 기록의 금액은 요청값이 아니라 실제 칩 이동에서 만든다:
        # 콜 = 이동액, 레이즈/올인 = 도달 베팅(to_amount = 이전 베팅 + 이동액), 폴드/체크 = 0
        real_amount = self._event_amount(result)

        try:
            self.recorder.record_action(
                positions.get(player.name, "BTN"), player.is_human,
                self.game.current_street, _ctx, action, real_amount,
                call_amount=call_amt, equity=_equity,
                bot_profile=_profile, players_state=_players_state,
                gto=_gto_for_record,
            )
        except Exception:
            pass
        self._acted.add(player.name)
        if result.reopens:
            # 풀 레이즈만 액션을 다시 연다. 불완전 올인 뒤 이미 행동한 사람은 콜/폴드만.
            self._acted = {player.name}
            idx = self._order.index(player)
            self._round_i = (idx + 1) % len(self._order)
        else:
            self._round_i += 1

        log_text = self._fmt_log(player, action, real_amount)
        self.action_log.append(log_text)

        # 액션 이벤트 발행
        self._emit({
            "type": "action",
            "player": player.name,
            "position": positions.get(player.name, ""),
            "action": action.value,
            "amount": real_amount,
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
                gs = self.game._get_game_state()
                gs["action_log"] = self.action_log  # 봇이 레이즈 횟수 파악에 사용
                action, amount = bot.decide_action(gs)
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

        # 새 스트리트 → 에퀴티 캐시 초기화 (결정 지점이 바뀜)
        self._equity_cache = {}

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
                    # 1명만 eligible한 팟 = 본인 초과 베팅 반환 → 승자 표시 안 함
                    if len(eligible) > 1:
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

        # RL 학습 데이터: 핸드 결과 + reward 역산
        try:
            positions = self.game.get_positions()
            self.recorder.finish_hand(
                self.game.community_cards,
                self.game.pot,
                [positions.get(w, "") for w in self.winners],
                {positions.get(p.name, ""): {
                    "start": self._hand_start_chips.get(p.name, p.chips),
                    "end": p.chips}
                 for p in self.game.players},
            )
        except Exception:
            pass

        # 세션 전체 누적 (요약 API용) — 이번 핸드 평가를 합산
        self.session_reviews.extend(self.hand_reviews)

        self.game.pot = 0
        self.game._advance_dealer()
        self.hand_over = True

        if self.human.chips <= 0 or sum(1 for p in self.game.players if p.chips > 0) < 2:
            self.game_over = True

    # ──────────────────────────────────────────
    # 헬퍼
    # ──────────────────────────────────────────

    @staticmethod
    def _event_amount(result) -> int:
        """ActionResult → 로그·이벤트 금액(콜=이동액, 레이즈/올인=도달 베팅, 그 외 0)."""
        if result.action == Action.CALL:
            return result.moved
        if result.action in (Action.RAISE, Action.ALL_IN):
            return result.to_amount
        return 0

    def _fmt_log(self, player: Player, action: Action, amount: int) -> str:
        """amount는 _event_amount() 값(실제 칩 이동 기준)."""
        positions = self.game.get_positions()
        pos = positions.get(player.name, "")
        pos_str = f"[{pos}]" if pos else ""
        if action == Action.FOLD:
            return f"{pos_str} {player.name}: 폴드"
        elif action == Action.CHECK:
            return f"{pos_str} {player.name}: 체크"
        elif action == Action.CALL:
            return f"{pos_str} {player.name}: 콜 ({amount})"
        elif action == Action.RAISE:
            return f"{pos_str} {player.name}: 레이즈 → {amount}"
        elif action == Action.ALL_IN:
            return f"{pos_str} {player.name}: 올인! ({amount})"
        return f"{pos_str} {player.name}: {action.value}"

    def _get_gto_key(self) -> Optional[dict]:
        """현재 프리플랍 상황의 GTO 레인지 조회 키 반환"""
        if self.game.current_street != Street.PREFLOP:
            return None
        if self.human.is_folded:
            return None

        positions = self.game.get_positions()
        my_pos = positions.get(self.human.name, "")
        if not my_pos:
            return None

        current_bet = self.game.current_bet
        bb = self.game.big_blind

        if current_bet <= bb:
            # RFI: 아직 아무도 레이즈 안 함
            return {"position": my_pos, "vs_position": None, "range_type": "open"}

        # 레이즈가 있는 상황 — action_log에서 레이즈 횟수와 포지션 파악
        raiser_positions = []
        for entry in self.action_log:
            if "──" in entry:  # 스트리트 구분선 = 프리플랍 끝
                break
            if "레이즈" in entry:
                for p in self.game.players:
                    if p.name in entry:
                        pos = positions.get(p.name, "")
                        if pos and pos not in raiser_positions:
                            raiser_positions.append(pos)
                        break

        if not raiser_positions:
            return None

        opener_pos = raiser_positions[0]

        if len(raiser_positions) == 1:
            return {"position": my_pos, "vs_position": opener_pos, "range_type": "vs_open"}
        else:
            three_bettor_pos = raiser_positions[1]
            vs_pos = f"{opener_pos}/{three_bettor_pos}"
            return {"position": my_pos, "vs_position": vs_pos, "range_type": "vs_3bet"}

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

    # ──────────────────────────────────────────
    # 에퀴티 패널 (Feature A)
    # ──────────────────────────────────────────

    def _build_gs_for_ranges(self) -> dict:
        """opponent_range_info에 넘길 state — game._get_game_state()에 action_log 부착"""
        gs = self.game._get_game_state()
        gs["action_log"] = self.action_log
        return gs

    def _human_stack(self) -> tuple:
        """유효 콜·팟 계산용 (내 남은 칩, 내 핸드 기여, 다른 모두의 핸드 기여 — 폴드 포함)."""
        others = [p.total_bet_this_round for p in self.game.players if p is not self.human]
        return self.human.chips, self.human.total_bet_this_round, others

    def _record_equity_history(self, vs_random: float) -> None:
        """스트리트당 한 번만 vs_random 히스토리에 기록"""
        street_name = self.game.current_street.value
        if street_name in self._equity_history_streets:
            return
        self._equity_history_streets.add(street_name)
        self.equity_history.append({"street": street_name, "vs_random": vs_random})

    def _get_equity_info(self, call_amount: Optional[int] = None) -> Optional[dict]:
        """
        현재 결정 지점의 에퀴티 정보. waiting_for_action=True일 때만 의미있게 호출된다.
        사람이 폴드했거나 홀카드가 없으면 None.
        같은 결정 지점(스트리트+현재벳) 재조회 시 캐시 재사용 (재계산 방지).
        """
        if self.human.is_folded or len(self.human.hole_cards) < 2:
            return None

        street = self.game.current_street
        current_bet = self.game.current_bet
        cache_key = (street.value, current_bet)
        if cache_key in self._equity_cache:
            return self._equity_cache[cache_key]

        hole = self.human.hole_cards
        community = self.game.community_cards

        opponents = [
            p for p in self.game.players
            if p is not self.human and not p.is_folded
        ]
        n_opps = max(1, len(opponents))

        if call_amount is None:
            call_amount = max(0, current_bet - self.human.current_bet)
        pot = self.game.pot
        big_blind = self.game.big_blind

        exact_river = (street == Street.RIVER and len(opponents) == 1)
        sims = 1000
        vs_random = smart_equity(
            hole, community, n_opps, sims,
            use_cache=True, contribute=True, exact_river=exact_river,
        )
        source = "exact" if exact_river else f"mc:{sims}"

        self._record_equity_history(vs_random)

        # vs_range: 살아있는 모든 상대 레인지 반영 종합 승률 (opponent_range_info 재사용)
        gs = self._build_gs_for_ranges()
        opp_dicts = [{"name": p.name, "is_folded": p.is_folded} for p in opponents]
        samplers_with_roles = opponent_range_info(gs, opp_dicts)

        samplers = [s for s, _ in samplers_with_roles]
        if any(samplers):
            vs_range = ranged_equity(hole, community, samplers, sims)
        else:
            vs_range = vs_random

        # 상대별 1:1 추정 (곱해서 종합이 되지 않음 — 개별 지표로 유지)
        opponents_out = []
        for opp, (sampler, role) in zip(opponents, samplers_with_roles):
            if sampler is not None:
                one_on_one = ranged_equity(hole, community, [sampler], sims)
            else:
                # 정보 없음 → 랜덤 1:1로 근사 (n_opps 기준 vs_random과는 상대 수가 달라 별도 계산)
                one_on_one = smart_equity(hole, community, 1, sims, use_cache=True, contribute=False)
            opponents_out.append({
                "name": opp.name,
                "position": self.game.get_positions().get(opp.name, ""),
                "role": role,
                "equity": round(one_on_one, 4),
            })
        opponents_out.sort(key=lambda o: o["equity"])

        # 숏스택 캡: 실제로 걸리는 칩(유효 콜)과 이길 수 있는 팟(유효 팟) 기준 (T-033)
        eff_call, eff_pot = effective_call_pot(pot, call_amount, *self._human_stack())
        pot_odds = calc_pot_odds(eff_call, eff_pot)
        call_ev_bb = None
        if eff_call > 0 and big_blind:
            call_ev_bb = calc_call_ev(vs_random, eff_call, eff_pot) / big_blind

        info = {
            "vs_random": round(vs_random, 4),
            "vs_range": round(vs_range, 4),
            "pot_odds": round(pot_odds, 4),
            "call_ev_bb": round(call_ev_bb, 2) if call_ev_bb is not None else None,
            "source": source,
            "samples": sims,
            "num_opponents": n_opps,
            "opponents": opponents_out,
            "history": list(self.equity_history),
        }
        self._equity_cache[cache_key] = info
        return info

    # ──────────────────────────────────────────
    # 플레이 평가 (Play Grader, Feature B)
    # ──────────────────────────────────────────

    def _grade_human_action(
        self, player: Player, action: Action, amount: int, street: Street, call_amt: int,
    ):
        """
        사람 액션을 GTO 빈도(프리플랍) / equity 기반 EV(포스트플랍)로 평가해
        self.hand_reviews / self.session_reviews에 누적.
        game.apply_action() 호출 '전'에 실행해야 한다 (팟/베팅이 액션 전 값이어야 함).

        반환: (equity|None, gto_frequencies|None) — recorder.record_action에 채워 넣을 값.
        """
        try:
            equity_info = self._get_equity_info(call_amt)
            vs_random = equity_info["vs_random"] if equity_info else None
            gto_freqs = None
            grade = None

            if street == Street.PREFLOP:
                positions = self.game.get_positions()
                my_pos = positions.get(self.human.name, "")
                game_state = self.game._get_game_state()
                game_state["action_log"] = self.action_log
                gto_rec = self.gto.get_recommendation(
                    self.human.hole_cards, my_pos, positions, game_state, self.game.big_blind,
                )
                grade = grade_preflop_action(action.value, gto_rec)
                gto_freqs = gto_rec["frequencies"] if gto_rec else None
            elif vs_random is not None:
                pot = self.game.pot
                big_blind = self.game.big_blind
                stack = self._human_stack()  # 숏스택 캡 (T-033)
                if action == Action.CALL:
                    grade = grade_postflop_call(vs_random, pot, call_amt, big_blind, stack=stack)
                elif action == Action.FOLD:
                    grade = grade_postflop_fold(vs_random, pot, call_amt, big_blind, stack=stack)
                else:
                    grade = grade_postflop_bet_or_raise(vs_random, action.value)

            if grade is not None:
                review = grade.to_dict()
                review["street"] = street.value
                review["action"] = action.value
                review["equity"] = vs_random
                review["pot_odds"] = equity_info["pot_odds"] if equity_info else None
                review["gto_freq"] = (gto_freqs or {}).get(
                    "raise" if action.value == "allin" else action.value
                ) if gto_freqs else None
                self.hand_reviews.append(review)

            return vs_random, gto_freqs
        except Exception:
            return None, None
