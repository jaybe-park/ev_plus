import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  SKIP_MODE_STORAGE_KEY, AUTO_NEXT_MS, readSkipMode, storeSkipMode, shouldAutoSkip, autoNextActive,
  remainingAfter, autoNextLabel, createCountdown,
} from "../autoAdvance";
import { initialDisplay, applyEvents, projectState } from "../hooks/eventQueueLogic";
import fixture from "../hooks/__tests__/fixtures/replay_session.json";
import type { GameState, PlayerState } from "../types";

class MemoryStorage {
  private m = new Map<string, string>();
  getItem(k: string) { return this.m.has(k) ? this.m.get(k)! : null; }
  setItem(k: string, v: string) { this.m.set(k, String(v)); }
  removeItem(k: string) { this.m.delete(k); }
}
const g = globalThis as unknown as { localStorage?: unknown };

describe("스킵 모드 보관 — 새로고침해도 유지(localStorage)", () => {
  beforeEach(() => { g.localStorage = new MemoryStorage(); });
  afterEach(() => { delete g.localStorage; });

  it("기본은 꺼짐, 켜서 저장하면 다시 읽어도 켜짐", () => {
    expect(readSkipMode()).toBe(false);
    storeSkipMode(true);
    expect(readSkipMode()).toBe(true);
    expect((g.localStorage as MemoryStorage).getItem(SKIP_MODE_STORAGE_KEY)).toBe("true");
    storeSkipMode(false);
    expect(readSkipMode()).toBe(false);
  });

  it("저장소 접근이 예외를 던져도 꺼짐으로 동작하고 저장은 조용히 실패", () => {
    g.localStorage = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
    expect(readSkipMode()).toBe(false);
    expect(() => storeSkipMode(true)).not.toThrow();
  });
});

const fold = fixture.fold_to_showdown as unknown as { prev: GameState; next: GameState };
const player = (over: Partial<PlayerState>): PlayerState => ({
  name: "Human", chips: 1000, current_bet: 0, is_folded: false, is_all_in: false, is_human: true,
  position: "UTG", hole_cards: null, ...over,
});

describe("폴드한 핸드는 바로 결과 — 남은 이벤트 즉시 소비", () => {
  it("스킵 모드 + 사람 폴드 + 핸드 종료일 때만", () => {
    const folded = { hand_over: true, players: [player({ is_folded: true })] };
    expect(shouldAutoSkip(true, folded)).toBe(true);
    expect(shouldAutoSkip(false, folded)).toBe(false);
    expect(shouldAutoSkip(true, { hand_over: true, players: [player({})] })).toBe(false);  // 쇼다운까지 간 내 핸드
    expect(shouldAutoSkip(true, { hand_over: false, players: [player({ is_folded: true })] })).toBe(false);
  });

  it("실제 세션 응답(사람 UTG 폴드 → 봇 쇼다운)에서 켜져 있으면 즉시 소비, 결과 = 서버 최종 상태", () => {
    expect(shouldAutoSkip(true, fold.next)).toBe(true);
    // enqueue(immediate)와 같은 경로: 시작점에 이벤트 전부 적용
    const d = applyEvents(initialDisplay(fold.prev, null, fold.next, false), fold.next.events);
    const shown = projectState(fold.next, d);
    expect(shown.pot).toBe(fold.next.pot);
    expect(shown.community_cards).toEqual(fold.next.community_cards);
    expect(shown.action_log).toEqual(fold.next.action_log);
  });
});

describe("결과 창 자동 진행 판단", () => {
  const base = { skipMode: true, gameOver: false, loading: false, sessionExpired: false, hasError: false };
  it("스킵 모드가 켜진 일반 핸드 결과에서만 돈다", () => {
    expect(autoNextActive(base)).toBe(true);
    expect(autoNextActive({ ...base, skipMode: false })).toBe(false);
  });
  it("파산·클리어(게임 오버) 화면은 자동으로 넘어가지 않는다", () => {
    expect(autoNextActive({ ...base, gameOver: true })).toBe(false);
  });
  it("요청 중·세션 만료·오류 뒤에는 멈춘다", () => {
    expect(autoNextActive({ ...base, loading: true })).toBe(false);
    expect(autoNextActive({ ...base, sessionExpired: true })).toBe(false);
    expect(autoNextActive({ ...base, hasError: true })).toBe(false);
  });
});

describe("남은 시간 계산", () => {
  it("경과만큼 줄고 0 아래로 가지 않는다, 멈춤 중엔 그대로", () => {
    expect(remainingAfter(5000, 1200, false)).toBe(3800);
    expect(remainingAfter(300, 1000, false)).toBe(0);
    expect(remainingAfter(3000, 1000, true)).toBe(3000);
    expect(remainingAfter(3000, -50, false)).toBe(3000);
  });
  it("안내 문구: 올림 초, 멈춤", () => {
    expect(autoNextLabel(5000, false)).toBe("5초 후 다음 핸드");
    expect(autoNextLabel(4001, false)).toBe("5초 후 다음 핸드");
    expect(autoNextLabel(4000, false)).toBe("4초 후 다음 핸드");
    expect(autoNextLabel(2500, true)).toContain("멈춤");
  });
});

describe("카운트다운 타이머 — 5초 후 다음 핸드, 마우스를 올리면 멈춘다", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("5초가 지나면 onDone 한 번", () => {
    const done = vi.fn();
    const ticks: number[] = [];
    createCountdown(AUTO_NEXT_MS, (r) => ticks.push(r), done);
    vi.advanceTimersByTime(4900);
    expect(done).not.toHaveBeenCalled();
    vi.advanceTimersByTime(100);
    expect(done).toHaveBeenCalledTimes(1);
    expect(ticks[ticks.length - 1]).toBe(0);
    vi.advanceTimersByTime(10_000);
    expect(done).toHaveBeenCalledTimes(1);
  });

  it("멈춘 동안은 줄지 않고, 다시 이어가면 남은 시간만큼 뒤에 끝난다", () => {
    const done = vi.fn();
    const c = createCountdown(AUTO_NEXT_MS, () => {}, done);
    vi.advanceTimersByTime(2000);
    expect(c.remaining()).toBe(3000);
    c.pause();
    vi.advanceTimersByTime(60_000);
    expect(done).not.toHaveBeenCalled();
    expect(c.remaining()).toBe(3000);
    c.resume();
    vi.advanceTimersByTime(2900);
    expect(done).not.toHaveBeenCalled();
    vi.advanceTimersByTime(100);
    expect(done).toHaveBeenCalledTimes(1);
  });

  it("stop하면(결과 창 닫힘·자동 진행 꺼짐) 부르지 않는다", () => {
    const done = vi.fn();
    const c = createCountdown(AUTO_NEXT_MS, () => {}, done);
    vi.advanceTimersByTime(1000);
    c.stop();
    vi.advanceTimersByTime(10_000);
    expect(done).not.toHaveBeenCalled();
  });
});
