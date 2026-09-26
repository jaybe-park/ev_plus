import { describe, it, expect } from "vitest";
import { gtoPanelView, gtoTitle } from "../gtoPanelLogic";
import type { GtoNode, GtoRange } from "../../types";

const node = (over: Partial<GtoNode> = {}): GtoNode => ({
  found: true, position: "BTN/SB", node_key: "F-F-F-F", approx: false,
  situation: "SB RFI", hand: "AKs", frequencies: { raise: 1 }, ...over,
});
const range = (over: Partial<GtoRange> = {}): GtoRange => ({
  found: true, action_seq: "F-F-F-F", situation: "SB RFI", summary: { raise: 0.5 },
  hands: { AKs: { raise: 1 } }, ...over,
});

describe("GTO 패널 — advisor 추천 node_key에 묶임 (T-013)", () => {
  it("추천과 같은 노드의 레인지면 레인지를 보인다", () => {
    expect(gtoPanelView(node(), range(), false)).toEqual({ kind: "range", title: "SB RFI", approx: false });
  });

  it("UTG RFI 노드 키(빈 문자열)도 유효한 노드다", () => {
    const v = gtoPanelView(node({ node_key: "", situation: "UTG RFI" }), range({ action_seq: "" }), false);
    expect(v.kind).toBe("range");
  });

  it("라벨 예비(approx) 결과는 제목에 (근사)를 붙인다 (ADR 0035)", () => {
    const v = gtoPanelView(node({ approx: true }), range(), false);
    expect(v).toEqual({ kind: "range", title: "SB RFI (근사)", approx: true });
    expect(gtoTitle("BB vs HJ open", true)).toBe("BB vs HJ open (근사)");
    expect(gtoTitle("BB vs HJ open", false)).toBe("BB vs HJ open");
  });

  it("다른 노드의 레인지 응답(요청 경합)은 쓰지 않는다 — 힌트와 패널은 같은 노드", () => {
    expect(gtoPanelView(node(), range({ action_seq: "R2.5" }), false).kind).toBe("loading");
  });

  it("추천이 없으면 '데이터 없음', 프리플랍 사람 차례가 아니면 안내", () => {
    expect(gtoPanelView({ found: false, position: "BB" }, null, false)).toEqual({ kind: "missing", position: "BB" });
    expect(gtoPanelView(null, range(), false)).toEqual({ kind: "idle" });
  });
});
