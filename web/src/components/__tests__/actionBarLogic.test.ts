import { describe, it, expect } from "vitest";
import { actionButtons, potPresets, betPresets, presetOff } from "../actionBarLogic";
import type { PlayerState } from "../../types";

const me = (chips: number, current_bet = 0): PlayerState => ({
  name: "Hero", chips, current_bet, is_folded: false, is_all_in: false,
  is_human: true, position: "BB", hole_cards: null,
});

describe("ActionBar — 액션이 닫힌 사람에게 레이즈·올인 숨김", () => {
  it("can_raise=false(불완전 올인으로 닫힘)면 레이즈·올인 버튼이 없다", () => {
    const b = actionButtons({ call_amount: 50, can_raise: false, min_raise_to: 100, players: [me(900)] });
    expect(b.showRaise).toBe(false);
    expect(b.showAllin).toBe(false);
    expect(b.canRaise).toBe(false);
    expect(b.callLabel).toBe("콜 50");
  });

  it("스택이 콜 이하면 콜 버튼이 올인을 맡는다", () => {
    const b = actionButtons({ call_amount: 300, can_raise: false, min_raise_to: 600, players: [me(120)] });
    expect(b.showAllin).toBe(false);
    expect(b.callLabel).toBe("콜 120 (올인)");
  });

  it("레이즈할 수 있으면 둘 다 보인다", () => {
    const b = actionButtons({ call_amount: 0, can_raise: true, min_raise_to: 20, players: [me(900)] });
    expect(b).toEqual({ showRaise: true, showAllin: true, canRaise: true, maxRaise: 900, callLabel: "체크" });
  });

  it("최대 도달 베팅 = 남은 칩 + 이번 스트리트 베팅, 최소 레이즈에 못 닿으면 금액 선택 불가", () => {
    const b = actionButtons({ call_amount: 40, can_raise: true, min_raise_to: 200, players: [me(100, 20)] });
    expect(b.maxRaise).toBe(120);
    expect(b.canRaise).toBe(false);
  });
});

describe("ActionBar — 팟 기준 프리셋 = current_bet + round(f × (pot + call))", () => {
  it("벳이 없을 때(플랍 팟 100): 1/3=33, 1/2=50, 3/4=75, 팟=100", () => {
    const v = potPresets({ pot: 100, call_amount: 0, current_bet: 0 }).map((p) => [p.label, p.value]);
    expect(v).toEqual([["1/3", 33], ["1/2", 50], ["3/4", 75], ["팟", 100]]);
  });

  it("벳을 마주함(팟 100에 상대 50 벳 → 팟 150, 콜 50): 팟 = 50 + 200 = 250, 1/2 = 150", () => {
    const v = potPresets({ pot: 150, call_amount: 50, current_bet: 50 }).map((p) => p.value);
    expect(v).toEqual([50 + 67, 150, 200, 250]);
  });

  it("프리플랍 SB 10·BB 20, UTG 차례(팟 30, 콜 20): 팟 레이즈 = 70", () => {
    const pot = potPresets({ pot: 30, call_amount: 20, current_bet: 20 }).find((p) => p.label === "팟")!;
    expect(pot.value).toBe(70);
  });

  it("이미 베팅한 사람이 레이즈를 마주함(BB 20 낸 사람, 상대 60 레이즈, 팟 90, 콜 40): 팟 = 60 + 130 = 190", () => {
    const pot = potPresets({ pot: 90, call_amount: 40, current_bet: 60 }).find((p) => p.label === "팟")!;
    expect(pot.value).toBe(190);
  });

  it("배율 프리셋은 상대 베팅의 k배(도달 베팅)", () => {
    expect(betPresets({ current_bet: 20 }).map((p) => p.value)).toEqual([40, 50, 60, 80]);
  });

  it("최소 레이즈 미만·스택 초과·레이즈 불가 프리셋은 고를 수 없다", () => {
    const b = { canRaise: true, maxRaise: 300 };
    expect(presetOff(50, b, 60)).toBe(true);
    expect(presetOff(301, b, 60)).toBe(true);
    expect(presetOff(200, b, 60)).toBe(false);
    expect(presetOff(200, { canRaise: false, maxRaise: 300 }, 60)).toBe(true);
  });
});
