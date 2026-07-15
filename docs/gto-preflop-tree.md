# 프리플랍 전체 트리 커버리지 — 설계 문서

프리플랍 GTO를 "RFI/vs_open/vs_3bet(오프너 본인만) 35개 조합"에서
**모든 도달 가능한 프리플랍 의사결정 노드**로 확장하기 위한 설계. (2026-07-13 착수)

관련 TODO: TODO.md "프리플랍 전체 트리 커버리지" 항목.
포스트플랍 추상화(docs/gto-postflop.md)와 대비 — 프리플랍은 근사가 아니라 완전 열거가 목표.

---

## 왜 프리플랍은 "전부"가 가능한가

포스트플랍이 전부 수집 불가인 이유는 **보드 카드 조합 폭발**(플랍만 1,755 텍스처 /
정확 보드 128만+)이다. 프리플랍은 커뮤니티 카드가 없고 **순수 액션 시퀀스**만
상황을 정의하므로 트리가 유한하고 열거 가능하다. 따라서 텍스처 클래스 근사가
필요 없이 "진짜 전부"를 목표로 잡아도 된다.

169핸드 매트릭스는 키에 넣지 않는다 — GTO Wizard가 노드당 전체 169핸드
전략을 한 번에 주므로, 기존 프리플랍 방식과 동일하게 데이터(핸드 빈도) 쪽에 포함된다.

---

## GTO Wizard 트리 구조 실측 (③ 정찰 결과, 2026-07-13)

Browser 페인으로 `Cash6mGeneral_6mNL25R25`, depth=100 스팟들을 직접 열어 확인.

### 핵심 발견 1 — 노드당 논-올인 레이즈 사이즈는 정확히 1개
각 의사결정 노드에서 가능한 액션은 **{Fold, Call(합법일 때), Raise <단일 사이즈>, Allin}**.
"레이즈 사이즈 여러 개"가 아니라 노드마다 **딱 하나의 레이즈 사이즈 + 올인**만 제공됨.
- RFI(UTG): Raise 2.5 / Allin / Fold
- vs_open(HJ vs UTG 오픈): Raise 8 / Call / Allin / Fold
- 콜드-4벳(CO, UTG오픈+HJ3벳 뒤): Raise 17.5 / Allin / Fold (콜 없음)
- 5벳(BTN, …4벳 뒤): Raise 35 / Allin / Fold

→ 트리의 분기 폭발이 "베팅 사이즈"에서 오지 않는다. 분기는 **누가 fold/call/raise/allin
하느냐**에서만 온다. 이것이 트리를 유한·소규모로 유지하는 핵심.

### 핵심 발견 2 — 리레이즈 깊이 (100bb 기준)
사이즈 에스컬레이션: **2.5(오픈) → 8(3벳) → 17.5(4벳) → 35(5벳) → 올인(6벳)**.
100bb에서 명시 레이즈 약 4단계 후 올인이 강제된다(5벳 35 이후 다음 공격은 사실상 올인).
스택 깊이가 바뀌면 이 단계 수도 바뀌지만, 우리는 **항상 100bb 가정**을 유지한다
(헤즈업 포함, docs/gto-data.md의 근사 원칙과 동일).

### 핵심 발견 3 — 스퀴즈/콜드콜/콜드-4벳 노드가 전부 존재하고 solvable
"UTG 오픈 → HJ 3벳 → CO 콜드-4벳" 같은 노드가 GTO Wizard에 실제로 있음(위에서 확인).
현재 우리 모델(오프너 본인만)이 스킵하던 바로 그 상황들이 여기서 채워진다.

### 핵심 발견 4 — 콜 옵션의 등장/소멸
Call은 vs_open(오픈에 대한 플랫콜)에는 있으나, 4벳+ 노드에는 없어짐(Fold/Raise/Allin만).
파서/스키마는 노드마다 가능한 액션 집합이 다름을 전제해야 한다.

### 핵심 발견 5 — 사이즈는 노드/포지션 의존, 공식 추론 불가
같은 "오픈에 대한 3벳"이라도 포지션마다 사이즈가 다름(기존 확인: HJ 3벳=8, SB=11, BB=13.5).
**모든 사이즈는 수집 시 화면에서 실측**해야 하며 계산/보간 금지.

