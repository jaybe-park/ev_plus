"""
GTO 데이터 로더 — SQLite 기반 (v2)
앱 시작 시 프리플랍 데이터 전체를 메모리에 로드하고 캐시.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random
from typing import Optional
from core.card import Card, Rank

_RANK_GTO = {"10": "T"}

def _rank_sym(rank) -> str:
    return _RANK_GTO.get(rank.symbol, rank.symbol)


def hand_to_notation(card1: Card, card2: Card) -> str:
    """
    홀카드 2장 → GTO 표기 문자열
    예) A♠ K♥ → "AKo",  T♠ 9♠ → "T9s",  K♦ K♣ → "KK"
    """
    r1, r2 = card1.rank, card2.rank
    suited = card1.suit == card2.suit

    if r1.rank_value < r2.rank_value:
        r1, r2 = r2, r1

    s1, s2 = _rank_sym(r1), _rank_sym(r2)
    if r1 == r2:
        return f"{s1}{s2}"
    elif suited:
        return f"{s1}{s2}s"
    else:
        return f"{s1}{s2}o"


# ──────────────────────────────────────────
# 메모리 캐시
# (position, vs_position, range_type) → range_data dict
# ──────────────────────────────────────────
_cache: dict = {}
_loaded: bool = False


def _load_all() -> None:
    """앱 첫 사용 시 DB에서 전체 프리플랍 데이터를 로드."""
    global _loaded
    if _loaded:
        return

    try:
        from db.connection import get_connection
        conn = get_connection()
        cur = conn.cursor()

        situations = cur.execute(
            "SELECT * FROM gto_preflop_situations"
        ).fetchall()

        for s in situations:
            hands_rows = cur.execute(
                "SELECT hand, freq_fold, freq_call, freq_raise, freq_allin "
                "FROM gto_preflop_hands WHERE situation_id = ?",
                (s["id"],)
            ).fetchall()

            hands = {}
            for h in hands_rows:
                freqs = {}
                if h["freq_fold"]  > 0: freqs["fold"]  = h["freq_fold"]
                if h["freq_call"]  > 0: freqs["call"]  = h["freq_call"]
                if h["freq_raise"] > 0: freqs["raise"] = h["freq_raise"]
                if h["freq_allin"] > 0: freqs["allin"] = h["freq_allin"]
                if not freqs:
                    freqs = {"fold": 1.0}
                hands[h["hand"]] = freqs

            key = (s["position"], s["vs_position"], s["range_type"])
            _cache[key] = {
                "situation":     s["situation_label"],
                "raise_size":    s["raise_size"] or "",
                "range_type":    s["range_type"],
                "hands":         hands,
            }

        conn.close()
        _loaded = True

    except Exception as e:
        # DB 없거나 마이그레이션 전이면 조용히 실패 (힌트 없음)
        _loaded = True  # 재시도 방지


def get_vs_3bet_range(my_pos: str, opener_pos: str, three_bettor_pos: str) -> Optional[dict]:
    """3벳에 대한 대응 레인지. vs_position = "opener/three_bettor" 형식"""
    _load_all()
    vs_pos = f"{opener_pos}/{three_bettor_pos}"
    return _cache.get((my_pos, vs_pos, "vs_3bet"))


def get_open_range(position: str) -> Optional[dict]:
    """포지션별 오픈(RFI) 레인지"""
    _load_all()
    return _cache.get((position, None, "open"))


def get_vs_open_range(my_pos: str, opener_pos: str) -> Optional[dict]:
    """상대 오픈에 대한 수비 레인지"""
    _load_all()
    return _cache.get((my_pos, opener_pos, "vs_open"))


def get_raise_range(position: str) -> Optional[dict]:
    """
    포지션의 RFI 레이즈 레인지 (notation → 빈도).
    상대가 오픈 레이즈했을 때 그 상대의 핸드 분포 추정에 사용.
    """
    _load_all()
    data = _cache.get((position, None, "open"))
    if data is None:
        return None
    weights = {}
    for hand, freqs in data.get("hands", {}).items():
        w = freqs.get("raise", 0.0) + freqs.get("allin", 0.0)
        if w > 0.02:
            weights[hand] = w
    return weights or None


def get_call_range(my_pos: str, opener_pos: str) -> Optional[dict]:
    """오픈에 콜한 플레이어의 핸드 분포 (notation → 빈도)."""
    _load_all()
    data = _cache.get((my_pos, opener_pos, "vs_open"))
    if data is None:
        return None
    weights = {}
    for hand, freqs in data.get("hands", {}).items():
        w = freqs.get("call", 0.0)
        if w > 0.02:
            weights[hand] = w
    return weights or None


def get_action_frequencies(range_data: dict, hand_notation: str) -> dict:
    """레인지 데이터에서 특정 핸드의 액션 빈도 반환. 없으면 fold 100%."""
    if range_data is None:
        return {"fold": 1.0}
    return range_data.get("hands", {}).get(hand_notation, {"fold": 1.0})


def sample_action(frequencies: dict) -> str:
    """빈도에 따라 랜덤하게 액션 선택 (혼합 전략)."""
    r = random.random()
    cumulative = 0.0
    for action, freq in frequencies.items():
        cumulative += freq
        if r < cumulative:
            return action
    return list(frequencies.keys())[-1]


def find_opener_position(positions: dict, game_state: dict, big_blind: int) -> Optional[str]:
    """현재 레이즈를 처음 한 플레이어의 포지션 찾기"""
    current_bet = game_state.get("current_bet", 0)
    if current_bet <= big_blind:
        return None
    players = game_state.get("players", [])
    opener = max(
        (p for p in players if p.get("current_bet", 0) == current_bet),
        key=lambda p: p.get("current_bet", 0),
        default=None,
    )
    if opener:
        return positions.get(opener["name"])
    return None
