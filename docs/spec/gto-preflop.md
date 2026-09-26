# 프리플랍 GTO — 현재 사양

> 최종 갱신: 2026-09-26 · 관련 결정: [0005](../decisions/0005-100bb-and-headsup-sb.md), [0005](../decisions/0005-100bb-and-headsup-sb.md), [0003](../decisions/0003-layered-css-parser.md), [0004](../decisions/0004-raise-size-measured.md), [0008](../decisions/0008-node-key-action-seq.md), [0009](../decisions/0009-measured-size-node-key.md), [0010](../decisions/0010-runtime-sibling-snap.md), [0011](../decisions/0011-data-driven-tree-collection.md), [0002](../decisions/0002-gto-values-verbatim.md), [0006](../decisions/0006-enum-first-and-model-guards.md), [0012](../decisions/0012-collector-operational-safety.md), [0013](../decisions/0013-no-arena-gate-collection-as-routine.md), [0037](../decisions/0037-allin-only-snaps-to-allin-sibling.md)
> 수집 현황: `python3 scripts/gto_tree_report.py` → `docs/gto-preflop-progress.md`(로컬 DB·체크포인트에서 생성, git 제외)

## 무엇을 하는가

GTO Wizard(6-max, `Cash6mGeneral_6mNL25R25`, 100bb) 프리플랍 솔루션을 노드(히어로 결정 지점) 단위로 긁어 SQLite(`poker.db`)에 169핸드 액션 빈도로 저장한다.
게임 중에는 현재 프리플랍 상황을 저장된 노드에 대응시켜 **사람 힌트**(`gto_hint`, GTO 패널), **봇 프리플랍 액션**(`gto_compliance` 확률), **플레이 평가**(`gto_freq`, Play Grader)에 쓴다.
대응 노드가 없거나 데이터가 손상됐으면 추측하지 않고 `None` → 상위(봇·힌트)는 휴리스틱 폴백 또는 힌트 없음.
포스트플랍 GTO는 이 도메인이 아니다(없음).

## 규칙 (지금 유효한 것만)

### 데이터 기준
- 솔루션은 항상 6-max·100bb 한 종류다. 스택 깊이·인원(헤즈업 포함)이 달라도 재솔브하지 않고 이 트리로 근사한다 — 근거: [0005](../decisions/0005-100bb-and-headsup-sb.md) · 강제 장치: 장치 없음
- 핸드 표기는 169개(`AA`/`AKs`/`AKo`, 10은 `T`) — 근거: 없음(GTO Wizard 표기) · 강제 장치: 장치 없음 (`hand_to_notation` 직접 테스트 없음)
- 핸드별 `fold+call+raise+allin` 합이 [0.9, 1.1] 밖이면 그 핸드는 로드 시 건너뛰고 경고 로그를 남긴다. 잔여를 fold 등 특정 액션에 몰아주지 않는다 — 근거: [0002](../decisions/0002-gto-values-verbatim.md) · 강제 장치: `tests/test_poker_full.py::test_7_2_corrupt_hand_skipped_not_folded`
- 노드에 없는 핸드(오프너 레인지 밖이라 셀이 비어 있던 핸드 = 저장 안 됨)를 조회하면 `None`이다(fold 100%로 채우지 않는다) — 근거: [0002](../decisions/0002-gto-values-verbatim.md) · 강제 장치: `tests/test_poker_full.py::test_7_3_missing_hand_returns_none`
- `raise_size`는 그 노드에서 히어로가 레이즈할 때의 **화면 실측** raise-to(bb, REAL). 모르면 NULL. 배수 공식·플레이스홀더로 채우지 않는다 — 근거: [0004](../decisions/0004-raise-size-measured.md) · 강제 장치: 장치 없음

