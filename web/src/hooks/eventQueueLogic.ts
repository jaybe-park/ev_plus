// useEventQueue의 "이벤트 하나를 보고 무엇을 표시할지" 판단 로직만 순수 함수로 뽑아둔 모듈.
// 타이머로 언제 반영할지(스케줄링)는 useEventQueue.ts가 맡고, 이 파일은 부작용 없이
// 입력(GameEvent)에서 출력(배지 텍스트/커밋 레이블/리셋 여부)만 계산한다 — vitest로
// 이벤트 순서·텍스트를 검증하기 위해 분리.
import type { GameEvent, ActionBadge, GameState } from "../types";

export const BET_ACTIONS = new Set(["call", "raise", "allin"]);

export function isBetAction(action: string): boolean {
  return BET_ACTIONS.has(action);
}

/** 블라인드 표기 "SB 10" / "BB 20". 헤즈업 버튼(BTN/SB)은 SB. */
export function blindLabel(position: string, amount: number): string {
  const isSmall = position === "SB" || position === "BTN/SB";
  return `${isSmall ? "SB" : "BB"} ${amount}`;
}

/** 이벤트 로그에서 배지(플레이어 옆 말풍선)에 표시할 텍스트를 만든다. 없으면 null. */
export function formatBadge(event: GameEvent): ActionBadge | null {
  if (event.type === "blind") {
    return { player: event.player, text: blindLabel(event.position, event.amount), variant: "blind" };
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
  if (event.type === "blind") return blindLabel(event.position, event.amount);
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

// ─────────────────────────────────────────────────────────────
// 재생 표시 상태
//   응답이 오면 서버 최종 상태(next)를 바로 그리지 않는다. 재생 중에는 "이전 상태 + 지금까지
//   소비한 이벤트"로 만든 DisplayState 하나만 그린다(applyEvent 리듀서). 팟·스트리트·베팅·칩·
//   폴드·카드 수·로그 줄 수가 모두 여기서 나오므로 애니메이션과 같은 시점에 바뀐다.
//   로그: 서버는 끝 30줄(action_log[-30:])만 보내므로, 아직 소비하지 않은 이벤트의 로그 줄 수
//   (logPending)를 들고 next.action_log의 끝에서 그만큼 숨긴다(앞 기준으로 자르면 30줄이 넘는
//   핸드에서 창이 밀려 어긋난다).
// ─────────────────────────────────────────────────────────────

export interface SeatView {
  chips: number;
  bet: number;               // 이번 스트리트 베팅
  folded: boolean;
  allIn: boolean;
  dealt: number;             // 받은 홀카드 수(딜링 애니메이션)
  committed: string | null;  // 좌석 아래 마지막 액션 레이블
}

export interface DisplayState {
  street: string;
  pot: number;
  cardCount: number;         // 보이는 커뮤니티 카드 수
  logPending: number;        // 아직 소비하지 않은 이벤트의 로그 줄 수(끝에서 숨김)
  showdownRevealed: boolean;
  seats: Record<string, SeatView>;
}

/**
 * 재생 시작점. 새 핸드면 블라인드 전(칩 = 직전 핸드 종료 칩, 없으면 next의 chips+current_bet),
 * 이어지는 액션이면 요청 직전 상태(prevState)에서 시작한다. 좌석 레이블은 직전 표시에서 이어받는다.
 */
export function initialDisplay(
  prevState: GameState | null,
  prevDisplay: DisplayState | null,
  next: GameState,
  isNewHand: boolean,
): DisplayState {
  const logPending = next.events.filter((e) => e.log).length;
  if (isNewHand || !prevState) {
    const prevChips = new Map((prevState?.players ?? []).map((p) => [p.name, p.chips]));
    const seats: Record<string, SeatView> = {};
    for (const p of next.players) {
      const handStart = isNewHand ? prevChips.get(p.name) : undefined;
      seats[p.name] = {
        chips: handStart ?? p.chips + p.current_bet,
        bet: 0, folded: false, allIn: false, dealt: 0, committed: null,
      };
    }
    return { street: "프리플랍", pot: 0, cardCount: 0, logPending, showdownRevealed: false, seats };
  }
  const seats: Record<string, SeatView> = {};
  for (const p of prevState.players) {
    seats[p.name] = {
      chips: p.chips, bet: p.current_bet, folded: p.is_folded, allIn: p.is_all_in, dealt: 2,
      committed: prevDisplay?.seats[p.name]?.committed ?? null,
    };
  }
  return {
    street: prevState.street,
    pot: prevState.pot,
    cardCount: prevState.community_cards.length,
    logPending,
    showdownRevealed: false,
    seats,
  };
}

function withSeat(d: DisplayState, name: string, patch: Partial<SeatView>): Record<string, SeatView> {
  const cur = d.seats[name] ?? { chips: 0, bet: 0, folded: false, allIn: false, dealt: 0, committed: null };
  return { ...d.seats, [name]: { ...cur, ...patch } };
}

/** 이벤트 하나를 소비한 뒤의 표시 상태(순수 리듀서). */
export function applyEvent(d: DisplayState, e: GameEvent): DisplayState {
  const logPending = e.log ? Math.max(0, d.logPending - 1) : d.logPending;
  switch (e.type) {
    case "deal_card": {
      const cur = d.seats[e.player]?.dealt ?? 0;
      return { ...d, logPending, seats: withSeat(d, e.player, { dealt: Math.min(cur + 1, 2) }) };
    }
    case "blind":
      return {
        ...d, logPending,
        pot: e.pot_after ?? d.pot + e.amount,
        seats: withSeat(d, e.player, {
          chips: e.chips_after ?? d.seats[e.player]?.chips ?? 0,
          bet: e.bet_after ?? e.amount,
          committed: makeCommitLabel(e),
        }),
      };
    case "action": {
      const seat = d.seats[e.player];
      const chips = e.chips_after ?? seat?.chips ?? 0;
      return {
        ...d, logPending,
        pot: e.pot_after ?? d.pot,
        seats: withSeat(d, e.player, {
          chips,
          bet: e.bet_after ?? seat?.bet ?? 0,
          folded: (seat?.folded ?? false) || e.action === "fold",
          allIn: (seat?.allIn ?? false) || e.action === "allin" || (e.action !== "fold" && chips === 0),
          committed: makeCommitLabel(e),
        }),
      };
    }
    case "street_start": {
      const seats: Record<string, SeatView> = {};
      for (const [k, s] of Object.entries(d.seats)) seats[k] = { ...s, bet: 0, committed: null };
      return { ...d, logPending, street: e.street, pot: e.pot_after ?? d.pot, seats };
    }
    case "community_card":
      return { ...d, logPending, cardCount: d.cardCount + 1 };
    case "showdown":
      return { ...d, logPending, showdownRevealed: true };
    case "winner": {
      let seats = d.seats;
      for (const [name, c] of Object.entries(e.winner_chips ?? {})) {
        seats = withSeat({ ...d, seats }, name, { chips: c });
      }
      return { ...d, logPending, pot: 0, seats };
    }
  }
  return d;
}

/** 이벤트 목록 전체를 소비한 표시 상태(스킵·테스트용). */
export function applyEvents(d: DisplayState, events: GameEvent[]): DisplayState {
  return events.reduce(applyEvent, d);
}

/**
 * 서버 최종 상태 next를 표시 상태로 덮어 "지금 화면에 보일 GameState" 하나를 만든다.
 * 팟·스트리트·보드·로그·좌석 칩/베팅/폴드/올인이 표시 상태에서 나온다.
 */
export function projectState(next: GameState, d: DisplayState): GameState {
  return {
    ...next,
    street: d.street,
    pot: d.pot,
    community_cards: next.community_cards.slice(0, d.cardCount),
    action_log: next.action_log.slice(0, Math.max(0, next.action_log.length - d.logPending)),
    players: next.players.map((p) => {
      const s = d.seats[p.name];
      return s ? { ...p, chips: s.chips, current_bet: s.bet, is_folded: s.folded, is_all_in: s.allIn } : p;
    }),
  };
}

/**
 * 힌트 패널(에퀴티·GTO)·액션 바가 읽을 상태. 재생 중엔 재생 직전 상태를 유지해, 아직 화면에
 * 깔리지 않은 카드가 반영된 새 에퀴티·GTO 노드를 먼저 보이지 않는다. 헤더 핸드 번호도 이 상태를 쓴다.
 */
export function panelState(isReplaying: boolean, replayBase: GameState | null, current: GameState): GameState {
  return isReplaying && replayBase ? replayBase : current;
}

/** 테이블이 그릴 상태 하나: 재생 중이면 표시 상태로 덮은 것, 아니면 서버 최종 상태. */
export function shownState(isReplaying: boolean, display: DisplayState | null, current: GameState): GameState {
  return isReplaying && display ? projectState(current, display) : current;
}

// ── 이벤트 타이밍 ─────────────────────────────────────────

/** 사람 자신의 액션은 "생각 중" 없이 즉시 반영하고 배지만 잠깐 보인다(봇만 연출 — 결정됨). */
export const HUMAN_ACTION_MS = 350;

export interface EventTiming {
  thinking: boolean;  // "생각 중" 점 표시 여부
  applyAt: number;    // 표시 상태에 반영하는 시각(ms, 이벤트 시작 기준)
  next: number;       // 다음 이벤트로 넘어가는 시각(ms)
}

/** delay는 getEventDelay 값. thinkingRatio는 봇 액션의 "생각 중" 비율. */
export function eventTiming(e: GameEvent, humanName: string | null, delay: number, thinkingRatio: number): EventTiming {
  if (e.type === "action") {
    if (humanName !== null && e.player === humanName) {
      return { thinking: false, applyAt: 0, next: HUMAN_ACTION_MS };
    }
    return { thinking: true, applyAt: delay * thinkingRatio, next: delay };
  }
  if (e.type === "deal_card") return { thinking: false, applyAt: delay, next: delay };
  return { thinking: false, applyAt: 0, next: delay };
}
