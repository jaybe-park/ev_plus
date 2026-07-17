"""
GTO 데이터 로더 — SQLite 기반 (v2)
앱 시작 시 프리플랍 데이터 전체를 메모리에 로드하고 캐시.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import random
from typing import Optional
from core.card import Card, Rank

logger = logging.getLogger(__name__)

# 핸드별 빈도 합 검증 허용 범위. 이 밖이면 손상 데이터로 간주해 조용히 넘어가지
# 않고(=fold 등 특정 액션에 잔여를 몰아주지 않고) "데이터 없음"으로 처리한다.
_FREQ_SUM_MIN = 0.9
_FREQ_SUM_MAX = 1.1

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
# ② 시퀀스 키(노드 키) → range_data dict. _cache와 같은 range_data 객체를 공유.
_cache_by_seq: dict = {}
_loaded: bool = False


def _load_all() -> None:
    """앱 첫 사용 시 DB에서 전체 프리플랍 데이터를 로드."""
    global _loaded
    if _loaded:
        return
    # 재로드(테스트가 _loaded=False로 무효화) 시 시퀀스 캐시도 함께 초기화
    _cache_by_seq.clear()

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
                freq_sum = (
                    h["freq_fold"] + h["freq_call"] + h["freq_raise"] + h["freq_allin"]
                )
                if not (_FREQ_SUM_MIN <= freq_sum <= _FREQ_SUM_MAX):
                    # 손상 핸드 — 원인 불명 상태에서 잔여를 특정 액션에 몰아주지
                    # 않고 "데이터 없음"으로 처리해 상위 호출부가 휴리스틱 폴백을
                    # 타도록 한다. 조용히 넘어가지 않고 식별 가능하게 경고 로그.
                    logger.warning(
                        "GTO 손상 핸드 스킵: situation_id=%s hand=%s freq_sum=%.3f "
                        "(fold=%.3f call=%.3f raise=%.3f allin=%.3f)",
                        s["id"], h["hand"], freq_sum,
                        h["freq_fold"], h["freq_call"], h["freq_raise"], h["freq_allin"],
                    )
                    continue

                freqs = {}
                if h["freq_fold"]  > 0: freqs["fold"]  = h["freq_fold"]
                if h["freq_call"]  > 0: freqs["call"]  = h["freq_call"]
                if h["freq_raise"] > 0: freqs["raise"] = h["freq_raise"]
                if h["freq_allin"] > 0: freqs["allin"] = h["freq_allin"]
                if not freqs:
                    freqs = {"fold": 1.0}
                hands[h["hand"]] = freqs

            key = (s["position"], s["vs_position"], s["range_type"])
            entry = {
                "situation":     s["situation_label"],
                "raise_size":    s["raise_size"],  # REAL(bb) 또는 None — 텍스트 플레이스홀더 없음
                "range_type":    s["range_type"],
                "hands":         hands,
            }
            _cache[key] = entry

            # ② 시퀀스 키 병렬 인덱스(있는 행만). enum 캐시와 동일 객체 공유 →
            # 두 경로가 항상 같은 레인지를 가리킴(검증 게이트 a).
            cols = s.keys()
            seq_key = s["action_seq"] if "action_seq" in cols else None
            if seq_key is not None:
                _cache_by_seq[seq_key] = entry

        conn.close()
        _loaded = True

    except Exception as e:
        # DB 없거나 마이그레이션 전이면 조용히 실패 (힌트 없음)
        _loaded = True  # 재시도 방지


def get_range_by_seq(node_key) -> Optional[dict]:
    """② 캐노니컬 노드 키로 프리플랍 레인지 조회(시퀀스 키 경로).

    node_key는 gto.advisor.canonical_node_key / gto.url_generator.situation_to_node_key가
    생성한 캐노니컬 문자열(예: "R2.5-R8-F-F-F-F", RFI UTG는 ""). 없으면 None.
    """
    _load_all()
    return _cache_by_seq.get(node_key)


def get_children_by_prefix(prefix) -> list:
    """②' 데이터 기반 트리-인지 스냅용: 주어진 프리픽스 **바로 다음 위치**에
    수집된 노드 키들이 실제로 갖는 토큰 목록(중복 제거, 등장 순서 유지)을 반환.

    prefix = 지금까지 만든 캐노니컬 토큰들을 '-'로 join한 문자열(루트=""). 반환 토큰은
    수집된 형제 노드들의 그 지점 액션(F/X/C/R{실측bb})이며, 레이즈 형제 스냅에 쓰인다.
    수집 데이터(_cache_by_seq)에서만 읽으므로 하드코딩 사이즈 테이블에 의존하지 않는다.

    예: 수집분에 "R2.5-R8-F-F-F-F"만 있으면
        get_children_by_prefix("")      → ["R2.5"]
        get_children_by_prefix("R2.5")  → ["R8"]
    """
    _load_all()
    pref_toks = prefix.split("-") if prefix else []
    n = len(pref_toks)
    out = []
    seen = set()
    for k in _cache_by_seq.keys():
        toks = k.split("-") if k else []
        if len(toks) <= n:
            continue
        if toks[:n] != pref_toks:
            continue
        child = toks[n]
        if child not in seen:
            seen.add(child)
            out.append(child)
    return out


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


def get_action_frequencies(range_data: dict, hand_notation: str) -> Optional[dict]:
    """
    레인지 데이터에서 특정 핸드의 액션 빈도 반환.
    핸드가 없으면(손상되어 로드 시 스킵됐거나 원래 미수집) None을 반환해
    상위 호출부가 "데이터 없음"으로 처리하고 휴리스틱 폴백을 타게 한다.
    (부족분을 fold 등 특정 액션에 몰아주지 않음 — 원인 불명 상태에서 새 가정을 얹지 않기 위함)
    """
    if range_data is None:
        return None
    return range_data.get("hands", {}).get(hand_notation)


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
