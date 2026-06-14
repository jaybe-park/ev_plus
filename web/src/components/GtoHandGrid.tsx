import { useState } from "react";

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

// 액션 색상
const ACTION_COLORS: Record<string, string> = {
  allin: "#991b1b",
  raise: "#ef4444",
  call:  "#22c55e",
  fold:  "#3b82f6",
};
const ACTION_ORDER = ["allin", "raise", "call", "fold"];

function cellStyle(freqs: Record<string, number> | undefined): React.CSSProperties {
  if (!freqs) return { backgroundColor: "#3b82f6" };

  const parts = ACTION_ORDER
    .map(a => ({ action: a, freq: freqs[a] ?? 0 }))
    .filter(p => p.freq > 0.001);

  if (parts.length === 0) return { backgroundColor: "#3b82f6" };
  if (parts.length === 1) return { backgroundColor: ACTION_COLORS[parts[0].action] };

  // 그라디언트 빌드
  let stops = "";
  let cum = 0;
  for (const p of parts) {
    const from = Math.round(cum * 100);
    const to   = Math.round((cum + p.freq) * 100);
    const col  = ACTION_COLORS[p.action];
    stops += `, ${col} ${from}%, ${col} ${to}%`;
    cum += p.freq;
  }
  return { backgroundImage: `linear-gradient(to right${stops})` };
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
                  ${!freqs ? "opacity-30" : ""}
                `}
                style={cellStyle(freqs)}
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
                <span className="text-gray-300 capitalize w-10">{action}</span>
                <div className="flex-1 bg-gray-700 rounded-full h-1.5">
                  <div
                    className="h-1.5 rounded-full"
                    style={{ width: `${freq * 100}%`, backgroundColor: ACTION_COLORS[action] }}
                  />
                </div>
                <span className="text-white w-10 text-right">{(freq * 100).toFixed(1)}%</span>
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
            <span className="text-gray-500 capitalize text-[9px]">{a}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
