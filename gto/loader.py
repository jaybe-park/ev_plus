"""
GTO 데이터 로더
홀카드 → 핸드 표기 변환 + JSON 레인지 로드
"""

import json
import os
from typing import Optional
from core.card import Card, Rank

# 데이터 루트 경로
_DATA_ROOT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "gto_data", "preflop")
_cache: dict = {}


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

    # 높은 랭크가 앞에
    if r1.rank_value < r2.rank_value:
        r1, r2 = r2, r1

    s1, s2 = _rank_sym(r1), _rank_sym(r2)
    if r1 == r2:
        return f"{s1}{s2}"
    elif suited:
        return f"{s1}{s2}s"
    else:
        return f"{s1}{s2}o"


def load_range(path: str) -> Optional[dict]:
    """JSON 레인지 파일 로드 (캐시)"""
    if path in _cache:
        return _cache[path]
    full_path = os.path.join(_DATA_ROOT, path)
    if not os.path.exists(full_path):
        return None
    with open(full_path, encoding="utf-8") as f:
        data = json.load(f)
    _cache[path] = data
    return data


def get_open_range(position: str) -> Optional[dict]:
    """포지션별 오픈 레인지 로드"""
    return load_range(f"open/{position}.json")


def get_vs_open_range(my_pos: str, opener_pos: str) -> Optional[dict]:
    """상대 오픈에 대한 수비 레인지 로드"""
    fname = f"vs_open/{my_pos}_vs_{opener_pos}.json"
    return load_range(fname)


def get_action_frequencies(range_data: dict, hand_notation: str) -> dict:
    """
    레인지 데이터에서 특정 핸드의 액션 빈도 반환
    없으면 fold 100% 반환
    """
    if range_data is None:
        return {"fold": 1.0}
    hands = range_data.get("hands", {})
    return hands.get(hand_notation, {"fold": 1.0})


def sample_action(frequencies: dict) -> str:
    """
    빈도에 따라 랜덤하게 액션 선택 (혼합 전략 구현)
    예) {"fold":0.3, "raise":0.7} → 70% 확률로 "raise"
    """
    import random
    r = random.random()
    cumulative = 0.0
    for action, freq in frequencies.items():
        cumulative += freq
        if r < cumulative:
            return action
    return list(frequencies.keys())[-1]


def get_open_situation(positions: dict, player_name: str, game_state: dict) -> Optional[str]:
    """
    현재 상황이 오픈 레인지에 해당하는지 판단
    아직 아무도 레이즈 안 했고 내가 첫 오픈이면 → 포지션 반환
    """
    players = game_state.get("players", [])
    # 나보다 앞에 액션한 플레이어 중 레이즈한 사람이 있는지 확인
    my_pos = positions.get(player_name, "")
    any_raise = game_state.get("current_bet", 0) > game_state.get("big_blind", 20)
    if not any_raise:
        return my_pos  # RFI 상황
    return None


def find_opener_position(positions: dict, game_state: dict, big_blind: int) -> Optional[str]:
    """현재 레이즈를 처음 한 플레이어의 포지션 찾기"""
    current_bet = game_state.get("current_bet", 0)
    if current_bet <= big_blind:
        return None
    # current_bet이 BB 초과 → 누군가 오픈했음
    # 가장 많이 베팅한 사람 = 오프너
    players = game_state.get("players", [])
    opener = max(
        (p for p in players if p.get("current_bet", 0) == current_bet),
        key=lambda p: p.get("current_bet", 0),
        default=None
    )
    if opener:
        return positions.get(opener["name"])
    return None
