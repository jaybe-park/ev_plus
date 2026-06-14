import type { PlayerState, ActionBadge } from "../types";
import CardView, { CardBack } from "./CardView";

interface Props {
  player: PlayerState;
  isWinner: boolean;
  isActive: boolean;
  isThinking: boolean;
  badge: ActionBadge | null;
  isFolded: boolean;
  isBetting: boolean;
  cardsDealt: number;        // 0~2: 받은 카드 수
  myCardsRevealed: boolean;  // 내 카드 공개 여부 (human만)
  onRevealCards?: () => void;
}

const BADGE_STYLES: Record<ActionBadge["variant"], string> = {
  blind:  "bg-yellow-500 text-black",
  fold:   "bg-red-600 text-white",
  check:  "bg-gray-500 text-white",
  call:   "bg-blue-600 text-white",
  raise:  "bg-orange-500 text-white",
  allin:  "bg-purple-600 text-white",
};

function Slot({ id }: { id: string }) {
  return <div key={id} className="w-8 h-11 rounded-md border border-dashed border-gray-600/40" />;
}

export default function PlayerSeat({
  player, isWinner, isActive, isThinking, badge,
  isFolded, isBetting, cardsDealt, myCardsRevealed, onRevealCards,
}: Props) {
  const ringClass = isWinner
    ? "ring-4 ring-yellow-400"
    : isActive
    ? "ring-4 ring-white/70 shadow-[0_0_16px_rgba(255,255,255,0.25)]"
    : "";

  const bgClass = player.is_human
    ? "bg-blue-900 border-blue-700"
    : "bg-gray-800 border-gray-600";

  function renderCards() {
    const isRevealed = player.is_human && myCardsRevealed;
    const cards = player.hole_cards ?? [];

    // 카드 슬롯별 렌더링 함수 (index: 0 or 1)
    function renderSlot(index: number) {
      const hasCard = cardsDealt > index;

      if (!hasCard) return <Slot key={`slot-${index}`} id={`slot-${index}`} />;

      // 봇이거나 사람이 공개하지 않은 경우: 뒷면
      if (!isRevealed) {
        return (
          <div key={`back-${index}`} className="animate-card-reveal">
            <CardBack size="sm" />
          </div>
        );
      }

      // 사람 + 공개: 실제 카드 (reveal 상태가 바뀔 때 key가 달라져 재애니메이션)
      const card = cards[index];
      if (!card) return <Slot key={`slot-${index}`} id={`slot-${index}`} />;
      return (
        <div key={`face-${index}-${myCardsRevealed}`} className="animate-card-reveal">
          <CardView card={card} size="sm" />
        </div>
      );
    }

    // 쇼다운: 봇 카드 공개
    if (!player.is_human && player.hole_cards) {
      return (
        <>
          {player.hole_cards.map((c, i) => (
            <div key={`showdown-${i}`} className="animate-card-reveal">
              <CardView card={c} size="sm" />
            </div>
          ))}
        </>
      );
    }

    return <>{renderSlot(0)}{renderSlot(1)}</>;
  }

  return (
    <div className={`relative flex flex-col items-center gap-1 transition-opacity duration-300 ${isFolded ? "opacity-40" : ""}`}>

      {/* 액션 배지 */}
      {badge?.player === player.name && (
        <div className={`
          absolute -top-7 left-1/2 -translate-x-1/2
          px-2 py-0.5 rounded-full text-xs font-bold whitespace-nowrap z-10
          shadow-lg animate-bounce-in ${BADGE_STYLES[badge.variant]}
        `}>
          {badge.text}
        </div>
      )}

      {/* 생각 중 점 */}
      {isThinking && (
        <div className="absolute -top-5 left-1/2 -translate-x-1/2 flex gap-0.5 z-10">
          {[0, 1, 2].map((i) => (
            <span key={i} className="w-1.5 h-1.5 rounded-full bg-white/70 animate-pulse"
              style={{ animationDelay: `${i * 150}ms` }} />
          ))}
        </div>
      )}

      {/* 카드 + 공개 버튼 (human) */}
      <div className="flex flex-col items-center gap-0.5 mb-1">
        <div className="flex gap-1">
          {renderCards()}
        </div>

        {/* 공개/숨기기 버튼 — 카드 받았을 때만 표시 */}
        {player.is_human && cardsDealt > 0 && onRevealCards && (
          <button
            onClick={onRevealCards}
            className="flex items-center gap-1 text-[10px] text-gray-400 hover:text-white bg-black/40 hover:bg-black/60 rounded px-1.5 py-0.5 transition-colors"
          >
            {myCardsRevealed ? "🙈" : "👁"} {myCardsRevealed ? "숨기기" : "보기"}
          </button>
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
        <div className={`text-yellow-300 text-xs font-bold bg-black/50 rounded px-1.5 py-0.5 ${isBetting ? "animate-bet-pop" : ""}`}>
          {player.current_bet}
        </div>
      )}

      {/* 상태 */}
      {isFolded     && <span className="text-[10px] text-red-400 font-bold">FOLD</span>}
      {player.is_all_in && <span className="text-[10px] text-orange-400 font-bold">ALL IN</span>}
      {isWinner     && <span className="text-[10px] text-yellow-400 font-bold">🏆 WIN</span>}
    </div>
  );
}
