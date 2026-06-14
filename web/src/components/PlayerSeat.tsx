import type { PlayerState } from "../types";
import CardView, { CardBack } from "./CardView";

interface Props {
  player: PlayerState;
  isActive: boolean;   // 현재 액션 차례
  isWinner: boolean;
}

export default function PlayerSeat({ player, isActive, isWinner }: Props) {
  const ringClass = isWinner
    ? "ring-4 ring-yellow-400"
    : isActive
    ? "ring-4 ring-green-400 animate-pulse"
    : "";

  const bgClass = player.is_human
    ? "bg-blue-900 border-blue-700"
    : "bg-gray-800 border-gray-600";

  const opacity = player.is_folded ? "opacity-40" : "";

  return (
    <div className={`relative flex flex-col items-center gap-1 ${opacity}`}>
      {/* 카드 */}
      <div className="flex gap-1 mb-1">
        {player.hole_cards ? (
          player.hole_cards.map((c, i) => (
            <CardView key={i} card={c} size="sm" />
          ))
        ) : (
          <>
            <CardBack size="sm" />
            <CardBack size="sm" />
          </>
        )}
      </div>

      {/* 플레이어 정보 */}
      <div className={`${bgClass} ${ringClass} border rounded-xl px-3 py-1.5 text-center min-w-[90px] shadow-lg`}>
        <div className="text-white text-xs font-semibold truncate max-w-[80px]">
          {player.name.replace("🤖 ", "")}
        </div>
        <div className="text-yellow-400 text-xs font-bold">{player.chips.toLocaleString()}</div>
        {player.position && (
          <span className="text-[10px] bg-gray-700 text-gray-300 rounded px-1">{player.position}</span>
        )}
      </div>

      {/* 현재 베팅 */}
      {player.current_bet > 0 && (
        <div className="text-yellow-300 text-xs font-bold bg-black/50 rounded px-1.5 py-0.5">
          {player.current_bet}
        </div>
      )}

      {/* 상태 배지 */}
      {player.is_folded && (
        <span className="text-[10px] text-red-400 font-bold">FOLD</span>
      )}
      {player.is_all_in && (
        <span className="text-[10px] text-orange-400 font-bold">ALL IN</span>
      )}
      {isWinner && (
        <span className="text-[10px] text-yellow-400 font-bold">🏆 WIN</span>
      )}
    </div>
  );
}
