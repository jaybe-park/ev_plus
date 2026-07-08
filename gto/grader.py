"""
플레이 평가 (Play Grader)
순수 함수 모음 — 사람의 액션이 GTO/EV 관점에서 얼마나 좋았는지 등급화한다.

- 프리플랍: GTO 빈도 기반 4등급
  ✅ 최선 = 최고빈도 액션 / 🟡 무난 = 빈도>25% / 🟠 의문 = 5~25% / 🔴 블런더 = <5%
  GTO 데이터 없는 스팟은 ⬜ "데이터 없음"
- 포스트플랍: equity 기반 근사 EV
  · 콜: EV(콜) = equity×(팟+콜) − 콜 → 음수면 감점 + bb 손실 추정
  · 폴드: equity > 팟오즈+마진이었으면 "놓친 EV" 감점
  · 벳/레이즈/체크: 폴드 에퀴티를 몰라 정확 평가 불가 → v1은 제한 판정만
"""

from dataclasses import dataclass
from typing import Optional, Dict


@dataclass
class GradeResult:
    street: str
    action: str
    grade: str
    reason: str
    ev_loss_bb: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "street": self.street,
            "action": self.action,
            "grade": self.grade,
            "reason": self.reason,
            "ev_loss_bb": self.ev_loss_bb,
        }


def grade_preflop_action(action: str, gto_recommendation: Optional[dict]) -> GradeResult:
    """
    프리플랍 액션 평가.
    gto_recommendation: {"hand", "frequencies": {...}, "situation", "raise_size", "raise_count"} 또는 None.
    """
    if gto_recommendation is None:
        return GradeResult(
            street="프리플랍", action=action, grade="⬜",
            reason="데이터 없음", ev_loss_bb=None,
        )

    freqs: Dict[str, float] = gto_recommendation.get("frequencies", {}) or {}
    if not freqs:
        return GradeResult(
            street="프리플랍", action=action, grade="⬜",
            reason="데이터 없음", ev_loss_bb=None,
        )

    max_action = max(freqs, key=lambda k: freqs[k])
    freq_str = ", ".join(f"{k} {v*100:.0f}%" for k, v in freqs.items() if v > 0.01)

    if action == max_action:
        reason = f"GTO 최빈 액션과 일치 ({freq_str})"
        return GradeResult(street="프리플랍", action=action, grade="✅", reason=reason, ev_loss_bb=None)

    chosen_freq = freqs.get(action, 0.0)
    if chosen_freq > 0.25:
        grade = "🟡"
    elif chosen_freq >= 0.05:
        grade = "🟠"
    else:
        grade = "🔴"

    reason = (f"최빈 액션은 {max_action} ({freqs.get(max_action, 0)*100:.0f}%), "
              f"선택한 {action}은 빈도 {chosen_freq*100:.0f}% ({freq_str})")
    return GradeResult(street="프리플랍", action=action, grade=grade, reason=reason, ev_loss_bb=None)


def grade_postflop_call(equity: float, pot: int, call_amount: int, big_blind: int) -> GradeResult:
    """콜 액션 평가. EV = equity*(pot+call) - call."""
    ev = equity * (pot + call_amount) - call_amount
    if ev < 0:
        ev_loss_bb = ev / big_blind
        reason = f"콜 EV={ev:.1f} (음수) — equity {equity*100:.1f}%로는 손해 콜"
        return GradeResult(street="", action="call", grade="🔴", reason=reason, ev_loss_bb=ev_loss_bb)

    reason = f"콜 EV={ev:.1f} (양수) — equity {equity*100:.1f}%로 이득 콜"
    return GradeResult(street="", action="call", grade="✅", reason=reason, ev_loss_bb=None)


def grade_postflop_fold(
    equity: float, pot: int, call_amount: int, big_blind: int, margin: float = 0.05
) -> GradeResult:
    """폴드 액션 평가. 팟오즈보다 equity가 충분히 높은데 폴드했으면 놓친 EV."""
    pot_odds = call_amount / (pot + call_amount) if call_amount > 0 else 0.0

    if equity > pot_odds + margin:
        ev = equity * (pot + call_amount) - call_amount
        ev_loss_bb = -(ev / big_blind)
        reason = f"equity {equity*100:.1f}%가 팟오즈 {pot_odds*100:.1f}%보다 충분히 높은데 폴드 — 놓친 EV"
        return GradeResult(street="", action="fold", grade="🔴", reason=reason, ev_loss_bb=ev_loss_bb)

    reason = f"equity {equity*100:.1f}%, 팟오즈 {pot_odds*100:.1f}% — 적절한 폴드"
    return GradeResult(street="", action="fold", grade="✅", reason=reason, ev_loss_bb=None)


def grade_postflop_bet_or_raise(equity: float, action: str, was_check_before: bool = False) -> GradeResult:
    """
    벳/레이즈/체크 평가 (v1 단순화).
    was_check_before는 현재 로직에 사용하지 않음 — "반복 체크로 밸류 놓침" 같은
    여러 스트리트에 걸친 시퀀스 추적은 v1 범위 밖. 향후 확장 지점으로 시그니처에만 남겨둠.
    """
    if equity > 0.7 and action == "check":
        return GradeResult(
            street="", action=action, grade="⚠️",
            reason=f"equity {equity*100:.1f}%의 강한 핸드인데 체크 — 밸류 놓침",
            ev_loss_bb=None,
        )

    if equity < 0.3 and action in ("raise", "allin"):
        return GradeResult(
            street="", action=action, grade="🟡",
            reason=f"equity {equity*100:.1f}%로 약한데 {action} — 블러프",
            ev_loss_bb=None,
        )

    return GradeResult(
        street="", action=action, grade="⬜",
        reason="데이터부족", ev_loss_bb=None,
    )
