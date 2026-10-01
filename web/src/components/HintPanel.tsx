import type { EquityInfo, GtoNode } from "../types";
import GtoHandGrid from "./GtoHandGrid";
import EquityPanel from "./EquityPanel";
import { cellBackground, gtoPanelView, type GtoFetch } from "./gtoPanelLogic";
import { hintLayout, type FreqBar } from "./hintPanelLogic";
import { pct } from "../format";

interface Props {
  gto: GtoNode | null;          // advisor 추천(게임 상태) — 레인지는 이 node_key로 조회한 것
  fetch: GtoFetch;              // 그 노드의 레인지 조회 상태
  equity: EquityInfo | null;
  callAmount: number;
  isMyTurn: boolean;
}

function FreqBarRow({ bar }: { bar: FreqBar }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="text-gray-300 w-10 shrink-0">{bar.label}</span>
      <div className="flex-1 bg-gray-700 rounded-full h-1.5">
        <div className="h-1.5 rounded-full" style={{ width: `${bar.freq * 100}%`, backgroundColor: bar.color }} />
      </div>
      <span className="text-white font-bold w-12 text-right shrink-0">{bar.text}</span>
    </div>
  );
}

const TONE: Record<string, string> = {
  ok: "text-green-400", warn: "text-yellow-500", muted: "text-gray-400", error: "text-red-400",
};

// 힌트 탭: ① 상황 라벨 ② GTO 빈도 ③ 내 패 액션 % ④ 에퀴티 — 순서·문자열은 hintPanelLogic.hintLayout.
// 레인지 그리드·레이즈 비교·상대별 1:1 등은 접힌 "자세히" 안에 둔다(패널이 액션 버튼을 밀어내지 않게).
export default function HintPanel({ gto, fetch, equity, callAmount, isMyTurn }: Props) {
  const layout = hintLayout(gto, fetch);
  const view = gtoPanelView(gto, fetch);
  const range = view.kind === "range" ? view.range : null;
  const hand = gto?.hand ?? null;
  const myRaise = (gto?.frequencies ?? (hand ? range?.hands?.[hand] : null))?.raise;
  const rangeRaise = range?.summary?.raise;

  return (
    <div className="p-3 space-y-3">
      {layout.sections.map((s, i) => {
        switch (s.kind) {
          case "situation":
            return (
              <div key={i} className={`text-sm font-semibold truncate ${TONE[s.tone]}`} title={s.text}>
                {s.text}
              </div>
            );
          case "gtoFreq":
            return (
              <div key={i} className="space-y-1">
                <div className="text-[10px] text-gray-500">GTO 빈도(레인지 전체)</div>
                {s.bars.map((b) => <FreqBarRow key={b.action} bar={b} />)}
              </div>
            );
          case "myHand":
            return (
              <div key={i} className="bg-gray-800/60 rounded-lg p-2 flex items-center gap-2">
                <div className="w-6 h-6 rounded-sm shrink-0" style={{ background: cellBackground(s.freqs) }} />
                <div className="min-w-0">
                  <div className="text-xs text-white font-bold">내 패 {s.hand}</div>
                  <div className="text-xs text-gray-300">{s.text}</div>
                </div>
              </div>
            );
          case "gtoNote":
            return <div key={i} className={`text-xs ${TONE[s.tone]}`}>{s.text}</div>;
          case "equity":
            return (
              <div key={i} className="border-t border-gray-800 pt-2">
                <EquityPanel equity={equity} callAmount={callAmount} isMyTurn={isMyTurn} />
              </div>
            );
        }
        return null;
      })}

      {(layout.gridAvailable || view.kind === "missing") && (
        <details className="border-t border-gray-800 pt-2">
          <summary className="text-xs text-gray-500 cursor-pointer select-none">GTO 자세히 (레인지 그리드)</summary>
          <div className="mt-2 space-y-3">
            {range && (
              <>
                {hand && typeof myRaise === "number" && typeof rangeRaise === "number" && (
                  <div className="text-[10px] text-gray-400">
                    레이즈 비교 — 내 패 {pct(myRaise)} · 레인지 {pct(rangeRaise)}
                  </div>
                )}
                <GtoHandGrid hands={range.hands ?? {}} myHand={hand} />
              </>
            )}
            {view.kind === "missing" && (
              <a
                href="https://app.gtowizard.com/solutions"
                target="_blank"
                rel="noopener noreferrer"
                className="block w-full py-1.5 bg-green-700 hover:bg-green-600 text-white text-xs font-medium rounded-lg text-center"
              >
                GTO Wizard에서 수집 →
              </a>
            )}
          </div>
        </details>
      )}
    </div>
  );
}