### URL = 자연스러운 캐노니컬 키
GTO Wizard URL이 전체 경로를 그대로 인코딩한다:
`preflop_actions=R2.5-R8-R17.5-F-F&history_spot=N`
(F=fold, C=call, R{bb}=raise to, 포지션 순서 UTG→HJ→CO→BTN→SB→BB로 매핑,
history_spot=N=지금까지 나온 액션 수=현재 액션할 좌석의 결정 시점 인덱스).
→ 이 `preflop_actions` 문자열이 그대로 우리 노드 키가 된다.

---

## 스키마 설계 (②)

### 키 = 액션 시퀀스 문자열
현재 `(position, vs_position, range_type)` enum 3종 키를
**정규화된 액션 시퀀스 문자열**(GTO Wizard `preflop_actions` 포맷)로 교체.
- 예: 현재 "HJ vs UTG open" = `R2.5-F` (UTG 2.5 오픈, HJ 결정 시점) → history_spot=1
- 예: 현재 "UTG vs HJ 3bet" = `R2.5-R8` → history_spot=2 (오프너 UTG가 3벳에 대응)
- 지금까지 모은 11~35개 조합은 포지션 순서/range_type 의미에서 시퀀스 문자열을
  **결정론적으로 역산 가능** → 마이그레이션 가능, 버릴 데이터 없음.

### 테이블 방향 (구현 시 확정)
- 안 A: `gto_preflop_situations`에 `action_seq TEXT` 컬럼 추가 + UNIQUE(action_seq).
  기존 (position, vs_position, range_type)은 조회 편의/디버깅용으로 파생 유지 or 폐기.
- 안 B: 신규 `gto_preflop_nodes(action_seq PK, hero_position, num_active, raise_size)`
  + 핸드 빈도는 기존 `gto_preflop_hands`를 새 FK로 재사용.
- 어느 쪽이든: `hero_position`, `num_active`(참여 인원)는 시퀀스에서 파생해 인덱스/쿼리용
  컬럼으로 둔다. `raise_size`는 그 노드에서 히어로가 레이즈할 때의 실측 to-금액(bb).

### 사이징 그래뉼래리티 (조회 시 필수 처리)
실전(사람/봇)의 베팅은 연속값인데 솔브 트리는 노드당 이산 사이즈 1개.
실시간 조회 시 **실제 시퀀스를 캐노니컬 노드로 스냅**해야 한다:
각 레이즈를 "그 노드의 캐노니컬 사이즈"로 반올림 매핑(예: 실전 3벳 7.5bb → 노드 8 트리로).
스냅 규칙은 ② 구현 시 정의(가장 가까운 캐노니컬 사이즈, 없으면 미수집 큐로).

---

## ② 구현 결정 및 완료 (2026-07-15, 순수 코드)

### 택한 스키마 = 안 A (저위험, additive)
`gto_preflop_situations`에 `action_seq TEXT`(캐노니컬 노드 키) + `hero_position TEXT`
+ `num_active INTEGER`(파생) 컬럼을 **추가**. 기존 `(position, vs_position, range_type)`
enum 컬럼과 UNIQUE는 **그대로 유지**(레거시/파생, nullable). 노드 키 유니크는 별도
부분 유니크 인덱스 `idx_gto_pre_seq`로 강제(SQLite ADD COLUMN이 UNIQUE 인라인 불가 +
nullable 다수 NULL 허용). `SCHEMA_VERSION` 11→12.
- **안 B(신규 gto_preflop_nodes 테이블) 반려 이유**: 핸드 빈도 FK 재배선/조회부 이중화
  비용이 크고, 기존 35개 enum 경로·봇·테스트를 건드릴 표면이 넓어짐. 안 A는 컬럼 추가만으로
  두 조회 경로를 병렬 공존시켜 "additive & non-breaking" 원칙에 가장 부합.