### 노드 키 (`action_seq`)
- 노드 키 = 히어로가 결정하기 **직전까지**의 자발적 액션 시퀀스. GTO Wizard `preflop_actions` 포맷과 같다: 토큰 `F`/`X`/`C`/`R{bb}`, `-`로 연결, 좌석 순서 UTG→HJ→CO→BTN→SB→BB, 블라인드는 토큰이 아니다. UTG RFI = `""` — 근거: [0008](../decisions/0008-node-key-action-seq.md) · 강제 장치: `tests/test_poker_full.py::test_6_10_squeeze_seq_includes_call`(캐노니컬 문자열), `::test_6_13_seq_key_and_enum_key_same_range`
- GTO Wizard 이동 URL = `preflop_actions=<노드 키>&history_spot=<토큰 수>`(`url_from_node_key`) — 강제 장치: 장치 없음
- 저장 키의 레이즈·올인 토큰은 **화면 실측 사이즈 그대로**(예 `R13.5`, 올인 `R100`). 깊이별 캐노니컬 사이즈로 뭉개지 않는다 — 근거: [0009](../decisions/0009-measured-size-node-key.md) · 강제 장치: `tests/test_gto_tree.py::test_compute_children_uses_measured_size`
- `/gto/preflop/save`에 `action_seq`가 오면 그대로 저장한다. 없을 때만 레거시 `situation_to_node_key`(깊이-캐노니컬 사이즈 표: 오픈 2.5/SB 3.5, 3벳 8, 4벳 17.5, 5벳 35)로 파생한다. 신규 코드는 이 표를 쓰지 않는다 — 근거: [0009](../decisions/0009-measured-size-node-key.md) · 강제 장치: `tests/test_poker_full.py::test_6_13_seq_key_and_enum_key_same_range`, `::test_6_14_runtime_snap_maps_near_size_to_node`(파생 키 값만 검증, save 엔드포인트 자체는 장치 없음)
- `vs_3bet`의 `vs_position`은 `opener/three_bettor` 형식. 반쪽(`"BB"`)이 오면 저장 시 `"<position>/BB"`로 정규화한다 — 강제 장치: `tests/test_poker_full.py::test_6_15_migration_normalizes_vs3bet_format`, `tests/test_poker_full.py::test_7_6_save_normalizes_vs3bet_half_format`

