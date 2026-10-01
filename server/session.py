"""
웹 게임 세션 — 한 번에 한 액션씩 처리하는 스텝 방식
HTTP 요청마다: 사람 액션 적용 → 봇들 자동 처리 → 다음 사람 차례까지 진행
이벤트 목록을 함께 반환해 프론트엔드 애니메이션에 활용
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import threading
from typing import List, Optional, Dict

from core.game import TexasHoldem, Action, Street
from core.player import Player
from core.pot_odds import effective_call_pot, pot_odds as calc_pot_odds, call_ev as calc_call_ev
from ai.bot import PokerBot, BotDifficulty, opponent_range_info
from ai.equity import smart_equity, equity_detail, ranged_equity, ranged_equity_detail, standard_error
from gto.advisor import GTOAdvisor
from gto.grader import (
    grade_preflop_action, grade_postflop_call, grade_postflop_fold,
    grade_postflop_bet_or_raise,
)
from db.recorder import GameRecorder

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

        # 룰(베팅 순서·액션 판정·라운드 진행·팟 분배·버튼)은 전부 core TexasHoldem이 갖는다.
        # 세션은 그 결과를 이벤트·로그·RL 기록·평가로 옮길 뿐이다(T-024).

        # 핸드/게임 상태
        self.hand_number: int = 0
        self.hand_over: bool = False
        self.game_over: bool = False
        self.winners: List[str] = []
        self.showdown_hands: Dict[str, str] = {}
        self.action_log: List[str] = []

        # 애니메이션 이벤트 버퍼 — 공개 변경 메서드 한 번(요청 하나) 동안만 쓰고, 그 메서드의
        # 반환값으로 넘긴 뒤 비운다. get_state()는 이 버퍼를 읽지도 비우지도 않는다(T-026).
        self._events: List[dict] = []

        # 같은 세션에 대한 동시 요청 직렬화용(엔드포인트가 with session.lock: 으로 감싼다).
        # FastAPI 동기 def 엔드포인트는 스레드풀에서 동시에 돈다(T-026).
        self.lock = threading.RLock()

        self._start_new_hand()
        # 생성자가 진행한 첫 핸드의 이벤트(POST /game/start 응답용)
        self.start_events: List[dict] = self._take_events()

    # ──────────────────────────────────────────
    # 공개 API
    #   상태를 바꾸는 메서드는 그 호출에서 새로 생긴 이벤트 목록을 반환한다.
    #   get_state(events)는 순수 조회 — 이벤트는 호출자가 넘긴 것을 그대로 싣는다.
    # ──────────────────────────────────────────

    def submit_action(self, action_str: str, amount: int) -> List[dict]:
        """사람 액션 적용 → 봇 자동 진행. 새로 생긴 이벤트를 반환(무시된 요청은 [])."""
        if self.hand_over or self.game_over:
            return []

        action_map = {
            "fold": Action.FOLD,
            "check": Action.CHECK,
            "call": Action.CALL,
            "raise": Action.RAISE,
            "allin": Action.ALL_IN,
        }
        action = action_map.get(action_str)
        if action is None:
            return []

        player = self._next_to_act()
        if player is None or not player.is_human:
            return []

        # 사람의 불법 액션은 상태를 바꾸기 전에 거절한다(API는 400으로 응답).
        self.game.validate(player, action, amount)

        self._events = []  # 이전 요청이 중간에 실패했어도 그 이벤트를 다시 내보내지 않는다
        self._apply(player, action, amount)
        self._run_until_human()
        return self._take_events()

    def next_hand(self) -> List[dict]:
        """hand_over일 때만 새 핸드 시작. 새로 생긴 이벤트를 반환(무시된 요청은 [])."""
        # 핸드 진행 중(hand_over=False) 호출은 무시한다. 가드가 없으면 팟에 들어간 칩이
        # _reset_hand()로 사라진다("다음 핸드" 연타·중복 요청 — T-025).
        if self.game_over or not self.hand_over:
            return []
        self._events = []
        self._start_new_hand()
        return self._take_events()

    def needs_recovery(self) -> bool:
        """핸드 진행 중인데 사람 차례가 아닌 채로 멈춰 있는가(요청 중간 예외의 흔적)."""
        if self.hand_over or self.game_over:
            return False
        p = self._next_to_act()
        return p is None or not p.is_human

    def recover(self) -> List[dict]:
        """봇 차례(또는 스트리트 전환 직전)에 멈춘 세션을 사람 차례·핸드 종료까지 진행한다.
        정상 상태(사람 차례·핸드 종료)면 아무것도 하지 않고 []. GET state가 호출한다."""
        if not self.needs_recovery():
            return []
        logger.warning("세션 %s: 봇 차례에 멈춘 상태를 복구합니다", self.session_id)
        self._events = []
        self._run_until_human()
        return self._take_events()

    def _take_events(self) -> List[dict]:
        events, self._events = self._events, []
        return events

    def get_state(self, events: Optional[List[dict]] = None) -> dict:
        """현재 상태 조회(이벤트 큐를 건드리지 않는다). events: 이 응답에 실을 이벤트."""
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
            can_raise = (self.game.can_raise(self.human)
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
            "gto": self._get_gto_panel() if waiting else None,
            "action_log": self.action_log[-30:],
            "call_amount": call_amount,
            "min_raise_to": min_raise_to,
            "can_raise": can_raise,
            "events": list(events or []),
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

        # 파산 플레이어 제거 + 무빙 버튼(직전 버튼 다음 생존자, ADR 0036) — core
        self.game.seat_for_next_hand()
        if len(self.game.players) < 2 or self.human not in self.game.players:
            self.game_over = True
            return

        self.hand_number += 1
        self._hand_start_chips = {p.name: p.chips for p in self.game.players}
        self.game.start_hand()  # 블라인드·홀카드·프리플랍 라운드 준비

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
        pot_so_far = self.game.pot - sum(max(0, x) for _, x in self.game.blind_posts)
        for (p, posted), kind in zip(self.game.blind_posts, ("스몰", "빅")):
            if posted <= 0:
                continue
            pot_so_far += posted  # 블라인드는 core가 이미 다 포스팅했다 — 이벤트 시점의 팟은 누적분
            pos = positions.get(p.name, "")
            log_text = f"[{pos}] {p.name}: {kind} 블라인드 ({posted})"
            self.action_log.append(log_text)
            self._emit({
                "type": "blind", "player": p.name, "position": pos,
                "amount": posted, "street": "프리플랍",
                "log": log_text, "chips_after": p.chips,
                # 재생 표시 상태용(T-029): 이 이벤트 직후의 팟·그 플레이어 이번 스트리트 베팅
                "pot_after": pot_so_far, "bet_after": posted,
            })

        self._run_until_human()

    # ──────────────────────────────────────────
    # 베팅 라운드 관리
    # ──────────────────────────────────────────

    def _can_raise(self, player: Player) -> bool:
        return self.game.can_raise(player)

    def _next_to_act(self) -> Optional[Player]:
        return self.game.next_to_act()

    def _apply(self, player: Player, action: Action, amount: int) -> None:
        positions = self.game.get_positions()
        street = self.game.current_street.value

        # 검증(core): 사람은 submit_action에서 이미 거절됐다. 봇의 불법 액션은 로그를 남기고
        # core의 안전 폴백(공격→콜/체크, 불법 체크→폴드)으로 대체한다. amount는 이후 실제로
        # 걸리는 도달 베팅(최소 레이즈 보정·스택 한도 반영)이라 평가·적용이 같은 값을 쓴다.
        if player.is_human:
            action, amount = self.game.validate(player, action, amount)
        else:
            requested, req_amount = action, amount
            action, amount, err = self.game.validate_or_fallback(player, action, amount)
            if err is not None:
                logger.warning("봇 불법 액션 대체: %s %s(%s) → %s (%s)",
                               player.name, requested.value, req_amount, action.value, err)

        # 콜 금액은 act 전에 계산
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

        result = self.game.act(player, action, amount)
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
            "pot_after": self.game.pot,          # 재생 표시 상태용(T-029)
            "bet_after": player.current_bet,
        })

    def _run_until_human(self) -> None:
        while True:
            player = self._next_to_act()
            if player is None:
                self._advance_street()
                return
            if player.is_human:
                return
            action, amount = self._bot_decision(player)
            self._apply(player, action, amount)

    def _bot_decision(self, player: Player):
        """봇 결정. 판단 중 예외가 나면 로그를 남기고 core의 안전 폴백(콜할 금액이 없으면
        체크, 있으면 폴드)으로 대신해 게임을 계속 진행한다(T-026)."""
        bot = self.bots.get(player.name)
        if bot is None:
            return self.game.fallback_action(player, Action.CHECK), 0
        try:
            gs = self.game._get_game_state()
            gs["action_log"] = self.action_log  # 봇이 레이즈 횟수 파악에 사용
            action, amount = bot.decide_action(gs)
            if not isinstance(action, Action):
                raise TypeError(f"봇이 Action이 아닌 값을 반환: {action!r}")
            return action, int(amount or 0)
        except Exception:
            safe = self.game.fallback_action(player, Action.CHECK)
            logger.exception("봇 판단 오류: %s → 안전 폴백 %s (세션 %s)",
                             player.name, safe.value, self.session_id)
            return safe, 0

    def _advance_street(self) -> None:
        street = self.game.advance_street()  # core: 카드 딜 + 라운드 준비(끝났으면 None)
        if street is None:
            self._do_showdown()
            return

        # 새 스트리트 → 에퀴티 캐시 초기화 (결정 지점이 바뀜)
        self._equity_cache = {}

        street_log = f"── {street.value} ──"
        self.action_log.append(street_log)

        # 스트리트 전환 이벤트
        self._emit({
            "type": "street_start",
            "street": street.value,
            "log": street_log,
            "pot_after": self.game.pot,  # 스트리트 전환 직후 팟(베팅은 모두 0) — T-029
        })

        # 커뮤니티 카드 이벤트 (장별로 분리)
        comm = self.game.community_cards
        if street == Street.FLOP:
            for card in comm[-3:]:
                self._emit({"type": "community_card", "card": str(card), "street": street.value})
        else:
            self._emit({"type": "community_card", "card": str(comm[-1]), "street": street.value})

        self._run_until_human()

    def _do_showdown(self) -> None:
        """core showdown()(사이드팟·홀수 칩 포함)을 호출하고 결과를 이벤트·로그로 옮긴다."""
        result = self.game.showdown()
        self.winners = [w.name for w in result.winners]

        if not result.contested:
            if not result.winners:  # 겨룰 카드가 없는 비정상 상태 — 팟만 정리
                self.hand_over = True
                return
            winner = result.winners[0]
            win_log = f"🏆 {winner.name} 승리 (상대 폴드)"
            self.action_log.append(win_log)
            self._emit({
                "type": "winner", "winners": [winner.name],
                "pot": result.pot, "log": win_log,
                "winner_chips": {winner.name: winner.chips},
            })
        else:
            by_name = {p.name: p for p in self.game.players}
            # 쇼다운 이벤트 — 봇 카드 공개
            self._emit({
                "type": "showdown",
                "hands": {
                    name: [str(c) for c in by_name[name].hole_cards]
                    for name in result.evaluations if not by_name[name].is_human
                },
            })
            self.showdown_hands = {name: str(ev) for name, ev in result.evaluations.items()}
            win_log = f"🏆 {', '.join(self.winners)} 승리"
            self.action_log.append(win_log)
            self._emit({
                "type": "winner",
                "log": win_log,
                "winners": self.winners,
                "pot": result.pot,
                "winner_chips": {w.name: w.chips for w in result.winners},
            })

        # RL 학습 데이터: 핸드 결과 + reward 역산
        try:
            positions = self.game.get_positions()
            self.recorder.finish_hand(
                self.game.community_cards,
                result.pot,
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

        # 딜러 이동은 다음 핸드 시작 시점(_start_new_hand → core seat_for_next_hand)에 한다
        # — 핸드 종료 응답의 포지션 라벨이 방금 친 핸드 기준으로 남는다(ADR 0036).
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

    def _get_gto_panel(self) -> Optional[dict]:
        """GTO 패널용 — advisor 추천(`get_recommendation`) 하나에서만 만든다(T-013, ADR 0007·0035).

        패널·플레이 평가·봇이 모두 같은 판정기(구조화 시퀀스 → 노드 키)를 쓴다. 패널은
        `node_key`로 `/gto/preflop/range?action_seq=`를 조회하므로 힌트와 레인지가 항상 같은 노드다.
        - 프리플랍이 아니거나 사람이 폴드했으면 None(패널 안내 문구)
        - 추천이 없으면 {"found": False, "position"} — 정확한 노드·간단 라벨 모두 없음
        - 있으면 {"found": True, node_key, approx(라벨 예비 = "(근사)"), situation, hand, frequencies}
        """
        if self.human.is_folded or self.game.current_street != Street.PREFLOP:
            return None
        state = self.game._get_game_state()
        positions = state.get("positions", {})
        my_pos = positions.get(self.human.name, "")
        rec = self.gto.get_recommendation(
            self.human.hole_cards, my_pos, positions, state, self.game.big_blind
        )
        if rec is None or rec.get("node_key") is None:
            return {"found": False, "position": my_pos}
        return {
            "found": True,
            "position": my_pos,
            "node_key": rec["node_key"],
            "approx": bool(rec.get("approx")),
            "situation": rec.get("situation", ""),
            "hand": rec["hand"],
            "frequencies": rec["frequencies"],
        }

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

    def _record_equity_history(self, vs_range: float) -> None:
        """스트리트당 한 번(그 스트리트 첫 결정)만 vs_range를 히스토리에 기록 — 패널과 같은 기준"""
        street_name = self.game.current_street.value
        if street_name in self._equity_history_streets:
            return
        self._equity_history_streets.add(street_name)
        self.equity_history.append({"street": street_name, "vs_range": round(vs_range, 4)})

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

        # vs_random: 프리플랍 = 상수 테이블, 리버 1:1 = 전수, 그 밖 = 적응형 MC (ADR 0034).
        # 화면에는 보이지 않는다(ADR 0022/0034) — 레인지 없을 때의 vs_range(그때는 Play Grader·기록도 이 값).
        detail = equity_detail(hole, community, n_opps)
        vs_random = detail.equity

        # vs_range(패널·Play Grader·기록이 쓰는 값, ADR 0049): 살아있는 모든 상대 레인지 반영 종합 승률.
        # 레인지 정보가 하나도 없으면(프리플랍 레이저 없음 등) vs_random과 같은 계산이다.
        # source/samples는 이 값을 실제로 만든 경로·샘플 수다.
        gs = self._build_gs_for_ranges()
        opp_dicts = [{"name": p.name, "is_folded": p.is_folded} for p in opponents]
        samplers_with_roles = opponent_range_info(gs, opp_dicts)

        samplers = [s for s, _ in samplers_with_roles]
        range_applied = any(samplers)
        shown = ranged_equity_detail(hole, community, samplers) if range_applied else detail
        vs_range = shown.equity

        self._record_equity_history(vs_range)

        # 상대별 1:1 추정 (곱해서 종합이 되지 않음 — 개별 지표로 유지)
        opponents_out = []
        random_1v1 = None  # 정보 없는 상대들은 모두 같은 값(랜덤 1:1) → 한 번만 계산
        for opp, (sampler, role) in zip(opponents, samplers_with_roles):
            if sampler is not None:
                one_on_one = ranged_equity(hole, community, [sampler])
            else:
                # 정보 없음 → 랜덤 1:1로 근사 (n_opps 기준 vs_random과는 상대 수가 달라 별도 계산)
                if random_1v1 is None:
                    random_1v1 = vs_random if n_opps == 1 else smart_equity(hole, community, 1)
                one_on_one = random_1v1
            opponents_out.append({
                "name": opp.name,
                "position": self.game.get_positions().get(opp.name, ""),
                "role": role,
                "equity": round(one_on_one, 4),
            })
        opponents_out.sort(key=lambda o: o["equity"])

        # 숏스택 캡: 실제로 걸리는 칩(유효 콜)과 이길 수 있는 팟(유효 팟) 기준
        eff_call, eff_pot = effective_call_pot(pot, call_amount, *self._human_stack())
        pot_odds = calc_pot_odds(eff_call, eff_pot)
        call_ev_bb = None
        if eff_call > 0 and big_blind:
            call_ev_bb = calc_call_ev(vs_range, eff_call, eff_pot) / big_blind  # 패널과 같은 기준

        info = {
            "vs_random": round(vs_random, 4),
            "vs_range": round(vs_range, 4),
            "pot_odds": round(pot_odds, 4),
            "call_ev_bb": round(call_ev_bb, 2) if call_ev_bb is not None else None,
            "range_applied": range_applied,
            "source": shown.source,
            "samples": shown.samples,
            # Play Grader 경계 판정용(ADR 0049) — vs_range를 만든 계산의 표준오차. 응답 스키마 밖(패널 비표시)
            "vs_range_se": standard_error(shown),
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
        game.act() 호출 '전'에 실행해야 한다 (팟/베팅이 액션 전 값이어야 함).

        판정 에퀴티는 패널과 같은 vs_range다(ADR 0049). 상대 레인지를 하나도 모르면
        (`range_applied=False`) vs_random과 같은 값이고 grader가 사유에 그 사실을 붙인다.

        반환: (equity|None, gto_frequencies|None) — recorder.record_action에 채워 넣을 값.
        """
        try:
            equity_info = self._get_equity_info(call_amt)
            equity = equity_info["vs_range"] if equity_info else None
            se = equity_info.get("vs_range_se", 0.0) if equity_info else 0.0
            range_known = bool(equity_info.get("range_applied")) if equity_info else False
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
            elif equity is not None:
                pot = self.game.pot
                big_blind = self.game.big_blind
                stack = self._human_stack()  # 숏스택 캡
                if action == Action.CALL:
                    grade = grade_postflop_call(equity, pot, call_amt, big_blind,
                                                stack=stack, se=se, range_known=range_known)
                elif action == Action.FOLD:
                    grade = grade_postflop_fold(equity, pot, call_amt, big_blind,
                                                stack=stack, se=se, range_known=range_known)
                else:
                    grade = grade_postflop_bet_or_raise(equity, action.value)

            if grade is not None:
                review = grade.to_dict()
                review["street"] = street.value
                review["action"] = action.value
                review["equity"] = equity  # 판정에 쓴 값(vs_range)
                review["pot_odds"] = equity_info["pot_odds"] if equity_info else None
                review["gto_freq"] = (gto_freqs or {}).get(
                    "raise" if action.value == "allin" else action.value
                ) if gto_freqs else None
                self.hand_reviews.append(review)

            return equity, gto_freqs
        except Exception:
            return None, None
