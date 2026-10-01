import { useState } from "react";
import type { EquityInfo } from "../types";
import { equityView, EQUITY_VS_GTO_TOOLTIP } from "./equityPanelLogic";
import { pct, displayName } from "../format";

interface Props {
  equity: EquityInfo | null;
  callAmount: number;
  isMyTurn: boolean;
}

const ROLE_LABELS: Record<string, string> = {
  raiser: "레이저",
  caller: "콜러",
  unknown: "랜덤",
};

const ROLE_COLORS: Record<string, string> = {
  raiser: "bg-red-900/60 text-red-300",
  caller: "bg-green-900/60 text-green-300",
  unknown: "bg-gray-700 text-gray-300",
};

export default function EquityPanel({ equity, callAmount, isMyTurn }: Props) {
  // 내 턴 아닐 때는 마지막 값 유지 (equity가 null이면 이전 값 재사용).
  // ref를 렌더 중 읽고/쓰는 대신, "직전 렌더에서 본 값"을 state로 들고 렌더 중
  // 비교해 필요할 때만 갱신한다(React 공식 패턴 — 최대 1회 추가 렌더로 수렴, 무한 루프 없음).
  const [lastEquity, setLastEquity] = useState<EquityInfo | null>(equity);
  if (equity && equity !== lastEquity) {
    setLastEquity(equity);
  }
  const display = equity ?? lastEquity;

  if (!display) {
    return (
      <div className="py-2 text-gray-600 text-xs text-center">
        내 차례가 되면 에퀴티가 표시됩니다
      </div>
    );
  }

  const stale = !isMyTurn || !equity;
  // 패널의 모든 숫자는 vs_range 한 기준(게이지·팟오즈 색·콜 EV·추이)
  const view = equityView(display);
  const fillPct = Math.max(0, Math.min(100, view.headline * 100));
  const oddsPct = Math.max(0, Math.min(100, display.pot_odds * 100));
  const callGood = view.callGood;

  const sortedOpponents = [...display.opponents].sort((a, b) => {
    const ae = a.equity ?? 1;
    const be = b.equity ?? 1;
    return ae - be; // 낮은(위협) 순
  });

  return (
    <div className={`space-y-2 transition-opacity ${stale ? "opacity-50" : ""}`}>
      {/* 게이지 */}
      <div>
        <div className="flex items-baseline justify-between mb-1">
          <span className="text-xs text-gray-400">
            {view.label}
            <span className="ml-1 cursor-help text-gray-500" title={EQUITY_VS_GTO_TOOLTIP}>ⓘ</span>
          </span>
          <span className="text-2xl font-bold text-green-400">{pct(view.headline)}</span>
        </div>
        <div className="relative w-full bg-gray-700 rounded-full h-3">
          <div
            className="h-3 rounded-full bg-green-500"
            style={{ width: `${fillPct}%` }}
          />
          {display.pot_odds > 0 && (
            <div
              className="absolute top-[-2px] w-0.5 h-[16px] bg-yellow-400"
              style={{ left: `${oddsPct}%` }}
              title={`팟 오즈 ${pct(display.pot_odds)}`}
            />
          )}
        </div>
        {display.pot_odds > 0 && (
          <div className="flex justify-between text-[10px] text-gray-500 mt-0.5">
            <span>0%</span>
            <span className={callGood ? "text-green-400" : "text-red-400"}>
              팟오즈 {pct(display.pot_odds)}
            </span>
            <span>100%</span>
          </div>
        )}
      </div>

      {/* 콜 EV */}
      {display.call_ev_bb !== null && callAmount > 0 && (
        <div className="flex items-center justify-between bg-gray-800/50 rounded-lg px-2 py-1.5 text-xs">
          <span className="text-gray-400">콜 EV</span>
          <span className={`font-bold ${display.call_ev_bb >= 0 ? "text-green-400" : "text-red-400"}`}>
            {display.call_ev_bb >= 0 ? "+" : ""}
            {display.call_ev_bb.toFixed(1)}bb
          </span>
        </div>
      )}

      {/* 자세히(접힘): 상대별 1:1 · 스트리트 추이 · 출처 */}
      <details>
        <summary className="text-xs text-gray-500 cursor-pointer select-none">에퀴티 자세히 (상대별 1:1)</summary>
        <div className="mt-1 space-y-2">
          <div className="space-y-0.5">
            {sortedOpponents.map((op) => (
              <div key={op.name} className="flex items-center justify-between px-1 py-0.5 text-xs">
                <div className="flex items-center gap-1.5 min-w-0">
                  <span className="text-gray-300 truncate">{displayName(op.name)}</span>
                  <span className="text-gray-500">{op.position}</span>
                  <span className={`px-1 rounded text-[10px] shrink-0 ${ROLE_COLORS[op.role]}`}>
                    {ROLE_LABELS[op.role]}
                  </span>
                </div>
                <span className="text-gray-300 shrink-0">
                  {op.equity !== null ? pct(op.equity) : "—"}
                </span>
              </div>
            ))}
          </div>
          {view.history.length > 0 && (
            <div className="text-[10px] text-gray-500">
              {view.history.map((h, i) => (
                <span key={h.street}>
                  {i > 0 && " → "}
                  {h.street} {pct(h.value)}
                </span>
              ))}
            </div>
          )}
          <div className="text-[10px] text-gray-600">{view.meta}</div>
        </div>
      </details>
    </div>
  );
}