### 게임 중 조회 (`gto/advisor.py`)
- 입력은 `core/game.py::preflop_action_seq()`가 만든 구조화 시퀀스(`game_state["preflop_seq"]`, 포지션·액션·to-amount bb). 한글 `action_log` 파싱이 아니다 — 근거: [0007](../decisions/0007-structured-preflop-seq.md) · 강제 장치: `tests/test_poker_full.py::test_6_10_squeeze_seq_includes_call`, `::test_6_11_headsup_seq_labels_btnSB`
- 조회 순서: **enum 경로 먼저**(RFI / vs_open / vs_3bet, `(position, vs_position, range_type)` 키), 없으면 **시퀀스 키 경로**로 폴백 — 근거: [0006](../decisions/0006-enum-first-and-model-guards.md) · 강제 장치: `tests/test_poker_full.py::test_6_12_vs_open_routing_via_seq`, `::test_6_14_runtime_snap_maps_near_size_to_node`
- enum 경로의 라운드 판정: `current_bet <= BB`면 RFI, 자발 `raise`가 1회 이하면 vs_open, 2회면 vs_3bet, 3회 이상이면 enum은 `None`. `allin`은 raise 횟수에 세지 않는다 — 강제 장치: 장치 없음
- enum 경로의 데이터 모델 밖 가드(조회도 큐 기록도 하지 않고 `None`): BB는 RFI 불가 / vs_open에서 오프너가 히어로보다 뒤 좌석 / vs_3bet에서 히어로 ≠ 오프너 — 근거: [0006](../decisions/0006-enum-first-and-model-guards.md) · 강제 장치: `tests/test_poker_full.py::test_6_10_squeeze_seq_includes_call`, `tests/test_poker_full.py::test_7_4_bb_never_rfi_and_no_queue`, `tests/test_poker_full.py::test_7_5_vs_open_opener_after_hero_is_none`
- 헤즈업 딜러 라벨 `BTN/SB`는 enum 경로에서만 `SB`로 치환해 6-max SB 데이터를 재사용한다(게임·UI 라벨은 `BTN/SB` 유지) — 근거: [0005](../decisions/0005-100bb-and-headsup-sb.md) · 강제 장치: `tests/test_poker_full.py::test_6_9_headsup_gto_btnSB_mapped_to_sb_rfi`, `::test_6_11_headsup_seq_labels_btnSB`
- 시퀀스 경로 스냅: 라이브 레이즈마다 그 프리픽스에서 **수집된 레이즈 형제**(`loader.get_children_by_prefix`) 중 bb 절대거리 최소로 스냅한다. 형제가 하나면 거리와 무관하게 그것. 사이즈 미상 레이즈는 형제가 하나일 때만. 형제가 없으면 `None` — 근거: [0010](../decisions/0010-runtime-sibling-snap.md) · 강제 장치: `tests/test_poker_full.py::test_6_14_runtime_snap_maps_near_size_to_node`, `::test_6_16_realsize_node_snaps_to_collected_sibling`, `::test_6_18_two_siblings_snap_to_nearest_bb`
- 라이브 **올인**은 위 규칙을 그대로 쓰지 않고 "올인 형제"로 후보를 좁힌다: 이 프리픽스 노드 자신의 저장된 `raise_size`(수집 당시 "레이즈" 액션 실측 사이즈)와 정확히 일치하는 형제는 "레이즈" 토큰임이 확정되므로 제외하고, 남는 형제(있다면)만 대상으로 스냅한다(숏스택 올인이 산술적으로 가깝다는 이유로 일반 레이즈 노드에 스냅되는 것 방지). 남는 형제가 없으면(올인 데이터 미수집, 혹은 이 프리픽스의 raise_size를 몰라 구분 불가) `None` — 근거: [0037](../decisions/0037-allin-only-snaps-to-allin-sibling.md) · 강제 장치: `tests/test_poker_full.py::test_6_19_allin_snaps_to_allin_sibling_not_nearest_raise`, `::test_6_20_allin_with_no_allin_sibling_returns_none`
- 스냅 실패 시 실측 라이브 키를 큐(`gto_missing_spots_preflop`, `range_type='seq'`, 노드 키는 `vs_position` 칸)에 넣고 `None`. 빈 키는 넣지 않는다. enum 경로 미수집은 `open`/`vs_open`/`vs_3bet` 행으로 큐에 넣는다 — 강제 장치: `tests/test_poker_full.py::test_6_17_uncollected_branch_returns_none_and_queues`(seq만)
- 봇: `random() > gto_compliance`면 GTO를 쓰지 않는다. 샘플된 `fold`인데 콜 비용 0이면 체크. `raise`면 `raise_size`(실측)를 쓰고, NULL이면 폴백 공식(오픈 2.5bb / 오픈 상대 ×3 / 그 이상 ×2.5, 스택 70%↑ 올인). 샘플된 `allin`은 `Action.ALL_IN`을 그대로 실행한다(레이즈로 뭉개거나 휴리스틱으로 떨어지지 않음). GTO가 `None`이고 raise 3회 이상이면 강한 패만 올인·나머지 폴드 — 근거: T-014 · 강제 장치: `tests/test_equity.py::test_gto_allin_action_and_hint`
- 로더 캐시는 프로세스당 1회 로드. `/gto/preflop/save`가 저장 후 캐시를 비운다. DB를 다른 경로로 바꾸면 서버 재시작 전까지 반영 안 됨 — 강제 장치: `tests/test_poker_full.py::test_7_1_save_invalidates_loader_cache`

