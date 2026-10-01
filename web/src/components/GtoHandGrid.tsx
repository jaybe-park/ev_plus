import { useState } from "react";
import { ACTION_COLORS, ACTION_LABELS, ACTION_ORDER, NO_DATA_COLOR, cellBackground } from "./gtoPanelLogic";
import { pct } from "../format";

interface Props {
  hands: Record<string, Record<string, number>>;
  myHand: string | null;
}

const RANKS = ["A", "K", "Q", "J", "T", "9", "8", "7", "6", "5", "4", "3", "2"];

// 그리드 (row r, col c) → 핸드 표기
function cellHand(r: number, c: number): string {
  if (r === c) return RANKS[r] + RANKS[r];               // 페어
  if (r < c)  return RANKS[r] + RANKS[c] + "s";          // suited (상단)
  return RANKS[c] + RANKS[r] + "o";                       // offsuit (하단)
}

export default function GtoHandGrid({ hands, myHand }: Props) {
  const [hovered, setHovered] = useState<string | null>(null);

  const tooltipHand = hovered ?? myHand;
  const tooltipFreqs = tooltipHand ? hands[tooltipHand] : null;

  return (
    <div className="flex flex-col gap-1 text-[8px] select-none">
      {/* 컬럼 헤더 */}
      <div className="flex gap-px ml-4">
        {RANKS.map(r => (
          <div key={r} className="w-5 h-3 flex items-center justify-center text-gray-500 font-mono">{r}</div>
        ))}
      </div>

      {/* 그리드 */}
      {RANKS.map((rowRank, r) => (
        <div key={r} className="flex items-center gap-px">
          {/* 로우 헤더 */}
          <div className="w-3 h-5 flex items-center justify-center text-gray-500 font-mono">{rowRank}</div>
          {RANKS.map((_, c) => {
            const hand = cellHand(r, c);
            const freqs = hands[hand];
            const isMyHand = hand === myHand;
            const isHovered = hand === hovered;
            return (
              <div
                key={c}
                className={`w-5 h-5 rounded-sm cursor-pointer transition-all duration-100 relative
                  ${isMyHand ? "ring-2 ring-white ring-offset-1 ring-offset-gray-900 z-10" : ""}
                  ${isHovered ? "opacity-80 scale-110 z-20" : ""}
                `}
                style={{ background: cellBackground(freqs) }}
                onMouseEnter={() => setHovered(hand)}
                onMouseLeave={() => setHovered(null)}
              >
                {isMyHand && (
                  <div className="absolute inset-0 flex items-center justify-center">
                    <div className="w-1 h-1 rounded-full bg-white opacity-70" />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ))}

      {/* 툴팁 */}
      {tooltipHand && tooltipFreqs && (
        <div className="mt-1 p-2 bg-gray-800 rounded-lg border border-gray-600 text-xs">
          <div className="font-bold text-white mb-1">{tooltipHand}</div>
          {ACTION_ORDER.map(action => {
            const freq = tooltipFreqs[action];
            if (!freq || freq < 0.001) return null;
            return (
              <div key={action} className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-sm flex-shrink-0" style={{ backgroundColor: ACTION_COLORS[action] }} />
                <span className="text-gray-300 w-10">{ACTION_LABELS[action]}</span>
                <div className="flex-1 bg-gray-700 rounded-full h-1.5">
                  <div
                    className="h-1.5 rounded-full"
                    style={{ width: `${freq * 100}%`, backgroundColor: ACTION_COLORS[action] }}
                  />
                </div>
                <span className="text-white w-10 text-right">{pct(freq, 1)}</span>
              </div>
            );
          })}
        </div>
      )}

      {/* 범례 */}
      <div className="flex gap-2 mt-1">
        {ACTION_ORDER.map(a => (
          <div key={a} className="flex items-center gap-1">
            <div className="w-2 h-2 rounded-sm" style={{ backgroundColor: ACTION_COLORS[a] }} />
            <span className="text-gray-500 text-[9px]">{ACTION_LABELS[a]}</span>
          </div>
        ))}
        <div className="flex items-center gap-1">
          <div className="w-2 h-2 rounded-sm" style={{ backgroundColor: NO_DATA_COLOR }} />
          <span className="text-gray-500 text-[9px]">데이터 없음</span>
        </div>
      </div>
    </div>
  );
}
