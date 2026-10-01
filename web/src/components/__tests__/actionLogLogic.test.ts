import { describe, it, expect, vi } from "vitest";
import { logLines, logCopyText, lineKind, isRedCard, copyToClipboard } from "../actionLogLogic";
import type { LogEntry } from "../../types";

const hero = ["A♠", "K♥"];
const flop = ["Q♦", "7♣", "2♠"];
const entry = (text: string, street: string, board: string[]): LogEntry => ({ text, street, board, hero_cards: hero });
const log = [
  "[SB] 🤖 A: 스몰 블라인드 (10)",
  "[BB] Human: 빅 블라인드 (20)",
  "── 플랍 ──",
  "[SB] 🤖 A: 체크",
  "🏆 Human 승리 (40, 상대 폴드)",
];
const entries = [
  entry(log[0], "프리플랍", []), entry(log[1], "프리플랍", []),
  entry(log[2], "플랍", flop), entry(log[3], "플랍", flop), entry(log[4], "플랍", flop),
];

describe("로그 줄 — 줄마다 그 시점 내 핸드·보드", () => {
  it("log_entries가 있으면 줄마다 내 홀카드와 그 시점 보드를 붙인다", () => {
    const lines = logLines({ action_log: log, log_entries: entries, community_cards: flop });
    expect(lines.map((l) => [l.text, l.heroCards, l.board])).toEqual([
      [log[0], hero, []], [log[1], hero, []], [log[2], hero, flop], [log[3], hero, flop], [log[4], hero, flop],
    ]);
    expect(lines.map((l) => l.kind)).toEqual(["normal", "normal", "street", "normal", "win"]);
  });

  it("줄 보드는 화면 보드 장수를 넘지 않는다(재생 중 street_start가 카드보다 먼저 소비됨)", () => {
    const lines = logLines({ action_log: log.slice(0, 3), log_entries: entries.slice(0, 3), community_cards: [] });
    expect(lines[2].board).toEqual([]);
    const one = logLines({ action_log: log.slice(0, 3), log_entries: entries.slice(0, 3), community_cards: ["Q♦"] });
    expect(one[2].board).toEqual(["Q♦"]);
  });

  it("log_entries가 없거나 길이·텍스트가 어긋나면 텍스트만(다른 줄 보드를 붙이지 않음)", () => {
    expect(logLines({ action_log: log, community_cards: flop }).every((l) => l.board.length === 0 && l.heroCards.length === 0)).toBe(true);
    expect(logLines({ action_log: log, log_entries: entries.slice(1), community_cards: flop })[2].board).toEqual([]);
    const shifted = [...entries]; shifted[3] = entry("다른 줄", "플랍", flop);
    const l = logLines({ action_log: log, log_entries: shifted, community_cards: flop });
    expect(l[3].board).toEqual([]);
    expect(l[2].board).toEqual(flop);
  });

  it("lineKind: ── 스트리트, 🏆 승리", () => {
    expect(lineKind("── 턴 ──")).toBe("street");
    expect(lineKind("🏆 x 승리 (1)")).toBe("win");
    expect(lineKind("[BTN] x: 콜 (20)")).toBe("normal");
  });

  it("♥♦는 빨강", () => {
    expect(isRedCard("K♥")).toBe(true);
    expect(isRedCard("10♦")).toBe(true);
    expect(isRedCard("A♠")).toBe(false);
  });
});

describe("로그 복사 — 텍스트만", () => {
  it("복사 문자열은 로그 텍스트를 줄바꿈으로 이은 것(카드 표시 없음)", () => {
    const text = logCopyText(logLines({ action_log: log, log_entries: entries, community_cards: flop }));
    expect(text).toBe(log.join("\n"));
    expect(text).not.toContain("A♠");
  });

  it("클립보드에 그 문자열을 쓴다", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    expect(await copyToClipboard("a\nb", { writeText })).toBe(true);
    expect(writeText).toHaveBeenCalledWith("a\nb");
  });

  it("클립보드 실패(권한 거부)·미지원은 조용히 무시", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    await expect(copyToClipboard("x", { writeText })).resolves.toBe(false);
    await expect(copyToClipboard("x", undefined)).resolves.toBe(false);
  });
});