### 수집 (`scripts/collect_gto_tree.py` + `scripts/gto_tree_worker.py`)
- 트리는 가정으로 열거하지 않는다. 노드에서 **콤보 가중 합산 빈도 > ε(0.0005)** 인 액션만 자식으로 뻗는다(버튼 존재는 기준이 아니다). 베팅이 끝나는 자식(결정 노드 아님)은 순수 포커 규칙 시뮬레이터 `_replay`로 거른다 — 근거: [0011](../decisions/0011-data-driven-tree-collection.md) · 강제 장치: `tests/test_gto_tree.py::test_branch_actions_epsilon`, `tests/test_gto_tree.py::test_replay_terminal_nodes`
- 방문 순서는 도달확률(경로 빈도 누적) 내림차순 best-first — 근거: [0011](../decisions/0011-data-driven-tree-collection.md) · 강제 장치: 장치 없음
- 셀 파싱은 레이어 방식: 겹친 `linear-gradient` 레이어를 앞→뒤로 색상 매칭(allin/raise/call/fold), `background-size` 누적 폭 차분이 빈도. `background:none` 셀은 저장하지 않는다 — 근거: [0003](../decisions/0003-layered-css-parser.md) · 강제 장치: 장치 없음
- 한 핸드라도 합이 [0.9, 1.1] 밖(badSum)이거나 파싱 핸드 0개면 저장하지 않고 `failed`로 남긴다(자동 재시도 안 함, 사람 확인). 서버 저장 API는 합을 검증하지 않는다 — 강제 장치: 장치 없음
- 실측 사이즈는 히어로 Actions 패널(`[data-tst="study_action_btns"] [data-tst^="action_"]`)에서만 읽는다(`action_R<size>_n`=레이즈, `action_RAI_n`=올인·텍스트에서 사이즈, 못 읽으면 100). 레이즈 사이즈는 첫 번째 것 하나만 쓴다(노드당 1개 전제). 사이즈를 못 읽은 레이즈·올인 가지는 만들지 않는다 — 강제 장치: `tests/test_gto_tree.py::test_compute_children_uses_measured_size`(가지 생성만. DOM 읽기는 장치 없음)
- 렌더 완료 = 색칠된 셀 수가 600ms 이상 변하지 않음(절대 개수 임계값 아님) — 강제 장치: 장치 없음
- 일일 한도 판단은 상단 `X/100` 카운터만 권위로 본다(항시 떠 있는 안내 문구는 카운터를 못 읽을 때만 폴백). 남은 여유 ≤ `--safety-margin`(5)이면 다음 이동 전에 멈춘다. 한도에 걸린 노드는 frontier로 되돌린다 — 근거: [0012](../decisions/0012-collector-operational-safety.md) · 강제 장치: `tests/test_gto_tree.py::test_limit_hit_counter_authority`, `tests/test_gto_tree.py::test_run_requeues_node_on_limit_and_env_failure`
- 추출 환경 오류(navigate 실패·렌더 대기 타임아웃·추출 JS 실패)는 `failed`에 넣지 않고 frontier로 되돌린다. 연속 2회면 탭 재생성, 연속 6회(`CONSEC_ENV_ABORT_THRESHOLD`)면 안전 중단. 저장 25건마다 예방적 탭 재생성 — 근거: [0012](../decisions/0012-collector-operational-safety.md) · 강제 장치: `tests/test_gto_tree.py::test_env_failure_classification`, `tests/test_gto_tree.py::test_run_requeues_node_on_limit_and_env_failure`
- `/gto/preflop/save` POST 실패(로컬 백엔드가 꺼져 있는 등)도 `failed`에 넣지 않고 frontier로 되돌리되, 탭 재생성과는 별도의 연속 실패 카운터(`consec_save_fail`)로 센다. 같은 노드를 무한 재시도하며 GTO Wizard 일일 한도를 헛되이 소진하지 않도록, 추출 환경 오류와 동일한 기준(`CONSEC_ENV_ABORT_THRESHOLD`=6)에 도달하면 "서버 확인" 메시지와 함께 안전 중단한다(성공 시 카운터 리셋) — 근거: T-012 · 강제 장치: `tests/test_gto_tree.py::test_run_aborts_on_persistent_save_failure`
- 노드 사이 2~5초 균등 랜덤 지연. 로그인은 대행하지 않는다(사용자가 로그인해 둔 디버그 크롬에 CDP로 붙음) — 강제 장치: 장치 없음
- 저장 라벨은 `derive_node_meta`가 노드 키에서 유도: 레이저 0명=`open`("{H} RFI"), 1명=`vs_open`, 2명=`vs_3bet`, n명=`vs_{n+1}bet`, `vs_position`은 레이저 좌석을 `/`로 연결 — 강제 장치: `tests/test_gto_tree.py::test_derive_node_meta_labels`(림프 노드 제외 — T-016)

