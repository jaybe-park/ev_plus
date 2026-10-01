// 결과 창의 팟 계층 표시 — 순수 함수(vitest 대상).
import type { PotShare } from "../types";
import { displayName } from "../format";

export interface PotLine {
  label: string;      // "메인 팟" / "사이드 팟 1" / "반환"
  amount: number;
  names: string;      // 승자(반환이면 돌려받은 사람) 표시 이름, 쉼표로
  returned: boolean;
}

/**
 * 서버 pots를 결과 창 줄로 바꾼다. 반환 계층은 "반환 N → 이름", 나머지는 첫 계층이 "메인 팟",
 * 이후가 "사이드 팟 k". 계층이 하나뿐이면(사이드 팟·반환 없음) 승자 줄과 같은 내용이라 빈 목록.
 * pots가 없거나 null이면(서버가 보내지 않음) 빈 목록 — 결과 창은 승자 줄만 보인다.
 */
export function potLines(pots: PotShare[] | null | undefined): PotLine[] {
  if (!pots || pots.length < 2) return [];
  let tier = 0;
  return pots.map((p) => {
    const who = (p.winners.length > 0 ? p.winners : p.eligible).map(displayName).join(", ");
    if (p.returned) return { label: "반환", amount: p.amount, names: who, returned: true };
    const label = tier === 0 ? "메인 팟" : `사이드 팟 ${tier}`;
    tier += 1;
    return { label, amount: p.amount, names: who, returned: false };
  });
}

/** 한 줄 텍스트. 반환: "반환 300 → Alice", 그 외: "사이드 팟 1 — 1,200 — Bob, Carol". */
export function potLineText(l: PotLine): string {
  if (l.returned) return `반환 ${l.amount.toLocaleString()} → ${l.names}`;
  return `${l.label} — ${l.amount.toLocaleString()} — ${l.names}`;
}