### 캐노니컬 스냅 = **레이즈 깊이 기준**(사이즈-근접 아님) — 핵심 결정
`gto/url_generator.py`에 단일 소스로 정의:
```
CANONICAL_OPEN_SIZE      = {UTG:2.5, HJ:2.5, CO:2.5, BTN:2.5, SB:3.5}   # 깊이1(오픈), 포지션 의존
CANONICAL_RAISE_BY_DEPTH = {1:2.5, 2:8.0, 3:17.5, 4:35.0}               # 3벳=8, 4벳=17.5, 5벳=35
```
`canonical_raise_size(depth, position)` — 저장(백필/save)과 런타임(advisor)이 **같은 함수**를
호출. 스냅은 베팅 **금액**이 아니라 **레이즈 순번(깊이)**으로 한다.
- **왜 사이즈-근접이 아니라 깊이인가**: 실측 3벳이 포지션마다 8/11/13.5bb로 흩어지는데,
  단순 "가장 가까운 캐노니컬 사이즈"로 스냅하면 13.5bb 3벳이 4벳(17.5)에 더 가까워
  **깊이 오분류**가 발생한다. 깊이는 액션 순서로 구조적으로 결정되므로 이 함정을 원천 차단.
- **트레이드오프**: 3벳+ 깊이는 포지션 의존 실제 사이즈(11/13.5)를 단일 캐노니컬(8)로 **뭉갠다**.
  이는 의도된 근사 — 저장 노드 키와 런타임 조회 키가 동일 테이블을 쓰므로 항상 매칭되는 것이
  최우선(키 생성 일원화). 노드의 히어로 **자기** 레이즈 사이즈(4벳 실측 등)는 `raise_size`
  컬럼에 그대로 보존되므로 봇 사이징 정보는 손실 없음(노드 키에만 스냅 적용).

### 노드 키 규약
- 노드 키 = 히어로가 결정하기 **직전까지**의 액션 시퀀스(자기 이번 액션 제외).
  GTO Wizard `preflop_actions` + `history_spot`(=토큰 수) 규약과 동일.
- 토큰: `F`=fold, `X`=check, `C`=call, `R{bb}`=raise/allin(깊이 캐노니컬 사이즈).
  포지션 순서 UTG→HJ→CO→BTN→SB→BB. RFI UTG = `""`(빈 문자열).
- 생성 단일 소스: `url_generator.situation_to_node_key(enum)`(백필/save 파생) ↔
  `advisor.canonical_node_key(preflop_seq)`(런타임 스냅). 두 함수는 같은 캐노니컬 사이즈
  테이블을 공유 → 결정론적으로 동일 문자열 생성.

### 마이그레이션 결과 (poker.db, 11행)
| 항목 | 값 |
|---|---|
| situations / hands | 11 / 1778 (변동 0, 데이터 손실 0) |
| action_seq 백필 | 11/11, 전부 distinct, NULL 0 |
| vs_3bet 정규화 | BTN 행 `vs_position` `"BB"` → `"BTN/BB"`(opener/three_bettor) |
백필 노드 키: RFI(`""`/`F`/`F-F`/`F-F-F`/`F-F-F-F`), vs_open(`R2.5` / `F-F-F-R2.5` /
`F-F-F-R2.5-F` / `R2.5-F-F-F-F`), vs_3bet(`R2.5-R8-F-F-F-F`, `F-F-F-R2.5-F-R8`).
마이그레이션은 `db/schema.py::backfill_v12`(콜러블 마이그레이션 스텝, `db/connection.py`가
SQL 문자열/콜러블 모두 지원하도록 확장) — 실행 전 `poker.db.pre-seq-migration.bak` 백업.

### 부수 수정 (같이 처리)
- **vs_3bet 포맷 불일치 정규화**로 인계된 버그가 함께 해소: `BTN vs BB 3bet`이 이제 enum
  경로(`get_vs_3bet_range('BTN','BTN','BB')`)로도 정상 조회됨(전엔 `"BB"` 반쪽 저장이라
  loader의 `opener/three_bettor` 키와 불일치해 None이었음). `save` 엔드포인트도 같은
  규칙으로 저장 시 정규화.
- **`vs_3bet_url` 선행 폴드 누락 버그 수정**: 비-UTG 오프너(예: BTN)일 때 오프너 앞
  포지션들의 폴드가 URL에 빠져 잘못된 노드를 가리키던 문제를 수정(노드 키 생성과 일관).

### 검증 게이트 (통과)
- `tests/run_all.py --full` 전체 통과(poker_full 60 + equity 39 + grader 31, 0 실패).
- 유닛테스트 3종 추가: 6-13(enum 키=시퀀스 키 동일 레인지), 6-14(런타임 사이즈 스냅→노드
  매핑), 6-15(마이그레이션 vs_3bet 포맷 정규화).
