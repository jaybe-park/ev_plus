import { useEffect, useRef, useState } from "react";
import type { GameState } from "../types";
import { AUTO_NEXT_MS, autoNextLabel, createCountdown, type Countdown } from "../autoAdvance";
import { displayName } from "../format";
import { evLossText } from "../reviewLogic";
import { potLines, potLineText } from "./handResultLogic";

interface Props {
  state: GameState;
  onNextHand: () => void;
  onNewGame: () => void;
  loading: boolean;
  autoNext: boolean;   // 스킵 모드 자동 진행(파산·클리어 화면에선 App이 false로 준다)
}

export default function HandResult({ state, onNextHand, onNewGame, loading, autoNext }: Props) {
  // 자동 진행: 결과 창이 뜨면 AUTO_NEXT_MS 카운트다운 후 "다음 핸드". 마우스가 결과 창 위에 있으면 멈춘다.
  const [remaining, setRemaining] = useState(AUTO_NEXT_MS);
  const [hovered, setHovered] = useState(false);
  const countdown = useRef<Countdown | null>(null);
  const onNextRef = useRef(onNextHand);
  useEffect(() => { onNextRef.current = onNextHand; }, [onNextHand]);
  const active = autoNext && !state.game_over;
  useEffect(() => {
    if (!active) return;
    const c = createCountdown(AUTO_NEXT_MS, setRemaining, () => onNextRef.current());
    countdown.current = c;
    return () => { c.stop(); countdown.current = null; };
  }, [active]);
  useEffect(() => {
    if (hovered) countdown.current?.pause();
    else countdown.current?.resume();
  }, [hovered, active]);
  const { winners, showdown_hands, game_over, players, hand_number, hand_review, pots } = state;
  const human = players.find((p) => p.is_human);
  const humanWon = human ? winners.includes(human.name) : false;
  const lines = potLines(pots);

  return (
    <div className="absolute inset-0 bg-black/70 flex items-center justify-center z-20 rounded-xl">
      <div
        className="bg-gray-800 border border-gray-600 rounded-2xl p-6 max-w-sm w-full mx-4 text-center shadow-2xl"
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        {game_over ? (
          <>
            <div className="text-4xl mb-2">{humanWon ? "🏆" : "💸"}</div>
            <h2 className="text-2xl font-bold text-white mb-1">
              {humanWon ? "게임 클리어!" : "게임 오버"}
            </h2>
            <p className="text-gray-400 text-sm mb-4">
              {humanWon ? "모든 상대를 이겼습니다!" : "칩이 모두 소진되었습니다."}
            </p>
            <button
              onClick={onNewGame}
              className="w-full py-3 bg-green-600 hover:bg-green-500 text-white font-bold rounded-xl"
            >
              새 게임
            </button>
          </>
        ) : (
          <>
            <div className="text-3xl mb-2">{humanWon ? "🎉" : "😔"}</div>
            <h2 className="text-xl font-bold text-white mb-1">
              핸드 #{hand_number} 결과
            </h2>
            <p className="text-yellow-400 font-bold mb-3">
              🏆 {winners.map(displayName).join(", ")} 승리
            </p>

            {lines.length > 0 && (
              <div className="bg-gray-900 rounded-lg p-3 mb-4 text-left space-y-1">
                {lines.map((l, i) => (
                  <div key={i} className={`text-xs ${l.returned ? "text-gray-500" : "text-gray-300"}`}>
                    {potLineText(l)}
                  </div>
                ))}
              </div>
            )}

            {Object.keys(showdown_hands).length > 0 && (
              <div className="bg-gray-900 rounded-lg p-3 mb-4 text-left space-y-1">
                {Object.entries(showdown_hands).map(([name, hand]) => (
                  <div key={name} className="flex justify-between text-xs">
                    <span className={`font-medium ${winners.includes(name) ? "text-yellow-400" : "text-gray-300"}`}>
                      {displayName(name)}
                    </span>
                    <span className="text-gray-400">{hand}</span>
                  </div>
                ))}
              </div>
            )}

            <div className="text-gray-400 text-sm mb-4">
              내 칩: <span className="text-white font-bold">{human?.chips.toLocaleString()}</span>
            </div>

            {hand_review && hand_review.length > 0 && (
              <div className="bg-gray-900 rounded-lg p-3 mb-4 text-left space-y-1.5 max-h-48 overflow-y-auto">
                <div className="text-xs text-gray-500 mb-1">내 플레이</div>
                {hand_review.map((r, i) => {
                  const loss = evLossText(r.ev_loss_bb);
                  return (
                  <div key={i} className="text-xs">
                    <div className="flex items-center gap-1.5">
                      <span className="text-gray-500 w-10 shrink-0">{r.street}</span>
                      <span className="text-gray-300 shrink-0">{r.action}</span>
                      <span className="shrink-0">{r.grade}</span>
                      {loss && <span className="text-red-400 font-medium shrink-0">{loss}</span>}
                    </div>
                    <div className="text-gray-500 text-[10px] pl-[3.2rem]">{r.reason}</div>
                  </div>
                  );
                })}
              </div>
            )}

            <button
              onClick={onNextHand}
              disabled={loading}
              className="w-full py-3 bg-green-600 hover:bg-green-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-bold rounded-xl"
            >
              다음 핸드 →
            </button>
            {active && (
              <div className="mt-2 text-xs text-gray-400" aria-live="polite">
                ⏭ {autoNextLabel(remaining, hovered)}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
