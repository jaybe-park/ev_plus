// 에퀴티 패널의 표시 판단만 순수 함수로 뽑은 모듈(vitest 대상, T-006).
// 패널이 보여주는 숫자는 전부 vs_range 한 기준이다(vs_random은 화면에 없다 — ADR 0022/0034).
import type { EquityInfo } from "../types";

/** 에퀴티와 GTO 추천이 어긋나 보이는 게 정상인 이유(한 줄 툴팁). 상세: docs/spec/equity.md */
export const EQUITY_VS_GTO_TOOLTIP =
  "에퀴티는 지금 패로 쇼다운까지 간다고 본 승률입니다. GTO는 폴드 에퀴티(상대가 접는 몫)·뒤에 남은 사람·다음 스트리트 플레이까지 반영하므로 다를 수 있습니다.";

export interface EquityView {
  headline: number;        // 큰 숫자·게이지 (vs_range)
  label: string;           // "내 에퀴티 (…)"
  callGood: boolean;       // 에퀴티 ≥ 팟오즈 (팟오즈 글자 색)
  meta: string;            // 출처·표본 수 — 실제 계산 그대로
  history: { street: string; value: number }[];
}

export function equityView(info: EquityInfo): EquityView {
  const headline = info.vs_range;
  const label = info.range_applied
    ? "내 에퀴티 (상대 레인지 반영)"
    : "내 에퀴티 (상대 레인지 모름 → 랜덤 핸드)";
  const src = info.source === "preflop-table" ? "프리플랍 표" : info.source === "exact" ? "전수" : info.source;
  const meta = `${src} · 샘플 ${info.samples.toLocaleString()} · 상대 ${info.num_opponents}명`;
  return {
    headline,
    label,
    callGood: headline >= info.pot_odds,
    meta,
    history: info.history.map((h) => ({ street: h.street, value: h.vs_range })),
  };
}
