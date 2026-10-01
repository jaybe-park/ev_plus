// 힌트 패널(사이드 "💡 힌트" 탭)의 구성 순서·표시 문자열만 순수 함수로 뽑은 모듈(vitest 대상).
// 순서는 고정: ① 상황 라벨 ② GTO 빈도(노드 전체 레인지) ③ 내 패 액션 %(그리드 셀 값) ④ 에퀴티.
// 그 밖의 것(레인지 그리드·레이즈 비교·상대별 1:1·스트리트 추이·출처)은 접힌 "자세히"로 뒤에 둔다.
import type { GtoNode } from "../types";
import { gtoPanelView, gtoTitle, ACTION_COLORS, ACTION_LABELS, ACTION_ORDER, type GtoFetch } from "./gtoPanelLogic";
import { pct } from "../format";

const MIN_FREQ = 0.001;

export interface FreqBar {
  action: string;
  label: string;   // "레이즈"
  freq: number;    // 0~1
  text: string;    // "65.0%"
  color: string;
}

/** 빈도 맵 → 막대 목록(올인·레이즈·콜·폴드 순, 0.1% 미만 제외). 없는 액션을 폴드로 채우지 않는다(ADR 0002). */
export function freqBars(freqs: Record<string, number> | null | undefined): FreqBar[] {
  if (!freqs) return [];
  return ACTION_ORDER
    .filter((a) => (freqs[a] ?? 0) >= MIN_FREQ)
    .map((a) => ({ action: a, label: ACTION_LABELS[a], freq: freqs[a], text: pct(freqs[a], 1), color: ACTION_COLORS[a] }));
}

/** 내 패 한 줄: "레이즈 65.0% · 콜 35.0%". 빈도가 없으면 "이 핸드 데이터 없음". */
export function myHandText(freqs: Record<string, number> | null | undefined): string {
  const bars = freqBars(freqs);
  if (bars.length === 0) return "이 핸드 데이터 없음";
  return bars.map((b) => `${b.label} ${b.text}`).join(" · ");
}

/** 상황 라벨. 레이즈 사이즈(실측 bb)가 있으면 "(N bb)"를 붙인다. */
export function situationText(title: string, raiseSize: number | null | undefined): string {
  return typeof raiseSize === "number" ? `${title} (${raiseSize}bb)` : title;
}

export type HintSection =
  | { kind: "situation"; text: string; tone: "ok" | "warn" | "muted" }
  | { kind: "gtoFreq"; bars: FreqBar[] }
  | { kind: "myHand"; hand: string; text: string; freqs: Record<string, number> | null }
  | { kind: "gtoNote"; text: string; tone: "muted" | "error" }   // 로딩·조회 실패 등 ②③ 자리의 안내
  | { kind: "equity" };

export interface HintLayout {
  sections: HintSection[];   // 이 순서대로 보인다
  gridAvailable: boolean;    // "자세히"에 레인지 그리드를 넣을 수 있나(레인지 조회 성공)
}

/**
 * 게임 상태 gto(advisor 추천)·레인지 조회 상태·에퀴티에서 힌트 패널 구성(순서·문자열)을 정한다.
 * - 프리플랍 사람 차례(gto 있음): ① 상황 ② GTO 빈도 ③ 내 패 ④ 에퀴티
 * - 이 상황의 GTO 데이터 없음: ① "포지션 — GTO 데이터 없음" ④ 에퀴티
 * - 포스트플랍·사람 차례 아님(gto 없음): ④ 에퀴티만
 * 에퀴티 섹션은 항상 마지막에 있다(값이 없을 때 안내는 에퀴티 컴포넌트가 보인다).
 */
export function hintLayout(gto: GtoNode | null, fetch: GtoFetch): HintLayout {
  const view = gtoPanelView(gto, fetch);
  const sections: HintSection[] = [];
  let gridAvailable = false;

  if (view.kind === "range") {
    const { raise_size, summary = {}, hands = {} } = view.range;
    const hand = gto?.hand ?? null;
    const myFreqs = gto?.frequencies ?? (hand ? hands[hand] ?? null : null);
    sections.push({ kind: "situation", text: situationText(view.title, raise_size), tone: "ok" });
    sections.push({ kind: "gtoFreq", bars: freqBars(summary) });
    if (hand) sections.push({ kind: "myHand", hand, text: myHandText(myFreqs), freqs: myFreqs });
    gridAvailable = true;
  } else if (view.kind === "missing") {
    sections.push({ kind: "situation", text: `${view.position} — GTO 데이터 없음`, tone: "warn" });
  } else if (view.kind === "loading" || view.kind === "error") {
    const label = gto?.situation ? gtoTitle(gto.situation, gto.approx) : gto?.position;
    if (label) sections.push({ kind: "situation", text: label, tone: "muted" });
    sections.push(view.kind === "loading"
      ? { kind: "gtoNote", text: "GTO 레인지 로딩 중…", tone: "muted" }
      : { kind: "gtoNote", text: "조회 실패 — GTO 레인지를 서버에서 받지 못했습니다", tone: "error" });
  }
  sections.push({ kind: "equity" });
  return { sections, gridAvailable };
}
