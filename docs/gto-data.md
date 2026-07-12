# GTO 데이터

프리플랍 레인지 데이터를 SQLite DB(`poker.db`)로 관리한다.
GTO Wizard에서 Claude in Chrome MCP로 추출해 저장한다.

> ⚠️ **2026-07-10 파서 버그로 전량 무효화, 재수집 대기 중.**
> `colorToAction()`의 RGB 임계값 버그(콜 `b < 80` — 실제 콜색 b=94라 상시 거짓,
> 올인 `r < 150` — 실제 올인색 r=153 경계로 불안정)로 콜 세그먼트 100% 유실,
> 올인 세그먼트 간헐적 유실. 아래 "현재 저장된 데이터 현황" 표는 **역사적 기록**이며
> 실제 DB의 `gto_preflop_situations`/`gto_preflop_hands`는 2026-07-12 전량 삭제됐다.
> `raise_size`도 대부분 `"3x"` 등 플레이스홀더였던 것을 REAL(실측 bb) 컬럼으로 교체.
> 재수집 시 아래 수정된 `colorToAction()`을 사용할 것 (5~7번 항목, TODO.md 참고).

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

**미수집 추적 큐 정리 (2026-07-10)**

`gto_missing_spots`에 기록되면 안 되는 오탐이 섞여 있던 버그를 수정했다.

- `gto/advisor.py` RFI 판정이 포지션을 안 가려 림프 팟에서 BB가 레이즈하면
  "BB RFI"로 오판(BB는 이미 강제 베팅 상태라 원천적으로 RFI 불가능). → 수정 후
  `my_position != "BB"`일 때만 open range 조회/기록.
- vs_3bet 판정이 `my_position == 오프너`인지 검증 안 해 "CO vs CO 3bet" 같은
  논리적으로 불가능한 조합이 대량 기록됨(우리 데이터 모델은 오프너가 3벳에
  대응하는 레인지만 수집). → 수정 후 my_position이 오프너일 때만 조회/기록.
- 정리 결과: open 2→1(BTN/SB 헤즈업 갭만 유지), vs_3bet 65→12(위 4개 미완성
  스팟에 대한 실제 갭만 남음), vs_open 18(변화 없음).

**미수집 추적 큐 정리 (2026-07-12, 3번째 유사 버그)**

BB RFI, vs_3bet 오프너 불일치에 이어 vs_open에서도 같은 계열의 "데이터
모델 밖 상황" 오탐이 발견됨: `find_opener_position()`이 "BTN 림프 후 BB가
아이솔레이트 레이즈, 액션이 BTN에게 돌아온" 상황에서 opener_pos='BB'를
반환 — 실제 가능한 상황이지만 우리 데이터 모델(open/vs_open/vs_3bet)은
"림프 후 아이솔레이트" 카테고리를 지원하지 않는다. 게다가 이 케이스는
`gto/url_generator.py`의 `vs_open_url()`이 오프너가 my_pos보다 뒤일 때
루프가 `range(my_idx)`까지만 돌아 오프너의 레이즈를 URL에 반영 못 하고
BTN RFI URL과 동일해지는 부수 문제도 있었다.

- `gto/advisor.py` vs_open 블록에서 opener_pos 확보 후, 오프너가 포지션
  순서(UTG,HJ,CO,BTN,SB,BB)상 my_position보다 뒤인 경우 조회/기록 없이
  None 반환하도록 수정(vs_3bet의 "my_position != opener_pos면 스킵" 패턴과
  동일 원칙). 포지션 비교는 `gto/url_generator.py`의 `POS_INDEX`를 재사용.
  헤즈업 포지션('BTN/SB' 등 POS_INDEX에 없는 값)은 비교 불가하므로 기존
  로직 유지.
- 큐 정리: 7개 → 6개. `position='BTN', vs_position='BB', range_type='vs_open'`
  1건이 이 버그로 생긴 오탐이라 삭제.

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
- 색상 매핑: 빨강 `rgb(240,60,60)` = raise, 파랑 `rgb(61,124,184)` = fold,
  초록 `#22c55e = rgb(34,197,94)` = call, 진빨강 `#991b1b = rgb(153,27,27)` = allin
- bgSize는 누적값: `"21% 100%, 100% 100%"` → raise 21%, fold 79%
- ⚠️ 아래 `colorToAction()`은 2026-07-10 확정된 버그(콜 `b < 80` — 실제 b=94라 상시
  거짓, 올인 `r < 150` — 실제 r=153 경계라 안티앨리어싱에 불안정) **수정 반영판**이다.
  재수집 시 반드시 이 버전을 사용할 것 (임계값 부등식 대신 정확한 hex 매칭이 더
  안전하니, Playwright 자동화 구현 시 그 방식으로 교체 고려).

### 저장 스크립트 (Chrome DevTools에서 실행)

```javascript
async function extractAndSave(position, label) {
  function colorToAction(rgb) {
    const m = rgb.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
    if (!m) return null;
    const [r, g, b] = [+m[1], +m[2], +m[3]];
    if (r > 200 && g < 100 && b < 100) return 'raise';
    if (r > 80 && r < 160 && g < 50 && b < 50) return 'allin';   // 수정: r<150 → r<160 (실제 r=153)
    if (r < 100 && g > 80 && b > 150) return 'fold';
    if (r < 80 && g > 150 && b < 110) return 'call';             // 수정: b<80 → b<110 (실제 b=94)
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

