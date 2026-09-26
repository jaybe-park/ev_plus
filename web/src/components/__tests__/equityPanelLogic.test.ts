import { describe, it, expect } from "vitest";
import { equityView, EQUITY_VS_GTO_TOOLTIP } from "../equityPanelLogic";
import type { EquityInfo } from "../../types";

const info = (over: Partial<EquityInfo> = {}): EquityInfo => ({
  vs_random: 0.8, vs_range: 0.3, range_applied: true, pot_odds: 0.33, call_ev_bb: -0.5,
  source: "mc:2250", samples: 2250, num_opponents: 1, opponents: [],
  history: [{ street: "프리플랍", vs_range: 0.42 }, { street: "플랍", vs_range: 0.3 }], ...over,
});

describe("에퀴티 패널 — vs_range 한 기준 (T-006)", () => {
  it("큰 숫자·팟오즈 색은 vs_random이 아니라 vs_range다", () => {
    const v = equityView(info());
    expect(v.headline).toBe(0.3);
    expect(v.callGood).toBe(false); // 0.30 < 팟오즈 0.33 (vs_random 0.8이면 true였을 것)
  });

  it("스트리트 추이도 vs_range", () => {
    expect(equityView(info()).history).toEqual([
      { street: "프리플랍", value: 0.42 }, { street: "플랍", value: 0.3 },
    ]);
  });

  it("출처·표본 수는 서버가 준 실제 계산 그대로", () => {
    expect(equityView(info()).meta).toBe("mc:2250 · 샘플 2,250 · 상대 1명");
    expect(equityView(info({ source: "preflop-table", samples: 1000000, num_opponents: 5 })).meta)
      .toBe("프리플랍 표 · 샘플 1,000,000 · 상대 5명");
    expect(equityView(info({ source: "exact", samples: 990 })).meta).toBe("전수 · 샘플 990 · 상대 1명");
  });

  it("레인지 정보가 없으면 라벨이 랜덤 핸드 기준임을 밝힌다", () => {
    expect(equityView(info({ range_applied: false })).label).toContain("랜덤 핸드");
    expect(equityView(info()).label).toContain("레인지 반영");
  });

  it("에퀴티·GTO 불일치 툴팁은 한 줄", () => {
    expect(EQUITY_VS_GTO_TOOLTIP).not.toContain("\n");
    expect(EQUITY_VS_GTO_TOOLTIP).toContain("폴드 에퀴티");
  });
});
