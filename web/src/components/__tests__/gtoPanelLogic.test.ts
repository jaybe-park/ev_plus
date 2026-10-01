import { describe, it, expect } from "vitest";
import {
  gtoPanelView, gtoTitle, gtoFetchState, cellBackground, ACTION_COLORS, NO_DATA_COLOR,
  type GtoFetch,
} from "../gtoPanelLogic";
import type { GtoNode, GtoRange } from "../../types";

const node = (over: Partial<GtoNode> = {}): GtoNode => ({
  found: true, position: "BTN/SB", node_key: "F-F-F-F", approx: false,
  situation: "SB RFI", hand: "AKs", frequencies: { raise: 1 }, ...over,
});
const range = (over: Partial<GtoRange> = {}): GtoRange => ({
  found: true, action_seq: "F-F-F-F", situation: "SB RFI", summary: { raise: 0.5 },
  hands: { AKs: { raise: 1 } }, ...over,
});
const ok = (r: GtoRange): GtoFetch => ({ status: "ok", range: r });

describe("GTO 패널 — advisor 추천 node_key에 묶임", () => {
  it("추천과 같은 노드의 레인지면 레인지를 보인다", () => {
    const r = range();
    expect(gtoPanelView(node(), ok(r))).toEqual({ kind: "range", title: "SB RFI", range: r });
  });

  it("UTG RFI 노드 키(빈 문자열)도 유효한 노드다", () => {
    const f = gtoFetchState("", { key: "", range: range({ action_seq: "" }) });
    expect(f.status).toBe("ok");
    expect(gtoPanelView(node({ node_key: "", situation: "UTG RFI" }), f).kind).toBe("range");
  });

  it("라벨 예비(approx) 결과는 제목에 (근사)를 붙인다 (ADR 0035)", () => {
    const v = gtoPanelView(node({ approx: true }), ok(range()));
    expect(v.kind === "range" && v.title).toBe("SB RFI (근사)");
    expect(gtoTitle("BB vs HJ open", true)).toBe("BB vs HJ open (근사)");
    expect(gtoTitle("BB vs HJ open", false)).toBe("BB vs HJ open");
  });

  it("다른 노드의 결과(요청 경합)는 쓰지 않는다 — 지금 노드 응답을 기다리는 로딩", () => {
    expect(gtoFetchState("F-F-F-F", { key: "R2.5", range: range({ action_seq: "R2.5" }) })).toEqual({ status: "loading" });
    expect(gtoFetchState("F-F-F-F", { key: "F-F-F-F", range: range({ action_seq: "R2.5" }) })).toEqual({ status: "loading" });
  });

  it("추천이 없으면 '데이터 없음', 프리플랍 사람 차례가 아니면 안내", () => {
    expect(gtoPanelView({ found: false, position: "BB" }, { status: "idle" })).toEqual({ kind: "missing", position: "BB" });
    expect(gtoPanelView(null, ok(range()))).toEqual({ kind: "idle" });
    expect(gtoPanelView(node(), ok(range({ found: false })))).toEqual({ kind: "missing", position: "BTN/SB" });
  });
});

describe("GTO 레인지 조회 상태 — loading / ok / error", () => {
  it("노드가 없으면 idle", () => {
    expect(gtoFetchState(null, null)).toEqual({ status: "idle" });
  });
  it("지금 노드의 결과가 아직 없으면 loading → 패널 '로딩 중'", () => {
    const f = gtoFetchState("F-F-F-F", null);
    expect(f).toEqual({ status: "loading" });
    expect(gtoPanelView(node(), f)).toEqual({ kind: "loading" });
  });
  it("응답이 오면 ok", () => {
    const r = range();
    expect(gtoFetchState("F-F-F-F", { key: "F-F-F-F", range: r })).toEqual({ status: "ok", range: r });
  });
  it("조회가 실패하면 error → 패널 '조회 실패'(로딩과 구분)", () => {
    const f = gtoFetchState("F-F-F-F", { key: "F-F-F-F", range: null });
    expect(f).toEqual({ status: "error" });
    expect(gtoPanelView(node(), f)).toEqual({ kind: "error" });
  });
  it("이전 노드의 실패는 새 노드를 실패로 보이지 않는다(새 노드는 loading)", () => {
    expect(gtoFetchState("R2.5", { key: "F-F-F-F", range: null })).toEqual({ status: "loading" });
  });
});

describe("GTO 그리드 색 — 데이터 없음·잔여는 중립 회색(폴드 색 아님, ADR 0002)", () => {
  it("데이터 없는 핸드는 회색", () => {
    expect(cellBackground(undefined)).toBe(NO_DATA_COLOR);
    expect(cellBackground({})).toBe(NO_DATA_COLOR);
    expect(NO_DATA_COLOR).not.toBe(ACTION_COLORS.fold);
  });
  it("한 액션 100%는 그 색 단색", () => {
    expect(cellBackground({ raise: 1 })).toBe(ACTION_COLORS.raise);
    expect(cellBackground({ fold: 1 })).toBe(ACTION_COLORS.fold);
  });
  it("빈도 합이 1이면 회색 없음", () => {
    const bg = cellBackground({ raise: 0.6, fold: 0.4 });
    expect(bg).toBe(`linear-gradient(to right, ${ACTION_COLORS.raise} 0%, ${ACTION_COLORS.raise} 60%, ${ACTION_COLORS.fold} 60%, ${ACTION_COLORS.fold} 100%)`);
    expect(bg).not.toContain(NO_DATA_COLOR);
  });
  it("빈도 합이 1 미만이면 남는 부분이 회색(폴드로 채우지 않음)", () => {
    const bg = cellBackground({ raise: 0.3 });
    expect(bg).toBe(`linear-gradient(to right, ${ACTION_COLORS.raise} 0%, ${ACTION_COLORS.raise} 30%, ${NO_DATA_COLOR} 30%, ${NO_DATA_COLOR} 100%)`);
    expect(bg).not.toContain(ACTION_COLORS.fold);
  });
  it("수집 오차 수준(합 0.999)은 잔여로 보지 않는다", () => {
    expect(cellBackground({ raise: 0.999 })).toBe(ACTION_COLORS.raise);
  });
});
