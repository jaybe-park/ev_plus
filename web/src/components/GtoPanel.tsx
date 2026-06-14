import { useState } from "react";
import type { GtoKey, GtoRange } from "../types";
import GtoHandGrid from "./GtoHandGrid";

interface Props {
  gtoKey: GtoKey | null;
  gtoRange: GtoRange | null;
  myHand: string | null;   // GTO 표기법 핸드 (e.g. "K7o")
  isLoading: boolean;
}

const ACTION_COLORS: Record<string, string> = {
  allin: "#991b1b",
  raise: "#ef4444",
  call:  "#22c55e",
  fold:  "#3b82f6",
};
const ACTION_ORDER = ["allin", "raise", "call", "fold"];
const ACTION_LABELS: Record<string, string> = {
  allin: "올인", raise: "레이즈", call: "콜", fold: "폴드",
};

function ActionBar({ label, freq, color }: { label: string; freq: number; color: string }) {
  return (
    <div className="space-y-0.5">
      <div className="flex justify-between text-xs">
        <span className="text-gray-300">{label}</span>
        <span className="text-white font-bold">{(freq * 100).toFixed(1)}%</span>
      </div>
      <div className="w-full bg-gray-700 rounded-full h-2">
        <div
          className="h-2 rounded-full transition-all duration-300"
          style={{ width: `${freq * 100}%`, backgroundColor: color }}
        />
      </div>
    </div>
  );
}

export default function GtoPanel({ gtoKey, gtoRange, myHand, isLoading }: Props) {
  const [tab, setTab] = useState<"overview" | "hands">("overview");

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-32 text-gray-500 text-sm">
        로딩 중...
      </div>
    );
  }

  if (!gtoKey) {
    return (
      <div className="flex items-center justify-center h-32 text-gray-600 text-sm text-center px-4">
        프리플랍 액션 시 GTO 정보가 표시됩니다
      </div>
    );
  }

  if (!gtoRange || !gtoRange.found) {
    return (
      <div className="p-3 space-y-3">
        <div className="text-center">
          <div className="text-yellow-500 text-sm font-medium mb-1">GTO 데이터 없음</div>
          <div className="text-gray-400 text-xs">
            {gtoKey.position}
            {gtoKey.vs_position ? ` vs ${gtoKey.vs_position}` : " RFI"}
            {" "}({gtoKey.range_type})
          </div>
        </div>
        <a
          href="https://app.gtowizard.com/solutions"
          target="_blank"
          rel="noopener noreferrer"
          className="block w-full py-2 bg-green-700 hover:bg-green-600 text-white text-xs font-medium rounded-lg text-center transition-colors"
        >
          GTO Wizard에서 수집 →
        </a>
      </div>
    );
  }

  const { situation, raise_size, summary = {}, hands = {} } = gtoRange;
  const myHandFreqs = myHand ? hands[myHand] : null;

  return (
    <div className="flex flex-col h-full">
      {/* 헤더 */}
      <div className="px-3 pt-2 pb-1 border-b border-gray-700">
        <div className="text-xs font-semibold text-green-400 truncate">
          {situation}
          {raise_size && <span className="text-gray-500 ml-1">({raise_size})</span>}
        </div>
      </div>

      {/* 서브탭 */}
      <div className="flex border-b border-gray-700 text-xs">
        {(["overview", "hands"] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex-1 py-1.5 font-medium transition-colors ${
              tab === t ? "text-white border-b-2 border-green-500" : "text-gray-500 hover:text-gray-300"
            }`}
          >
            {t === "overview" ? "개요" : "핸드"}
          </button>
        ))}
      </div>

      {/* 컨텐츠 */}
      <div className="flex-1 overflow-y-auto p-3">
        {tab === "overview" ? (
          <div className="space-y-4">
            {/* 내 패 */}
            {myHand && (
              <div>
                <div className="text-xs text-gray-400 mb-1.5">내 패 — {myHand}</div>
                {myHandFreqs ? (
                  <div className="space-y-1.5 bg-gray-800/50 rounded-lg p-2">
                    {ACTION_ORDER.map(action => {
                      const freq = myHandFreqs[action];
                      if (!freq || freq < 0.001) return null;
                      return (
                        <ActionBar
                          key={action}
                          label={ACTION_LABELS[action]}
                          freq={freq}
                          color={ACTION_COLORS[action]}
                        />
                      );
                    })}
                  </div>
                ) : (
                  <div className="text-xs text-gray-500">데이터 없음</div>
                )}
              </div>
            )}

            {/* 전체 레인지 */}
            <div>
              <div className="text-xs text-gray-400 mb-1.5">전체 레인지</div>
              <div className="space-y-1.5">
                {ACTION_ORDER.map(action => {
                  const freq = summary[action];
                  if (!freq || freq < 0.001) return null;
                  return (
                    <ActionBar
                      key={action}
                      label={ACTION_LABELS[action]}
                      freq={freq}
                      color={ACTION_COLORS[action]}
                    />
                  );
                })}
              </div>
            </div>

            {/* 내 패 vs 레인지 비교 */}
            {myHand && myHandFreqs && summary.raise !== undefined && (
              <div className="bg-gray-800/50 rounded-lg p-2 text-xs">
                <div className="text-gray-400 mb-1">레이즈 비교</div>
                <div className="flex items-center gap-2">
                  <span className="text-gray-300 w-14">내 패</span>
                  <div className="flex-1 bg-gray-700 rounded-full h-2">
                    <div className="h-2 rounded-full bg-red-500" style={{ width: `${(myHandFreqs.raise ?? 0) * 100}%` }} />
                  </div>
                  <span className="text-white w-10 text-right">{((myHandFreqs.raise ?? 0) * 100).toFixed(0)}%</span>
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-gray-300 w-14">레인지</span>
                  <div className="flex-1 bg-gray-700 rounded-full h-2">
                    <div className="h-2 rounded-full bg-red-800" style={{ width: `${(summary.raise ?? 0) * 100}%` }} />
                  </div>
                  <span className="text-white w-10 text-right">{((summary.raise ?? 0) * 100).toFixed(0)}%</span>
                </div>
                <div className="text-gray-500 mt-1.5 text-[10px]">
                  {(myHandFreqs.raise ?? 0) > (summary.raise ?? 0)
                    ? "↑ 레인지 평균보다 강한 패"
                    : (myHandFreqs.raise ?? 0) > 0
                    ? "↔ 경계선 패"
                    : "↓ 폴드 패"}
                </div>
              </div>
            )}
          </div>
        ) : (
          <GtoHandGrid hands={hands} myHand={myHand} />
        )}
      </div>
    </div>
  );
}
