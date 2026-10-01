import { describe, it, expect } from "vitest";
import { potLines, potLineText } from "../handResultLogic";
import type { PotShare } from "../../types";

const pot = (amount: number, winners: string[], eligible: string[], returned = false): PotShare =>
  ({ amount, winners, eligible, returned });

describe("결과 창 사이드팟 — 계층별 '메인/사이드 팟 k — 금액 — 승자', 반환은 '반환 N → 이름'", () => {
  it("pots가 없거나 null이면 계층 표시 없음(승자 줄만)", () => {
    expect(potLines(undefined)).toEqual([]);
    expect(potLines(null)).toEqual([]);
  });

  it("계층이 하나뿐이면 승자 줄과 같아 따로 보이지 않는다", () => {
    expect(potLines([pot(300, ["🤖 A"], ["🤖 A", "Hero"])])).toEqual([]);
  });

  it("메인 → 사이드 1 → 사이드 2 → 반환, 봇 이름 접두사는 뗀다", () => {
    const lines = potLines([
      pot(400, ["Hero"], ["Hero", "🤖 A", "🤖 B", "🤖 C"]),
      pot(600, ["🤖 A", "🤖 B"], ["🤖 A", "🤖 B", "🤖 C"]),
      pot(200, ["🤖 C"], ["🤖 B", "🤖 C"]),
      pot(150, ["🤖 C"], ["🤖 C"], true),
    ]).map(potLineText);
    expect(lines).toEqual([
      "메인 팟 — 400 — Hero",
      "사이드 팟 1 — 600 — A, B",
      "사이드 팟 2 — 200 — C",
      "반환 150 → C",
    ]);
  });

  it("반환 계층은 사이드 팟 번호를 차지하지 않고, 승자가 비어 있으면 eligible로 이름을 쓴다", () => {
    const lines = potLines([
      pot(100, ["Hero"], ["Hero", "🤖 A"]),
      pot(50, [], ["🤖 A"], true),
    ]).map(potLineText);
    expect(lines).toEqual(["메인 팟 — 100 — Hero", "반환 50 → A"]);
  });
});
