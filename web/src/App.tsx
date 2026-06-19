import { useState, useCallback, useRef, useEffect } from "react";
import type { GameState, SetupConfig, GtoRange } from "./types";
import { api } from "./api";
import { useEventQueue } from "./hooks/useEventQueue";
import SetupForm from "./components/SetupForm";
import PokerTable from "./components/PokerTable";
import ActionBar from "./components/ActionBar";
import ActionLog from "./components/ActionLog";
import HandResult from "./components/HandResult";
import GtoPanel from "./components/GtoPanel";

export default function App() {
  const [state, setState] = useState<GameState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [myCardsRevealed, setMyCardsRevealed] = useState(false);
  const [rightTab, setRightTab] = useState<"log" | "gto">("log");
  const [gtoRange, setGtoRange] = useState<GtoRange | null>(null);
  const [gtoLoading, setGtoLoading] = useState(false);

  const prevHandNumber = useRef<number>(0);

  const {
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
  } = useEventQueue();

  // 서버 응답을 받아 이벤트 큐를 세팅하는 공통 처리
  const applyNewState = useCallback(
    (next: GameState) => {
      const isNewHand = next.hand_number !== prevHandNumber.current;
      prevHandNumber.current = next.hand_number;
      if (isNewHand) setMyCardsRevealed(false); // 새 핸드: 카드 숨김 초기화

      // 새 핸드: 커뮤니티 카드 0부터 시작
      // 이어지는 액션: 이전 표시 카드 수부터 시작
      const initialCardCount = isNewHand ? 0 : (state?.community_cards.length ?? 0);
      const initialFolded    = isNewHand ? [] : (state?.players.filter((p) => p.is_folded).map((p) => p.name) ?? []);
      const initialLogCount  = isNewHand ? 0 : (state?.action_log.length ?? 0);
      // 새 핸드: 블라인드가 이미 반영된 next.players 에서 chips+current_bet 으로 역산
      // → SB: 990+10=1000, BB: 980+20=1000 (블라인드 포스팅 전 값)
      // 기존 핸드: 직전 상태의 chips (이번 액션 전 값)
      const initialChips = isNewHand
        ? Object.fromEntries(next.players.map((p) => [p.name, p.chips + p.current_bet]))
        : Object.fromEntries((state?.players ?? next.players).map((p) => [p.name, p.chips]));

      setState(next);

      if (next.events.length > 0) {
        enqueue(next.events, initialCardCount, initialFolded, initialLogCount, isNewHand, initialChips);
      } else {
        setVisibleCardCount(next.community_cards.length);
      }
    },
    [state, enqueue, setVisibleCardCount]
  );

  const run = useCallback(
    async (fn: () => Promise<GameState>) => {
      setLoading(true);
      setError(null);
      try {
        const next = await fn();
        applyNewState(next);
      } catch (e) {
        setError(e instanceof Error ? e.message : "오류가 발생했습니다.");
      } finally {
        setLoading(false);
      }
    },
    [applyNewState]
  );

  // GTO 레인지 페치 — gto_key가 바뀔 때마다
  useEffect(() => {
    const key = state?.gto_key;
    if (!key) { setGtoRange(null); return; }

    let cancelled = false;
    setGtoLoading(true);
    api.getGtoRange(key)
      .then(r => { if (!cancelled) setGtoRange(r); })
      .catch(() => { if (!cancelled) setGtoRange(null); })
      .finally(() => { if (!cancelled) setGtoLoading(false); });

    return () => { cancelled = true; };
  }, [state?.gto_key?.position, state?.gto_key?.vs_position, state?.gto_key?.range_type]);

  const handleStart    = (config: SetupConfig) => run(() => api.startGame(config));
  const handleAction   = (action: string, amount = 0) => {
    if (!state) return;
    run(() => api.submitAction(state.session_id, action, amount));
  };
  const handleNextHand = () => { if (!state) return; run(() => api.nextHand(state.session_id)); };
  const handleNewGame  = () => { skip(); setState(null); setMyCardsRevealed(false); };

  // 홀카드 → GTO 핸드 표기 변환
  function toGtoHand(cards: string[] | null): string | null {
    if (!cards || cards.length < 2) return null;
    const RANK_VAL: Record<string, number> = {
      A:14,K:13,Q:12,J:11,"10":10,T:10,"9":9,"8":8,"7":7,"6":6,"5":5,"4":4,"3":3,"2":2
    };
    const GTO_RANK: Record<string, string> = {
      A:"A",K:"K",Q:"Q",J:"J","10":"T","9":"9","8":"8","7":"7","6":"6","5":"5","4":"4","3":"3","2":"2"
    };
    const SUITS = ["♠","♥","♦","♣"];
    const parse = (c: string) => {
      const suit = SUITS.find(s => c.endsWith(s)) ?? "";
      const rank = c.slice(0, -1);
      return { rank, suit, val: RANK_VAL[rank] ?? 0, gto: GTO_RANK[rank] ?? rank };
    };
    const [c1, c2] = [parse(cards[0]), parse(cards[1])];
    const [hi, lo] = c1.val >= c2.val ? [c1, c2] : [c2, c1];
    if (hi.rank === lo.rank) return hi.gto + lo.gto;
    return hi.gto + lo.gto + (hi.suit === lo.suit ? "s" : "o");
  }

  if (!state) return <SetupForm onStart={handleStart} />;

  const human = state.players.find((p) => p.is_human);

  // 액션 버튼: 재생 중이거나 로딩 중이면 비활성
  const actionDisabled = isReplaying || loading;

  return (
    <div className="min-h-screen bg-gray-950 flex flex-col lg:flex-row">
      {/* 메인 게임 영역 */}
      <div className="flex-1 flex flex-col min-h-0">
        {/* 헤더 */}
        <div className="bg-gray-900 border-b border-gray-700 px-4 py-2 flex items-center justify-between shrink-0">
          <h1 className="text-white font-bold text-sm">♠ Texas Hold'em</h1>
          <div className="flex items-center gap-4 text-sm">
            <span className="text-gray-400">핸드 #{state.hand_number}</span>
            <span className="text-yellow-400 font-bold">
              {human?.name}: {(isReplaying && human ? (displayedChips.get(human.name) ?? human.chips) : human?.chips ?? 0).toLocaleString()} 칩
            </span>
            {isReplaying && (
              <button
                onClick={skip}
                className="text-xs text-gray-400 hover:text-white border border-gray-600 rounded px-2 py-0.5"
              >
                스킵 ⏩
              </button>
            )}
            <button
              onClick={handleNewGame}
              className="text-xs text-gray-500 hover:text-gray-300"
            >
              새 게임
            </button>
          </div>
        </div>

        {/* 테이블 */}
        <div className="flex-1 flex items-center justify-center p-4 relative">
          <div className="w-full max-w-3xl relative">
            <PokerTable
              state={state}
              activePlayer={activePlayer}
              isThinking={isThinking}
              badge={badge}
              visibleCardCount={visibleCardCount}
              foldedDuringReplay={foldedDuringReplay}
              bettingPlayer={bettingPlayer}
              isReplaying={isReplaying}
              dealtCards={dealtCards}
              myCardsRevealed={myCardsRevealed}
              onRevealCards={() => setMyCardsRevealed((v) => !v)}
              showdownRevealed={showdownRevealed}
              displayedChips={displayedChips}
              committedActions={committedActions}
            />
            {state.hand_over && !isReplaying && (
              <HandResult
                state={state}
                onNextHand={handleNextHand}
                onNewGame={handleNewGame}
              />
            )}
          </div>
        </div>

        {/* 액션 바 — 항상 표시, 내 차례 아닐 때 disabled */}
        {!state.game_over && (
          <div className="shrink-0">
            <ActionBar
              state={state}
              onAction={handleAction}
              loading={loading}
              disabled={actionDisabled || !state.waiting_for_action || state.hand_over}
            />
          </div>
        )}

        {/* 에러 */}
        {error && (
          <div className="shrink-0 bg-red-900/80 text-red-300 text-sm text-center py-2 px-4">
            {error}
          </div>
        )}
      </div>

      {/* 사이드패널 — 로그 / GTO 탭 */}
      <div className="lg:w-72 shrink-0 flex flex-col border-t lg:border-t-0 lg:border-l border-gray-800">
        {/* 탭 헤더 */}
        <div className="flex border-b border-gray-700 shrink-0">
          {(["log", "gto"] as const).map(t => (
            <button
              key={t}
              onClick={() => setRightTab(t)}
              className={`flex-1 py-2 text-xs font-medium transition-colors ${
                rightTab === t
                  ? "text-white border-b-2 border-green-500 bg-gray-900"
                  : "text-gray-500 hover:text-gray-300"
              }`}
            >
              {t === "log" ? "📋 로그" : "📊 GTO"}
              {t === "gto" && state.gto_key && (
                <span className="ml-1 text-[10px]">
                  {gtoRange?.found ? "🟢" : "🔴"}
                </span>
              )}
            </button>
          ))}
        </div>
        {/* 탭 컨텐츠 */}
        <div className="flex-1 overflow-hidden">
          {rightTab === "log" ? (
            <div className="p-3 h-full">
              <ActionLog
                log={isReplaying
                  ? state.action_log.slice(0, visibleLogCount)
                  : state.action_log}
              />
            </div>
          ) : (
            <GtoPanel
              gtoKey={state.gto_key}
              gtoRange={gtoRange}
              myHand={toGtoHand(
                state.players.find(p => p.is_human)?.hole_cards ?? null
              )}
              isLoading={gtoLoading}
            />
          )}
        </div>
      </div>
    </div>
  );
}
