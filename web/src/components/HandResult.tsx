import type { GameState } from "../types";

interface Props {
  state: GameState;
  onNextHand: () => void;
  onNewGame: () => void;
}

export default function HandResult({ state, onNextHand, onNewGame }: Props) {
  const { winners, showdown_hands, game_over, players, hand_number } = state;
  const human = players.find((p) => p.is_human);
  const humanWon = human ? winners.includes(human.name) : false;

  return (
    <div className="absolute inset-0 bg-black/70 flex items-center justify-center z-20 rounded-xl">
      <div className="bg-gray-800 border border-gray-600 rounded-2xl p-6 max-w-sm w-full mx-4 text-center shadow-2xl">
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
              🏆 {winners.join(", ")} 승리
            </p>

            {Object.keys(showdown_hands).length > 0 && (
              <div className="bg-gray-900 rounded-lg p-3 mb-4 text-left space-y-1">
                {Object.entries(showdown_hands).map(([name, hand]) => (
                  <div key={name} className="flex justify-between text-xs">
                    <span className={`font-medium ${winners.includes(name) ? "text-yellow-400" : "text-gray-300"}`}>
                      {name.replace("🤖 ", "")}
                    </span>
                    <span className="text-gray-400">{hand}</span>
                  </div>
                ))}
              </div>
            )}

            <div className="text-gray-400 text-sm mb-4">
              내 칩: <span className="text-white font-bold">{human?.chips.toLocaleString()}</span>
            </div>

            <button
              onClick={onNextHand}
              className="w-full py-3 bg-green-600 hover:bg-green-500 text-white font-bold rounded-xl"
            >
              다음 핸드 →
            </button>
          </>
        )}
      </div>
    </div>
  );
}
