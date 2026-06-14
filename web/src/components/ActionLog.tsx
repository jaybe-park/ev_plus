import { useEffect, useRef } from "react";

interface Props {
  log: string[];
}

export default function ActionLog({ log }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [log]);

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-xl overflow-hidden flex flex-col h-48">
      <div className="text-xs text-gray-500 px-3 py-1.5 border-b border-gray-700 font-medium">
        액션 로그
      </div>
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-0.5">
        {log.map((entry, i) => {
          const isStreet = entry.startsWith("──");
          const isWin = entry.startsWith("🏆");
          return (
            <div
              key={i}
              className={`text-xs ${
                isStreet
                  ? "text-blue-400 font-semibold mt-1"
                  : isWin
                  ? "text-yellow-400 font-bold"
                  : "text-gray-300"
              }`}
            >
              {entry}
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
