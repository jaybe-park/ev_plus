// GTO 패널·그리드의 표시 판단만 순수 함수로 뽑은 모듈(vitest 대상).
import type { GtoNode, GtoRange } from "../types";

// ── 액션 색·순서·이름(패널 막대·그리드·범례 공용) ─────────────
export const ACTION_ORDER = ["allin", "raise", "call", "fold"] as const;
export const ACTION_COLORS: Record<string, string> = {
  allin: "#991b1b", raise: "#ef4444", call: "#22c55e", fold: "#3b82f6",
};
export const ACTION_LABELS: Record<string, string> = {
  allin: "올인", raise: "레이즈", call: "콜", fold: "폴드",
};
/** 데이터 없음(수집 안 된 핸드)·빈도 합이 1에 못 미치는 잔여 — 폴드 색이 아닌 중립 회색(ADR 0002). */
export const NO_DATA_COLOR = "#4b5563";

const MIN_FREQ = 0.001;

/**
 * 그리드 칸 배경(CSS background 값). 데이터가 없으면 회색, 한 액션뿐이면 단색, 여럿이면 가로
 * 그라디언트. 빈도 합이 1에 못 미치면 남는 부분을 회색으로 채운다 — 화면에 없는 값을 폴드로 보이지 않는다.
 */
export function cellBackground(freqs: Record<string, number> | undefined | null): string {
  if (!freqs) return NO_DATA_COLOR;
  const parts: { color: string; freq: number }[] = ACTION_ORDER
    .map((a) => ({ color: ACTION_COLORS[a], freq: freqs[a] ?? 0 }))
    .filter((p) => p.freq > MIN_FREQ);
  const total = parts.reduce((s, p) => s + p.freq, 0);
  if (1 - total > MIN_FREQ * 5) parts.push({ color: NO_DATA_COLOR, freq: 1 - total });
  if (parts.length === 0) return NO_DATA_COLOR;
  if (parts.length === 1) return parts[0].color;
  let stops = "";
  let cum = 0;
  for (const p of parts) {
    const from = Math.round(cum * 100);
    const to = Math.round(Math.min(1, cum + p.freq) * 100);
    stops += `, ${p.color} ${from}%, ${p.color} ${to}%`;
    cum += p.freq;
  }
  return `linear-gradient(to right${stops})`;
}

// ── 레인지 조회 상태 ─────────────────────────────────────

/** 마지막 레인지 조회 결과. key = 요청한 노드 키, range = null이면 조회 실패. */
export interface GtoFetchResult {
  key: string;
  range: GtoRange | null;
}

export type GtoFetch =
  | { status: "idle" }                       // 조회할 노드가 없음
  | { status: "loading" }                    // 지금 노드의 응답을 기다리는 중
  | { status: "ok"; range: GtoRange }
  | { status: "error" };                     // 지금 노드 조회가 실패함

/** 지금 노드(nodeKey)에 대한 조회 상태. 다른 노드의 결과(요청 경합)는 쓰지 않는다. */
export function gtoFetchState(nodeKey: string | null, result: GtoFetchResult | null): GtoFetch {
  if (nodeKey === null) return { status: "idle" };
  if (!result || result.key !== nodeKey) return { status: "loading" };
  if (!result.range) return { status: "error" };
  if (result.range.action_seq !== undefined && result.range.action_seq !== nodeKey) return { status: "loading" };
  return { status: "ok", range: result.range };
}

// ── 패널 ───────────────────────────────────────────────

export type GtoPanelView =
  | { kind: "idle" }                         // 프리플랍 사람 차례가 아님
  | { kind: "missing"; position: string }    // 이 상황의 GTO 데이터 없음(advisor 추천 없음)
  | { kind: "loading" }
  | { kind: "error" }                        // 레인지 조회 실패(서버 오류·네트워크)
  | { kind: "range"; title: string; range: GtoRange };

/** 상황 제목. 라벨 예비(approx) 결과면 "(근사)"를 붙인다(ADR 0035 — 힌트 문자열과 같은 표기). */
export function gtoTitle(situation: string | undefined, approx: boolean | undefined): string {
  const base = situation || "";
  return approx ? `${base} (근사)` : base;
}

/**
 * 게임 상태 gto(=advisor 추천)와 그 node_key로 받은 레인지 조회 상태에서 패널에 무엇을 보일지 정한다.
 * 힌트와 패널은 항상 같은 노드다.
 */
export function gtoPanelView(gto: GtoNode | null, fetch: GtoFetch): GtoPanelView {
  if (!gto) return { kind: "idle" };
  if (!gto.found || gto.node_key === null || gto.node_key === undefined) {
    return { kind: "missing", position: gto.position };
  }
  if (fetch.status === "error") return { kind: "error" };
  if (fetch.status !== "ok") return { kind: "loading" };
  if (!fetch.range.found) return { kind: "missing", position: gto.position };
  return { kind: "range", title: gtoTitle(gto.situation || fetch.range.situation, gto.approx), range: fetch.range };
}
