import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { ApiError } from "../api";
import {
  SESSION_STORAGE_KEY,
  readStoredSessionId,
  storeSessionId,
  clearStoredSessionId,
  isSessionGone,
} from "../sessionStore";

class MemoryStorage {
  private m = new Map<string, string>();
  getItem(k: string) { return this.m.has(k) ? this.m.get(k)! : null; }
  setItem(k: string, v: string) { this.m.set(k, String(v)); }
  removeItem(k: string) { this.m.delete(k); }
}

const g = globalThis as unknown as { sessionStorage?: unknown };

describe("세션 번호 보관 — 새로고침 후 이어하기 (ADR 0043)", () => {
  beforeEach(() => { g.sessionStorage = new MemoryStorage(); });
  afterEach(() => { delete g.sessionStorage; });

  it("저장한 세션 번호를 다시 읽고, 지우면 없다", () => {
    expect(readStoredSessionId()).toBeNull();
    storeSessionId("abc");
    expect(readStoredSessionId()).toBe("abc");
    expect((g.sessionStorage as MemoryStorage).getItem(SESSION_STORAGE_KEY)).toBe("abc");
    clearStoredSessionId();
    expect(readStoredSessionId()).toBeNull();
  });

  it("저장소가 없거나 예외를 던져도 게임을 막지 않는다", () => {
    delete g.sessionStorage;
    expect(readStoredSessionId()).toBeNull();
    expect(() => storeSessionId("x")).not.toThrow();
    g.sessionStorage = {
      getItem() { throw new Error("blocked"); },
      setItem() { throw new Error("blocked"); },
      removeItem() { throw new Error("blocked"); },
    };
    expect(readStoredSessionId()).toBeNull();
    expect(() => storeSessionId("x")).not.toThrow();
    expect(() => clearStoredSessionId()).not.toThrow();
  });
});

describe("세션 만료 판정", () => {
  it("404만 세션 만료로 본다", () => {
    expect(isSessionGone(new ApiError("세션을 찾을 수 없습니다.", 404))).toBe(true);
    expect(isSessionGone(new ApiError("불법 액션", 400))).toBe(false);
    expect(isSessionGone(new TypeError("Failed to fetch"))).toBe(false);
    expect(isSessionGone(undefined)).toBe(false);
  });
});
