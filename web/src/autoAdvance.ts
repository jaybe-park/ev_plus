// 스킵 모드(⏭) + 결과 창 자동 진행. 판단·남은 시간 계산은 순수 함수, 타이머는 createCountdown 하나 —
// 둘 다 vitest 대상(타이머는 vi.useFakeTimers).
import type { GameState } from "./types";

export const SKIP_MODE_STORAGE_KEY = "ev_plus_skip_mode";
/** 결과 창이 뜬 뒤 자동으로 "다음 핸드"를 누르기까지(ms). */
export const AUTO_NEXT_MS = 5000;
const TICK_MS = 100;

// ── 보관(localStorage) — 사이트 데이터 차단 등으로 접근이 예외를 던질 수 있어 모두 감싼다 ──

function storage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

export function readSkipMode(): boolean {
  try {
    return storage()?.getItem(SKIP_MODE_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

export function storeSkipMode(on: boolean): void {
  try {
    storage()?.setItem(SKIP_MODE_STORAGE_KEY, String(on));
  } catch {
    // 저장 실패는 무시(다음 방문에 기본값 꺼짐)
  }
}

// ── 판단 ──────────────────────────────────────────────

/**
 * 이 응답의 이벤트를 재생 없이 바로 소비할지: 스킵 모드가 켜져 있고 사람이 이 핸드에서 폴드했고
 * 핸드가 끝났을 때(폴드한 사람은 더 행동하지 않으므로 서버가 핸드 끝까지 진행한 응답이다).
 */
export function shouldAutoSkip(skipMode: boolean, next: Pick<GameState, "players" | "hand_over">): boolean {
  if (!skipMode || !next.hand_over) return false;
  const human = next.players.find((p) => p.is_human);
  return !!human && human.is_folded;
}

export interface AutoNextInput {
  skipMode: boolean;
  gameOver: boolean;        // 파산·클리어 화면 — 자동으로 넘어가지 않는다
  loading: boolean;
  sessionExpired: boolean;
  hasError: boolean;        // 직전 요청 실패 — 자동 재시도로 오류를 반복하지 않는다
}

/** 결과 창 자동 진행 카운트다운을 돌릴지. 스킵 모드가 켜진 일반 핸드 결과에서만. */
export function autoNextActive(i: AutoNextInput): boolean {
  return i.skipMode && !i.gameOver && !i.loading && !i.sessionExpired && !i.hasError;
}

/** 남은 시간(ms): 일시정지 중이 아닌 경과 시간만 뺀다. 0 아래로 가지 않는다. */
export function remainingAfter(remainingMs: number, elapsedMs: number, paused: boolean): number {
  if (paused) return remainingMs;
  return Math.max(0, remainingMs - Math.max(0, elapsedMs));
}

/** 결과 창 안내 문구. */
export function autoNextLabel(remainingMs: number, paused: boolean): string {
  if (paused) return "자동 진행 멈춤 — 마우스를 치우면 이어서";
  return `${Math.ceil(remainingMs / 1000)}초 후 다음 핸드`;
}

// ── 타이머 ────────────────────────────────────────────

export interface Countdown {
  pause(): void;
  resume(): void;
  stop(): void;
  remaining(): number;
}

/**
 * totalMs 카운트다운. 일시정지 중엔 줄지 않고, 0이 되면 onDone을 한 번 부른 뒤 멈춘다.
 * onTick은 남은 시간이 바뀔 때마다(TICK_MS 간격) 불린다.
 */
export function createCountdown(totalMs: number, onTick: (remainingMs: number) => void, onDone: () => void): Countdown {
  let remaining = totalMs;
  let paused = false;
  let done = false;
  let last = Date.now();
  const id = setInterval(() => {
    const now = Date.now();
    const elapsed = now - last;
    last = now;
    if (done) return;
    const next = remainingAfter(remaining, elapsed, paused);
    if (next === remaining) return;
    remaining = next;
    onTick(remaining);
    if (remaining <= 0) {
      done = true;
      clearInterval(id);
      onDone();
    }
  }, TICK_MS);
  return {
    pause() { paused = true; },
    resume() { if (paused) { paused = false; last = Date.now(); } },
    stop() { done = true; clearInterval(id); },
    remaining: () => remaining,
  };
}
