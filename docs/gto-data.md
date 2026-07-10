# GTO 데이터

프리플랍 레인지 데이터를 SQLite DB(`poker.db`)로 관리한다.
GTO Wizard에서 Claude in Chrome MCP로 추출해 저장한다.

---

## DB 테이블 구조

```
gto_preflop_situations   ← 상황 단위 (position, vs_position, range_type)
gto_preflop_hands        ← 핸드별 빈도 (169개 * N situations)
gto_postflop_situations  ← 포스트플랍 상황 (미사용)
gto_postflop_hands       ← 포스트플랍 핸드별 빈도 (미사용)
```

---

## 현재 저장된 데이터 현황

### RFI (오픈 레인지) — GTO Wizard ✅

| 스팟 | 오픈률 | 상태 |
|---|---|---|
| UTG RFI | 30% | ✅ GTO Wizard |
| HJ RFI | 34% | ✅ GTO Wizard |
| CO RFI | 40% | ✅ GTO Wizard |
| BTN RFI | 52% | ✅ GTO Wizard |
| SB RFI | 59% | ✅ GTO Wizard |

### vs_open (수비 레인지) — GTO Wizard ✅

| 스팟 | 3bet 핸드 수 | 상태 |
|---|---|---|
| HJ vs UTG open | 38/169 (~22%) | ✅ GTO Wizard |
| CO vs UTG open | 41/169 (~24%) | ✅ GTO Wizard |
| BTN vs UTG open | 43/169 (~25%) | ✅ GTO Wizard |
| SB vs UTG open | 39/169 (~23%) | ✅ GTO Wizard |
| BB vs UTG open | 54/169 (~32%) | ✅ GTO Wizard |
| CO vs HJ open | 42/169 (~25%) | ✅ GTO Wizard |
| BTN vs HJ open | 43/169 (~25%) | ✅ GTO Wizard |
| SB vs HJ open | 45/169 (~27%) | ✅ GTO Wizard |
| BB vs HJ open | 57/169 (~34%) | ✅ GTO Wizard |
| BTN vs CO open | 47/169 (~28%) | ✅ GTO Wizard |
| SB vs CO open | 41/169 (~24%) | ✅ GTO Wizard |
| BB vs CO open | 60/169 (~36%) | ✅ GTO Wizard |
| SB vs BTN open | 46/169 (~27%) | ✅ GTO Wizard |
| BB vs BTN open | 67/169 (~40%) | ✅ GTO Wizard |
| BB vs SB open | 90/169 (~53%) | ✅ GTO Wizard |

### vs_3bet — GTO Wizard (31/35 완료)

> ⚠️ GTO Wizard 무료 계정 하루 100스팟 제한으로 4개 미완성. 내일 이어서 수집 가능.

**완료 (31개):**

| 오프너 | 3베터 | 대응 포지션 |
|---|---|---|
| UTG | HJ | CO, BTN, SB, BB, UTG |
| UTG | CO | BTN, SB, BB, UTG |
| UTG | BTN | SB, BB, UTG |
| UTG | SB | BB, UTG |
| UTG | BB | UTG |
| HJ | CO | BTN, SB, BB, HJ |
| HJ | BTN | SB, BB, HJ |
| HJ | SB | BB, HJ |
| HJ | BB | HJ |
| CO | BTN | SB, BB, CO |
| CO | SB | BB, CO |
| CO | BB | CO |

**미완성 (4개) — 내일 수집:**

| 스팟 | 상태 |
|---|---|
| BB vs [BTN open / SB 3bet] | ❌ 한도 초과 |
| BTN vs SB 3bet | ❌ 한도 초과 |
| BTN vs BB 3bet | ❌ 한도 초과 |
| SB vs BB 3bet | ❌ 한도 초과 |
| BTN vs [UTG open / HJ 3bet] | 24/169 | ✅ GTO Wizard |
| SB vs [UTG open / HJ 3bet] | 20/169 | ✅ GTO Wizard |
| BB vs [UTG open / HJ 3bet] | 20/169 | ✅ GTO Wizard |
| UTG vs HJ 3bet | 51/169 | ✅ GTO Wizard |
| BTN vs [UTG open / CO 3bet] | 24/169 | ✅ GTO Wizard |
| SB vs [UTG open / CO 3bet] | 20/169 | ✅ GTO Wizard |
| BB vs [UTG open / CO 3bet] | 17/169 | ✅ GTO Wizard |
| UTG vs CO 3bet | 51/169 | ✅ GTO Wizard |

### vs_open — 미존재 (fold 100% 폴백)

현재 기본 vs_open 12개 모두 수집 완료. 아래는 아직 없는 심화 스팟.

| 스팟 | 비고 |
|---|---|
| HJ vs UTG cold call | 수집 예정 |
| CO vs UTG cold call | 수집 예정 |
| vs_3bet 전체 | 수집 예정 |

