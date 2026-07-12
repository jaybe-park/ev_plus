"""
GTO 어드바이저
현재 게임 상황 → GTO 추천 액션 + 빈도 반환
사람 힌트 표시 및 봇 전략에 활용
"""

from typing import Optional
from .loader import (
    hand_to_notation, get_open_range, get_vs_open_range, get_vs_3bet_range,
    get_action_frequencies, sample_action, find_opener_position
)
from .url_generator import get_url, POS_INDEX
from core.card import Card


def _save_missing_spot(
    range_type: str, position: str, vs_position: str, situation_label: str
) -> None:
    """미수집 GTO 스팟을 DB에 저장 (중복 무시)."""
    try:
        from db.connection import get_connection
        url = get_url(range_type, position, vs_position)
        conn = get_connection()
        conn.execute(
            """
            INSERT OR IGNORE INTO gto_missing_spots_preflop
                (street, position, vs_position, range_type, situation_label, gto_wizard_url)
            VALUES ('preflop', ?, ?, ?, ?, ?)
            """,
            (position, vs_position, range_type, situation_label, url),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # DB 없거나 오류 시 조용히 무시


def _count_preflop_raises(action_log: list) -> int:
    """action_log에서 프리플랍 레이즈 횟수 계산"""
    count = 0
    for entry in action_log:
        if "──" in entry:  # 스트리트 구분선
            break
        if "레이즈" in entry:
            count += 1
    return count


def _find_raisers_in_log(action_log: list, positions: dict) -> list:
    """action_log에서 레이즈한 포지션 목록 (순서대로)"""
    raisers = []
    for entry in action_log:
        if "──" in entry:
            break
        if "레이즈" in entry:
            for name, pos in positions.items():
                if name in entry and pos not in raisers:
                    raisers.append(pos)
                    break
    return raisers


class GTOAdvisor:

    def get_recommendation(
        self,
        hole_cards: list,
        my_position: str,
        positions: dict,
        game_state: dict,
        big_blind: int = 20,
    ) -> Optional[dict]:
        """
        현재 상황에 맞는 GTO 추천 반환.
        RFI / vs_open / vs_3bet 세 가지 상황 지원.
        """
        if len(hole_cards) < 2:
            return None

        hand = hand_to_notation(hole_cards[0], hole_cards[1])
        current_bet = game_state.get("current_bet", 0)
        street = game_state.get("street", "프리플랍")
        action_log = game_state.get("action_log", [])

        if street != "프리플랍":
            return None

        # ── 베팅 라운드 판별 ────────────────────────────
        raise_count = _count_preflop_raises(action_log)
        is_rfi = current_bet <= big_blind

        # RFI
        # BB는 강제 베팅 상태라 "오픈(RFI)"이 원천적으로 불가능하다.
        # 림프된 팟(current_bet == big_blind)에서 BB가 레이즈하는 상황은
        # 우리 데이터 모델이 지원하지 않으므로 조회/기록 없이 폴백시킨다.
        if is_rfi and my_position != "BB":
            range_data = get_open_range(my_position)
            if range_data is None:
                _save_missing_spot("open", my_position, "", f"{my_position} RFI")
                return None
            freqs = get_action_frequencies(range_data, hand)
            if freqs is None:
                # 핸드 데이터 손상(로드 시 스킵됨) 또는 미수집 — 특정 액션에
                # 몰아주지 않고 상위(봇)가 휴리스틱 폴백을 타도록 None 반환.
                return None
            return {
                "hand": hand,
                "frequencies": freqs,
                "situation": range_data.get("situation", f"{my_position} RFI"),
                # 실측 bb 값만 사용 — 없으면 None (추측/플레이스홀더 금지, 상위에서 폴백 처리)
                "raise_size": range_data.get("raise_size") or None,
                "raise_count": 0,
            }

        # vs_open (레이즈 1번)
        if raise_count <= 1:
            opener_pos = find_opener_position(positions, game_state, big_blind)
            if opener_pos is None:
                return None
            # 우리 데이터 모델은 "오프너가 나보다 먼저 행동하는" open/vs_open
            # 구조만 지원한다. (예: 림프 후 아이솔레이트 레이즈처럼) 오프너가
            # 포지션 순서상 my_position보다 뒤인 경우는 데이터 모델 밖의
            # 상황이므로 조회/기록 없이 None 반환. 헤즈업 포지션(BTN/SB 등
            # POS_INDEX에 없는 값)은 비교 불가하므로 기존 로직을 유지한다.
            if my_position in POS_INDEX and opener_pos in POS_INDEX:
                if POS_INDEX[opener_pos] > POS_INDEX[my_position]:
                    return None
            range_data = get_vs_open_range(my_position, opener_pos)
            if range_data is None:
                _save_missing_spot(
                    "vs_open", my_position, opener_pos,
                    f"{my_position} vs {opener_pos} open"
                )
                return None
            freqs = get_action_frequencies(range_data, hand)
            if freqs is None:
                return None
            return {
                "hand": hand,
                "frequencies": freqs,
                "situation": range_data.get("situation", f"{my_position} vs {opener_pos}"),
                "raise_size": range_data.get("raise_size") or None,
                "raise_count": 1,
            }

        # vs_3bet (레이즈 2번)
        if raise_count == 2:
            raisers = _find_raisers_in_log(action_log, positions)
            if len(raisers) >= 2:
                opener_pos, three_bettor_pos = raisers[0], raisers[1]
                # 우리 데이터 모델은 "원래 오프너가 3벳에 대응하는" 레인지만
                # 수집한다. my_position이 오프너가 아니면(림프 후 대응 등)
                # 데이터 모델 밖의 상황이므로 조회/기록 없이 None 반환.
                if my_position != opener_pos:
                    return None
                range_data = get_vs_3bet_range(my_position, opener_pos, three_bettor_pos)
                if range_data is None:
                    _save_missing_spot(
                        "vs_3bet", my_position,
                        f"{opener_pos}/{three_bettor_pos}",
                        f"{my_position} vs {three_bettor_pos} 3bet (over {opener_pos})"
                    )
                    return None
                freqs = get_action_frequencies(range_data, hand)
                if freqs is None:
                    return None
                return {
                    "hand": hand,
                    "frequencies": freqs,
                    "situation": range_data.get("situation", f"{my_position} vs 3bet"),
                    "raise_size": range_data.get("raise_size") or None,
                    "raise_count": 2,
                }

        # 4벳+ 이상: GTO 데이터 없음 → None 반환 (봇이 별도 처리)
        return None

    def format_hint(self, recommendation: Optional[dict]) -> Optional[str]:
        """사람용 힌트 문자열 생성"""
        if recommendation is None:
            return None

        freqs = recommendation["frequencies"]
        hand = recommendation["hand"]
        situation = recommendation["situation"]

        action_map = {"fold": "폴드", "call": "콜", "raise": "레이즈"}
        parts = []
        for action, freq in freqs.items():
            if freq > 0.01:
                label = action_map.get(action, action)
                parts.append(f"{label} {freq*100:.0f}%")

        if not parts:
            return None

        return f"📊 GTO [{hand}] {situation}: {' / '.join(parts)}"

    def get_bot_action(
        self,
        hole_cards: list,
        my_position: str,
        positions: dict,
        game_state: dict,
        big_blind: int = 20,
        gto_compliance: float = 1.0,
    ) -> Optional[dict]:
        """
        봇용 GTO 액션 샘플링.
        반환: {"action": "fold"|"call"|"raise", "raise_count": N} 또는 None
        """
        import random
        if random.random() > gto_compliance:
            return None

        rec = self.get_recommendation(hole_cards, my_position, positions, game_state, big_blind)
        if rec is None:
            return None

        action = sample_action(rec["frequencies"])
        return {
            "action": action,
            "raise_count": rec.get("raise_count", 0),
            "raise_size": rec.get("raise_size"),  # 실측 bb (REAL) 또는 None
        }
