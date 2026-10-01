import { describe, it, expect } from "vitest";
import { hintLayout, freqBars, myHandText, situationText } from "../hintPanelLogic";
import type { GtoFetch } from "../gtoPanelLogic";
import type { GtoNode, GtoRange } from "../../types";

const node = (over: Partial<GtoNode> = {}): GtoNode => ({
  found: true, position: "HJ", node_key: "R2.5", approx: false,
  situation: "HJ vs UTG open", hand: "AQs", frequencies: { raise: 0.65, call: 0.35 }, ...over,
});
const range = (over: Partial<GtoRange> = {}): GtoRange => ({
  found: true, action_seq: "R2.5", situation: "HJ vs UTG open", raise_size: 7.5,
  summary: { raise: 0.08, call: 0.1, fold: 0.82 },
  hands: { AQs: { raise: 0.5, call: 0.5 }, AA: { raise: 1 } }, ...over,
});
const ok = (r: GtoRange): GtoFetch => ({ status: "ok", range: r });
const kinds = (g: GtoNode | null, f: GtoFetch) => hintLayout(g, f).sections.map((s) => s.kind);

describe("힌트 패널 순서 — ① 상황 ② GTO 빈도 ③ 내 패 ④ 에퀴티", () => {
  it("프리플랍 사람 차례: 네 섹션이 이 순서로만 보인다(레인지 그리드는 섹션 밖 '자세히')", () => {
    const l = hintLayout(node(), ok(range()));
    expect(l.sections.map((s) => s.kind)).toEqual(["situation", "gtoFreq", "myHand", "equity"]);
    expect(l.gridAvailable).toBe(true);
  });

  it("vs_3bet(올인·레이즈·콜·폴드 4갈래)에서도 섹션은 네 개뿐", () => {
    const g = node({ situation: "UTG vs HJ 3bet", node_key: "R2.5-F-R7.5", frequencies: { allin: 0.1, raise: 0.2, call: 0.3, fold: 0.4 } });
    const r = range({ action_seq: "R2.5-F-R7.5", raise_size: 19, summary: { allin: 0.05, raise: 0.1, call: 0.3, fold: 0.55 } });
    expect(kinds(g, ok(r))).toEqual(["situation", "gtoFreq", "myHand", "equity"]);
  });

  it("① 상황 라벨: 제목 + 실측 레이즈 사이즈, 근사면 (근사)", () => {
    const s = hintLayout(node(), ok(range())).sections[0];
    expect(s).toEqual({ kind: "situation", text: "HJ vs UTG open (7.5bb)", tone: "ok" });
    const a = hintLayout(node({ approx: true }), ok(range({ raise_size: null }))).sections[0];
    expect(a.kind === "situation" && a.text).toBe("HJ vs UTG open (근사)");
    expect(situationText("BTN RFI", undefined)).toBe("BTN RFI");
  });

  it("② GTO 빈도는 노드 전체 레인지 summary — 올인·레이즈·콜·폴드 순, 0인 액션 제외", () => {
    const s = hintLayout(node(), ok(range())).sections[1];
    expect(s.kind === "gtoFreq" && s.bars.map((b) => [b.label, b.text])).toEqual([
      ["레이즈", "8.0%"], ["콜", "10.0%"], ["폴드", "82.0%"],
    ]);
  });

  it("③ 내 패 액션 %는 advisor 추천 빈도(그리드 셀 값) 그대로, 없으면 레인지의 그 핸드", () => {
    const s = hintLayout(node(), ok(range())).sections[2];
    expect(s).toMatchObject({ kind: "myHand", hand: "AQs", text: "레이즈 65.0% · 콜 35.0%" });
    const f = hintLayout(node({ frequencies: null }), ok(range())).sections[2];
    expect(f).toMatchObject({ kind: "myHand", text: "레이즈 50.0% · 콜 50.0%" });
  });

  it("없는 액션을 폴드로 채우지 않는다(ADR 0002) — 합이 1 미만이어도 있는 값만", () => {
    expect(freqBars({ raise: 0.3 }).map((b) => b.action)).toEqual(["raise"]);
    expect(myHandText({ raise: 0.3 })).toBe("레이즈 30.0%");
    expect(myHandText(null)).toBe("이 핸드 데이터 없음");
    expect(myHandText({})).toBe("이 핸드 데이터 없음");
  });

  it("GTO 데이터 없음: ① '포지션 — GTO 데이터 없음' ④ 에퀴티", () => {
    const l = hintLayout({ found: false, position: "BB" }, { status: "idle" });
    expect(l.sections).toEqual([
      { kind: "situation", text: "BB — GTO 데이터 없음", tone: "warn" },
      { kind: "equity" },
    ]);
    expect(l.gridAvailable).toBe(false);
  });

  it("포스트플랍(gto 없음): 에퀴티만", () => {
    expect(kinds(null, { status: "idle" })).toEqual(["equity"]);
  });

  it("로딩·조회 실패는 ②③ 자리에 안내 한 줄, 에퀴티는 여전히 마지막", () => {
    expect(kinds(node(), { status: "loading" })).toEqual(["situation", "gtoNote", "equity"]);
    const e = hintLayout(node(), { status: "error" });
    expect(e.sections[1]).toMatchObject({ kind: "gtoNote", tone: "error" });
    expect(e.sections[e.sections.length - 1].kind).toBe("equity");
  });
});
