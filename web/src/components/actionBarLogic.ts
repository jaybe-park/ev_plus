// ActionBar의 버튼 표시 판단만 순수 함수로 뽑은 모듈(vitest 대상, T-039).
import type { GameState } from "../types";

export interface ActionButtons {
  showRaise: boolean;   // 레이즈 버튼(슬라이더 금액)
  showAllin: boolean;   // 올인(레이즈) 버튼
  callLabel: string;    // "체크" / "콜 40" / "콜 25 (올인)"
}

/**
 * 서버 can_raise가 false면(불완전 올인으로 액션이 닫힘, 또는 스택이 콜 이하) 레이즈·올인 버튼을
 * 보이지 않는다 — 눌러도 서버가 400으로 거절한다. 콜 금액 이하 올인은 콜 버튼이 맡는다
 * (서버가 콜을 남은 칩까지로 자른다).
 */
export function actionButtons(state: Pick<GameState, "call_amount" | "can_raise" | "players">): ActionButtons {
  const human = state.players.find((p) => p.is_human);
  const chips = human?.chips ?? 0;
  const call = state.call_amount;
  let callLabel: string;
  if (call === 0) callLabel = "체크";
  else if (chips <= call) callLabel = `콜 ${chips} (올인)`;
  else callLabel = `콜 ${call}`;
  return { showRaise: state.can_raise, showAllin: state.can_raise, callLabel };
}
