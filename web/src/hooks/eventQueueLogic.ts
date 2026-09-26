// useEventQueue의 "이벤트 하나를 보고 무엇을 표시할지" 판단 로직만 순수 함수로 뽑아둔 모듈.
// 타이머로 언제 반영할지(스케줄링)는 useEventQueue.ts가 맡고, 이 파일은 부작용 없이
// 입력(GameEvent)에서 출력(배지 텍스트/커밋 레이블/리셋 여부)만 계산한다 — vitest로
// 이벤트 순서·텍스트를 검증하기 위해 분리(T-030).
import type { GameEvent, ActionBadge } from "../types";

export const BET_ACTIONS = new Set(["call", "raise", "allin"]);

export function isBetAction(action: string): boolean {
  return BET_ACTIONS.has(action);
}

/** 이벤트 로그에서 배지(플레이어 옆 말풍선)에 표시할 텍스트를 만든다. 없으면 null. */
export function formatBadge(event: GameEvent): ActionBadge | null {
  if (event.type === "blind") {
    const isSmall = event.position === "SB" || event.position === "BTN/SB";
    return { player: event.player, text: `${isSmall ? "SB" : "BB"} ${event.amount}`, variant: "blind" };
  }
  if (event.type === "action") {
    const { player, action, amount } = event;
    switch (action) {
      case "fold":  return { player, text: "FOLD",              variant: "fold" };
      case "check": return { player, text: "CHECK",             variant: "check" };
      case "call":  return { player, text: `CALL ${amount}`,    variant: "call" };
      case "raise": return { player, text: `RAISE → ${amount}`, variant: "raise" };
      case "allin": return { player, text: "ALL IN",            variant: "allin" };
    }
  }
  return null;
}

/** 좌석 아래 "커밋된" 액션 레이블(예: "레이즈 → 44", "콜 20")을 만든다. 없으면 null. */
export function makeCommitLabel(event: GameEvent): string | null {
  if (event.type === "blind") {
    const isSmall = event.position === "SB" || event.position === "BTN/SB";
    return `${isSmall ? "SB" : "BB"} ${event.amount}`;
  }
  if (event.type === "action") {
    const { action, amount } = event as { action: string; amount: number };
    switch (action) {
      case "fold":  return "폴드";
      case "check": return "체크";
      case "call":  return `콜 ${amount}`;
      case "raise": return `레이즈 → ${amount}`;
      case "allin": return "올인";
    }
  }
  return null;
}

export type CommitEffect =
  | { kind: "set"; player: string; label: string }
  | { kind: "reset" }
  | { kind: "none" };

/**
 * 이벤트 하나가 좌석 커밋 레이블 맵(committedActions)에 어떤 영향을 주는지 계산한다.
 * - blind/action: 그 플레이어에게 레이블을 세팅
 * - street_start: 맵 전체 초기화(새 스트리트 시작)
 * - 그 외: 영향 없음
 */
export function commitEffectFor(event: GameEvent): CommitEffect {
  if (event.type === "street_start") return { kind: "reset" };
  if (event.type === "blind" || event.type === "action") {
    const label = makeCommitLabel(event);
    const player = (event as { player?: string }).player;
    if (label && player) return { kind: "set", player, label };
  }
  return { kind: "none" };
}

/**
 * 이벤트 배열을 순서대로 "리플레이"했을 때 좌석 커밋 레이블 맵이 어떤 순서로
 * 갱신되는지 계산한다(타이머 없이, 순수하게). 이벤트 순서 회귀 테스트용.
 */
export function replayCommitEffects(events: GameEvent[]): CommitEffect[] {
  return events.map(commitEffectFor);
}
