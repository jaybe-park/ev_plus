// GTO 패널의 표시 판단만 순수 함수로 뽑은 모듈(vitest 대상, T-013).
import type { GtoNode, GtoRange } from "../types";

export type GtoPanelView =
  | { kind: "idle" }                         // 프리플랍 사람 차례가 아님
  | { kind: "missing"; position: string }    // 이 상황의 GTO 데이터 없음(advisor 추천 없음)
  | { kind: "loading" }
  | { kind: "range"; title: string; approx: boolean };

/** 상황 제목. 라벨 예비(approx) 결과면 "(근사)"를 붙인다(ADR 0035 — 힌트 문자열과 같은 표기). */
export function gtoTitle(situation: string | undefined, approx: boolean | undefined): string {
  const base = situation || "";
  return approx ? `${base} (근사)` : base;
}

/**
 * 게임 상태 gto(=advisor 추천)와 그 node_key로 받은 레인지에서 패널에 무엇을 보일지 정한다.
 * 레인지 응답이 다른 노드의 것이면(요청 경합) 쓰지 않는다 — 힌트와 패널은 항상 같은 노드.
 */
export function gtoPanelView(
  gto: GtoNode | null,
  range: GtoRange | null,
  isLoading: boolean,
): GtoPanelView {
  if (!gto) return { kind: "idle" };
  if (!gto.found || gto.node_key === null || gto.node_key === undefined) {
    return { kind: "missing", position: gto.position };
  }
  if (isLoading || !range || range.action_seq !== gto.node_key) return { kind: "loading" };
  if (!range.found) return { kind: "missing", position: gto.position };
  return { kind: "range", title: gtoTitle(gto.situation || range.situation, gto.approx), approx: !!gto.approx };
}
