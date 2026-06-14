import { useState } from "react";
import type { GameState } from "../types";

interface Props {
  state: GameState;
  onAction: (action: string, amount?: number) => void;
  loading: boolean;
}

export default function ActionBar({ state, onAction, loading }: Props) {
  const [raiseAmount, setRaiseAmount] = useState<number>(state.min_raise_to);
  const { call_amount, min_raise_to, players, big_blind } = state;

  const human = players.find((p) => p.is_human);
  if (!human) return null;

  const canCheck = call_amount === 0;
  const maxRaise = human.chips + human.current_bet;

  const handleRaise = () => {
    const amt = Math.max(min_raise_to, Math.min(raiseAmount, maxRaise));
    onAction("raise", amt);
  };

  const presets = [
    { label: "Min", value: min_raise_to },
    { label: "½ Pot", value: Math.floor(state.pot / 2) + (state.current_bet - human.current_bet) },
    { label: "Pot", value: state.pot + (state.current_bet - human.current_bet) },
    { label: "2x", value: state.current_bet * 2 + call_amount },
  ].filter((p) => p.value <= maxRaise && p.value >= min_raise_to);

  return (
    <div className="bg-gray-900/95 border-t border-gray-700 p-4 space-y-3">
      {/* GTO 힌트 */}
      {state.gto_hint && (
        <div className="text-center text-sm text-emerald-400 bg-emerald-950/50 rounded-lg py-1.5 px-3">
          {state.gto_hint}
        </div>
      )}

      {/* 레이즈 컨트롤 */}
      {human.chips > call_amount && (
        <div className="flex items-center gap-2">
          <span className="text-gray-400 text-xs w-12 shrink-0">레이즈</span>
          <input
            type="range"
            min={min_raise_to}
            max={maxRaise}
            step={big_blind}
            value={raiseAmount}
            onChange={(e) => setRaiseAmount(Number(e.target.value))}
            className="flex-1 accent-orange-500"
          />
          <input
            type="number"
            min={min_raise_to}
            max={maxRaise}
            value={raiseAmount}
            onChange={(e) => setRaiseAmount(Number(e.target.value))}
            className="w-20 bg-gray-800 border border-gray-600 text-white text-sm rounded px-2 py-1 text-right"
          />
        </div>
      )}

      {/* 레이즈 프리셋 */}
      {human.chips > call_amount && presets.length > 0 && (
        <div className="flex gap-2">
          {presets.map((p) => (
            <button
              key={p.label}
              onClick={() => setRaiseAmount(p.value)}
              className="flex-1 text-xs py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded"
            >
              {p.label}
              <br />
              <span className="text-yellow-400">{p.value}</span>
            </button>
          ))}
        </div>
      )}

      {/* 메인 액션 버튼 */}
      <div className="flex gap-3">
        {!canCheck && (
          <button
            disabled={loading}
            onClick={() => onAction("fold")}
            className="flex-1 py-3 bg-red-700 hover:bg-red-600 disabled:opacity-50 text-white font-bold rounded-xl transition-colors"
          >
            폴드
          </button>
        )}

        <button
          disabled={loading}
          onClick={() => onAction(canCheck ? "check" : "call")}
          className="flex-2 flex-grow py-3 bg-blue-700 hover:bg-blue-600 disabled:opacity-50 text-white font-bold rounded-xl transition-colors"
        >
          {canCheck ? "체크" : `콜 ${call_amount}`}
        </button>

        {human.chips > call_amount && (
          <>
            <button
              disabled={loading}
              onClick={handleRaise}
              className="flex-2 flex-grow py-3 bg-orange-600 hover:bg-orange-500 disabled:opacity-50 text-white font-bold rounded-xl transition-colors"
            >
              레이즈 → {raiseAmount}
            </button>
            <button
              disabled={loading}
              onClick={() => onAction("allin")}
              className="flex-1 py-3 bg-purple-700 hover:bg-purple-600 disabled:opacity-50 text-white font-bold rounded-xl transition-colors text-sm"
            >
              올인
              <br />
              <span className="text-xs">{human.chips}</span>
            </button>
          </>
        )}
      </div>
    </div>
  );
}
