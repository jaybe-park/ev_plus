// 새로고침·탭 다시 열기 후 이어하기(ADR 0043): 진행 중인 세션 번호를 sessionStorage에 둔다.
// 저장소 접근은 브라우저 설정(사이트 데이터 차단 등)에 따라 예외를 던질 수 있어 모두 감싼다.
import { ApiError } from "./api";

export const SESSION_STORAGE_KEY = "ev_plus_session_id";

export const SESSION_EXPIRED_MESSAGE = "세션 만료 — 새 게임";

function storage(): Storage | null {
  try {
    return typeof sessionStorage === "undefined" ? null : sessionStorage;
  } catch {
    return null;
  }
}

export function readStoredSessionId(): string | null {
  try {
    const v = storage()?.getItem(SESSION_STORAGE_KEY);
    return v ? v : null;
  } catch {
    return null;
  }
}

export function storeSessionId(id: string): void {
  try {
    storage()?.setItem(SESSION_STORAGE_KEY, id);
  } catch {
    // 저장 실패는 게임 진행을 막지 않는다(새로고침 복구만 안 됨)
  }
}

export function clearStoredSessionId(): void {
  try {
    storage()?.removeItem(SESSION_STORAGE_KEY);
  } catch {
    // 무시
  }
}

// 서버가 세션을 모른다(재시작·정리됨) = 404. 네트워크 오류 등은 만료가 아니다.
export function isSessionGone(e: unknown): boolean {
  return e instanceof ApiError && e.status === 404;
}
