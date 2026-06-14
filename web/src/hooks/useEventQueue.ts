import { useState, useEffect, useCallback, useRef } from "react";
import type { GameEvent, ActionBadge } from "../types";
import { getEventDelay, THINKING_RATIO } from "../config/timing";

const BET_ACTIONS = new Set(["call", "raise", "allin"]);

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
  showdownRevealed: boolean;         // showdown 이벤트가 재생됐는지 (봇 카드 공개 시점)
  enqueue: (
    events: GameEvent[],
    initialCardCount: number,
    initialFolded: string[],
    initialLogCount: number,          // 이전 상태 로그 개수
    isNewHand: boolean
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
      isNewHand: boolean
    ) => {
      clearTimers();
      setVisibleCardCount(initialCardCount);
      setVisibleLogCount(initialLogCount);
      setFoldedDuringReplay(new Set(initialFolded));
      if (isNewHand) setDealtCards(new Map());
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
        // 로그: 배지가 표시될 때 함께 등장
        if (current.log) setVisibleLogCount((n) => n + 1);
        if (BET_ACTIONS.has((current as { action: string }).action)) {
          setBettingPlayer((current as { player: string }).player);
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
      // showdown 이벤트: 봇 카드 공개
      if (current.type === "showdown") setShowdownRevealed(true);

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
    enqueue,
    skip,
    setVisibleCardCount,
  };
}
