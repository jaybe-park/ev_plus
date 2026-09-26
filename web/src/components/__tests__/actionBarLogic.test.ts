import { describe, it, expect } from "vitest";
import { actionButtons } from "../actionBarLogic";
import type { PlayerState } from "../../types";

const me = (chips: number): PlayerState => ({
  name: "Hero", chips, current_bet: 0, is_folded: false, is_all_in: false,
  is_human: true, position: "BB", hole_cards: null,
});

describe("ActionBar — 액션이 닫힌 사람에게 레이즈·올인 숨김 (T-039)", () => {
  it("can_raise=false(불완전 올인으로 닫힘)면 레이즈·올인 버튼이 없다", () => {
    const b = actionButtons({ call_amount: 50, can_raise: false, players: [me(900)] });
    expect(b.showRaise).toBe(false);
    expect(b.showAllin).toBe(false);
    expect(b.callLabel).toBe("콜 50");
  });

  it("스택이 콜 이하면 콜 버튼이 올인을 맡는다", () => {
    const b = actionButtons({ call_amount: 300, can_raise: false, players: [me(120)] });
    expect(b.showAllin).toBe(false);
    expect(b.callLabel).toBe("콜 120 (올인)");
  });

  it("레이즈할 수 있으면 둘 다 보인다", () => {
    const b = actionButtons({ call_amount: 0, can_raise: true, players: [me(900)] });
    expect(b).toEqual({ showRaise: true, showAllin: true, callLabel: "체크" });
  });
});
