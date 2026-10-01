import type { GameState, SetupConfig, GtoRange, SessionReview } from "./types";

// 기본은 HTTPS 백엔드(ADR 0025). 프리뷰·테스트 도구가 HTTP 백엔드를 띄울 때만 VITE_API_BASE로 바꾼다.
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "https://localhost:8765";

// FastAPI(Pydantic) 422는 detail이 배열이다: [{loc, msg, type}, ...].
// 그대로 new Error(array)에 넘기면 "[object Object]"가 뜬다(W13) — 사람이
// 읽을 수 있는 한 줄 문장으로 평탄화한다.
interface ValidationErrorItem {
  loc?: (string | number)[];
  msg?: string;
}

export function formatApiError(detail: unknown): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          const { loc, msg } = item as ValidationErrorItem;
          const field = Array.isArray(loc)
            ? loc.filter((p) => p !== "body").join(".")
            : "";
          return field ? `${field}: ${msg}` : String(msg ?? "");
        }
        return String(item);
      })
      .filter(Boolean)
      .join(" / ");
  }
  return "요청을 처리할 수 없습니다.";
}

// HTTP 상태 코드를 함께 싣는 오류 — 404(세션 없음)를 다른 오류와 구분한다
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(formatApiError(err.detail), res.status);
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

  // 노드 키(action_seq)로 레인지 조회 — UTG RFI는 빈 문자열
  getGtoRange: (actionSeq: string): Promise<GtoRange> =>
    request(`/gto/preflop/range?${new URLSearchParams({ action_seq: actionSeq })}`),

  getSessionReview: (id: string): Promise<SessionReview> =>
    request(`/session/${id}/review`),
};
