"""
GTO 어드바이저
현재 게임 상황 → GTO 추천 액션 + 빈도 반환
사람 힌트 표시 및 봇 전략에 활용
"""

from typing import Optional
from .loader import (
    hand_to_notation, get_open_range, get_vs_open_range,
    get_action_frequencies, sample_action, find_opener_position
)
from core.card import Card


class GTOAdvisor:

    def get_recommendation(
        self,
        hole_cards: list[Card],
        my_position: str,
        positions: dict,
        game_state: dict,
        big_blind: int = 20,
    ) -> Optional[dict]:
        """
        현재 상황에 맞는 GTO 추천 반환
        반환: {"hand": "AKs", "frequencies": {"fold":0.0, "raise":1.0}, "situation": "BTN RFI"}
        데이터 없으면 None
        """
        if len(hole_cards) < 2:
            return None

        hand = hand_to_notation(hole_cards[0], hole_cards[1])
        current_bet = game_state.get("current_bet", 0)
        street = game_state.get("street", "프리플랍")

        # 포스트플랍은 아직 미지원
        if street != "프리플랍":
            return None

        # ── 상황 판단 ──────────────────────────────────────
        is_rfi = current_bet <= big_blind  # 아직 오픈 없음 (BB 포스팅만 있는 상태)

        if is_rfi:
            # RFI: 오픈 레인지 참조
            range_data = get_open_range(my_position)
            if range_data is None:
                return None
            freqs = get_action_frequencies(range_data, hand)
            return {
                "hand": hand,
                "frequencies": freqs,
                "situation": range_data.get("situation", f"{my_position} RFI"),
                "raise_size": range_data.get("raise_size", "2.5bb"),
            }

        else:
            # vs 오픈: 오프너 포지션 찾기
            opener_pos = find_opener_position(positions, game_state, big_blind)
            if opener_pos is None:
                return None

            range_data = get_vs_open_range(my_position, opener_pos)
            if range_data is None:
                return None
            freqs = get_action_frequencies(range_data, hand)
            return {
                "hand": hand,
                "frequencies": freqs,
                "situation": range_data.get("situation", f"{my_position} vs {opener_pos}"),
                "raise_size": range_data.get("raise_size", "3x"),
            }

    def format_hint(self, recommendation: Optional[dict]) -> Optional[str]:
        """사람용 힌트 문자열 생성"""
        if recommendation is None:
            return None

        freqs = recommendation["frequencies"]
        hand = recommendation["hand"]
        situation = recommendation["situation"]

        # 빈도 0인 액션 제외 후 표시
        action_map = {"fold": "폴드", "call": "콜", "raise": "레이즈"}
        parts = []
        for action, freq in freqs.items():
            if freq > 0.01:
                label = action_map.get(action, action)
                parts.append(f"{label} {freq*100:.0f}%")

        if not parts:
            return None

        freq_str = " / ".join(parts)
        return f"📊 GTO [{hand}] {situation}: {freq_str}"

    def get_bot_action(
        self,
        hole_cards: list[Card],
        my_position: str,
        positions: dict,
        game_state: dict,
        big_blind: int = 20,
        gto_compliance: float = 1.0,
    ) -> Optional[str]:
        """
        봇용 GTO 액션 샘플링
        gto_compliance: 0.0~1.0 (GTO를 따를 확률)
        None이면 GTO 데이터 없음 → 기존 전략 사용
        """
        import random
        if random.random() > gto_compliance:
            return None  # 기존 전략으로 폴백

        rec = self.get_recommendation(hole_cards, my_position, positions, game_state, big_blind)
        if rec is None:
            return None

        return sample_action(rec["frequencies"])
