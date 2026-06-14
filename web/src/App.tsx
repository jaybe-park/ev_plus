import { useState, useCallback, useRef } from "react";
import type { GameState, SetupConfig } from "./types";
import { api } from "./api";
import { useEventQueue } from "./hooks/useEventQueue";
import SetupForm from "./components/SetupForm";
import PokerTable from "./components/PokerTable";
import ActionBar from "./components/ActionBar";
import ActionLog from "./components/ActionLog";
import HandResult from "./components/HandResult";

export default function App() {
  const [state, setState] = useState<GameState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const prevHandNumber = useRef<number>(0);

  const {
    isReplaying,
    activePlayer,
    isThinking,
    badge,
    visibleCardCount,
    enqueue,
    skip,
    setVisibleCardCount,
  } = useEventQueue();

  // 서버 응답을 받아 이벤트 큐를 세팅하는 공통 처리
  const applyNewState = useCallback(
    (next: GameState) => {
      const isNewHand = next.hand_number !== prevHandNumber.current;
      prevHandNumber.current = next.hand_number;

      // 새 핸드: 커뮤니티 카드 0부터 시작
      // 이어지는 액션: 이전 표시 카드 수부터 시작
      const initialCardCount = isNewHand ? 0 : (state?.community_cards.length ?? 0);

      setState(next);

      if (next.events.length > 0) {
        enqueue(next.events, initialCardCount);
      } else {
        // 이벤트 없으면 즉시 모든 카드 표시
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

  const handleStart    = (config: SetupConfig) => run(() => api.startGame(config));
  const handleAction   = (action: string, amount = 0) => {
    if (!state) return;
    run(() => api.submitAction(state.session_id, action, amount));
  };
  const handleNextHand = () => { if (!state) return; run(() => api.nextHand(state.session_id)); };
  const handleNewGame  = () => { skip(); setState(null); };

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
              {human?.name}: {human?.chips.toLocaleString()} 칩
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

        {/* 액션 바 */}
        {state.waiting_for_action && !state.hand_over && (
          <div className="shrink-0">
            <ActionBar
              state={state}
              onAction={handleAction}
              loading={actionDisabled}
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

      {/* 사이드패널 — 액션 로그 */}
      <div className="lg:w-64 shrink-0 p-4 border-t lg:border-t-0 lg:border-l border-gray-800">
        <ActionLog log={state.action_log} />
      </div>
    </div>
  );
}
