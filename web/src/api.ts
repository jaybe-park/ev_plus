import type { GameState, SetupConfig, GtoKey, GtoRange, SessionReview } from "./types";

const BASE = "https://localhost:8765";

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

  getGtoRange: (key: GtoKey): Promise<GtoRange> => {
    const params = new URLSearchParams({ position: key.position, range_type: key.range_type });
    if (key.vs_position !== null && key.vs_position !== undefined) {
      params.set("vs_position", key.vs_position);
    }
    return request(`/gto/preflop/range?${params}`);
  },

  getSessionReview: (id: string): Promise<SessionReview> =>
    request(`/session/${id}/review`),
};
