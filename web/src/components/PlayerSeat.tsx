import type { PlayerState, ActionBadge } from "../types";
import CardView, { CardBack } from "./CardView";

interface Props {
  player: PlayerState;
  isWinner: boolean;
  isActive: boolean;       // 이벤트 재생 중 현재 플레이어
  isThinking: boolean;     // 봇 생각 중 표시
  badge: ActionBadge | null;
}

const BADGE_STYLES: Record<ActionBadge["variant"], string> = {
  blind:  "bg-yellow-500 text-black",
  fold:   "bg-red-600 text-white",
  check:  "bg-gray-500 text-white",
  call:   "bg-blue-600 text-white",
  raise:  "bg-orange-500 text-white",
  allin:  "bg-purple-600 text-white",
};

export default function PlayerSeat({ player, isWinner, isActive, isThinking, badge }: Props) {
  const ringClass = isWinner
    ? "ring-4 ring-yellow-400"
    : isActive
    ? "ring-4 ring-white/70 shadow-[0_0_16px_rgba(255,255,255,0.3)]"
    : "";

  const bgClass = player.is_human
    ? "bg-blue-900 border-blue-700"
    : "bg-gray-800 border-gray-600";

  const opacity = player.is_folded ? "opacity-40" : "";

  return (
    <div className={`relative flex flex-col items-center gap-1 ${opacity}`}>
      {/* 배지 (액션 결과) */}
      {badge?.player === player.name && (
        <div
          className={`
            absolute -top-7 left-1/2 -translate-x-1/2
            px-2 py-0.5 rounded-full text-xs font-bold whitespace-nowrap z-10
            shadow-lg animate-bounce-in
            ${BADGE_STYLES[badge.variant]}
          `}
        >
          {badge.text}
        </div>
      )}

      {/* 생각 중 표시 */}
      {isThinking && isActive && player.name === player.name && (
        <div className="absolute -top-6 left-1/2 -translate-x-1/2 flex gap-0.5 z-10">
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              className="w-1.5 h-1.5 rounded-full bg-white/70 animate-pulse"
              style={{ animationDelay: `${i * 150}ms` }}
            />
          ))}
        </div>
      )}

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
      <div className={`${bgClass} ${ringClass} border rounded-xl px-3 py-1.5 text-center min-w-[90px] shadow-lg transition-all duration-200`}>
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
      {player.is_folded && <span className="text-[10px] text-red-400 font-bold">FOLD</span>}
      {player.is_all_in && <span className="text-[10px] text-orange-400 font-bold">ALL IN</span>}
      {isWinner && <span className="text-[10px] text-yellow-400 font-bold">🏆 WIN</span>}
    </div>
  );
}
