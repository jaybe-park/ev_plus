import { useState, useEffect } from "react";
import type { GameState } from "../types";

interface Props {
  state: GameState;
  onAction: (action: string, amount?: number) => void;
  loading: boolean;
  disabled: boolean;
}

export default function ActionBar({ state, onAction, loading, disabled }: Props) {
  const { call_amount, min_raise_to, players, big_blind, pot, current_bet } = state;
  const human = players.find((p) => p.is_human);
  if (!human) return null;

  const maxRaise = human.chips + human.current_bet;
  const [raiseAmount, setRaiseAmount] = useState<number>(min_raise_to || big_blind * 2);

  // 내 차례가 될 때 슬라이더 초기화
  useEffect(() => {
    if (!disabled && min_raise_to > 0) setRaiseAmount(min_raise_to);
  }, [disabled, min_raise_to]);

  const isDisabled = disabled || loading;
  const canCheck = call_amount === 0;
  const canRaise = human.chips > call_amount && min_raise_to > 0 && maxRaise >= min_raise_to;

  const clampRaise = (v: number) => Math.max(min_raise_to, Math.min(v, maxRaise));

  // 팟 기준 프리셋
  const potPresets = [
    { label: "1/3", value: Math.round(pot / 3) + call_amount },
    { label: "1/2", value: Math.round(pot / 2) + call_amount },
    { label: "3/4", value: Math.round((pot * 3) / 4) + call_amount },
    { label: "팟", value: pot + call_amount },
  ];

  // 상대 베팅 기준 프리셋
  const betPresets = [
    { label: "2x",   value: Math.round(current_bet * 2) },
    { label: "2.5x", value: Math.round(current_bet * 2.5) },
    { label: "3x",   value: Math.round(current_bet * 3) },
    { label: "4x",   value: Math.round(current_bet * 4) },
  ];

  // 슬라이더 dead zone 퍼센트
  const deadPct   = maxRaise > 0 ? (min_raise_to / maxRaise) * 100 : 0;
  const activePct = maxRaise > 0 ? (raiseAmount / maxRaise) * 100 : deadPct;

  return (
    <div className={`bg-gray-900/95 border-t border-gray-700 p-3 space-y-2.5 transition-opacity duration-200 ${isDisabled ? "opacity-40 pointer-events-none" : ""}`}>

      {/* ── Row 1: 슬라이더 | 팟 기준 | 베팅 배율 ── */}
      <div className="flex gap-3 items-stretch">

        {/* 슬라이더 섹션 */}
        <div className="flex-1 flex flex-col gap-1.5 min-w-0">
          {/* 금액 표시 */}
          <div className="flex justify-between items-baseline text-xs">
            <span className="text-gray-400">레이즈</span>
            <span>
              <span className="text-white font-bold text-sm">{canRaise ? raiseAmount : "—"}</span>
              {canRaise && big_blind > 0 && (
                <span className="text-gray-500 ml-1.5">({(raiseAmount / big_blind).toFixed(1)}BB)</span>
              )}
            </span>
          </div>

          {/* 커스텀 슬라이더 */}
          <div className="relative h-7 flex items-center">
            {/* 트랙 */}
            <div className="absolute left-0 right-0 h-2 rounded-full pointer-events-none">
              {/* Dead zone */}
              <div
                className="absolute top-0 left-0 h-full rounded-l-full bg-gray-600/60"
                style={{ width: `${deadPct}%` }}
              />
              {/* Dead zone 경계선 */}
              {deadPct > 0 && deadPct < 100 && (
                <div
                  className="absolute top-0 h-full w-0.5 bg-yellow-400/80"
                  style={{ left: `${deadPct}%` }}
                />
              )}
              {/* Active filled */}
              <div
                className="absolute top-0 h-full bg-orange-500"
                style={{ left: `${deadPct}%`, width: `${Math.max(0, activePct - deadPct)}%` }}
              />
              {/* Active unfilled */}
              <div
                className="absolute top-0 h-full rounded-r-full bg-gray-700"
                style={{ left: `${activePct}%`, right: 0 }}
              />
            </div>

            {/* 커스텀 thumb */}
            <div
              className="absolute w-4 h-4 rounded-full bg-orange-500 border-2 border-white shadow-lg pointer-events-none z-10"
              style={{ left: `calc(${activePct}% - 8px)` }}
            />

            {/* 실제 range input (투명) */}
            <input
              type="range"
              min={0}
              max={maxRaise}
              value={raiseAmount}
              step={1}
              disabled={!canRaise || isDisabled}
              onChange={(e) => {
                const v = Number(e.target.value);
                setRaiseAmount(v < min_raise_to ? min_raise_to : v);
              }}
              className="absolute left-0 right-0 w-full h-full opacity-0 cursor-pointer z-20"
            />
          </div>
        </div>

        {/* 팟 기준 프리셋 */}
        <div className="flex flex-col gap-1 shrink-0">
          <span className="text-[10px] text-gray-500 text-center">팟 기준</span>
          <div className="grid grid-cols-2 gap-1">
            {potPresets.map((p) => {
              const val = clampRaise(p.value);
              const tooSmall = p.value < min_raise_to;
              const tooBig = p.value > maxRaise;
              const off = !canRaise || tooSmall || tooBig;
              return (
                <button
                  key={p.label}
                  disabled={isDisabled || off}
                  onClick={() => setRaiseAmount(val)}
                  className="px-2 py-1.5 text-xs bg-gray-700 hover:bg-gray-600 disabled:opacity-30 disabled:cursor-not-allowed text-gray-300 rounded leading-tight text-center"
                >
                  <div>{p.label}</div>
                  <div className="text-yellow-400">{off ? "—" : p.value}</div>
                </button>
              );
            })}
          </div>
        </div>

        {/* 베팅 배율 프리셋 */}
        <div className="flex flex-col gap-1 shrink-0">
          <span className="text-[10px] text-gray-500 text-center">배율</span>
          <div className="grid grid-cols-2 gap-1">
            {betPresets.map((p) => {
              const val = clampRaise(p.value);
              const tooSmall = p.value < min_raise_to;
              const tooBig = p.value > maxRaise;
              const off = !canRaise || tooSmall || tooBig;
              return (
                <button
                  key={p.label}
                  disabled={isDisabled || off}
                  onClick={() => setRaiseAmount(val)}
                  className="px-2 py-1.5 text-xs bg-gray-700 hover:bg-gray-600 disabled:opacity-30 disabled:cursor-not-allowed text-gray-300 rounded leading-tight text-center"
                >
                  <div>{p.label}</div>
                  <div className="text-yellow-400">{off ? "—" : p.value}</div>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* ── Row 2: 액션 버튼 ── */}
      <div className="flex gap-2">
        {/* 폴드 */}
        <button
          disabled={isDisabled || canCheck}
          onClick={() => onAction("fold")}
          className="flex-1 py-3 bg-red-700 hover:bg-red-600 disabled:opacity-30 disabled:cursor-not-allowed text-white font-bold rounded-xl transition-colors"
        >
          폴드
        </button>

        {/* 체크 / 콜 */}
        <button
          disabled={isDisabled}
          onClick={() => onAction(canCheck ? "check" : "call")}
          className="flex-1 py-3 bg-blue-700 hover:bg-blue-600 disabled:cursor-not-allowed text-white font-bold rounded-xl transition-colors"
        >
          {canCheck ? "체크" : `콜 ${call_amount}`}
        </button>

        {/* 레이즈 */}
        <button
          disabled={isDisabled || !canRaise}
          onClick={() => onAction("raise", clampRaise(raiseAmount))}
          className="flex-1 py-3 bg-orange-600 hover:bg-orange-500 disabled:opacity-30 disabled:cursor-not-allowed text-white font-bold rounded-xl transition-colors"
        >
          {!isDisabled && canRaise ? `레이즈 → ${raiseAmount}` : "레이즈"}
        </button>

        {/* 올인 */}
        <button
          disabled={isDisabled}
          onClick={() => onAction("allin")}
          className="flex-1 py-3 bg-purple-700 hover:bg-purple-600 disabled:cursor-not-allowed text-white font-bold rounded-xl transition-colors text-sm"
        >
          올인
          <div className="text-xs text-purple-300">{human.chips}</div>
        </button>
      </div>
    </div>
  );
}
