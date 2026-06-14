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

| 스팟 | 소스 | 상태 |
|---|---|---|
| UTG RFI (30% open) | GTO Wizard | ✅ 정확 |
| MP/HJ RFI (34% open) | GTO Wizard | ✅ 정확 |
| CO RFI (40% open) | GTO Wizard | ✅ 정확 |
| BTN RFI (52% open) | GTO Wizard | ✅ 정확 |
| SB RFI (59% open) | GTO Wizard | ✅ 정확 |
| BB vs BTN | 구 JSON | ⚠️ 교정 필요 |
| BB vs CO | 구 JSON | ⚠️ 교정 필요 |
| BB vs MP | 구 JSON | ⚠️ 교정 필요 |
| BB vs UTG | 구 JSON | ⚠️ AKo 오류 포함 |
| SB vs BTN | 구 JSON | ⚠️ 교정 필요 |

**미존재 스팟 (데이터 없음 → fold 100% 폴백)**
- vs_3bet 레인지 전체
- BB_vs_SB, SB_vs_CO, SB_vs_MP, SB_vs_UTG
- 포스트플랍 레인지 전체

---

## GTO Wizard에서 데이터 추출하는 방법

### 준비
1. 서버 HTTPS 실행: `./start.sh`
2. Chrome에서 `https://localhost:8000` 접속 → 인증서 허용 (`thisisunsafe` 입력)
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
  const r = await fetch('https://localhost:8000/gto/preflop/save', {
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

---

## 포지션 네이밍 주의

GTO Wizard는 6-max에서 `UTG → HJ → CO → BTN → SB → BB`를 사용하지만,
우리 게임 엔진(`game.py`)은 `UTG → MP → CO → BTN → SB → BB`를 사용한다.

GTO Wizard의 **HJ = 우리 코드의 MP**.
DB 저장 시 position 컬럼은 게임 엔진 기준(`MP`)으로 저장해야 힌트가 정상 작동한다.
