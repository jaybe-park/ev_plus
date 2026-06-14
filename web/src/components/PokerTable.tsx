import type { GameState, PlayerState, ActionBadge } from "../types";
import PlayerSeat from "./PlayerSeat";
import CardView from "./CardView";

interface Props {
  state: GameState;
  activePlayer: string | null;
  isThinking: boolean;
  badge: ActionBadge | null;
  visibleCardCount: number;
  foldedDuringReplay: Set<string>;
  bettingPlayer: string | null;
  isReplaying: boolean;
  dealtCards: Map<string, number>;
  myCardsRevealed: boolean;
  onRevealCards: () => void;
  showdownRevealed: boolean;
}

const POSITIONS: Record<number, [number, number][]> = {
  2: [[50, 85], [50, 5]],
  3: [[50, 85], [10, 20], [88, 20]],
  4: [[50, 85], [5,  48], [50, 5],  [95, 48]],
  5: [[50, 85], [8,  65], [12, 12], [88, 12], [92, 65]],
  6: [[50, 85], [5,  60], [12, 10], [50, 2],  [88, 10], [95, 60]],
};

export default function PokerTable({
  state, activePlayer, isThinking, badge, visibleCardCount,
  foldedDuringReplay, bettingPlayer, isReplaying,
  dealtCards, myCardsRevealed, onRevealCards, showdownRevealed,
}: Props) {
  const { players, community_cards, pot, street, winners, hand_over } = state;

  const human   = players.find((p) => p.is_human)!;
  const bots    = players.filter((p) => !p.is_human);
  const ordered: PlayerState[] = [human, ...bots];

  const n = Math.min(ordered.length, 6) as 2 | 3 | 4 | 5 | 6;
  const seatPositions = POSITIONS[n] ?? POSITIONS[6];
  const visibleCards  = community_cards.slice(0, visibleCardCount);

  const isFolded = (p: PlayerState) =>
    isReplaying ? foldedDuringReplay.has(p.name) : p.is_folded;

  // 재생 중이면 dealtCards 기준, 아니면 전부 2장 표시
  const getCardsDealt = (p: PlayerState) =>
    isReplaying ? (dealtCards.get(p.name) ?? 0) : 2;

  const bettingIdx = bettingPlayer
    ? ordered.findIndex((p) => p.name === bettingPlayer)
    : -1;

  return (
    <div className="relative w-full" style={{ paddingTop: "62%" }}>
      {/* 테이블 펠트 */}
      <div className="absolute inset-[8%] rounded-[50%] bg-green-800 border-8 border-yellow-800/60 shadow-2xl" />
      <div className="absolute inset-[10%] rounded-[50%] border-2 border-green-700/40" />

      {/* 커뮤니티 카드 + 팟 */}
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 pointer-events-none">
        <div className="flex flex-col items-center gap-1">
          <span className="text-green-300 text-xs font-medium bg-black/30 rounded px-2 py-0.5">
            {street}
          </span>
          {pot > 0 && (
            <span className="text-yellow-300 text-sm font-bold bg-black/40 rounded-full px-3 py-0.5">
              💰 {pot.toLocaleString()}
            </span>
          )}
        </div>
        <div className="flex gap-1.5">
          {Array.from({ length: 5 }).map((_, i) => {
            const card = visibleCards[i];
            return card ? (
              <div key={`${i}-${card}`} className="animate-card-reveal">
                <CardView card={card} size="md" />
              </div>
            ) : (
              <div key={i} className="w-10 h-14 rounded-md border-2 border-dashed border-green-600/40" />
            );
          })}
        </div>
      </div>

      {/* 베팅 칩 애니메이션 */}
      {bettingIdx >= 0 && bettingIdx < seatPositions.length && (() => {
        const [pLeft, pTop] = seatPositions[bettingIdx];
        const dx = (50 - pLeft) * 2.8;
        const dy = (50 - pTop) * 2.2;
        return (
          <div
            className="absolute text-lg pointer-events-none z-20 select-none"
            style={{
              left: `${pLeft}%`, top: `${pTop}%`,
              transform: "translate(-50%, -50%)",
              animation: "chip-fly-to-pot 0.55s ease-in forwards",
              ["--dx" as string]: `${dx}px`,
              ["--dy" as string]: `${dy}px`,
            }}
          >
            🪙
          </div>
        );
      })()}

      {/* 플레이어 좌석 */}
      {ordered.slice(0, n).map((player, i) => {
        const [left, top] = seatPositions[i];
        const isActive = activePlayer === player.name;
        return (
          <div
            key={player.name}
            className="absolute"
            style={{ left: `${left}%`, top: `${top}%`, transform: "translate(-50%, -50%)" }}
          >
            <PlayerSeat
              player={player}
              isWinner={hand_over && winners.includes(player.name)}
              isActive={isActive}
              isThinking={isThinking && isActive}
              badge={badge}
              isFolded={isFolded(player)}
              isBetting={bettingPlayer === player.name}
              cardsDealt={getCardsDealt(player)}
              myCardsRevealed={myCardsRevealed}
              onRevealCards={player.is_human ? onRevealCards : undefined}
              showdownRevealed={!isReplaying || showdownRevealed}
            />
          </div>
        );
      })}
    </div>
  );
}
