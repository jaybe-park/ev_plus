import { useEffect, useRef, useState } from "react";
import { copyToClipboard, isRedCard, logCopyText, type LogLine } from "./actionLogLogic";

interface Props {
  lines: LogLine[];
}

function Cards({ cards }: { cards: string[] }) {
  return (
    <span className="font-mono">
      {cards.map((c, i) => (
        <span key={i} className={isRedCard(c) ? "text-red-400" : "text-gray-300"}>{c}</span>
      ))}
    </span>
  );
}

// 로그 영역은 내용만큼 늘어나고(부모 높이까지), 넘치면 안에서 스크롤한다.
// 줄마다 오른쪽에 그 시점의 내 핸드 | 보드. 우상단 복사 버튼은 로그 텍스트만 클립보드에 넣는다.
export default function ActionLog({ lines }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [lines]);

  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1200);
    return () => clearTimeout(t);
  }, [copied]);

  const handleCopy = async () => {
    if (await copyToClipboard(logCopyText(lines))) setCopied(true);
  };

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-xl overflow-hidden flex flex-col min-h-0 max-h-[60vh] lg:max-h-none">
      <div className="flex items-center justify-between text-xs text-gray-500 px-3 py-1.5 border-b border-gray-700 font-medium shrink-0">
        <span>액션 로그</span>
        <button
          onClick={handleCopy}
          disabled={lines.length === 0}
          title="로그 텍스트 복사"
          className="text-[10px] border border-gray-600 rounded px-1.5 py-0.5 hover:text-gray-200 disabled:opacity-40"
        >
          {copied ? "복사됨" : "복사"}
        </button>
      </div>
      <div className="min-h-0 overflow-y-auto px-3 py-2 space-y-0.5">
        {lines.map((l, i) => (
          <div
            key={i}
            className={`flex items-baseline justify-between gap-2 text-xs ${
              l.kind === "street"
                ? "text-blue-400 font-semibold mt-1"
                : l.kind === "win"
                ? "text-yellow-400 font-bold"
                : "text-gray-300"
            }`}
          >
            <span className="min-w-0 break-words">{l.text}</span>
            {(l.heroCards.length > 0 || l.board.length > 0) && (
              <span className="shrink-0 text-[10px] font-normal text-gray-500 whitespace-nowrap">
                <Cards cards={l.heroCards} />
                {l.board.length > 0 && (
                  <>
                    <span className="mx-0.5">|</span>
                    <Cards cards={l.board} />
                  </>
                )}
              </span>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
