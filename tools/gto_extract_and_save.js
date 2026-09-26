// GTO Wizard 콘솔에서 1스팟 수동 재검증·저장.
//
// 용도: 대량 수집은 scripts/collect_gto_tree.py(Playwright/CDP)가 담당하고, 이 스크립트는
// 특정 스팟 하나를 눈으로 확인하며 수동으로 재추출·재검증·재저장할 때 쓴다
// (Chrome DevTools 콘솔 또는 Chrome MCP javascript_tool에서 실행).
//
// 사용법 (GTO Wizard에서 저장할 스팟으로 이동한 상태에서):
//   extractAndSave(raiseSize)
//   예) extractAndSave(2.5).then(console.log);     // 화면 Actions 패널의 레이즈 사이즈(bb)
//       extractAndSave(null).then(console.log);    // 레이즈 사이즈를 모르면 null(추측 금지)
//
// 노드 키(action_seq)는 현재 URL의 preflop_actions(앞에서 history_spot개 토큰)를 그대로
// 보낸다(ADR 0008/0009). 포지션·상황 종류·라벨은 서버가 action_seq에서 유도한다(ADR 0038).
// 서버도 빈도합 [0.9, 1.1]을 검증해 불량이면 422로 거부한다(ADR 0002).
function currentActionSeq() {
  const params = new URL(location.href).searchParams;
  const raw = params.get('preflop_actions') || '';
  const tokens = raw ? raw.split('-') : [];
  const spotParam = params.get('history_spot');
  if (spotParam === null) return tokens.join('-');
  const spot = parseInt(spotParam, 10);
  if (Number.isNaN(spot) || spot < 0 || spot > tokens.length) {
    throw new Error(`history_spot=${spotParam}가 preflop_actions 토큰 수(${tokens.length})와 맞지 않음`);
  }
  return tokens.slice(0, spot).join('-');
}

async function extractAndSave(raiseSize = null) {
  function colorToAction(rgb) {
    const m = rgb.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
    if (!m) return null;
    const [r, g, b] = [+m[1], +m[2], +m[3]];
    if (r >= 110 && r <= 140 && g < 50 && b < 50) return 'allin';
    if (r > 200 && g < 100 && b < 100) return 'raise';
    if (r < 100 && g > 150 && b < 160) return 'call';
    if (r < 100 && g > 100 && g < 160 && b > 150) return 'fold';
    return null;
  }
  const actionSeq = currentActionSeq();
  const cells = document.querySelectorAll('[data-tst^="range_table_cell_0_"]');
  const hands = {};
  let badSum = 0;
  for (const cell of cells) {
    const hand = cell.getAttribute('data-tst').replace('range_table_cell_0_', '');
    const s = window.getComputedStyle(cell);
    if (s.backgroundImage === 'none' || !s.backgroundImage) continue; // 오픈레인지에 없는 핸드 → 정당하게 제외
    const grads = s.backgroundImage.split('), linear-gradient(');
    const sizes = s.backgroundSize.split(',').map(x => parseFloat(x.trim()));
    const freqs = {}; let prev = 0;
    for (let i = 0; i < grads.length; i++) {
      const colorMatches = [...grads[i].matchAll(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/g)];
      if (!colorMatches.length) continue;
      const m = colorMatches[0]; // 각 gradient의 첫 색상(솔리드 컬러라 두 색상 동일)
      const a = colorToAction(`rgb(${m[1]},${m[2]},${m[3]})`);
      const cum = sizes[i] ?? 100;
      const f = parseFloat(((cum - prev) / 100).toFixed(4));
      if (a && f > 0.001) freqs[a] = (freqs[a] || 0) + f;
      prev = cum;
    }
    const sum = Object.values(freqs).reduce((a, b) => a + b, 0);
    if (sum < 0.9 || sum > 1.1) badSum++;
    hands[hand] = freqs;
  }
  if (badSum > 0) {
    console.error(`검증 실패: badSum=${badSum} — 저장하지 않음`);
    return { ok: false, badSum };
  }
  const r = await fetch('https://localhost:8765/gto/preflop/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action_seq: actionSeq, raise_size: raiseSize, hands })
  });
  return r.json();
}
