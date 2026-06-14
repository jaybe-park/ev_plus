import { useState, useEffect, useCallback, useRef } from "react";
import type { GameEvent, ActionBadge } from "../types";
import { getEventDelay, THINKING_RATIO } from "../config/timing";

function formatBadge(event: GameEvent): ActionBadge | null {
  if (event.type === "blind") {
    const isSmall = event.position === "SB" || event.position === "BTN/SB";
    return {
      player: event.player,
      text: `${isSmall ? "SB" : "BB"} ${event.amount}`,
      variant: "blind",
    };
  }
  if (event.type === "action") {
    const { player, action, amount } = event;
    switch (action) {
      case "fold":  return { player, text: "FOLD",           variant: "fold" };
      case "check": return { player, text: "CHECK",          variant: "check" };
      case "call":  return { player, text: `CALL ${amount}`, variant: "call" };
      case "raise": return { player, text: `RAISE → ${amount}`, variant: "raise" };
      case "allin": return { player, text: "ALL IN",         variant: "allin" };
    }
  }
  return null;
}

export interface EventQueueState {
  isReplaying: boolean;
  activePlayer: string | null;    // 현재 하이라이트할 플레이어
  isThinking: boolean;            // 봇 "생각 중" 표시
  badge: ActionBadge | null;      // 플레이어 위에 띄울 액션 배지
  visibleCardCount: number;       // 현재 보여줄 커뮤니티 카드 수
  enqueue: (events: GameEvent[], initialCardCount: number) => void;
  skip: () => void;
  setVisibleCardCount: (n: number) => void;
}

export function useEventQueue(): EventQueueState {
  const [queue, setQueue] = useState<GameEvent[]>([]);
  const [isReplaying, setIsReplaying] = useState(false);
  const [activePlayer, setActivePlayer] = useState<string | null>(null);
  const [isThinking, setIsThinking] = useState(false);
  const [badge, setBadge] = useState<ActionBadge | null>(null);
  const [visibleCardCount, setVisibleCardCount] = useState(0);

  // 타이머 정리용
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);
  const clearTimers = () => {
    timersRef.current.forEach(clearTimeout);
    timersRef.current = [];
  };

  const enqueue = useCallback((events: GameEvent[], initialCardCount: number) => {
    clearTimers();
    setVisibleCardCount(initialCardCount);
    setQueue(events);
    if (events.length > 0) setIsReplaying(true);
  }, []);

  const skip = useCallback(() => {
    clearTimers();
    setQueue([]);
    setActivePlayer(null);
    setIsThinking(false);
    setBadge(null);
    setIsReplaying(false);
  }, []);

  useEffect(() => {
    if (queue.length === 0) {
      setIsReplaying(false);
      setActivePlayer(null);
      setIsThinking(false);
      setBadge(null);
      return;
    }

    const [current, ...rest] = queue;
    const delay = getEventDelay(
      current.type,
      "street" in current ? current.street : undefined
    );

    // 커뮤니티 카드는 즉시 카운트 증가
    if (current.type === "community_card") {
      setVisibleCardCount((c) => c + 1);
    }

    // 플레이어 관련 이벤트 하이라이트
    const player = "player" in current ? current.player : null;
    if (player) setActivePlayer(player);

    const isAction = current.type === "action";

    if (isAction) {
      // 1단계: 생각 중 표시
      setIsThinking(true);
      setBadge(null);

      const t1 = setTimeout(() => {
        setIsThinking(false);
        setBadge(formatBadge(current));
      }, delay * THINKING_RATIO);

      const t2 = setTimeout(() => {
        setBadge(null);
        setActivePlayer(null);
        setQueue(rest);
      }, delay);

      timersRef.current = [t1, t2];
    } else {
      // 기계적 이벤트: 배지 표시 후 바로 다음으로
      setBadge(formatBadge(current));

      const t = setTimeout(() => {
        setBadge(null);
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
    enqueue,
    skip,
    setVisibleCardCount,
  };
}