## 화면·경로·데이터

| 대상 | 무엇 | 비고 |
|---|---|---|
| `gto_preflop_situations` | 노드 1행: `position`,`vs_position`,`range_type`(open/vs_open/vs_3bet/vs_4bet/vs_5bet), `raise_size`, `situation_label`, `action_seq`, `hero_position`, `num_active`(=6−F 토큰 수) | `UNIQUE(position,vs_position,range_type)` + `idx_gto_pre_seq UNIQUE(action_seq)`. 상세 스키마: `db/schema.py`, 운영: [db.md](db.md) |
| `gto_preflop_hands` | 노드×핸드 `freq_fold/call/raise/allin` | FK CASCADE |
| `gto_missing_spots_preflop` | 미수집 스팟 큐(enum 행 + `range_type='seq'` 행) | `collected`를 1로 바꾸는 코드는 없다 |
| `POST /gto/preflop/save` | 노드 저장(덮어쓰기). 기존 행은 **`(position, vs_position, range_type)`으로 찾는다**. 핸드 전부 삭제 후 재삽입, 캐시 무효화 | 호출자: 수집 워커, 브라우저 수동 저장 |
| `GET /gto/preflop/range` | enum 키로 레인지 + 콤보가중 요약 | `action_seq`로는 조회 불가 |
| `GET /gto/preflop/situations` | 저장 노드 목록 | |
| 게임 상태 `gto_hint` | advisor 추천 문자열("📊 GTO [AKs] BTN RFI: 레이즈 100%") | `server/session.py::_get_gto_hint` |
| 게임 상태 `gto_key` → GTO 패널 | `server/session.py::_get_gto_key`가 한글 `action_log`로 따로 판정한 enum 키 → `/gto/preflop/range` | advisor와 판정 로직이 별개 |
| CORS | `https://*.gtowizard.com` 허용, 백엔드 HTTPS(8765) | 브라우저 수동 저장용(Mixed Content 방지) |

### 운영 방법

**자동 수집(기본)** — 매번 확인:
1. 평소 크롬을 모두 끄고 디버그 크롬을 띄운 뒤 그 창에서 `https://app.gtowizard.com`에 로그인, 실행 내내 켜 둔다.
   `/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --user-data-dir="$HOME/chrome-gto-debug"`
2. 백엔드 실행: `./start.sh` (`https://localhost:8765/docs` 응답 확인). 문제 시 `curl -s http://localhost:9222/json/version`으로 크롬 확인.
3. 최초 1회 파서 눈검증: `python3 scripts/collect_gto_tree.py --dry-run` (첫 노드만 추출, 저장 안 함).
4. 수집: `python3 scripts/collect_gto_tree.py --limit 200` — 한도 근처에서 스스로 멈춘다. 다음 날 같은 명령으로 이어간다. Ctrl+C도 안전.
5. 확인: `python3 scripts/audit_gto_preflop.py`(빈도합·RFI 순서·100% 쏠림), `python3 scripts/gto_tree_report.py`(현황 문서 재생성), `python3 scripts/show_missing_spots.py [--all]`(큐).

