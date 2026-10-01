// ActionBar의 버튼·프리셋 판단만 순수 함수로 뽑은 모듈(vitest 대상).
// 레이즈 금액은 서버와 같은 "도달 베팅(raise-to)" 기준이다.
import type { GameState } from "../types";

type BarState = Pick<GameState, "call_amount" | "can_raise" | "players" | "min_raise_to">;

export interface ActionButtons {
  showRaise: boolean;   // 레이즈 버튼(슬라이더 금액)·올인 버튼을 보이나(서버 can_raise)
  showAllin: boolean;
  canRaise: boolean;    // 레이즈 금액을 고를 수 있나(보이고, 최소 레이즈에 닿는 스택)
  maxRaise: number;     // 내가 도달할 수 있는 최대 베팅(남은 칩 + 이번 스트리트 베팅)
  callLabel: string;    // "체크" / "콜 40" / "콜 25 (올인)"
}

/**
 * 서버 can_raise가 false면(불완전 올인으로 액션이 닫힘, 또는 스택이 콜 이하) 레이즈·올인 버튼을
 * 보이지 않는다 — 눌러도 서버가 400으로 거절한다. 콜 금액 이하 올인은 콜 버튼이 맡는다
 * (서버가 콜을 남은 칩까지로 자른다).
 */
export function actionButtons(state: BarState): ActionButtons {
  const human = state.players.find((p) => p.is_human);
  const chips = human?.chips ?? 0;
  const call = state.call_amount;
  const maxRaise = chips + (human?.current_bet ?? 0);
  let callLabel: string;
  if (call === 0) callLabel = "체크";
  else if (chips <= call) callLabel = `콜 ${chips} (올인)`;
  else callLabel = `콜 ${call}`;
  const canRaise = state.can_raise && chips > call && state.min_raise_to > 0 && maxRaise >= state.min_raise_to;
  return { showRaise: state.can_raise, showAllin: state.can_raise, canRaise, maxRaise, callLabel };
}

export interface Preset {
  label: string;
  value: number;  // 도달 베팅(raise-to)
}

export const POT_FRACTIONS: { label: string; f: number }[] = [
  { label: "1/3", f: 1 / 3 },
  { label: "1/2", f: 1 / 2 },
  { label: "3/4", f: 3 / 4 },
  { label: "팟", f: 1 },
];

/**
 * 팟 기준 프리셋: 콜한 뒤의 팟(pot + call)의 f만큼 더 올린다 → 도달 베팅 = current_bet + round(f × (pot + call)).
 * pot은 이번 스트리트 베팅을 포함한 테이블 위 전체 팟.
 */
export function potPresets(state: Pick<GameState, "pot" | "call_amount" | "current_bet">): Preset[] {
  const after = state.pot + state.call_amount;
  return POT_FRACTIONS.map(({ label, f }) => ({ label, value: state.current_bet + Math.round(f * after) }));
}

/** 상대 베팅 배율 프리셋: 도달 베팅 = round(k × current_bet). */
export function betPresets(state: Pick<GameState, "current_bet">): Preset[] {
  return [2, 2.5, 3, 4].map((k) => ({ label: `${k}x`, value: Math.round(state.current_bet * k) }));
}

/** 프리셋이 지금 고를 수 없는 금액인가(레이즈 불가, 최소 레이즈 미만, 스택 초과). */
export function presetOff(value: number, b: Pick<ActionButtons, "canRaise" | "maxRaise">, minRaiseTo: number): boolean {
  return !b.canRaise || value < minRaiseTo || value > b.maxRaise;
}
