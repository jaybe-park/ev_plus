import type { GameState, PlayerState } from "../types";
import PlayerSeat from "./PlayerSeat";
import CardView from "./CardView";

interface Props {
  state: GameState;
}

// 플레이어 좌석 위치 [left%, top%] — 인간은 항상 index 0 (하단 중앙)
const POSITIONS: Record<number, [number, number][]> = {
  2: [[50, 85], [50, 5]],
  3: [[50, 85], [10, 20], [88, 20]],
  4: [[50, 85], [5,  48], [50, 5],  [95, 48]],
  5: [[50, 85], [8,  65], [12, 12], [88, 12], [92, 65]],
  6: [[50, 85], [5,  60], [12, 10], [50, 2],  [88, 10], [95, 60]],
};

export default function PokerTable({ state }: Props) {
  const { players, community_cards, pot, street, winners, hand_over } = state;

  // human 먼저, 나머지는 순서대로
  const human = players.find((p) => p.is_human)!;
  const bots = players.filter((p) => !p.is_human);
  const ordered: PlayerState[] = [human, ...bots];

  const n = Math.min(ordered.length, 6) as 2 | 3 | 4 | 5 | 6;
  const positions = POSITIONS[n] ?? POSITIONS[6];

  // 현재 액션 플레이어 찾기
  const activePlayer = state.waiting_for_action && !hand_over
    ? ordered.find((p) => p.is_human && !p.is_folded && !p.is_all_in)
    : undefined;

  return (
    <div className="relative w-full" style={{ paddingTop: "62%" }}>
      {/* 테이블 펠트 */}
      <div className="absolute inset-[8%] rounded-[50%] bg-green-800 border-8 border-yellow-800/60 shadow-2xl" />
      <div className="absolute inset-[10%] rounded-[50%] border-2 border-green-700/40" />

      {/* 커뮤니티 카드 + 팟 */}
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 pointer-events-none">
        {/* 스트리트 & 팟 */}
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

        {/* 커뮤니티 카드 */}
        <div className="flex gap-1.5">
          {Array.from({ length: 5 }).map((_, i) => {
            const card = community_cards[i];
            return card ? (
              <CardView key={i} card={card} size="md" />
            ) : (
              <div
                key={i}
                className="w-10 h-14 rounded-md border-2 border-dashed border-green-600/40"
              />
            );
          })}
        </div>
      </div>

      {/* 플레이어 좌석 */}
      {ordered.slice(0, n).map((player, i) => {
        const [left, top] = positions[i];
        return (
          <div
            key={player.name}
            className="absolute"
            style={{
              left: `${left}%`,
              top: `${top}%`,
              transform: "translate(-50%, -50%)",
            }}
          >
            <PlayerSeat
              player={player}
              isActive={!!activePlayer && player.name === activePlayer.name}
              isWinner={hand_over && winners.includes(player.name)}
            />
          </div>
        );
      })}
    </div>
  );
}
