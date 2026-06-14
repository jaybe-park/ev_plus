import { useState, useCallback } from "react";
import type { GameState, SetupConfig } from "./types";
import { api } from "./api";
import SetupForm from "./components/SetupForm";
import PokerTable from "./components/PokerTable";
import ActionBar from "./components/ActionBar";
import ActionLog from "./components/ActionLog";
import HandResult from "./components/HandResult";

export default function App() {
  const [state, setState] = useState<GameState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async (fn: () => Promise<GameState>) => {
    setLoading(true);
    setError(null);
    try {
      const next = await fn();
      setState(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "오류가 발생했습니다.");
    } finally {
      setLoading(false);
    }
  }, []);

  const handleStart = (config: SetupConfig) =>
    run(() => api.startGame(config));

  const handleAction = (action: string, amount = 0) => {
    if (!state) return;
    run(() => api.submitAction(state.session_id, action, amount));
  };

  const handleNextHand = () => {
    if (!state) return;
    run(() => api.nextHand(state.session_id));
  };

  const handleNewGame = () => setState(null);

  if (!state) return <SetupForm onStart={handleStart} />;

  const human = state.players.find((p) => p.is_human);

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
            <PokerTable state={state} />
            {state.hand_over && (
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
            <ActionBar state={state} onAction={handleAction} loading={loading} />
          </div>
        )}

        {/* 에러 */}
        {error && (
          <div className="shrink-0 bg-red-900/80 text-red-300 text-sm text-center py-2 px-4">
            {error}
          </div>
        )}

        {/* 봇 처리 중 */}
        {loading && (
          <div className="shrink-0 text-center text-gray-500 text-xs py-1">
            처리 중...
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