- `scripts/audit_gto_preflop.py` 통과(11 스팟). 실 DB에서 enum↔seq 두 경로가 11개 전부
  동일 객체 반환 확인. advisor 스모크(UTG RFI 정상, 스퀴즈 BTN None 폴백) 정상.

### 사용자 검토 필요 / 미결 질문
1. **3벳+ 깊이 캐노니컬을 단일값(8/17.5/35)으로 뭉갠 근사**가 조회 정확도에 충분한지 —
   ④ 수집에서 포지션별 실측 3벳(11/13.5 등)을 별도 노드로 나눌지, 계속 깊이-8로 스냅할지
   ⑤ 파일럿 아레나 bb/100로 판단 필요.
2. **allin 노드 키 표현**: 현재 allin도 깊이 기준 `R{캐노니컬}`로 스냅(현 수집분에 allin
   노드 키 없어 매칭 이슈 0). ④에서 실측 allin 노드 수집 시 별도 토큰(`A` 등) 필요 여부 재검토.
3. **num_active 정의**(=6 − 폴드 토큰 수 = 히어로 결정 시점 미폴드 인원)는 조회 편의용
   근사 — 멀티웨이 세분화 쿼리에 쓸 때 정의가 충분한지 확인.

### ④(수집)로 넘길 때 주의점
- 수집 노드 키는 `situation_to_node_key` 또는 실전 `canonical_node_key`가 만든 **캐노니컬
  스냅 키**로 저장해야 런타임 조회와 매칭됨(GTO Wizard 화면 실측 사이즈를 그대로 키에 넣지 말 것).
- 단, GTO Wizard **이동 URL**(`url_generator.url_from_node_key`)은 캐노니컬 사이즈를 쓰므로
  3벳+에서 화면 실측 사이즈(13.5 등)와 다를 수 있음 → 이동 후 반드시 화면 사이징 확인
  (`THREE_BET_SIZE` 경고와 동일 원칙). `raise_size` 컬럼엔 화면 실측값을 저장.
- `save` 엔드포인트는 `action_seq`를 직접 받거나(임의 노드) enum에서 파생 가능. 스퀴즈/멀티웨이
  같은 enum-불가 노드는 `action_seq`를 명시해 저장하면 시퀀스 경로로만 조회된다.

---

## 실시간 조회를 위한 선행 조건 (①) — 코드 조사 결과

**게임 진행 중 advisor가 쓸 구조화된 액션 히스토리가 현재 코드에 없다.**
- `core/game.py`의 `event_log`: `_emit("action", {player, action(한글), amount})`로
  기록되나 **position/street 필드가 없고, 아무도 소비 안 함**(dead code에 가까움).
  포지션은 `get_positions()`(이름→라벨, 헤즈업은 "BTN/SB")로 별도 조회해야 함.
- 실제 동작 경로는 `server/session.py`의 `action_log: List[str]`(한글 텍스트,
  예 "UTG 레이즈 2.5bb")이고, `gto/advisor.py`가 이를 **문자열 부분매칭**으로
  재파싱(`_count_preflop_raises`, `_find_raisers_in_log`) → 콜/정확한 순서/참여
  인원을 구조적으로 판별 불가.
- DB `preflop_actions` 테이블은 핸드 종료 후 기록용이라 실시간 조회 불가.

### ① 구현 방향
`core/game.py`에 프리플랍 구조화 시퀀스 생성을 추가:
- `event_log`의 "action" 이벤트에 position(get_positions로) + street를 포함하거나,
  `TexasHoldem.preflop_action_seq()` 헬퍼로 프리플랍(플랍 street_started 이전) 액션을
  `[{position, action: fold|call|raise|allin|check, amount_bb}]`로 반환.
- `_get_game_state()`에 이 구조화 시퀀스를 노출(예: `preflop_seq`).
- `gto/advisor.py`가 한글 파싱 대신 이 구조화 시퀀스 → 캐노니컬 `preflop_actions`
  문자열로 변환 후 조회. 블라인드(SB/BB 강제 베팅)는 시퀀스에 액션으로 넣지 않음
  (GTO Wizard 포맷과 동일 — 자발적 액션만).