**미존재 스팟 (데이터 없음 → fold 100% 폴백)**
- vs_3bet 레인지 전체
- BB_vs_SB, SB_vs_CO, SB_vs_MP, SB_vs_UTG
- 포스트플랍 레인지 전체

---

## GTO Wizard에서 데이터 추출하는 방법

### 준비
1. 서버 HTTPS 실행: `./start.sh`
2. Chrome에서 `https://localhost:8765` 접속 → 인증서 허용 (`thisisunsafe` 입력)
3. GTO Wizard 로그인 (핫스팟 필요 — 회사 와이파이 차단)

### URL 패턴 (6-max, Cash6mGeneral_6mNL25R25, 100bb)

| 스팟 | URL 파라미터 |
|---|---|
| UTG RFI | `preflop_actions=F-F-F&history_spot=0` |
| MP/HJ RFI | `preflop_actions=F&history_spot=1` |
| CO RFI | `preflop_actions=F-F&history_spot=2` |
| BTN RFI | `preflop_actions=F-F-F&history_spot=3` |
| SB RFI | `preflop_actions=F-F-F-F&history_spot=4` |
| BB vs BTN | `preflop_actions=F-F-F-R&history_spot=5` |
| BB vs CO | `preflop_actions=F-F-R&history_spot=5` |
| BB vs MP | `preflop_actions=F-R&history_spot=5` |
| BB vs UTG | `preflop_actions=R&history_spot=5` |
| SB vs BTN | `preflop_actions=F-F-F-R&history_spot=4` |

전체 URL 형식:
```
https://app.gtowizard.com/solutions?solution_type=gwiz&gametype=Cash6mGeneral_6mNL25R25&depth=100&preflop_actions=F-F-F&history_spot=3
```

### 추출 원리

GTO Wizard 레인지 그리드 각 셀의 `background-size` CSS 속성에 action 빈도가 인코딩됨:
- 색상 매핑: 빨강 `rgb(240,60,60)` = raise, 파랑 `rgb(61,124,184)` = fold, 진빨강 `rgb(125,31,31)` = allin
- bgSize는 누적값: `"21% 100%, 100% 100%"` → raise 21%, fold 79%

### 저장 스크립트 (Chrome DevTools에서 실행)

```javascript
async function extractAndSave(position, label) {
  function colorToAction(rgb) {
    const m = rgb.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
    if (!m) return null;
    const [r, g, b] = [+m[1], +m[2], +m[3]];
    if (r > 200 && g < 100 && b < 100) return 'raise';
    if (r > 80 && r < 150 && g < 50 && b < 50) return 'allin';
    if (r < 100 && g > 80 && b > 150) return 'fold';
    if (r < 80 && g > 150 && b < 80) return 'call';
    return null;
  }
  const cells = document.querySelectorAll('[data-tst^="range_table_cell_0_"]');
  const hands = {};
  for (const cell of cells) {
    const hand = cell.getAttribute('data-tst').replace('range_table_cell_0_', '');
    const s = window.getComputedStyle(cell);
    const grads = s.backgroundImage.split('), linear-gradient(');
    const sizes = s.backgroundSize.split(',').map(x => parseFloat(x.trim()));
    const freqs = {}; let prev = 0;
    for (let i = 0; i < grads.length; i++) {
      const m = grads[i].match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
      if (!m) continue;
      const a = colorToAction(`rgb(${m[1]},${m[2]},${m[3]})`);
      const cum = sizes[i] ?? 100;
      const f = parseFloat(((cum - prev) / 100).toFixed(4));
      if (a && f > 0.001) freqs[a] = f;
      prev = cum;
    }
    if (!Object.keys(freqs).length) freqs.fold = 1;
    hands[hand] = freqs;
  }
  const r = await fetch('https://localhost:8765/gto/preflop/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ position, vs_position: null, range_type: 'open',
                           raise_size: '2.5bb', situation_label: label, hands })
  });
  return r.json();
}

// 실행 예시 (BTN RFI 페이지에서)
extractAndSave('BTN', 'BTN RFI').then(console.log);
```

---

## 코드에서 사용하는 방법

```python
from gto.loader import get_open_range, get_vs_open_range, get_action_frequencies

# BTN RFI 레인지 (앱 시작 시 자동 로드)
range_data = get_open_range("BTN")
freqs = get_action_frequencies(range_data, "AKs")
# → {"raise": 1.0}

# BB vs BTN 레인지
range_data = get_vs_open_range("BB", "BTN")
```

---

## 핸드 표기 규칙

| 표기 | 의미 | 예시 |
|---|---|---|
| `AKs` | suited (같은 무늬) | A♠K♠ |
| `AKo` | offsuit (다른 무늬) | A♠K♥ |
| `AA` | 페어 | A♠A♥ |

- 169개 핸드 전체 저장 (누락 핸드 = fold 100% 폴백)
- 빈도 합계 ≈ 1.0

