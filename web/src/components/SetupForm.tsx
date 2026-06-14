import { useState } from "react";
import type { SetupConfig } from "../types";

interface Props {
  onStart: (config: SetupConfig) => void;
}

export default function SetupForm({ onStart }: Props) {
  const [form, setForm] = useState<SetupConfig>({
    player_name: "Player",
    chips: 1000,
    num_bots: 5,
    difficulty: "medium",
    big_blind: 10,
  });

  const set = <K extends keyof SetupConfig>(k: K, v: SetupConfig[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  return (
    <div className="min-h-screen bg-gray-900 flex items-center justify-center p-4">
      <div className="bg-gray-800 rounded-2xl p-8 w-full max-w-md shadow-2xl border border-gray-700">
        <h1 className="text-3xl font-bold text-white text-center mb-2">
          ♠ Texas Hold'em
        </h1>
        <p className="text-gray-400 text-center mb-8 text-sm">게임 설정</p>

        <div className="space-y-5">
          <Field label="플레이어 이름">
            <input
              className="input"
              value={form.player_name}
              onChange={(e) => set("player_name", e.target.value)}
            />
          </Field>

          <Field label="시작 칩">
            <input
              type="number"
              className="input"
              value={form.chips}
              min={100}
              step={100}
              onChange={(e) => set("chips", Number(e.target.value))}
            />
          </Field>

          <Field label={`AI 봇 수: ${form.num_bots}명`}>
            <input
              type="range"
              min={1}
              max={5}
              value={form.num_bots}
              onChange={(e) => set("num_bots", Number(e.target.value))}
              className="w-full accent-green-500"
            />
          </Field>

          <Field label="난이도">
            <div className="flex gap-2">
              {(["easy", "medium", "hard"] as const).map((d) => (
                <button
                  key={d}
                  onClick={() => set("difficulty", d)}
                  className={`flex-1 py-2 rounded-lg text-sm font-medium transition-colors ${
                    form.difficulty === d
                      ? "bg-green-600 text-white"
                      : "bg-gray-700 text-gray-300 hover:bg-gray-600"
                  }`}
                >
                  {d === "easy" ? "쉬움" : d === "medium" ? "보통" : "어려움"}
                </button>
              ))}
            </div>
          </Field>

          <Field label="빅 블라인드 (BB)">
            <input
              type="number"
              className="input"
              value={form.big_blind}
              min={1}
              step={5}
              onChange={(e) => set("big_blind", Number(e.target.value))}
            />
          </Field>
        </div>

        <button
          onClick={() => onStart(form)}
          className="w-full mt-8 py-3 bg-green-600 hover:bg-green-500 text-white font-bold rounded-xl text-lg transition-colors shadow-lg"
        >
          게임 시작
        </button>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-gray-300 text-sm font-medium mb-1.5">{label}</label>
      {children}
    </div>
  );
}
