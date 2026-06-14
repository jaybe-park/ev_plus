"""
분석용 쿼리 헬퍼
"""

import json
from typing import Optional
from .connection import get_connection


class PokerDB:
    def __init__(self, db_path: Optional[str] = None):
        self.conn = get_connection(db_path) if db_path else get_connection()

    # ── 게임 조회 ─────────────────────────────────────

    def get_game(self, game_uuid: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM games WHERE game_uuid = ?", (game_uuid,)
        ).fetchone()
        return dict(row) if row else None

    def get_recent_games(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM games ORDER BY played_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_hand_actions(self, game_uuid: str) -> list[dict]:
        """한 판의 전체 액션 (프리플랍 + 포스트플랍 통합, 시간순)"""
        pre = self.conn.execute("""
            SELECT 'preflop' as type, action_seq, street_seq, position, is_human,
                   'preflop' as street, bet_round, pot_before, stack_before,
                   current_bet, call_amount, action, amount, amount_bb,
                   gto_fold, gto_call, NULL as gto_check,
                   gto_raise as gto_raise_main, gto_allin,
                   NULL as reward
            FROM preflop_actions WHERE game_uuid = ?
        """, (game_uuid,)).fetchall()

        post = self.conn.execute("""
            SELECT 'postflop' as type, action_seq, street_seq, position, is_human,
                   street, NULL as bet_round, pot_before, stack_before,
                   current_bet, call_amount, action, amount, NULL as amount_bb,
                   gto_fold, gto_call, gto_check,
                   gto_raise_75 as gto_raise_main, gto_allin,
                   reward
            FROM postflop_actions WHERE game_uuid = ?
        """, (game_uuid,)).fetchall()

        combined = [dict(r) for r in pre] + [dict(r) for r in post]
        return sorted(combined, key=lambda x: x["action_seq"])

    # ── 통계 쿼리 ─────────────────────────────────────

    def get_player_stats(self, is_human: bool = True) -> dict:
        """
        VPIP / PFR / 3bet 빈도 등 기본 통계
        VPIP: 프리플랍에서 자발적으로 베팅/콜한 비율 (SB/BB 포스팅 제외)
        PFR:  프리플랍 레이즈 비율
        """
        h = int(is_human)
        total_games = self.conn.execute(
            "SELECT COUNT(DISTINCT game_uuid) n FROM preflop_actions WHERE is_human=?", (h,)
        ).fetchone()["n"]

        if total_games == 0:
            return {}

        vpip = self.conn.execute("""
            SELECT COUNT(DISTINCT game_uuid) n FROM preflop_actions
            WHERE is_human=? AND action IN ('call','raise','allin')
            AND bet_round = 'open'
        """, (h,)).fetchone()["n"]

        pfr = self.conn.execute("""
            SELECT COUNT(DISTINCT game_uuid) n FROM preflop_actions
            WHERE is_human=? AND action IN ('raise','allin')
            AND bet_round = 'open'
        """, (h,)).fetchone()["n"]

        threbet = self.conn.execute("""
            SELECT COUNT(DISTINCT game_uuid) n FROM preflop_actions
            WHERE is_human=? AND action IN ('raise','allin')
            AND bet_round = '3bet'
        """, (h,)).fetchone()["n"]

        total_postflop = self.conn.execute(
            "SELECT COUNT(*) n FROM postflop_actions WHERE is_human=?", (h,)
        ).fetchone()["n"]

        avg_reward = self.conn.execute("""
            SELECT AVG(reward) v FROM postflop_actions
            WHERE is_human=? AND street='river' AND reward IS NOT NULL
        """, (h,)).fetchone()["v"]

        return {
            "total_games":   total_games,
            "vpip":          round(vpip / total_games * 100, 1),
            "pfr":           round(pfr  / total_games * 100, 1),
            "3bet_pct":      round(threbet / total_games * 100, 1),
            "total_actions": total_postflop,
            "avg_reward_bb": round(avg_reward, 2) if avg_reward else None,
        }

    def get_gto_deviation(self, is_human: bool = True) -> list[dict]:
        """
        GTO 대비 가장 많이 이탈한 상황 TOP 10
        GTO가 fold를 권장(>50%)했는데 실제로 call/raise한 경우 등
        """
        h = int(is_human)
        rows = self.conn.execute("""
            SELECT
                p.game_uuid, p.street, p.position, p.action,
                p.pot_before, p.amount,
                p.gto_fold, p.gto_call, p.gto_raise_75,
                p.reward,
                g.played_at
            FROM postflop_actions p
            JOIN games g ON p.game_uuid = g.game_uuid
            WHERE p.is_human = ?
              AND p.gto_fold > 0.5
              AND p.action IN ('call','raise','allin')
            ORDER BY p.gto_fold DESC
            LIMIT 10
        """, (h,)).fetchall()
        return [dict(r) for r in rows]

    def get_position_stats(self, is_human: bool = True) -> list[dict]:
        """포지션별 수익 통계"""
        h = int(is_human)
        rows = self.conn.execute("""
            SELECT
                position,
                COUNT(*) total_actions,
                SUM(CASE WHEN action IN ('raise','allin') THEN 1 ELSE 0 END) raises,
                SUM(CASE WHEN action = 'fold' THEN 1 ELSE 0 END) folds,
                AVG(reward) avg_reward
            FROM postflop_actions
            WHERE is_human = ?
            GROUP BY position
            ORDER BY position
        """, (h,)).fetchall()
        return [dict(r) for r in rows]

    def get_preflop_range_stats(self, position: str, is_human: bool = True) -> dict:
        """특정 포지션의 프리플랍 오픈 통계"""
        h = int(is_human)
        rows = self.conn.execute("""
            SELECT action, COUNT(*) n, AVG(amount_bb) avg_bb
            FROM preflop_actions
            WHERE is_human=? AND position=? AND bet_round='open'
            GROUP BY action
        """, (h, position)).fetchall()
        return {r["action"]: {"count": r["n"], "avg_bb": r["avg_bb"]} for r in rows}

    def close(self):
        self.conn.close()
