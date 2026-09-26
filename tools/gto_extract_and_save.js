// GTO Wizard 콘솔에서 1스팟 수동 재검증·저장.
//
// 용도: 대량 수집은 scripts/collect_gto_tree.py(Playwright/CDP)가 담당하고, 이 스크립트는
// 특정 스팟 하나를 눈으로 확인하며 수동으로 재추출·재검증·재저장할 때 쓴다
// (Chrome DevTools 콘솔 또는 Chrome MCP javascript_tool에서 실행).
//
// 사용법:
//   extractAndSave(position, label, raiseSize, vsPosition, rangeType)
//   예) extractAndSave('HJ', 'HJ RFI', 2.5).then(console.log);
//       extractAndSave('BB', 'BB vs BTN open', 2.5, 'BTN', 'vs_open').then(console.log);
//
// 주의: 이 스크립트는 action_seq를 보내지 않으므로 서버가 레거시 파생 키로 저장한다
// (TODO T-001에서 action_seq 전송 추가 예정).
async function extractAndSave(position, label, raiseSize, vsPosition = null, rangeType = 'open') {
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
    body: JSON.stringify({ position, vs_position: vsPosition, range_type: rangeType,
                           raise_size: raiseSize, situation_label: label, hands })
  });
  return r.json();
}
