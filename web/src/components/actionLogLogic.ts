// 액션 로그(사이드 "📋 로그" 탭)의 줄 구성·복사 문자열만 순수 함수로 뽑은 모듈(vitest 대상).
import type { GameState, LogEntry } from "../types";

export type LogLineKind = "street" | "win" | "normal";

export interface LogLine {
  text: string;
  kind: LogLineKind;
  heroCards: string[];   // 그 줄 시점의 내 홀카드(없으면 빈 배열)
  board: string[];       // 그 줄 시점의 보드(프리플랍은 빈 배열)
}

export function lineKind(text: string): LogLineKind {
  if (text.startsWith("──")) return "street";
  if (text.startsWith("🏆")) return "win";
  return "normal";
}

/**
 * 화면에 그릴 로그 줄. 서버 log_entries가 action_log와 같은 길이면(정상) 줄마다 그 시점 보드·내 홀카드를
 * 붙이고, 없거나 길이가 어긋나면(구 응답) 텍스트만 쓴다 — 다른 줄의 보드를 잘못 붙이지 않는다.
 * 둘 다 재생 중에는 projectState가 끝에서 같은 개수(logPending)만큼 숨긴 값이다. 줄의 보드는 지금 화면
 * 보드(state.community_cards) 장수를 넘지 않는다. heroRevealed=false(테이블에서 내 카드를 숨긴 상태)면
 * 내 홀카드 자리에 뒷면(🂠)을 그려 로그가 카드를 드러내지 않는다.
 */
export function logLines(
  state: Pick<GameState, "action_log" | "log_entries" | "community_cards">,
  heroRevealed = true,
): LogLine[] {
  const entries: LogEntry[] | undefined = state.log_entries;
  const aligned = !!entries && entries.length === state.action_log.length;
  return state.action_log.map((text, i) => {
    const e = aligned ? entries![i] : undefined;
    return {
      text,
      kind: lineKind(text),
      heroCards: e && e.text === text ? (heroRevealed ? e.hero_cards : e.hero_cards.map(() => "🂠")) : [],
      // 화면 보드보다 앞서지 않게 자른다: 스트리트 헤더 줄은 서버가 카드를 깐 뒤 기록하지만, 재생 중엔
      // street_start가 community_card보다 먼저 소비되므로 테이블에 깔린 장수까지만 보인다
      board: e && e.text === text ? e.board.slice(0, state.community_cards.length) : [],
    };
  });
}

/** 복사 버튼이 클립보드에 넣는 문자열 — 로그 텍스트만(카드 표시 제외), 줄바꿈으로 잇는다. */
export function logCopyText(lines: LogLine[]): string {
  return lines.map((l) => l.text).join("\n");
}

/** 카드 글자 색: ♥♦는 빨강. */
export function isRedCard(card: string): boolean {
  const suit = card.slice(-1);
  return suit === "♥" || suit === "♦";
}

/** 클립보드 복사. 지원 안 함·권한 거부 등 실패는 조용히 무시하고 false. */
export async function copyToClipboard(text: string, clip: Pick<Clipboard, "writeText"> | undefined = globalThis.navigator?.clipboard): Promise<boolean> {
  try {
    if (!clip) return false;
    await clip.writeText(text);
    return true;
  } catch {
    return false;
  }
}