주요 옵션: `--limit`(기본 90) `--safety-margin`(5) `--min-delay/--max-delay`(2/5초) `--epsilon`(0.0005) `--nav-timeout`(30000ms) `--cdp-url`(`http://localhost:9222`) `--server`(`https://localhost:8765`) `--checkpoint`(`<repo>/gto_tree_checkpoint.json`, gitignore).
체크포인트(`visited`/`frontier`/`failed`)는 저장마다 원자적으로 기록된다. 체크포인트가 없거나 frontier가 비면 DB의 수집 트리를 루트부터 훑어 미수집 자식으로 frontier를 다시 만든다.

**수동 1스팟 재검증** — 특정 스팟을 눈으로 대조할 때만: 백엔드 실행 → 크롬에서 `https://localhost:8765` 인증서 허용 → GTO Wizard에서 스팟 이동 → 콘솔에서 `extractAndSave(position, label, raiseSize, vsPosition, rangeType)` 실행(badSum>0이면 저장 거부). 스크립트: `tools/gto_extract_and_save.js`(콘솔에 붙여 넣기). 수동 저장은 `action_seq`를 안 보내므로 레거시 파생 키가 된다(TODO T-001에서 수정).

**한도**: GTO Wizard 무료 계정은 프리플랍 **100스팟/일**(스팟 이동 1회 = 1). 회사 와이파이에서는 GTO Wizard 접속이 막혀 핫스팟이 필요하다.

## 알려진 한계

- 100bb 고정 — 딥/숏/헤즈업 모두 100bb 6-max 트리로 근사한다.
- 라이브 사이즈는 수집된 형제로 스냅되므로 사이즈 오차가 근사로 남는다. 형제가 하나면 거리 제한 없이 매칭한다(단, 라이브 올인은 올인 형제로만 좁혀 스냅 — 아래 "수집" 절 참고).
- enum 경로는 콜러·중간 액션을 구분하지 않는다(예: "BB vs BTN open"은 SB가 콜했든 폴드했든 같은 행). 멀티웨이·헤즈업 팟이 같은 데이터를 받는다 — D-02, T-001
- **저장 API가 `(position, vs_position, range_type)`으로 행을 찾으므로 이 3개가 같은 서로 다른 노드(예 `R2.5-F`와 `R2.5-C`)는 한 행에 덮어써진다** — 한 쪽만 남는다. 현재 vs_open 13행이 전부 콜러 있는 노드다. 수정 전에는 수집 워커를 돌리지 않는다 — T-001
- 헤즈업 시퀀스에는 앞 4좌석 폴드가 없어서, 시퀀스 경로로 가면 6-max UTG부터 시작하는 노드로 스냅될 수 있다(enum 경로만 `BTN/SB`→`SB` 치환) — T-001
- GTO 패널(`gto_key`)은 advisor와 별개로 한글 로그를 판정하고 enum 키만 조회한다 — 시퀀스로만 있는 노드(4벳+ 등)는 패널에 안 나오고, 힌트와 패널이 다른 노드를 가리킬 수 있다 — T-013
- 미수집 큐는 쌓이기만 한다 — 워커가 읽지 않고 `collected`도 갱신되지 않는다 — T-015
- 림프 노드(SB 림프 후 BB)가 `open`/"BB RFI"로 저장된다 — T-016
- `num_active`(= 6 − 폴드 토큰 수)는 아직 소비자가 없다. 멀티웨이 조회에 쓰기 시작할 때 정의가 충분한지 다시 본다.
- 수집은 무료 한도(100/일)에 묶여 트리 전체에 여러 날이 걸린다. 전체 규모는 미리 알 수 없다(현황 문서는 %를 쓰지 않는다).
- `audit_gto_preflop.py`는 `poker.db`를 직접 연다(`EV_PLUS_DB` 무시). 노드 키·라벨 일치나 덮어쓰기는 검사하지 않는다 — T-001(ADR 0040)
- 서버 저장 API는 빈도합을 검증하지 않는다(워커만 검증) — T-001
