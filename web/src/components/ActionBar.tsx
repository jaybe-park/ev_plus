import { useState } from "react";
import type { GameState } from "../types";
import { actionButtons, potPresets, betPresets, presetOff, type Preset } from "./actionBarLogic";

interface Props {
  state: GameState;
  onAction: (action: string, amount?: number) => void;
  loading: boolean;
  disabled: boolean;
}

export default function ActionBar({ state, onAction, loading, disabled }: Props) {
  const { min_raise_to, players, big_blind } = state;
  const human = players.find((p) => p.is_human);

  // 훅은 항상 같은 순서로 호출해야 하므로 (인간 부재 시) 조기 return보다 먼저 온다.
  const [raiseAmount, setRaiseAmount] = useState<number>(min_raise_to || big_blind * 2);

  // 내 차례가 될 때 슬라이더 초기화 — "disabled/min_raise_to가 바뀔 때"를 렌더 중
  // 직전 값과 비교해 판단한다(useEffect의 setState는 rules-of-hooks의 set-state-in-effect
  // 경고 대상이라 렌더 중 조정 패턴으로 대체 — 동작은 기존 useEffect와 동일).
  const turnKey = `${disabled}:${min_raise_to}`;
  const [prevTurnKey, setPrevTurnKey] = useState(turnKey);
  if (turnKey !== prevTurnKey) {
    setPrevTurnKey(turnKey);
    if (!disabled && min_raise_to > 0) setRaiseAmount(min_raise_to);
  }

  if (!human) return null;

  const isDisabled = disabled || loading;
  const canCheck = state.call_amount === 0;
  const buttons = actionButtons(state);
  const { canRaise, maxRaise } = buttons;

  const clampRaise = (v: number) => Math.max(min_raise_to, Math.min(v, maxRaise));

  const presetGroup = (title: string, presets: Preset[]) => (
    <div className="flex flex-col gap-1 shrink-0">
      <span className="text-[10px] text-gray-500 text-center">{title}</span>
      <div className="grid grid-cols-2 gap-1">
        {presets.map((p) => {
          const off = presetOff(p.value, buttons, min_raise_to);
          return (
            <button
              key={p.label}
              disabled={isDisabled || off}
              onClick={() => setRaiseAmount(clampRaise(p.value))}
              className="px-2 py-1.5 text-xs bg-gray-700 hover:bg-gray-600 disabled:opacity-30 disabled:cursor-not-allowed text-gray-300 rounded leading-tight text-center"
            >
              <div>{p.label}</div>
              <div className="text-yellow-400">{off ? "—" : p.value}</div>
            </button>
          );
        })}
      </div>
    </div>
  );

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

        {presetGroup("팟 기준", potPresets(state))}
        {presetGroup("배율", betPresets(state))}
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
          {buttons.callLabel}
        </button>

        {/* 레이즈 — 액션이 닫혔으면(can_raise=false) 숨김 */}
        {buttons.showRaise && (
        <button
          disabled={isDisabled || !canRaise}
          onClick={() => onAction("raise", clampRaise(raiseAmount))}
          className="flex-1 py-3 bg-orange-600 hover:bg-orange-500 disabled:opacity-30 disabled:cursor-not-allowed text-white font-bold rounded-xl transition-colors"
        >
          {!isDisabled && canRaise ? `레이즈 → ${raiseAmount}` : "레이즈"}
        </button>
        )}

        {/* 올인 — 액션이 닫혔으면 숨김(콜 금액 이하 올인은 콜 버튼) */}
        {buttons.showAllin && (
        <button
          disabled={isDisabled}
          onClick={() => onAction("allin")}
          className="flex-1 py-3 bg-purple-700 hover:bg-purple-600 disabled:cursor-not-allowed text-white font-bold rounded-xl transition-colors text-sm"
        >
          올인
          <div className="text-xs text-purple-300">{human.chips}</div>
        </button>
        )}
      </div>
    </div>
  );
}
