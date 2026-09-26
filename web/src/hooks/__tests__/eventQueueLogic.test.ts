import { describe, it, expect } from "vitest";
import type { GameEvent } from "../../types";
import {
  isBetAction,
  formatBadge,
  makeCommitLabel,
  commitEffectFor,
  replayCommitEffects,
} from "../eventQueueLogic";

describe("isBetAction", () => {
  it("call/raise/allin만 배팅 액션으로 본다", () => {
    expect(isBetAction("call")).toBe(true);
    expect(isBetAction("raise")).toBe(true);
    expect(isBetAction("allin")).toBe(true);
    expect(isBetAction("fold")).toBe(false);
    expect(isBetAction("check")).toBe(false);
  });
});

describe("formatBadge", () => {
  it("blind는 SB/BB 라벨과 금액을 낸다", () => {
    const sb: GameEvent = { type: "blind", player: "Human", position: "SB", amount: 10, street: "preflop" };
    const bb: GameEvent = { type: "blind", player: "🤖 A", position: "BB", amount: 20, street: "preflop" };
    expect(formatBadge(sb)).toEqual({ player: "Human", text: "SB 10", variant: "blind" });
    expect(formatBadge(bb)).toEqual({ player: "🤖 A", text: "BB 20", variant: "blind" });
  });

  it("헤즈업 BTN/SB 포지션도 SB로 취급한다", () => {
    const e: GameEvent = { type: "blind", player: "Human", position: "BTN/SB", amount: 10, street: "preflop" };
    expect(formatBadge(e)?.text).toBe("SB 10");
  });

  it("action 타입별로 정확한 배지 텍스트를 만든다", () => {
    const base = { type: "action" as const, player: "Human", position: "BTN", street: "preflop" };
    expect(formatBadge({ ...base, action: "fold", amount: 0 })).toEqual({ player: "Human", text: "FOLD", variant: "fold" });
    expect(formatBadge({ ...base, action: "check", amount: 0 })).toEqual({ player: "Human", text: "CHECK", variant: "check" });
    expect(formatBadge({ ...base, action: "call", amount: 20 })).toEqual({ player: "Human", text: "CALL 20", variant: "call" });
    expect(formatBadge({ ...base, action: "raise", amount: 60 })).toEqual({ player: "Human", text: "RAISE → 60", variant: "raise" });
    expect(formatBadge({ ...base, action: "allin", amount: 500 })).toEqual({ player: "Human", text: "ALL IN", variant: "allin" });
  });

  it("배지가 없는 이벤트는 null", () => {
    expect(formatBadge({ type: "street_start", street: "flop" })).toBeNull();
    expect(formatBadge({ type: "community_card", card: "As", street: "flop" })).toBeNull();
  });
});

describe("makeCommitLabel", () => {
  it("action은 한국어 커밋 레이블을 만든다", () => {
    const base = { type: "action" as const, player: "Human", position: "BTN", street: "preflop" };
    expect(makeCommitLabel({ ...base, action: "fold", amount: 0 })).toBe("폴드");
    expect(makeCommitLabel({ ...base, action: "check", amount: 0 })).toBe("체크");
    expect(makeCommitLabel({ ...base, action: "call", amount: 20 })).toBe("콜 20");
    expect(makeCommitLabel({ ...base, action: "raise", amount: 60 })).toBe("레이즈 → 60");
    expect(makeCommitLabel({ ...base, action: "allin", amount: 500 })).toBe("올인");
  });
});

describe("commitEffectFor / replayCommitEffects — 이벤트 순서", () => {
  it("blind→action→street_start 순서로 재생하면 set→set→reset 순서가 나온다", () => {
    const events: GameEvent[] = [
      { type: "blind", player: "Human", position: "SB", amount: 10, street: "preflop" },
      { type: "blind", player: "🤖 A", position: "BB", amount: 20, street: "preflop" },
      { type: "action", player: "Human", position: "SB", action: "call", amount: 20, street: "preflop" },
      { type: "action", player: "🤖 A", position: "BB", action: "check", amount: 0, street: "preflop" },
      { type: "street_start", street: "flop" },
    ];
    const effects = replayCommitEffects(events);
    expect(effects).toEqual([
      { kind: "set", player: "Human", label: "SB 10" },
      { kind: "set", player: "🤖 A", label: "BB 20" },
      { kind: "set", player: "Human", label: "콜 20" },
      { kind: "set", player: "🤖 A", label: "체크" },
      { kind: "reset" },
    ]);
  });

  it("fold/showdown/winner/community_card/deal_card는 커밋 레이블에 영향 없음", () => {
    const noneEvents: GameEvent[] = [
      { type: "deal_card", player: "Human", position: "BTN", round: 1, street: "preflop" },
      { type: "community_card", card: "Kd", street: "flop" },
      { type: "showdown", hands: {} },
      { type: "winner", winners: ["Human"], pot: 100 },
    ];
    for (const e of noneEvents) {
      expect(commitEffectFor(e)).toEqual({ kind: "none" });
    }
  });
});
