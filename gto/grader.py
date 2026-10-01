"""
플레이 평가 (Play Grader)
순수 함수 모음 — 사람의 액션이 GTO/EV 관점에서 얼마나 좋았는지 등급화한다.

- 프리플랍: GTO 빈도 기반 4등급
  ✅ 최선 = 최고빈도 액션 / 🟡 무난 = 빈도>25% / 🟠 의문 = 5~25% / 🔴 블런더 = <5%
  GTO 데이터 없는 스팟은 ⬜ "데이터 없음"
- 포스트플랍: equity 기반 근사 EV
  · 콜·폴드는 대칭이다(ADR 0049): 경계폭 = max(2×표준오차, 1%p).
    |equity − 팟오즈| < 경계폭이면 ⬜ "경계 — 거의 본전", 그 밖은 콜은 EV 부호,
    폴드는 equity > 팟오즈면 "놓친 EV" 🔴 (고정 마진 없음)
    (팟·콜은 숏스택이면 유효값 — core/pot_odds.effective_call_pot)
  · equity 입력은 세션이 패널과 같은 vs_range(상대 레인지 반영)를 넘긴다. 레인지를 모르면
    vs_random이고 사유에 "상대 레인지 모름(랜덤 기준)"이 붙는다
  · 벳/레이즈/체크: 폴드 에퀴티를 몰라 정확 평가 불가 → v1은 제한 판정만
"""

from dataclasses import dataclass
from typing import Optional, Dict, Iterable, Tuple

from core.pot_odds import effective_call_pot, call_ev, pot_odds as _pot_odds


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
    # 간단 라벨 예비 조회 결과(정확한 노드 아님, ADR 0035)는 평가 사유에도 근사로 표시
    approx = "(근사) " if gto_recommendation.get("approx") else ""

    if action == max_action:
        reason = f"{approx}GTO 최빈 액션과 일치 ({freq_str})"
        return GradeResult(street="프리플랍", action=action, grade="✅", reason=reason, ev_loss_bb=None)

    chosen_freq = freqs.get(action, 0.0)
    if chosen_freq > 0.25:
        grade = "🟡"
    elif chosen_freq >= 0.05:
        grade = "🟠"
    else:
        grade = "🔴"

    reason = (f"{approx}최빈 액션은 {max_action} ({freqs.get(max_action, 0)*100:.0f}%), "
              f"선택한 {action}은 빈도 {chosen_freq*100:.0f}% ({freq_str})")
    return GradeResult(street="프리플랍", action=action, grade=grade, reason=reason, ev_loss_bb=None)


def _effective(pot: int, call_amount: int, stack: Optional[Tuple[int, int, Iterable[int]]]):
    """stack=(내 남은 칩, 내 기여, 상대 기여들)이면 유효 콜·유효 팟으로 캡, 없으면 원값."""
    if stack is None:
        return max(0, call_amount), pot
    my_chips, my_bet, other_bets = stack
    return effective_call_pot(pot, call_amount, my_chips, my_bet, other_bets)


MIN_BAND = 0.01  # 경계 최소 반폭 1%p — 전수(σ=0) 경로도 이 안은 "거의 본전"(ADR 0049)
RANGE_UNKNOWN_NOTE = "상대 레인지 모름(랜덤 기준)"


def band_width(se: float) -> float:
    """경계 반폭 = max(2σ, 1%p). 콜·폴드 공통(ADR 0049)."""
    return max(2 * se, MIN_BAND)


def _odds_text(equity: float, pot_odds: float, se: float, range_known: bool) -> str:
    """복기 사유에 붙는 판정 근거: 에퀴티·팟오즈·표본 오차(±2σ, 전수·테이블은 0)·경계폭·레인지 여부."""
    err = f"표본 오차 ±{2 * se * 100:.1f}%p" if se > 0 else "표본 오차 0(전수)"
    text = (f"에퀴티 {equity*100:.1f}% · 팟오즈 {pot_odds*100:.1f}% · {err}"
            f" · 경계 ±{band_width(se)*100:.1f}%p")
    if not range_known:
        text += f" · {RANGE_UNKNOWN_NOTE}"
    return text


