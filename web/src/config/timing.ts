/** 이벤트 타입별 애니메이션 딜레이 설정 (ms) */

// 기계적 이벤트 — 짧고 빠르게
export const MECHANICAL_DELAYS: Record<string, number> = {
  blind: 500,
  deal_card: 220,       // 한 장씩 빠르게
  street_start: 600,
  community_card: 500,
  showdown: 900,
  winner: 1000,
};

// 봇 액션 딜레이 — 스트리트별 기본값
export const ACTION_BASE_DELAYS: Record<string, number> = {
  프리플랍: 1200,
  플랍: 1600,
  턴: 2000,
  리버: 2500,
};

// 랜덤 편차 범위 (±ms)
export const ACTION_VARIANCE = 300;

// 액션 이벤트 내 "생각 중" 비율 (앞 40%는 thinking, 뒤 60%는 배지 표시)
export const THINKING_RATIO = 0.4;

export function getEventDelay(type: string, street?: string): number {
  if (type === "action") {
    const base = ACTION_BASE_DELAYS[street ?? "프리플랍"] ?? 1200;
    const variance = (Math.random() - 0.5) * 2 * ACTION_VARIANCE;
    return Math.max(800, base + variance);
  }
  return MECHANICAL_DELAYS[type] ?? 500;
}
