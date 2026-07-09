"""
게임 기록기
플레이 중 발생하는 액션을 DB에 저장
"""

import json
import uuid
from datetime import datetime
from typing import Optional

from core.card import Card
from core.game import Action, Street
from core.player import Player
from .card_notation import card_to_str, cards_to_str
from .connection import get_connection


def _detect_bet_round(history: list[dict], current_action: str) -> str:
    """
    현재 베팅 라운드 판별 (open / 3bet / 4bet / 5bet)

    history: 이 액션 직전까지의 기록 (현재 액션 미포함)
    current_action: 현재 실행할 액션 문자열

    라운드 판별 기준 (현재 액션 포함 raise 횟수):
      raise 1번 → open   (첫 오픈)
      raise 1번 후 fold/call → open 라운드 반응
      raise 2번 → 3bet
      raise 2번 후 fold/call → 3bet 라운드 반응
      raise 3번 → 4bet
      ...
    """
    past_raises = sum(1 for a in history if a["action"] in ("raise", "allin"))
    is_raise = current_action in ("raise", "allin")
    total = past_raises + (1 if is_raise else 0)

    if total <= 1:
        return "open"
    elif total == 2:
        return "3bet"
    elif total == 3:
        return "4bet"
    else:
        return "5bet"


class GameRecorder:
    """
    핸드 한 판을 기록하는 컨텍스트 매니저 역할 객체.

    사용법:
        recorder = GameRecorder(big_blind=20)
        recorder.start_hand(players, dealer_pos, hole_cards_map)
        recorder.record_action(player, position, street, game_state, action, amount)
        recorder.finish_hand(community_cards, pot_total, winner_positions, player_results)
    """

    def __init__(self, db_path: Optional[str] = None, big_blind: int = 20):
        self.big_blind = big_blind
        self.db_path = db_path

        self.game_uuid: str = ""
        self.action_seq: int = 0
        self.street_seqs: dict = {"preflop": 0, "flop": 0, "turn": 0, "river": 0}
        self._preflop_history: list = []  # bet_round 판별용

        # record_action()은 DB에 쓰지 않고 여기 버퍼링만 한다.
        # finish_hand()에서 한 트랜잭션으로 일괄 INSERT+commit.
        self._pending_preflop: list = []
        self._pending_postflop: list = []

    def start_hand(
        self,
        players: list[Player],
        dealer_pos: str,
        hole_cards_map: dict[str, list[Card]],  # {"BTN": [Card, Card], ...}
        small_blind: int = 10,
    ):
        """새 핸드 시작 — games 테이블에 기본 정보 삽입"""
        self.game_uuid = str(uuid.uuid4())
        self.action_seq = 0
        self.street_seqs = {"preflop": 0, "flop": 0, "turn": 0, "river": 0}
        self._preflop_history = []
        # 이전 핸드가 finish_hand() 없이 비정상 종료된 경우 남아있을 수 있는
        # pending 버퍼를 버리고 새로 시작한다.
        self._pending_preflop = []
        self._pending_postflop = []

        # 홀카드 JSON 직렬화
        hole_cards_json = {
            pos: "".join(card_to_str(c) for c in cards)
            for pos, cards in hole_cards_map.items()
        }

        # player_results 초기값 (시작 칩만)
        player_results = {
            p.name: {"start": p.chips, "end": 0}
            for p in players
        }

        conn = get_connection(self.db_path) if self.db_path else get_connection()
        try:
            cur = conn.execute("""
                INSERT INTO games (
                    game_uuid, played_at, num_players,
                    small_blind, big_blind, dealer_pos,
                    hole_cards, pot_total, winner_pos, player_results
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                self.game_uuid,
                datetime.now().isoformat(),
                len(players),
                small_blind,
                self.big_blind,
                dealer_pos,
                json.dumps(hole_cards_json),
                0,           # 나중에 finish_hand에서 업데이트
                json.dumps([]),
                json.dumps(player_results),
            ))
            cur.close()
            conn.commit()
        finally:
            conn.close()

    def record_action(
        self,
        position: str,
        is_human: bool,
        street: Street,
        game_state: dict,
        action: Action,
        amount: int,
        gto: Optional[dict] = None,
        call_amount: Optional[int] = None,
        equity: Optional[float] = None,
        bot_profile: Optional[str] = None,
        players_state: Optional[str] = None,
    ):
        """
        액션 1건 기록.
        gto 예시:
          프리플랍: {"fold":0.0, "call":0.2, "raise":0.8, "allin":0.0}
          포스트플랍: {"fold":0.3, "check":0.0, "call":0.4, "raise_33":0.1, "raise_75":0.2, ...}

        DB에는 접근하지 않는다 — 값만 계산해 pending 버퍼에 append하고,
        실제 INSERT는 finish_hand()에서 한 트랜잭션으로 일괄 처리한다.
        (액션마다 커밋하면 recorder 커넥션이 쓰기 트랜잭션을 장시간 점유해
        다른 프로세스의 쓰기가 busy_timeout까지 블로킹되는 문제가 있었음)
        """
        street_name = street.value  # "프리플랍" 등 한글 → 영문 매핑
        street_key = {
            "프리플랍": "preflop", "플랍": "flop",
            "턴": "turn", "리버": "river"
        }.get(street_name, street_name)

        seq = self.action_seq
        s_seq = self.street_seqs[street_key]
        self.action_seq += 1
        self.street_seqs[street_key] += 1

        action_str = action.value  # "fold", "call" 등
        pot_before = game_state.get("pot", 0)
        current_bet = game_state.get("current_bet", 0)
        if call_amount is None:
            call_amount = 0

        if street_key == "preflop":
            self._buffer_preflop(
                position, is_human, seq, s_seq,
                pot_before, game_state.get("stack_before", 0),
                current_bet, call_amount,
                action_str, amount, gto, equity, bot_profile, players_state
            )
            self._preflop_history.append({"action": action_str})
        else:
            self._buffer_postflop(
                position, is_human, street_key, seq, s_seq,
                pot_before, game_state.get("stack_before", 0),
                current_bet, call_amount,
                action_str, amount, gto, equity, bot_profile, players_state
            )

    def _buffer_preflop(
        self, position, is_human, seq, s_seq,
        pot_before, stack_before, current_bet, call_amount,
        action, amount, gto, equity=None, bot_profile=None, players_state=None
    ):
        bet_round = _detect_bet_round(self._preflop_history, action)
        amount_bb = round(amount / self.big_blind, 2) if amount > 0 else 0.0
        g = gto or {}
        self._pending_preflop.append((
            self.game_uuid, seq, s_seq,
            position, int(is_human), bet_round,
            pot_before, stack_before, current_bet, call_amount,
            action, amount, amount_bb,
            equity, bot_profile, players_state,
            g.get("fold"), g.get("call"), g.get("raise"), g.get("allin"),
        ))

    def _buffer_postflop(
        self, position, is_human, street, seq, s_seq,
        pot_before, stack_before, current_bet, call_amount,
        action, amount, gto, equity=None, bot_profile=None, players_state=None
    ):
        g = gto or {}
        self._pending_postflop.append((
            self.game_uuid, seq, s_seq,
            position, int(is_human), street,
            pot_before, stack_before, current_bet, call_amount,
            action, amount,
            equity, bot_profile, players_state,
            g.get("fold"), g.get("check"), g.get("call"),
            g.get("raise_33"), g.get("raise_50"), g.get("raise_75"),
            g.get("raise_100"), g.get("raise_150"), g.get("allin"),
        ))

    def finish_hand(
        self,
        community_cards: list[Card],
        pot_total: int,
        winner_positions: list[str],
        player_results: dict,   # {"BTN": {"start":1000,"end":1150}, ...}
    ):
        """
        핸드 종료 — pending 액션 일괄 INSERT, games 테이블 업데이트,
        postflop/preflop reward 역산까지 전부 한 트랜잭션으로 처리 후 commit.
        """
        comm = cards_to_str(community_cards)
        flop  = comm[:3] if len(comm) >= 3 else [None, None, None]
        turn  = comm[3]  if len(comm) >= 4 else None
        river = comm[4]  if len(comm) >= 5 else None

        conn = get_connection(self.db_path) if self.db_path else get_connection()
        try:
            if self._pending_preflop:
                cur = conn.executemany("""
                    INSERT INTO preflop_actions (
                        game_uuid, action_seq, street_seq,
                        position, is_human, bet_round,
                        pot_before, stack_before, current_bet, call_amount,
                        action, amount, amount_bb,
                        equity, bot_profile, players_state,
                        gto_fold, gto_call, gto_raise, gto_allin
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, self._pending_preflop)
                cur.close()

            if self._pending_postflop:
                cur = conn.executemany("""
                    INSERT INTO postflop_actions (
                        game_uuid, action_seq, street_seq,
                        position, is_human, street,
                        pot_before, stack_before, current_bet, call_amount,
                        action, amount,
                        equity, bot_profile, players_state,
                        gto_fold, gto_check, gto_call,
                        gto_raise_33, gto_raise_50, gto_raise_75,
                        gto_raise_100, gto_raise_150, gto_allin
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, self._pending_postflop)
                cur.close()

            cur = conn.execute("""
                UPDATE games SET
                    flop_1 = ?, flop_2 = ?, flop_3 = ?,
                    turn_card = ?, river_card = ?,
                    pot_total = ?,
                    winner_pos = ?,
                    player_results = ?
                WHERE game_uuid = ?
            """, (
                flop[0], flop[1], flop[2],
                turn, river,
                pot_total,
                json.dumps(winner_positions),
                json.dumps(player_results),
                self.game_uuid,
            ))
            cur.close()

            # postflop reward 역산: 포지션별 손익 / big_blind
            for pos, result in player_results.items():
                reward = (result["end"] - result["start"]) / self.big_blind
                for table in ("postflop_actions", "preflop_actions"):
                    cur = conn.execute(
                        f"UPDATE {table} SET reward = ? "
                        "WHERE game_uuid = ? AND position = ?",
                        (reward, self.game_uuid, pos))
                    cur.close()

            conn.commit()
        finally:
            conn.close()

        # pending 버퍼 비우기
        self._pending_preflop = []
        self._pending_postflop = []

    def close(self):
        """하위호환용 no-op. 커넥션을 더 이상 영속 보관하지 않는다."""
        pass
