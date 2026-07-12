# GTO 데이터

프리플랍 레인지 데이터를 SQLite DB(`poker.db`)로 관리한다.
GTO Wizard에서 Claude in Chrome MCP로 추출해 저장한다.

> ⚠️ **2026-07-10 파서 버그로 전량 무효화 → 2026-07-12 레이어 기반 파서로 재수집 진행 중.**
> 기존 "단일 gradient + % 색상 스탑" 가정 파서는 실제 GTO Wizard CSS 구조(여러 개
> 겹친 `linear-gradient` 레이어 + `background-size` 누적 폭)와 달라 call/allin이
> 섞이는 스팟에서 파싱 실패(`badSum` 발생)했다. 아래 "저장 스크립트"는 레이어
> 순서(`allin, raise, call, fold`) 매칭 + 누적폭 차분 방식으로 교체된 최신판이다.
> `raise_size`도 대부분 `"3x"` 등 플레이스홀더였던 것을 REAL(실측 bb) 컬럼으로 교체.
> 재수집 중 발견된 HJ RFI 데이터 오염 건은 아래 "현재 저장된 데이터 현황" 참고.

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

> ⚠️ 2026-07-10 파서 버그로 전량 무효화 후 2026-07-12부터 레이어 기반 새 파서로
> 재수집 진행 중. 아래 표는 **현재 DB 실측 기준(2026-07-12, 전수검사 완료)**이며,
> 재수집된 스팟만 반영돼 있다(vs_open/vs_3bet 대부분은 아직 `gto_missing_spots_preflop`
> 큐 기반으로 실전 우선순위 수집 중).

### RFI (오픈 레인지) — GTO Wizard ✅ (5/5 완료, 전수검사 통과)

fold=100%인 핸드 수(169개 중)로 표시 — 작을수록 넓게 오픈. UTG < HJ < CO < BTN < SB
순으로 넓어지는 정상 패턴 확인됨(2026-07-12 `scripts/audit_gto_preflop.py` 검증).

| 스팟 | fold100 카운트 | 상태 |
|---|---|---|
| UTG RFI | 117/169 | ✅ GTO Wizard (레이어 파서) |
| HJ RFI | 111/169 | ✅ GTO Wizard (2026-07-12 재수집 — 아래 "HJ RFI 데이터 오염" 참고) |
| CO RFI | 102/169 | ✅ GTO Wizard (레이어 파서) |
| BTN RFI | 81/169 | ✅ GTO Wizard (레이어 파서) |
| SB RFI | 61/169 | ✅ GTO Wizard (레이어 파서) |

### vs_open (수비 레인지) — 일부 수집 (큐 기반 진행 중)

| 스팟 | 사이징(실측 bb) | 상태 |
|---|---|---|
| HJ vs UTG open | 8.0 | ✅ GTO Wizard |
| BB vs UTG open | 13.5 | ✅ GTO Wizard |
| BB vs BTN open | 13.5 | ✅ GTO Wizard |
| SB vs BTN open | 11.0 | ✅ GTO Wizard |

나머지 vs_open 스팟은 `gto_missing_spots_preflop` 큐가 실전에서 채워지는 대로 수집.

### vs_3bet — 일부 수집 (큐 기반 진행 중)

| 오프너 | 3베터 | 사이징(실측 bb) | 상태 |
|---|---|---|---|
| UTG | HJ | 21.5 | ✅ GTO Wizard |
| BTN | BB | 28.5 | ✅ GTO Wizard |

나머지 vs_3bet 조합은 큐 기반으로 계속 수집.

### HJ RFI 데이터 오염 확인 및 재수집 (2026-07-12)

- **증상**: DB 직접 조회로 `HJ RFI` 169핸드 전부가 `freq_fold>=0.999`로 저장돼
  있음을 발견(비교: UTG fold100=117, CO=102, BTN=81, SB=61 — 포지션이 늦을수록
  오픈이 넓어지는 정상 패턴인데 HJ만 유일하게 전부 폴드로 붕괴).
- **원인 확정**: GTO Wizard에서 HJ RFI 스팟(`preflop_actions=F&history_spot=1`)을
  Chrome MCP로 직접 재확인한 결과, 실제 GTO 솔루션은 raise 21.7% / fold 78.3% /
  allin 0% — 저장된 "전부 fold"는 실제 GTO 값이 아니라 **재수집(v11 스키마 전환)
  과정에서의 저장 버그**였음이 확정됨(추측 아님, 화면 확인 및 재저장으로 검증).
- **조치**: 레이어 기반 파서(아래 "저장 스크립트" 참고)로 재추출(`badSum=0`,
  169핸드 전체 파싱 성공, Overview 패널의 21.7%/78.3%와 일치) 후 재저장.
  재저장 후 fold100=111/169로 UTG(117)와 CO(102) 사이에 정상 위치.
- **전수 검사**: `scripts/audit_gto_preflop.py` 작성 — 현재 DB에 저장된 모든
  `gto_preflop_situations`(11개)에 대해 핸드별 빈도합 검증(0.9~1.1 범위), RFI
  포지션 간 오픈 비율 순서 검증, 특정 액션 100%/0% 쏠림 탐지를 수행. HJ RFI
  수정 후 **11개 전체 통과**, 추가 이상 스팟 없음.

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

> **100bb 고정 가정(헤즈업 포함)은 의도된 근사**: 6-max GTO 데이터는 항상
> 100bb 기준으로 수집되며(캐시게임 특성상 매 핸드 스택이 벌어져도 스택별
> 재솔브는 하지 않음), 파산으로 2인(헤즈업)까지 줄어든 경우도 같은 원칙을
> 그대로 적용한다. 헤즈업 조회 시 `gto/advisor.py`가 `"BTN/SB"` 포지션을
> 6-max `"SB"`로 매핑해 재사용한다(2026-07-12).

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

### 추출 원리 (레이어 기반, 2026-07-12 확정)

GTO Wizard 레인지 그리드 각 셀은 **여러 개의 겹친 `linear-gradient` 레이어**로
구성되고, 각 레이어의 `background-size` 누적 폭(%)이 action 빈도를 인코딩한다
(단일 gradient + 색상 스탑 구조라는 기존 가정은 틀렸음 — call/allin이 섞인
스팟에서 파싱 실패로 확인됨, 2026-07-12).

- 레이어를 앞→뒤 순서로 `allin, raise, call, fold` 색상에 매칭하고, 누적폭
  차분(현재 레이어 bg-size % − 이전 레이어 %)으로 각 액션의 빈도를 계산
- 색상 매핑(실측): raise `r>200,g<100,b<100`, allin `110<=r<=140,g<50,b<50`,
  call `r<100,g>150,b<160`, fold `r<100,100<g<160,b>150`
- bgImage가 `'none'`인 핸드는 오프너 오픈레인지에 아예 없는 핸드라 정당하게
  제외(억지로 fold=1 채우지 않음)
- 핸드별 빈도 합이 `[0.9, 1.1]` 밖이면 `badSum`으로 카운트해 검증 실패 처리

### 저장 스크립트 (Chrome DevTools / Chrome MCP `javascript_tool`에서 실행)

```javascript
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

// 실행 예시 (HJ RFI 페이지에서, 오버뷰 패널의 사이징을 그대로 실측값으로 입력)
extractAndSave('HJ', 'HJ RFI', 2.5).then(console.log);
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