- **호환성**: 기존 35개 enum 조회 경로가 깨지지 않도록, ② 스키마 전환 전까지는
  구조화 시퀀스 → 기존 enum(RFI/vs_open/vs_3bet) 판정으로 매핑하는 어댑터를 두거나,
  ②와 함께 시퀀스 키 조회로 일괄 전환. 모든 기존 테스트 통과가 게이트.

### ① 구현 완료 (2026-07-15)

**택한 방식 = event_log 이벤트 강화 + 별도 파생 메서드.**
- `core/game.py::apply_action`의 "action" 이벤트에 `position`(get_positions,
  헤즈업 "BTN/SB" 원본 유지) + `street` + `to_amount`(해당 라운드 도달 총 베팅액;
  fold/check는 None) 필드 추가. event_log는 기존에 미사용(외부 소비자 0)이라 필드
  추가는 완전 하위 호환.
- `core/game.py::preflop_action_seq()`: event_log를 `street=="프리플랍"`으로 필터
  → `[{position, action: fold|call|raise|allin|check, amount_bb}]` 반환
  (amount_bb = to_amount / big_blind). 블라인드는 "blinds" 이벤트라 자동 제외.
- `_get_game_state()`에 `preflop_seq` 노출. `server/session.py`는 advisor 호출 시
  `game._get_game_state()`를 그대로 쓰므로 자동 전달(session.py 변경 불필요).
  UI 표시용 한글 `action_log`는 그대로 유지.
- `gto/advisor.py`: 한글 문자열 파서(`_count_preflop_raises`/`_find_raisers_in_log`)를
  seq 기반(`_count_raises`/`_raisers`)으로 교체. 라우팅/헤즈업 매핑/모델-밖 가드는
  동작 불변. **기존 quirk 보존**: raise 카운트는 "raise"만(allin 제외 — 구 파서가
  "레이즈" 문자열만 셌던 것과 동일). vs_open 오프너는 seq 첫 레이저, 레이즈 없이
  current_bet>BB인 올인 엣지만 `find_opener_position` 폴백.
- `gto/advisor.py::canonical_preflop_actions(seq)`: F/X/C/R{bb} 캐노니컬 문자열
  생성 헬퍼(② 노드 키 생성에 재사용).

**검증**: `run_all.py --full` 전체 통과 + 유닛테스트 3종 추가(스퀴즈 콜 구조화/
헤즈업 라벨 유지/vs_open 라우팅). ②로 넘길 때 주의: 실 DB의 vs_3bet `vs_position`
저장 포맷이 불일치(UTG는 "UTG/HJ", BTN은 "BB") — ② 마이그레이션 때 정규화 필요.

---

## 수집·검증 전략 (④⑤⑥)

- **④ 수집 엔진**: 노드 수가 커질 수 있어 Chrome 수동 수집(토큰)으로는 규모 부적합.
  TODO "GTO 수집 Playwright 완전 자동화"가 선행되거나 이 작업이 그 첫 실사용 사례.
  트리 워크: BFS/DFS로 `preflop_actions` 경로를 넓혀가며 각 노드 수집(노드당 레이즈
  사이즈는 화면 실측 후 다음 경로 문자열에 사용 — 추측 조립 금지).
- **⑤ 파일럿+검증**: 전체 크롤링 전에 스퀴즈/멀티웨이 소수 노드만 수집 →
  아레나 bb/100으로 "equity 휴리스틱 대비 개선" 확인(포스트플랍 계획과 동일 게이트).
  실전 볼륨 대부분(싱글레이즈/싱글3벳)은 이미 35개로 커버되므로 이득은 롱테일에 집중.
- **⑥ 본격 확장**: 파일럿에서 개선 확인 시 트리 전체로 확장. 개선 없으면 롤백.

---

## 알고 시작하는 한계

- 항상 100bb 가정(스택별 재솔브 안 함) — 헤즈업/딥/숏 모두 100bb 트리로 근사.
- 실전 베팅 사이즈는 캐노니컬 노드로 스냅 → 스냅 오차는 근사로 남음.
- GTO Wizard 무료 한도(100스팟/일)가 수집 속도를 제한 → 트리 전체는 여러 날 소요 가능.
