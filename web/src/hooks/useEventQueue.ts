import { useState, useEffect, useCallback, useRef } from "react";
import type { GameEvent, ActionBadge } from "../types";
import { getEventDelay, THINKING_RATIO } from "../config/timing";

const BET_ACTIONS = new Set(["call", "raise", "allin"]);

function makeCommitLabel(event: GameEvent): string | null {
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

function formatBadge(event: GameEvent): ActionBadge | null {
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

export interface EventQueueState {
  isReplaying: boolean;
  activePlayer: string | null;
  isThinking: boolean;
  badge: ActionBadge | null;
  visibleCardCount: number;
  visibleLogCount: number;
  foldedDuringReplay: Set<string>;
  bettingPlayer: string | null;
  dealtCards: Map<string, number>;
  showdownRevealed: boolean;
  displayedChips: Map<string, number>;
  committedActions: Map<string, string>; // 플레이어별 마지막 액션 레이블 ("레이즈 44", "콜 20", ...)
  enqueue: (
    events: GameEvent[],
    initialCardCount: number,
    initialFolded: string[],
    initialLogCount: number,
    isNewHand: boolean,
    initialChips: Record<string, number>  // 이전 상태의 플레이어 칩
  ) => void;
  skip: () => void;
  setVisibleCardCount: (n: number) => void;
}

export function useEventQueue(): EventQueueState {
  const [queue, setQueue]                           = useState<GameEvent[]>([]);
  const [isReplaying, setIsReplaying]               = useState(false);
  const [activePlayer, setActivePlayer]             = useState<string | null>(null);
  const [isThinking, setIsThinking]                 = useState(false);
  const [badge, setBadge]                           = useState<ActionBadge | null>(null);
  const [visibleCardCount, setVisibleCardCount]     = useState(0);
  const [visibleLogCount, setVisibleLogCount]       = useState(0);
  const [foldedDuringReplay, setFoldedDuringReplay] = useState<Set<string>>(new Set());
  const [bettingPlayer, setBettingPlayer]           = useState<string | null>(null);
  const [dealtCards, setDealtCards]                 = useState<Map<string, number>>(new Map());
  const [showdownRevealed, setShowdownRevealed]     = useState(false);
  const [displayedChips, setDisplayedChips]         = useState<Map<string, number>>(new Map());
  const [committedActions, setCommittedActions]     = useState<Map<string, string>>(new Map());

  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);
  const clearTimers = () => {
    timersRef.current.forEach(clearTimeout);
    timersRef.current = [];
  };

  const enqueue = useCallback(
    (
      events: GameEvent[],
      initialCardCount: number,
      initialFolded: string[],
      initialLogCount: number,
      isNewHand: boolean,
      initialChips: Record<string, number>
    ) => {
      clearTimers();
      setVisibleCardCount(initialCardCount);
      setVisibleLogCount(initialLogCount);
      setFoldedDuringReplay(new Set(initialFolded));
      setDisplayedChips(new Map(Object.entries(initialChips)));
      if (isNewHand) { setDealtCards(new Map()); setCommittedActions(new Map()); }
      setShowdownRevealed(false);
      setQueue(events);
      if (events.length > 0) setIsReplaying(true);
    },
    []
  );

  const skip = useCallback(() => {
    clearTimers();
    setQueue([]);
    setActivePlayer(null);
    setIsThinking(false);
    setBadge(null);
    setBettingPlayer(null);
    setIsReplaying(false);
    setShowdownRevealed(false);
    setCommittedActions(new Map()); // 스킵 시 초기화 → current_bet 폴백 표시
  }, []);

  useEffect(() => {
    if (queue.length === 0) {
      setIsReplaying(false);
      setActivePlayer(null);
      setIsThinking(false);
      setBadge(null);
      setBettingPlayer(null);
      return;
    }

    const [current, ...rest] = queue;
    const delay = getEventDelay(
      current.type,
      "street" in current ? (current as { street?: string }).street : undefined
    );

    // 커뮤니티 카드
    if (current.type === "community_card") {
      setVisibleCardCount((c) => c + 1);
    }

    // 카드 한 장 딜링 — 하이라이트 없이
    if (current.type === "deal_card") {
      const p = (current as { player: string }).player;
      const t = setTimeout(() => {
        setDealtCards((prev) => {
          const next = new Map(prev);
          next.set(p, Math.min((next.get(p) ?? 0) + 1, 2));
          return next;
        });
        setQueue(rest);
      }, delay);
      timersRef.current = [t];
      return clearTimers;
    }

    // 플레이어 하이라이트
    const player = "player" in current ? (current as { player: string }).player : null;
    if (player) setActivePlayer(player);

    const isAction = current.type === "action";

    if (isAction) {
      setIsThinking(true);
      setBadge(null);
      setBettingPlayer(null);

      const t1 = setTimeout(() => {
        setIsThinking(false);
        setBadge(formatBadge(current));
        if (current.log) setVisibleLogCount((n) => n + 1);
        if (BET_ACTIONS.has((current as { action: string }).action)) {
          setBettingPlayer((current as { player: string }).player);
        }
        // 칩 업데이트
        const chips = (current as { chips_after?: number }).chips_after;
        if (chips !== undefined && chips !== null && current.player) {
          setDisplayedChips((prev) => {
            const next = new Map(prev);
            next.set((current as { player: string }).player, chips);
            return next;
          });
        }
        // 액션 레이블 커밋 (배지와 동시에)
        const label = makeCommitLabel(current);
        if (label && (current as { player?: string }).player) {
          setCommittedActions((prev) => {
            const next = new Map(prev);
            next.set((current as { player: string }).player, label);
            return next;
          });
        }
      }, delay * THINKING_RATIO);

      const t2 = setTimeout(() => {
        setBadge(null);
        setBettingPlayer(null);
        setActivePlayer(null);
        if ((current as { action: string }).action === "fold") {
          setFoldedDuringReplay((prev) =>
            new Set([...prev, (current as { player: string }).player])
          );
        }
        setQueue(rest);
      }, delay);

      timersRef.current = [t1, t2];
    } else {
      // 기계적 이벤트 (blind, street_start, showdown, winner)
      const b = formatBadge(current);
      if (b) setBadge(b);
      if (current.log) setVisibleLogCount((n) => n + 1);
      if (current.type === "blind" && player) setBettingPlayer(player);
      if (current.type === "showdown") setShowdownRevealed(true);
      // blind: 즉시 커밋 레이블 등록
      if (current.type === "blind" && player) {
        const label = makeCommitLabel(current);
        if (label) setCommittedActions((prev) => { const m = new Map(prev); m.set(player, label); return m; });
      }
      // street_start: 커밋 레이블 초기화 (새 스트리트 시작)
      if (current.type === "street_start") {
        setCommittedActions(new Map());
      }

      // blind: 칩 즉시 반영
      if (current.type === "blind") {
        const chips = (current as { chips_after?: number }).chips_after;
        if (chips !== undefined && chips !== null && player) {
          setDisplayedChips((prev) => { const m = new Map(prev); m.set(player, chips); return m; });
        }
      }
      // winner: 승자 칩 반영
      if (current.type === "winner") {
        const wc = (current as { winner_chips?: Record<string, number> }).winner_chips;
        if (wc) {
          setDisplayedChips((prev) => {
            const m = new Map(prev);
            for (const [name, c] of Object.entries(wc)) m.set(name, c);
            return m;
          });
        }
      }

      const t = setTimeout(() => {
        setBadge(null);
        setBettingPlayer(null);
        setActivePlayer(null);
        setQueue(rest);
      }, delay);

      timersRef.current = [t];
    }

    return clearTimers;
  }, [queue]);

  return {
    isReplaying,
    activePlayer,
    isThinking,
    badge,
    visibleCardCount,
    visibleLogCount,
    foldedDuringReplay,
    bettingPlayer,
    dealtCards,
    showdownRevealed,
    displayedChips,
    committedActions,
    enqueue,
    skip,
    setVisibleCardCount,
  };
}
