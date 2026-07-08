import { useRef } from "react";
import type { EquityInfo } from "../types";

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

function pct(v: number): string {
  return `${(v * 100).toFixed(0)}%`;
}

export default function EquityPanel({ equity, callAmount, isMyTurn }: Props) {
  // 내 턴 아닐 때는 마지막 값 유지 (equity가 null이면 이전 값 재사용)
  const lastRef = useRef<EquityInfo | null>(null);
  if (equity) lastRef.current = equity;
  const display = equity ?? lastRef.current;

  if (!display) {
    return (
      <div className="flex items-center justify-center h-24 text-gray-600 text-xs text-center px-4">
        내 차례가 되면 에퀴티가 표시됩니다
      </div>
    );
  }

  const stale = !isMyTurn || !equity;
  const fillPct = Math.max(0, Math.min(100, display.vs_random * 100));
  const oddsPct = Math.max(0, Math.min(100, display.pot_odds * 100));
  const callGood = fillPct >= oddsPct;

  const sortedOpponents = [...display.opponents].sort((a, b) => {
    const ae = a.equity ?? 1;
    const be = b.equity ?? 1;
    return ae - be; // 낮은(위협) 순
  });

  return (
    <div className={`p-3 space-y-3 transition-opacity ${stale ? "opacity-50" : ""}`}>
      {/* 게이지 */}
      <div>
        <div className="flex items-baseline justify-between mb-1">
          <span className="text-xs text-gray-400">내 에퀴티 (vs 랜덤)</span>
          <span className="text-2xl font-bold text-green-400">{pct(display.vs_random)}</span>
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

      {/* 상대별 브레이크다운 */}
      <div className="space-y-1">
        <div className="flex items-center justify-between bg-gray-800/70 rounded-lg px-2 py-1.5">
          <span className="text-xs text-gray-300">종합 (전체 상대)</span>
          <span className="text-sm font-bold text-white">{pct(display.vs_range)}</span>
        </div>
        {sortedOpponents.map((op) => (
          <div key={op.name} className="flex items-center justify-between px-2 py-1 text-xs">
            <div className="flex items-center gap-1.5 min-w-0">
              <span className="text-gray-300 truncate">{op.name.replace("🤖 ", "")}</span>
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

      {/* 스트리트 히스토리 */}
      {display.history.length > 0 && (
        <div className="text-[10px] text-gray-500">
          {display.history.map((h, i) => (
            <span key={h.street}>
              {i > 0 && " → "}
              {h.street} {pct(h.vs_random)}
            </span>
          ))}
        </div>
      )}

      {/* 메타 */}
      <div className="text-[10px] text-gray-600">
        {display.source} · 샘플 {display.samples.toLocaleString()} · 상대 {display.num_opponents}명
      </div>
    </div>
  );
}
