import { useState, useEffect, useCallback, useRef } from "react";
import type { GameEvent, ActionBadge } from "../types";
import { getEventDelay, THINKING_RATIO } from "../config/timing";
import { isBetAction, formatBadge, commitEffectFor } from "./eventQueueLogic";

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
  // isReplaying은 "큐에 아직 이벤트가 남았나"에서 100% 파생되는 값이라 별도 state로
  // 안 두고 매 렌더 계산한다(예전엔 enqueue에서 true로, 큐가 비면 effect에서 false로
  // 두 곳에서 동기화했는데 그 자체가 set-state-in-effect 위반의 원인이었다).
  const isReplaying = queue.length > 0;
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
    setShowdownRevealed(false);
    setCommittedActions(new Map()); // 스킵 시 초기화 → current_bet 폴백 표시
  }, []);

  // 큐가 "이벤트 있음 ↔ 없음"으로 전환될 때 하이라이트류 상태를 정리한다.
  // useEffect 대신 렌더 중 조정 패턴(React 공식 권장)을 쓴다 — 큐가 실제로
  // 빈 상태로 "전환"된 시점에만 1회 실행되고 무한 루프로 번지지 않는다.
  const queueEmpty = queue.length === 0;
  const [prevQueueEmpty, setPrevQueueEmpty] = useState(true);
  if (queueEmpty !== prevQueueEmpty) {
    setPrevQueueEmpty(queueEmpty);
    if (queueEmpty) {
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

    // 커뮤니티 카드 — 이벤트 큐를 소비할 때마다 즉시 카운트를 올린다(다음 이벤트로
    // 넘어가는 기준 지연은 아래 else 분기의 setTimeout이 담당). props/state를 따라
    // 파생값을 리셋하는 패턴이 아니라 "큐에서 이벤트를 하나 소비"하는 처리라
    // 이 규칙이 겨냥하는 antipattern은 아니지만, 같은 effect 안의 동기 setState라
    // 규칙이 함께 잡는다.
    if (current.type === "community_card") {
      // eslint-disable-next-line react-hooks/set-state-in-effect
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
        if (isBetAction((current as { action: string }).action)) {
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
        const commitEffect = commitEffectFor(current);
        if (commitEffect.kind === "set") {
          const { player: p, label } = commitEffect;
          setCommittedActions((prev) => {
            const next = new Map(prev);
            next.set(p, label);
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
      // blind: 즉시 커밋 레이블 등록 / street_start: 커밋 레이블 초기화(새 스트리트 시작)
      const commitEffect = commitEffectFor(current);
      if (commitEffect.kind === "set") {
        const { player: p, label } = commitEffect;
        setCommittedActions((prev) => { const m = new Map(prev); m.set(p, label); return m; });
      } else if (commitEffect.kind === "reset") {
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