def _borderline(equity: float, pot_odds: float, se: float) -> bool:
    """|에퀴티 − 팟오즈| < max(2σ, 1%p) → 거의 본전이라 ✅/🔴로 가르지 않는다(ADR 0049)."""
    return abs(equity - pot_odds) < band_width(se)


def _borderline_result(action: str, equity: float, pot_odds: float, se: float,
                       range_known: bool) -> GradeResult:
    return GradeResult(
        street="", action=action, grade="⬜",
        reason=f"경계 — 거의 본전 ({_odds_text(equity, pot_odds, se, range_known)})", ev_loss_bb=None,
    )


def grade_postflop_call(
    equity: float, pot: int, call_amount: int, big_blind: int,
    stack: Optional[Tuple[int, int, Iterable[int]]] = None,
    se: float = 0.0,
    range_known: bool = True,
) -> GradeResult:
    """
    콜 액션 평가. EV = equity*(유효 팟+유효 콜) - 유효 콜.
    equity는 판정에 쓸 값(세션은 패널과 같은 vs_range). range_known=False면 상대 레인지를 몰라
    vs_random을 넘겼다는 뜻이라 사유에 "상대 레인지 모름(랜덤 기준)"을 붙인다.
    stack=(내 남은 칩, 내 기여, 상대 기여들)을 주면 숏스택 캡을 적용한다(core/pot_odds).
    se = 에퀴티 추정의 표준오차(`ai.equity.standard_error`). |에퀴티−팟오즈| < max(2·se, 1%p)면
    ⬜ 경계(ADR 0049). 전수 계산(se=0)도 1%p 안은 경계다.
    """
    call_amount, pot = _effective(pot, call_amount, stack)
    odds = _pot_odds(call_amount, pot)
    if _borderline(equity, odds, se):
        return _borderline_result("call", equity, odds, se, range_known)
    ev = call_ev(equity, call_amount, pot)
    basis = _odds_text(equity, odds, se, range_known)
    if ev < 0:
        ev_loss_bb = -ev / big_blind  # 손실 크기를 양수로 표현 (grade_postflop_fold와 부호 통일)
        reason = f"콜 EV={ev:.1f} (음수) — 손해 콜 ({basis})"
        return GradeResult(street="", action="call", grade="🔴", reason=reason, ev_loss_bb=ev_loss_bb)

    reason = f"콜 EV={ev:.1f} (양수) — 이득 콜 ({basis})"
    return GradeResult(street="", action="call", grade="✅", reason=reason, ev_loss_bb=None)


def grade_postflop_fold(
    equity: float, pot: int, call_amount: int, big_blind: int,
    stack: Optional[Tuple[int, int, Iterable[int]]] = None,
    se: float = 0.0,
    range_known: bool = True,
) -> GradeResult:
    """폴드 액션 평가. 콜과 대칭이다(ADR 0049): 경계 밖에서 equity > 팟오즈면 놓친 EV 🔴,
    아니면 적절한 폴드 ✅. 고정 마진은 없다. 인자는 grade_postflop_call과 같다."""
    call_amount, pot = _effective(pot, call_amount, stack)
    pot_odds = _pot_odds(call_amount, pot)
    if _borderline(equity, pot_odds, se):
        return _borderline_result("fold", equity, pot_odds, se, range_known)
    basis = _odds_text(equity, pot_odds, se, range_known)

    if equity > pot_odds:
        ev = call_ev(equity, call_amount, pot)
        ev_loss_bb = ev / big_blind  # 콜했다면 얻었을 EV = 폴드로 놓친 EV (양수)
        reason = f"팟오즈보다 에퀴티가 높은데 폴드 — 놓친 EV ({basis})"
        return GradeResult(street="", action="fold", grade="🔴", reason=reason, ev_loss_bb=ev_loss_bb)

    reason = f"적절한 폴드 ({basis})"
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
