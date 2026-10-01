"""
GTO 데이터 로더 — SQLite 기반
프리플랍 노드를 처음 쓸 때 DB에서 전부 읽어 메모리에 캐시한다.
노드+핸드 읽기(`read_preflop_nodes`)와 빈도합 허용 범위(`FREQ_SUM_MIN/MAX`)는 이 모듈 하나가
주인이다 — 서버 저장 API·수집기·감사 스크립트가 같은 함수·상수를 쓴다.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import random
from typing import Optional
from core.card import Card

logger = logging.getLogger(__name__)

# 핸드별 fold+call+raise+allin 합 허용 범위(ADR 0002). 밖이면 손상 데이터 — 저장 거부,
# 로드 시 스킵(잔여를 특정 액션에 몰아주지 않는다).
FREQ_SUM_MIN = 0.9
FREQ_SUM_MAX = 1.1

ACTIONS = ("fold", "call", "raise", "allin")

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


def freq_sum_ok(freqs: dict) -> bool:
    """핸드 하나의 액션 빈도 합이 [FREQ_SUM_MIN, FREQ_SUM_MAX] 안인가."""
    total = sum((freqs.get(a) or 0.0) for a in ACTIONS)
    return FREQ_SUM_MIN <= total <= FREQ_SUM_MAX


def read_preflop_nodes(conn) -> list:
    """`gto_preflop_situations` 전 행(id 순)을 핸드와 함께 읽는다(필터·검증 없음).

    반환: [{id, action_seq, position, vs_position, range_type, raise_size, situation_label,
    hero_position, hands: {hand: {action: freq}}}] — 핸드 빈도는 0보다 큰 액션만 담는다.
    conn은 sqlite3.Row 팩토리 연결(읽기 전용 연결도 된다).
    """
    hands_by_sid: dict = {}
    for h in conn.execute(
        "SELECT situation_id, hand, freq_fold, freq_call, freq_raise, freq_allin "
        "FROM gto_preflop_hands"
    ):
        freqs = {a: h[f"freq_{a}"] for a in ACTIONS if (h[f"freq_{a}"] or 0) > 0}
        hands_by_sid.setdefault(h["situation_id"], {})[h["hand"]] = freqs
    nodes = []
    for s in conn.execute("SELECT * FROM gto_preflop_situations ORDER BY id"):
        keys = s.keys()
        nodes.append({
            "id": s["id"],
            "action_seq": s["action_seq"],
            "position": s["position"],
            "vs_position": s["vs_position"],
            "range_type": s["range_type"],
            "raise_size": s["raise_size"],
            "situation_label": s["situation_label"],
            "hero_position": s["hero_position"] if "hero_position" in keys else None,
            "hands": hands_by_sid.get(s["id"], {}),
        })
    return nodes


def collected_by_seq(nodes: list) -> dict:
    """read_preflop_nodes 결과 → {action_seq: {"hands", "raise_size"}} (수집기·감사용)."""
    return {
        n["action_seq"]: {"hands": n["hands"], "raise_size": n["raise_size"]}
        for n in nodes if n["action_seq"] is not None
    }


# ──────────────────────────────────────────
# 메모리 캐시
# _cache: (position, vs_position, range_type) → range_data (콜러 없는 노드만)
# _cache_by_seq: action_seq → range_data (같은 객체 공유)
# ──────────────────────────────────────────
_cache: dict = {}
_cache_by_seq: dict = {}
_loaded: bool = False


def invalidate() -> None:
    """캐시를 비운다 — 다음 조회 때 DB에서 다시 읽는다(저장 API가 저장 후 호출)."""
    global _cache, _cache_by_seq, _loaded
    _cache = {}
    _cache_by_seq = {}
    _loaded = False


def _load_all() -> None:
    """첫 사용 시 DB에서 전체 프리플랍 데이터를 로드."""
    global _cache, _cache_by_seq, _loaded
    if _loaded:
        return
    by_label: dict = {}
    by_seq: dict = {}
    try:
        from db.connection import get_connection
        from gto.node_key import has_caller

        conn = get_connection()
        try:
            nodes = read_preflop_nodes(conn)
        finally:
            conn.close()

        for s in nodes:
            hands = {}
            for hand, freqs in s["hands"].items():
                if not freq_sum_ok(freqs):
                    logger.warning(
                        "GTO 손상 핸드 스킵: situation_id=%s hand=%s freqs=%s",
                        s["id"], hand, freqs,
                    )
                    continue
                hands[hand] = freqs

            seq_key = s["action_seq"]
            entry = {
                "situation":  s["situation_label"],
                "raise_size": s["raise_size"],  # REAL(bb) 또는 None
                "range_type": s["range_type"],
                "hands":      hands,
                "node_key":   seq_key,
            }
            if seq_key is not None:
                by_seq[seq_key] = entry

            # 간단 라벨(ADR 0035 2순위)은 콜러 없는 노드만 대표한다 — 콜러 있는 노드를 라벨로
            # 내주면 헤즈업 팟이 멀티웨이 데이터를 받는다(ADR 0044).
            if seq_key is None or has_caller(seq_key):
                continue
            key = (s["position"], s["vs_position"], s["range_type"])
            if key in by_label:
                logger.warning(
                    "GTO 라벨 %s에 콜러 없는 노드가 여럿: %r 유지, %r 무시",
                    key, by_label[key].get("node_key"), seq_key,
                )
                continue
            by_label[key] = entry
    except Exception as e:
        # DB 없거나 마이그레이션 전이면 실패 (힌트 없음) — 원인은 로그로 남긴다
        logger.warning("GTO 프리플랍 데이터 로드 실패: %s", e)
    _cache, _cache_by_seq, _loaded = by_label, by_seq, True


def get_range_by_seq(node_key) -> Optional[dict]:
    """노드 키(action_seq)로 프리플랍 레인지 조회. UTG RFI는 "". 없으면 None."""
    _load_all()
    return _cache_by_seq.get(node_key)


def get_children_by_prefix(prefix) -> list:
    """프리픽스 **바로 다음 위치**에 수집된 노드 키들이 갖는 토큰 목록(중복 제거, 등장 순).

    prefix = 토큰을 '-'로 이은 문자열(루트=""). 반환 토큰은 수집된 형제 노드들의 그 지점
    액션(F/X/C/R{실측bb})이며 레이즈 형제 스냅에 쓰인다(ADR 0010).

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
    핸드가 없으면(손상되어 로드 시 스킵됐거나 원래 미수집) None — 상위 호출부가 "데이터 없음"으로
    처리하고 휴리스틱 폴백을 탄다(부족분을 fold 등 특정 액션에 몰아주지 않음, ADR 0002).
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
