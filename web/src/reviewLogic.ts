// 플레이 평가(복기·세션 요약)의 표시 판단 — 순수 함수(vitest 대상).
// 서버 ev_loss_bb / total_ev_loss_bb는 양수 = 손실 크기다(gto/grader.py).
import type { GameState, SessionReview } from "./types";
import { pct } from "./format";

/** 복기 줄의 손실 표기 "−N.Nbb". 손실이 없거나(null·0 이하) 판정하지 않은 줄은 null. */
export function evLossText(evLossBb: number | null | undefined): string | null {
  if (evLossBb == null || !(evLossBb > 0)) return null;
  return `−${evLossBb.toFixed(1)}bb`;
}

/** 헤더 세션 요약 "GTO 62% · EV 손실 3.4bb". */
export function sessionSummaryText(review: SessionReview): string {
  const gto = review.gto_match_rate != null ? pct(review.gto_match_rate) : "—";
  return `GTO ${gto} · EV 손실 ${Math.max(0, review.total_ev_loss_bb).toFixed(1)}bb`;
}

/**
 * 세션 요약을 다시 받아올 때인가. 핸드가 끝났고 그 핸드의 재생이 끝난 뒤에만 받는다 —
 * 재생 중에 받으면 헤더가 아직 화면에 안 나온 결과를 먼저 보인다.
 */
export function shouldFetchReview(isReplaying: boolean, state: Pick<GameState, "hand_over" | "session_id"> | null): boolean {
  return !isReplaying && !!state?.hand_over && !!state.session_id;
}
