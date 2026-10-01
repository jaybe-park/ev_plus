import { describe, it, expect } from "vitest";
import { evLossText, sessionSummaryText, shouldFetchReview } from "../reviewLogic";
import { pct, displayName } from "../format";

describe("복기 EV 손실 표기 — 서버 ev_loss_bb 양수 = 손실 크기", () => {
  it("손실이 있으면 '−N.Nbb'", () => {
    expect(evLossText(1.234)).toBe("−1.2bb");
    expect(evLossText(0.5)).toBe("−0.5bb");
  });
  it("판정하지 않은 줄(null)·손실 없음(0 이하)은 표시하지 않는다", () => {
    expect(evLossText(null)).toBeNull();
    expect(evLossText(undefined)).toBeNull();
    expect(evLossText(0)).toBeNull();
    expect(evLossText(-0.3)).toBeNull();
  });
});

describe("헤더 세션 요약 — 'EV 손실 N.Nbb'(+ 부호 없음)", () => {
  it("GTO 일치율과 누적 손실", () => {
    expect(sessionSummaryText({ total_actions: 10, grade_counts: {}, total_ev_loss_bb: 3.44, gto_match_rate: 0.625 }))
      .toBe("GTO 63% · EV 손실 3.4bb");
  });
  it("일치율 없음은 '—', 손실 0은 'EV 손실 0.0bb'", () => {
    const t = sessionSummaryText({ total_actions: 0, grade_counts: {}, total_ev_loss_bb: 0, gto_match_rate: null });
    expect(t).toBe("GTO — · EV 손실 0.0bb");
    expect(t).not.toContain("+");
  });
});

describe("헤더 세션 요약은 재생이 끝난 뒤에 바뀐다", () => {
  const over = { hand_over: true, session_id: "s1" };
  it("핸드가 끝나도 재생 중이면 받지 않는다", () => {
    expect(shouldFetchReview(true, over)).toBe(false);
  });
  it("재생이 끝나면 받는다", () => {
    expect(shouldFetchReview(false, over)).toBe(true);
  });
  it("핸드 진행 중·상태 없음은 받지 않는다", () => {
    expect(shouldFetchReview(false, { hand_over: false, session_id: "s1" })).toBe(false);
    expect(shouldFetchReview(false, null)).toBe(false);
  });
});

describe("공용 표기", () => {
  it("pct — 자릿수", () => {
    expect(pct(0.625)).toBe("63%");
    expect(pct(0.625, 1)).toBe("62.5%");
  });
  it("displayName — 봇 접두사 '🤖 '만 뗀다", () => {
    expect(displayName("🤖 Alice")).toBe("Alice");
    expect(displayName("Hero")).toBe("Hero");
  });
});
