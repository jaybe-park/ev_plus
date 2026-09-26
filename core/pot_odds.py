"""
유효 콜·유효 팟 — 스택으로 캡한 팟오즈/콜 EV 계산 (세션 패널·Play Grader·봇 공용).

숏스택이 큰 벳/올인을 받으면 실제로 걸리는 칩은 내 남은 칩까지이고(`Player.place_bet`이 캡),
이길 수 있는 팟도 각 상대 기여 중 "내 총 기여"까지뿐이다(초과분은 사이드팟).
원래 콜 금액·전체 팟으로 계산하면 올바른 콜을 손해 콜로 판정한다(T-033).

기여액 기준: `my_bet`/`other_bets`는 같은 기준이면 된다.
- 핸드 전체 기여(`total_bet_this_round`) — 항상 정확.
- 이번 스트리트 기여(`current_bet`) — 아직 액션할 수 있는(올인 아닌) 플레이어라면
  이전 스트리트의 모든 벳을 맞췄으므로 이전 스트리트 기여는 누구도 내 것을 넘지 않는다.
  따라서 스트리트 기준으로도 정확하다. 봇 game_state에는 이것만 있다.
`other_bets`에는 폴드한 플레이어의 기여도 넣는다(데드 머니도 내 기여 한도까지만 이길 수 있다).
"""

from typing import Iterable, Tuple


def effective_call_pot(
    pot: int, call_amount: int, my_chips: int, my_bet: int, other_bets: Iterable[int],
) -> Tuple[int, int]:
    """
    (유효 콜, 유효 팟) 반환.
    - 유효 콜 = min(콜 금액, 남은 칩)
    - 유효 팟 = 전체 팟 − Σ max(0, 상대 기여 − (내 기여 + 유효 콜))  (콜하기 전 팟 기준)
    """
    eff_call = max(0, min(call_amount, my_chips))
    cap = my_bet + eff_call
    excess = sum(max(0, b - cap) for b in other_bets)
    return eff_call, max(0, pot - excess)


def pot_odds(eff_call: int, eff_pot: int) -> float:
    """콜에 필요한 최소 에퀴티 = 콜 / (팟 + 콜). 콜 0이면 0."""
    return eff_call / (eff_pot + eff_call) if eff_call > 0 else 0.0


def call_ev(equity: float, eff_call: int, eff_pot: int) -> float:
    """콜 EV(칩) = equity × (팟 + 콜) − 콜."""
    return equity * (eff_pot + eff_call) - eff_call
