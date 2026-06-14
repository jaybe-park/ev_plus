import type { GameState, SetupConfig } from "./types";

const BASE = "http://localhost:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Request failed");
  }
  return res.json() as Promise<T>;
}

export const api = {
  startGame: (config: SetupConfig): Promise<GameState> =>
    request("/game/start", { method: "POST", body: JSON.stringify(config) }),

  getState: (id: string): Promise<GameState> =>
    request(`/game/${id}/state`),

  submitAction: (id: string, action: string, amount = 0): Promise<GameState> =>
    request(`/game/${id}/action`, {
      method: "POST",
      body: JSON.stringify({ action, amount }),
    }),

  nextHand: (id: string): Promise<GameState> =>
    request(`/game/${id}/next-hand`, { method: "POST" }),
};
