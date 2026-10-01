// 화면 공용 표기 — 여러 컴포넌트가 같은 규칙으로 보이도록 한 곳에 둔다.

/** 비율(0~1)을 "%"로. digits는 소수 자릿수. */
export function pct(v: number, digits = 0): string {
  return `${(v * 100).toFixed(digits)}%`;
}

/** 봇 이름 접두사 "🤖 "를 뗀 표시 이름. 이름 자체(좌석 식별자)는 그대로 두고 화면에서만 뗀다. */
export function displayName(name: string): string {
  return name.startsWith("🤖 ") ? name.slice("🤖 ".length) : name;
}
