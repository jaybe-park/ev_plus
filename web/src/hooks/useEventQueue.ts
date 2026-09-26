import { useState, useEffect, useCallback, useRef } from "react";
import type { GameEvent, ActionBadge, GameState } from "../types";
import { getEventDelay, THINKING_RATIO } from "../config/timing";
import {
  isBetAction, formatBadge, initialDisplay, applyEvent, applyEvents, eventTiming,
  type DisplayState,
} from "./eventQueueLogic";

// 이벤트 큐 재생(T-029). 무엇을 보일지는 순수 리듀서(eventQueueLogic.applyEvent)가 정하고,
// 이 훅은 "언제" 반영할지(타이머)와 하이라이트류 연출(생각 중·배지·칩 날아가기)만 맡는다.
export interface EventQueueState {
  isReplaying: boolean;
  display: DisplayState | null;        // 재생 표시 상태(재생이 끝나면 서버 최종 상태와 같다)
  activePlayer: string | null;
  isThinking: boolean;
  badge: ActionBadge | null;
  bettingPlayer: string | null;
  enqueue: (events: GameEvent[], prevState: GameState | null, next: GameState, isNewHand: boolean) => void;
  skip: () => void;
  reset: () => void;
}

export function useEventQueue(): EventQueueState {
  const [queue, setQueue]                   = useState<GameEvent[]>([]);
  const isReplaying = queue.length > 0;
  const [display, setDisplay]               = useState<DisplayState | null>(null);
  const [humanName, setHumanName]           = useState<string | null>(null);
  const [activePlayer, setActivePlayer]     = useState<string | null>(null);
  const [isThinking, setIsThinking]         = useState(false);
  const [badge, setBadge]                   = useState<ActionBadge | null>(null);
  const [bettingPlayer, setBettingPlayer]   = useState<string | null>(null);

  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);
  const queueRef = useRef<GameEvent[]>([]);  // skip이 남은 이벤트를 읽는다(렌더 밖에서만 갱신)
  const headAppliedRef = useRef(false);      // 큐 맨 앞 이벤트를 이미 표시 상태에 반영했나
  useEffect(() => { queueRef.current = queue; }, [queue]);
  const clearTimers = () => {
    timersRef.current.forEach(clearTimeout);
    timersRef.current = [];
  };

  const enqueue = useCallback(
    (events: GameEvent[], prevState: GameState | null, next: GameState, isNewHand: boolean) => {
      clearTimers();
      setHumanName(next.players.find((p) => p.is_human)?.name ?? null);
      // 시작점 = 요청 직전 상태(새 핸드면 블라인드 전). 좌석 레이블은 직전 표시에서 이어받는다.
      setDisplay((prevDisplay) => initialDisplay(prevState, prevDisplay, next, isNewHand));
      setQueue(events);
    },
    []
  );

  const skip = useCallback(() => {
    clearTimers();
    // 남은 이벤트를 한 번에 소비 — 표시 상태가 서버 최종 상태와 같아진다
    const rest = headAppliedRef.current ? queueRef.current.slice(1) : queueRef.current;
    if (rest.length > 0) setDisplay((d) => (d ? applyEvents(d, rest) : d));
    setQueue([]);
    setActivePlayer(null);
    setIsThinking(false);
    setBadge(null);
    setBettingPlayer(null);
  }, []);

  const reset = useCallback(() => {
    clearTimers();
    setQueue([]);
    setDisplay(null);
    setActivePlayer(null);
    setIsThinking(false);
    setBadge(null);
    setBettingPlayer(null);
  }, []);

  // 큐가 비는 순간 하이라이트류 정리(렌더 중 조정 패턴 — set-state-in-effect 회피)
  const [prevQueueEmpty, setPrevQueueEmpty] = useState(true);
  if ((queue.length === 0) !== prevQueueEmpty) {
    setPrevQueueEmpty(queue.length === 0);
    if (queue.length === 0) {
      setActivePlayer(null);
      setIsThinking(false);
      setBadge(null);
      setBettingPlayer(null);
    }
  }

  useEffect(() => {
    if (queue.length === 0) return;
    const [current, ...rest] = queue;
    const delay = getEventDelay(
      current.type,
      "street" in current ? (current as { street?: string }).street : undefined
    );
    const timing = eventTiming(current, humanName, delay, THINKING_RATIO);
    const player = "player" in current ? (current as { player: string }).player : null;

    headAppliedRef.current = false;
    const commit = () => {
      headAppliedRef.current = true;
      setDisplay((d) => (d ? applyEvent(d, current) : d));
      if (current.type === "action") {
        setIsThinking(false);
        setBadge(formatBadge(current));
        if (isBetAction(current.action)) setBettingPlayer(current.player);
      } else if (current.type === "blind") {
        setBadge(formatBadge(current));
        setBettingPlayer(current.player);
      }
    };

    // 하이라이트 시작(딜링 제외). 봇 액션은 "생각 중" 먼저.
    // 큐에서 이벤트를 하나 소비하는 처리라 파생 상태 리셋 antipattern은 아니다.
    if (player && current.type !== "deal_card") {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setActivePlayer(player);
    }
    if (timing.thinking) {
      setIsThinking(true);
      setBadge(null);
      setBettingPlayer(null);
    }

    const timers: ReturnType<typeof setTimeout>[] = [];
    if (timing.applyAt <= 0) commit();
    else timers.push(setTimeout(commit, timing.applyAt));
    timers.push(setTimeout(() => {
      setBadge(null);
      setBettingPlayer(null);
      setActivePlayer(null);
      setQueue(rest);
    }, timing.next));
    timersRef.current = timers;
    return clearTimers;
  }, [queue, humanName]);

  return { isReplaying, display, activePlayer, isThinking, badge, bettingPlayer, enqueue, skip, reset };
}
