interface Props {
  card: string;     // e.g. "A♠", "K♥"
  size?: "sm" | "md" | "lg";
  faceDown?: boolean;
}

const RED_SUITS = ["♥", "♦"];

export default function CardView({ card, size = "md", faceDown = false }: Props) {
  const sizeClass = {
    sm: "w-8 h-11 text-xs",
    md: "w-10 h-14 text-sm",
    lg: "w-14 h-20 text-base",
  }[size];

  if (faceDown) {
    return (
      <div className={`${sizeClass} rounded-md bg-blue-800 border-2 border-blue-600 flex items-center justify-center shadow-md`}>
        <span className="text-blue-400 text-lg">🂠</span>
      </div>
    );
  }

  const suit = card.slice(-1);
  const rank = card.slice(0, -1);
  const isRed = RED_SUITS.includes(suit);

  return (
    <div className={`${sizeClass} rounded-md bg-white border border-gray-300 flex flex-col items-center justify-center shadow-md select-none`}>
      <span className={`font-bold leading-none ${isRed ? "text-red-600" : "text-gray-900"}`}>
        {rank}
      </span>
      <span className={`leading-none ${isRed ? "text-red-600" : "text-gray-900"}`}>
        {suit}
      </span>
    </div>
  );
}

export function CardBack({ size = "md" }: { size?: "sm" | "md" | "lg" }) {
  return <CardView card="" size={size} faceDown />;
}
