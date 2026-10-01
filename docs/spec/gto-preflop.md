# 프리플랍 GTO — 현재 사양

> 최종 갱신: 2026-10-01 · 관련 결정: [0035](../decisions/0035-gto-lookup-sequence-first.md), [0044](../decisions/0044-node-row-key-is-action-seq.md), [0046](../decisions/0046-limp-nodes-are-vs-limp-not-open.md), [0005](../decisions/0005-100bb-and-headsup-sb.md), [0003](../decisions/0003-layered-css-parser.md), [0004](../decisions/0004-raise-size-measured.md), [0008](../decisions/0008-node-key-action-seq.md), [0009](../decisions/0009-measured-size-node-key.md), [0010](../decisions/0010-runtime-sibling-snap.md), [0011](../decisions/0011-data-driven-tree-collection.md), [0002](../decisions/0002-gto-values-verbatim.md), [0006](../decisions/0006-enum-first-and-model-guards.md), [0012](../decisions/0012-collector-operational-safety.md), [0013](../decisions/0013-no-arena-gate-collection-as-routine.md), [0037](../decisions/0037-allin-only-snaps-to-allin-sibling.md), [0040](../decisions/0040-no-arena-gate-audit-checks.md)
> 수집 현황: `python3 scripts/gto_tree_report.py` → `docs/gto-preflop-progress.md`(로컬 DB·체크포인트에서 생성, git 제외)

## 무엇을 하는가

GTO Wizard(6-max, `Cash6mGeneral_6mNL25R25`, 100bb) 프리플랍 솔루션을 노드(히어로 결정 지점) 단위로 긁어 SQLite(`poker.db`)에 169핸드 액션 빈도로 저장한다.
게임 중에는 현재 프리플랍 상황을 저장된 노드에 대응시켜 **사람 힌트**(GTO 패널, 게임 상태 `gto`), **봇 프리플랍 액션**(`gto_compliance` 확률), **플레이 평가**(`gto_freq`, Play Grader)에 쓴다.
대응 노드가 없거나 데이터가 손상됐으면 추측하지 않고 `None` → 상위(봇·힌트)는 휴리스틱 폴백 또는 힌트 없음.
포스트플랍 GTO는 이 도메인이 아니다(없음).

## 규칙 (지금 유효한 것만)

### 데이터 기준
- 솔루션은 항상 6-max·100bb 한 종류다. 스택 깊이·인원이 달라도 재솔브하지 않는다. 헤즈업은 6-max SB vs BB 트리로 근사하고, 3~5인 테이블은 대응시키지 않는다(아래 "게임 중 조회") — 근거: [0005](../decisions/0005-100bb-and-headsup-sb.md) · 강제 장치: `tests/test_poker_full.py::test_6_9_headsup_gto_btnSB_mapped_to_sb_rfi`, `::test_7_22_short_handed_table_has_no_label_fallback`
- 핸드 표기는 169개(`AA`/`AKs`/`AKo`, 10은 `T`) — 근거: 없음(GTO Wizard 표기) · 강제 장치: 장치 없음 (`hand_to_notation` 직접 테스트 없음)
- 빈도합 허용 범위는 `gto/loader.py::FREQ_SUM_MIN/MAX`(0.9/1.1) 한 곳이다. 저장 API·로더·수집기·감사가 같은 `freq_sum_ok`를 쓴다 — 근거: [0002](../decisions/0002-gto-values-verbatim.md)
- 핸드별 `fold+call+raise+allin` 합이 범위 밖인 핸드가 하나라도 있거나 핸드가 0개인 노드는 저장 API가 422로 거부한다(저장 안 함) — 근거: [0002](../decisions/0002-gto-values-verbatim.md), [0044](../decisions/0044-node-row-key-is-action-seq.md) · 강제 장치: `tests/test_poker_full.py::test_7_9_save_rejects_corrupt_frequencies`
- 그래도 DB에 합이 범위 밖인 핸드가 있으면 그 핸드는 로드 시 건너뛰고 경고 로그를 남긴다. 잔여를 fold 등 특정 액션에 몰아주지 않는다 — 근거: [0002](../decisions/0002-gto-values-verbatim.md) · 강제 장치: `tests/test_poker_full.py::test_7_2_corrupt_hand_skipped_not_folded`
- 노드에 없는 핸드(오프너 레인지 밖이라 셀이 비어 있던 핸드 = 저장 안 됨)를 조회하면 `None`이다(fold 100%로 채우지 않는다) — 근거: [0002](../decisions/0002-gto-values-verbatim.md) · 강제 장치: `tests/test_poker_full.py::test_7_3_missing_hand_returns_none`
- `raise_size`는 그 노드에서 히어로가 레이즈할 때의 **화면 실측** raise-to(bb, REAL). 모르면 NULL. 배수 공식·플레이스홀더로 채우지 않는다 — 근거: [0004](../decisions/0004-raise-size-measured.md) · 강제 장치: 장치 없음

### 노드 키 (`action_seq`)
- 노드 키 = 히어로가 결정하기 **직전까지**의 자발적 액션 시퀀스. GTO Wizard `preflop_actions` 포맷과 같다: 토큰 `F`/`X`/`C`/`R{bb}`, `-`로 연결, 좌석 순서 UTG→HJ→CO→BTN→SB→BB, 블라인드는 토큰이 아니다. UTG RFI = `""` — 근거: [0008](../decisions/0008-node-key-action-seq.md) · 강제 장치: `tests/test_poker_full.py::test_6_10_squeeze_seq_includes_call`(캐노니컬 문자열), `::test_6_13_seq_key_and_enum_key_same_range`
- GTO Wizard 이동 URL = `preflop_actions=<노드 키>&history_spot=<토큰 수>`(`url_from_node_key`) — 강제 장치: 장치 없음
- 저장 키의 레이즈·올인 토큰은 **화면 실측 사이즈 그대로**(예 `R13.5`, 올인 `R100`). 깊이별 캐노니컬 사이즈로 뭉개지 않는다 — 근거: [0009](../decisions/0009-measured-size-node-key.md) · 강제 장치: `tests/test_gto_tree.py::test_compute_children_uses_measured_size`
- 노드 행의 유일 키는 `action_seq` 하나다(`NOT NULL` + 유니크 인덱스). 3종 키(`position`,`vs_position`,`range_type`)가 같은 서로 다른 노드(예 `F-F-F-R2.5-F`와 `F-F-F-R2.5-C`)는 각자 다른 행이다 — 근거: [0044](../decisions/0044-node-row-key-is-action-seq.md) · 강제 장치: `tests/test_poker_full.py::test_7_7_distinct_action_seq_distinct_rows`, `::test_7_14_migration_v13_preserves_data`
- `/gto/preflop/save`는 `action_seq` 필수(없으면 422). 행은 `action_seq`로만 찾아 덮어쓰거나 새로 넣는다. 깊이-캐노니컬 사이즈 표(`gto/url_generator.py::situation_to_node_key`)는 v12 백필에만 쓰인다 — 근거: [0009](../decisions/0009-measured-size-node-key.md), [0044](../decisions/0044-node-row-key-is-action-seq.md) · 강제 장치: `tests/test_poker_full.py::test_7_8_save_requires_action_seq_and_consistent_keys`
- 저장 행의 3종 키·`hero_position`·라벨 기본값은 서버가 `gto/node_key.py::derive_node_meta(action_seq)`로 유도한다: 레이저 0명 + 콜(림프) 없음=`open`("{H} RFI"), 레이저 0명 + 콜(림프) 있음=`vs_limp`("{H} vs {limper(s)} limp", `vs_position`은 림퍼 좌석을 `/`로 연결 — 근거: [0046](../decisions/0046-limp-nodes-are-vs-limp-not-open.md)), 레이저 1명=`vs_open`, 2명=`vs_3bet`, n명=`vs_{n+1}bet`, `vs_position`은 레이저 좌석을 `/`로 연결. 요청에 3종 키가 오면 유도값과 대조해 다르면 422, 결정 노드가 아닌 키(베팅 종료)도 422. `vs_3bet` 반쪽 포맷(`"BB"`)은 `"<position>/BB"`로 정규화한 뒤 대조한다 — 근거: [0044](../decisions/0044-node-row-key-is-action-seq.md) · 강제 장치: `tests/test_gto_tree.py::test_derive_node_meta_labels`, `tests/test_poker_full.py::test_7_8_save_requires_action_seq_and_consistent_keys`, `::test_7_6_save_normalizes_vs3bet_half_format`, `::test_6_15_migration_normalizes_vs3bet_format`(v12 백필)
- `range_type='open'`으로 저장됐지만 `derive_node_meta`가 `vs_limp`로 유도하는 행은 v14 마이그레이션(`db/schema.py::relabel_limp_nodes_v14`)이 `vs_limp`로 재라벨링한다. 그 밖의 라벨은 손대지 않는다 — 근거: [0046](../decisions/0046-limp-nodes-are-vs-limp-not-open.md) · 강제 장치: `tests/test_poker_full.py::test_7_15_migration_v14_relabels_limp_nodes`

### 게임 중 조회 (`gto/advisor.py`)
- 입력은 `core/game.py::preflop_action_seq()`가 만든 구조화 시퀀스(`game_state["preflop_seq"]`, 포지션·액션·to-amount bb). 한글 `action_log` 파싱이 아니다 — 근거: [0007](../decisions/0007-structured-preflop-seq.md) · 강제 장치: `tests/test_poker_full.py::test_6_10_squeeze_seq_includes_call`, `::test_6_11_headsup_seq_labels_btnSB`
- 조회 순서(`get_recommendation`): ① **액션 순서 키로 정확한 노드**(결과 `approx=False`) → ② 없을 때만 **간단 라벨**(RFI / vs_open / vs_3bet, `(position, vs_position, range_type)`)로 찾고 결과에 `approx=True` → ③ 둘 다 없으면 `None`(힌트 없음·봇 휴리스틱)이고 정확한 노드 키를 미수집 큐에 넣는다. 결과에는 쓰인 노드의 `node_key`가 실린다 — 근거: [0035](../decisions/0035-gto-lookup-sequence-first.md) · 강제 장치: `tests/test_poker_full.py::test_7_10_exact_node_preferred_over_label`, `::test_7_11_label_fallback_is_marked_approx`, `::test_6_12_vs_open_routing_via_seq`
- 근사 표시: `approx=True`면 GTO 패널 제목 뒤에 `"(근사)"`(예 "BB vs HJ open (근사)"), 힌트 문자열(`format_hint`, CLI)에 `"(근사)"`, 플레이 평가 사유 앞에 `"(근사) "`가 붙는다 — 근거: [0035](../decisions/0035-gto-lookup-sequence-first.md) · 강제 장치: `tests/test_poker_full.py::test_7_11_label_fallback_is_marked_approx`, `::test_7_19_label_fallback_panel_marked_approx`(세션 → 패널), `web/src/components/__tests__/gtoPanelLogic.test.ts`(제목 표기)
- **GTO 패널은 advisor 추천 하나에 묶인다**: 사람의 프리플랍 차례마다 `server/session.py::_get_gto_panel`이 `get_recommendation`을 한 번 불러 게임 상태 `gto` = `{found, position, node_key, approx, situation, hand, frequencies}`를 싣는다(추천이 없으면 `{found: false, position}`, 포스트플랍·폴드 후엔 `null`). 패널은 `node_key`로 `GET /gto/preflop/range?action_seq=`를 조회하고, 응답의 `action_seq`가 지금 노드와 다르면 쓰지 않는다. 내 패 빈도는 추천의 `frequencies` 그대로다. 그래서 힌트·평가·패널이 항상 같은 노드다(헤즈업 `F-F-F-F…`, 콜러 노드, 4벳+ 포함) — 근거: [0007](../decisions/0007-structured-preflop-seq.md), [0035](../decisions/0035-gto-lookup-sequence-first.md) · 강제 장치: `tests/test_poker_full.py::test_7_17_panel_is_bound_to_advisor_node_key`, `::test_7_18_headsup_first_decision_panel_shows_range`, `::test_8_5_headsup_btnsb_first_decision_has_gto_hint`, `web/src/components/__tests__/gtoPanelLogic.test.ts`(다른 노드 응답 무시)
- 간단 라벨은 그 라벨의 **콜러 없는 노드**(노드 키에 `C` 토큰 없음)만 가리킨다. 콜러 없는 노드가 없으면 라벨 조회는 `None`이다. 같은 라벨의 콜러 없는 노드가 둘 이상이면 먼저 저장된 행(id 작은 쪽)을 쓰고 경고 로그를 남긴다. `get_raise_range`/`get_call_range`(봇 상대 레인지)도 이 라벨 캐시를 쓴다 — 근거: [0044](../decisions/0044-node-row-key-is-action-seq.md) · 강제 장치: `tests/test_poker_full.py::test_7_12_headsup_pot_not_given_caller_node`
- 헤즈업(히어로·시퀀스·`positions`에 딜러 라벨 `BTN/SB`가 있음): 라이브 시퀀스 앞에 `F-F-F-F`를 붙여 6-max SB vs BB 트리의 노드 키로 조회하고, 라벨 경로는 `BTN/SB`를 `SB`로 치환한다(게임·UI 라벨은 `BTN/SB` 유지) — 근거: [0005](../decisions/0005-100bb-and-headsup-sb.md) · 강제 장치: `tests/test_poker_full.py::test_6_9_headsup_gto_btnSB_mapped_to_sb_rfi`, `::test_7_13_headsup_not_snapped_to_utg_tree`, `::test_7_12_headsup_pot_not_given_caller_node`, `::test_6_11_headsup_seq_labels_btnSB`
- 3~5인 테이블(`positions` 3~5명)은 액션 순서 키 경로도 간단 라벨 경로도 쓰지 않는다 — 추천 `None`(패널 "GTO 데이터 없음"), 큐 기록 없음 — 근거: [0005](../decisions/0005-100bb-and-headsup-sb.md) · 강제 장치: `tests/test_poker_full.py::test_7_22_short_handed_table_has_no_label_fallback`
- 노드 키가 가리키는 히어로(`derive_node_meta`)가 실제 히어로와 다르면(시퀀스 오염 등) 그 노드를 쓰지도, 큐에 넣지도 않는다 — 근거: [0044](../decisions/0044-node-row-key-is-action-seq.md) · 강제 장치: 장치 없음(간접: `::test_6_17_uncollected_branch_returns_none_and_queues`는 히어로가 맞는 완전한 시퀀스로만 큐 기록)
- 라벨 경로의 라운드 판정: 시퀀스에 `allin`이 있으면 `None`(올인을 레이즈 라벨로 읽지 않는다 — 근거: [0037](../decisions/0037-allin-only-snaps-to-allin-sibling.md)). RFI는 `current_bet <= BB`이고 시퀀스에 콜·레이즈가 없을 때만(림프 팟은 RFI가 아니다 — 근거: [0046](../decisions/0046-limp-nodes-are-vs-limp-not-open.md)). 자발 `raise` 1회=vs_open(오프너 = 첫 레이저), 2회=vs_3bet, 그 밖(레이즈 없는 림프 팟, 3회 이상)은 `None` — 강제 장치: `tests/test_poker_full.py::test_7_20_allin_in_seq_label_fallback_none_and_queued`, `::test_7_21_limped_pot_is_not_rfi`
- 라벨 경로의 데이터 모델 밖 가드(`None`): BB는 RFI 불가 / vs_open에서 오프너가 히어로보다 뒤 좌석 / vs_3bet에서 히어로 ≠ 오프너. 라벨 경로는 큐에 기록하지 않는다 — 근거: [0006](../decisions/0006-enum-first-and-model-guards.md) · 강제 장치: `tests/test_poker_full.py::test_6_10_squeeze_seq_includes_call`, `::test_7_4_bb_never_rfi_and_no_queue`, `::test_7_5_vs_open_opener_after_hero_is_none`
- 시퀀스 경로 스냅: 라이브 레이즈마다 그 프리픽스에서 **수집된 레이즈 형제**(`loader.get_children_by_prefix`) 중 bb 절대거리 최소로 스냅한다. 형제가 하나면 거리와 무관하게 그것. 사이즈 미상 레이즈는 형제가 하나일 때만. 형제가 없으면 `None` — 근거: [0010](../decisions/0010-runtime-sibling-snap.md) · 강제 장치: `tests/test_poker_full.py::test_6_14_runtime_snap_maps_near_size_to_node`, `::test_6_16_realsize_node_snaps_to_collected_sibling`, `::test_6_18_two_siblings_snap_to_nearest_bb`
- 라이브 **올인**은 "올인 형제"로 후보를 좁힌다: 이 프리픽스 노드 자신의 저장된 `raise_size`와 정확히 일치하는 형제는 레이즈 토큰이므로 제외하고, 남는 형제만 대상으로 스냅한다. 남는 형제가 없으면(올인 데이터 미수집, 또는 이 프리픽스의 raise_size를 몰라 구분 불가) `None` — 근거: [0037](../decisions/0037-allin-only-snaps-to-allin-sibling.md) · 강제 장치: `tests/test_poker_full.py::test_6_19_allin_snaps_to_allin_sibling_not_nearest_raise`, `::test_6_20_allin_with_no_allin_sibling_returns_none`
- 미수집 큐(`gto_missing_spots_preflop`, `range_type='seq'`, 노드 키는 `vs_position` 칸, `position`은 6-max 히어로 좌석)에는 정확한 노드·라벨 둘 다 없을 때만 넣는다. 넣는 키: 스냅 실패면 실측 라이브 키(헤즈업은 `F-F-F-F` 포함), 스냅은 됐지만 그 노드가 미수집이면 스냅된 키. 노드는 있고 그 핸드만 없거나 손상이면 넣지 않는다. 라벨 enum 행(`open`/`vs_open`/`vs_3bet`)은 넣지 않는다 — 근거: [0035](../decisions/0035-gto-lookup-sequence-first.md) · 강제 장치: `tests/test_poker_full.py::test_6_17_uncollected_branch_returns_none_and_queues`, `::test_7_11_label_fallback_is_marked_approx`(라벨로 답하면 미기록), `::test_7_12_headsup_pot_not_given_caller_node`, `::test_7_20_allin_in_seq_label_fallback_none_and_queued`
- 봇: `random() > gto_compliance`면 GTO를 쓰지 않는다. 샘플된 `fold`인데 콜 비용 0이면 체크. `raise`면 `raise_size`(실측)를 쓰고, NULL이면 폴백 공식(오픈 2.5bb / 오픈 상대 ×3 / 그 이상 ×2.5, 스택 70%↑ 올인). 샘플된 `allin`은 `Action.ALL_IN`을 그대로 실행한다. GTO가 `None`이고 raise 3회 이상이면 강한 패만 올인·나머지 폴드 — 강제 장치: `tests/test_equity.py::test_gto_allin_action_and_hint`
- 로더 캐시는 프로세스당 1회 로드(`gto/loader.py::read_preflop_nodes`로 노드+핸드를 한 번에 읽는다). `/gto/preflop/save`가 저장 후 `loader.invalidate()`로 캐시를 비운다. DB를 다른 경로로 바꾸면 서버 재시작 또는 `invalidate()` 전까지 반영 안 됨 — 강제 장치: `tests/test_poker_full.py::test_7_1_save_invalidates_loader_cache`

### 수집 (`scripts/collect_gto_tree.py` + `scripts/gto_tree_worker.py`)
- 트리는 가정으로 열거하지 않는다. 노드에서 **콤보 가중 합산 빈도 > ε(0.0005)** 인 액션만 자식으로 뻗는다(버튼 존재는 기준이 아니다). 베팅이 끝나는 자식(결정 노드 아님)은 순수 포커 규칙 시뮬레이터 `_replay`로 거른다 — 근거: [0011](../decisions/0011-data-driven-tree-collection.md) · 강제 장치: `tests/test_gto_tree.py::test_branch_actions_epsilon`, `::test_replay_terminal_nodes`
- 방문 순서는 도달확률(경로 빈도 누적) 내림차순 best-first — 근거: [0011](../decisions/0011-data-driven-tree-collection.md) · 강제 장치: 장치 없음
- 미수집 큐(`range_type='seq'`)는 매 실행 `load_missing_queue_from_db`로 읽어 `queue_frontier_additions`가 **보조 2순위**로 프론티어에 얹는다 — 고정 우선순위 `QUEUE_FRONTIER_REACH`=1e-9라 정상 트리 프론티어(reach ≥ ε)가 먼저 소진된다. 건너뛰는 키: 결정 노드가 아님 / 이미 수집됨 / **트리 밖**(경로의 수집된 조상 노드에서 다음 액션의 콤보 가중 빈도 ≤ ε — 예 UTG RFI 뒤 림프 `C`, 화면에 없는 사이즈 `R2.9`. 레이즈 토큰은 조상의 `raise_size`와 같으면 raise, 100bb면 allin, 그 밖의 사이즈는 0). 그 밖엔 **가장 얕은 미수집 조상**(자기 자신 포함)만 추가한다 — 조상이 먼저 수집돼야 자식이 정상 확장으로 이어지고, 다음 실행에서 한 단계 더 깊어진다. 저장 성공 시 큐 행 `collected` 갱신은 `POST /gto/preflop/save`가 맡는다 — 근거: [0011](../decisions/0011-data-driven-tree-collection.md) · 강제 장치: `tests/test_gto_tree.py::test_queue_frontier_additions_ancestor_first`, `::test_load_missing_queue_from_db_filters_collected`
- 셀 파싱은 레이어 방식: 겹친 `linear-gradient` 레이어를 앞→뒤로 색상 매칭(allin/raise/call/fold), `background-size` 누적 폭 차분이 빈도. `background:none` 셀은 저장하지 않는다 — 근거: [0003](../decisions/0003-layered-css-parser.md) · 강제 장치: 장치 없음
- 한 핸드라도 빈도합이 범위 밖(badSum)이거나 파싱 핸드 0개면 저장하지 않고 `failed`로 남긴다(자동 재시도 안 함, 사람 확인). 서버 저장 API도 같은 기준으로 거부한다(이중 방어) — 강제 장치: 워커 쪽은 장치 없음, 서버 쪽 `tests/test_poker_full.py::test_7_9_save_rejects_corrupt_frequencies`
- 실측 사이즈는 히어로 Actions 패널(`[data-tst="study_action_btns"] [data-tst^="action_"]`)에서만 읽는다(`action_R<size>_n`=레이즈, `action_RAI_n`=올인·텍스트에서 사이즈, 못 읽으면 100). 레이즈 사이즈는 첫 번째 것 하나만 쓴다(노드당 1개 전제). 사이즈를 못 읽은 레이즈·올인 가지는 만들지 않는다 — 강제 장치: `tests/test_gto_tree.py::test_compute_children_uses_measured_size`(가지 생성만. DOM 읽기는 장치 없음)
- 렌더 완료 = 색칠된 셀 수가 600ms 이상 변하지 않음(절대 개수 임계값 아님) — 강제 장치: 장치 없음
- 일일 한도 판단은 상단 `X/100` 카운터만 권위로 본다(항시 떠 있는 안내 문구는 카운터를 못 읽을 때만 폴백). 남은 여유 ≤ `--safety-margin`(5)이면 다음 이동 전에 멈춘다. 한도에 걸린 노드는 frontier로 되돌린다 — 근거: [0012](../decisions/0012-collector-operational-safety.md) · 강제 장치: `tests/test_gto_tree.py::test_limit_hit_counter_authority`, `::test_run_requeues_node_on_limit_and_env_failure`
- 추출 환경 오류(navigate 실패·렌더 대기 타임아웃·추출 JS 실패)는 `failed`에 넣지 않고 frontier로 되돌린다. 연속 2회면 탭 재생성, 연속 6회(`CONSEC_ENV_ABORT_THRESHOLD`)면 안전 중단. 저장 25건마다 예방적 탭 재생성 — 근거: [0012](../decisions/0012-collector-operational-safety.md) · 강제 장치: `tests/test_gto_tree.py::test_env_failure_classification`, `::test_run_requeues_node_on_limit_and_env_failure`
- `/gto/preflop/save` POST 실패(로컬 백엔드가 꺼져 있는 등)도 `failed`에 넣지 않고 frontier로 되돌리되, 별도의 연속 실패 카운터(`consec_save_fail`)로 센다. 6회(`CONSEC_ENV_ABORT_THRESHOLD`) 연속이면 "서버 확인" 메시지와 함께 안전 중단한다(일일 한도를 헛되이 소진하지 않기 위함, 성공 시 리셋) — 근거: [0012](../decisions/0012-collector-operational-safety.md) · 강제 장치: `tests/test_gto_tree.py::test_run_aborts_on_persistent_save_failure`
- 노드 사이 2~5초 균등 랜덤 지연. 로그인은 대행하지 않는다(사용자가 로그인해 둔 디버그 크롬에 CDP로 붙음) — 강제 장치: 장치 없음
- 워커는 노드 키와 `derive_node_meta`(`gto/node_key.py`, 서버와 같은 함수)로 유도한 3종 키·라벨을 함께 보낸다 — 강제 장치: `tests/test_gto_tree.py::test_derive_node_meta_labels`
- 체크포인트(`visited`/`frontier`/`failed`)는 저장마다 원자적으로 기록된다. 체크포인트가 없거나 frontier가 비면 DB의 수집 트리를 루트부터 훑어(`seed_frontier_from_db`) 미수집 자식으로 frontier를 만든다 — 강제 장치: `tests/test_gto_tree.py::test_run_requeues_node_on_limit_and_env_failure`(체크포인트 없이 시작)
- `--reseed-checkpoint`는 브라우저·네트워크 없이 DB를 읽기 전용으로 열어 체크포인트를 다시 만든다: frontier = DB 시드 ∪ 기존 frontier(이미 visited인 키 제외, 같은 키는 큰 reach), visited = 기존 visited + DB 수집 키 − "visited인데 DB·failed에 없는 결정 노드"(다시 수집되게), failed는 그대로. 쓰기 전에 기존 파일을 `<checkpoint>.bak`으로 복사하고, `--dry-run`을 붙이면 바뀔 내용만 출력한다 — 강제 장치: `tests/test_gto_tree.py::test_reseed_checkpoint`
- `scripts/audit_gto_preflop.py`(읽기 전용, `--db` → `EV_PLUS_DB` → `poker.db`, `--checkpoint`)가 검사한다: 빈도합 / RFI 오픈 비율 순서 / 100% 쏠림 / 행의 3종 키·`hero_position` = `derive_node_meta(action_seq)` / **자식 핸드 ⊆ 부모 지지 집합**(히어로가 직전 액션을 한 부모 노드에서 그 액션 빈도 > ε인 핸드. 부모 미수집·히어로 첫 결정은 생략. 부모 지지 집합에 있지만 자식에 없는 핸드는 GTO Wizard가 미세 빈도 핸드를 비워 두는 경우라 실패로 보지 않는다) / 체크포인트 visited 결정 노드인데 DB·`failed`에 없음 = 0 / **DB 재구성 frontier ⊆ 체크포인트 frontier ∪ visited ∪ failed**(체크포인트가 없으면 마지막 두 검사 생략). 하나라도 걸리면 종료 코드 1 — 근거: [0040](../decisions/0040-no-arena-gate-audit-checks.md), [0044](../decisions/0044-node-row-key-is-action-seq.md) · 강제 장치: `tests/test_gto_tree.py::test_audit_checks`
- 미수집 큐의 옛 enum 행(`range_type != 'seq'`, 처리 경로 없음)은 `scripts/prune_missing_spots.py`로만 지운다: `--dry-run`(읽기 전용 연결로 대상만 출력) / `--apply`(삭제) / 옵션 없으면 아무것도 안 함 — 근거: [0033](../decisions/0033-no-direct-writes-to-shared-db.md) · 강제 장치: `tests/test_gto_tree.py::test_prune_missing_spots`

## 화면·경로·데이터

| 대상 | 무엇 | 비고 |
|---|---|---|
| `gto_preflop_situations` | 노드 1행: `action_seq`(유일 키, NOT NULL), `position`,`vs_position`,`range_type`(open/vs_limp/vs_open/vs_3bet/vs_4bet/vs_5bet — `action_seq`에서 유도), `raise_size`, `situation_label`, `hero_position`, `num_active`(=6−F 토큰 수) | 스키마 v14: `idx_gto_pre_seq UNIQUE(action_seq)`, `idx_gto_pre_sit`(3종 키, 비유일). 상세: `db/schema.py`, 운영: [db.md](db.md) |
| `gto_preflop_hands` | 노드×핸드 `freq_fold/call/raise/allin` | FK CASCADE |
| `gto_missing_spots_preflop` | 미수집 노드 큐(`range_type='seq'` 행. 옛 enum 행이 남아 있을 수 있음 — `prune_missing_spots.py`) | `/gto/preflop/save`가 같은 `action_seq`(=`vs_position` 칸) 큐 행을 `collected=1`로 갱신 |
| `POST /gto/preflop/save` | 노드 저장. 본문 `action_seq`(필수)·`hands`·`raise_size`, 선택 `position`/`vs_position`/`range_type`(대조용)·`situation_label`. 행은 **`action_seq`로 찾는다**. 핸드 전부 삭제 후 재삽입, 저장 성공 시 같은 `action_seq`를 가리키던 미수집 큐 행을 `collected=1`/`collected_at`으로 갱신, `loader.invalidate()`. 거부 422: `action_seq` 없음·결정 노드 아님·3종 키 불일치·빈도합 불량·핸드 0개 | 호출자: 수집 워커, 브라우저 수동 저장 · 강제 장치: `tests/test_poker_full.py::test_7_16_save_marks_missing_queue_collected` |
| `GET /gto/preflop/range?action_seq=` | 노드 키로 레인지(전체 핸드) + 콤보가중 요약, 응답에 `action_seq` 포함. 없으면 `{found: false}`. UTG RFI는 빈 문자열 | 호출자: GTO 패널(게임 상태 `gto.node_key`) |
| `GET /gto/preflop/situations` | 저장 노드 목록 | |
| 게임 상태 `gto` → GTO 패널 | advisor 추천의 노드 키·근사 여부·상황 라벨·내 패 빈도(`server/session.py::_get_gto_panel`) → `/gto/preflop/range?action_seq=` | 프리플랍 사람 차례에만 |
| CORS | `https://*.gtowizard.com` 허용, 백엔드 HTTPS(8765) | 브라우저 수동 저장용(Mixed Content 방지) |
| `gto_tree_checkpoint.json` | 수집 체크포인트(`visited`/`frontier`/`failed`), 재시드 시 `.json.bak` | 저장소 루트, gitignore |

### 운영 방법

**자동 수집(기본)** — 매번 확인:
1. 평소 크롬을 모두 끄고 디버그 크롬을 띄운 뒤 그 창에서 `https://app.gtowizard.com`에 로그인, 실행 내내 켜 둔다.
   `/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --user-data-dir="$HOME/chrome-gto-debug"`
2. 백엔드 실행: `./start.sh` (`https://localhost:8765/docs` 응답 확인). 문제 시 `curl -s http://localhost:9222/json/version`으로 크롬 확인.
3. 최초 1회 파서 눈검증: `python3 scripts/collect_gto_tree.py --dry-run` (첫 노드만 추출, 저장 안 함).
4. 수집: `python3 scripts/collect_gto_tree.py --limit 200` — 한도 근처에서 스스로 멈춘다. 다음 날 같은 명령으로 이어간다. Ctrl+C도 안전.
5. 확인: `python3 scripts/audit_gto_preflop.py`, `python3 scripts/gto_tree_report.py`(현황 문서 재생성), `python3 scripts/show_missing_spots.py [--all]`(큐).
6. audit이 체크포인트 검사(visited 유실·frontier 유실)를 실패로 보고하면: 수집 워커가 멈춘 상태에서 `python3 scripts/collect_gto_tree.py --reseed-checkpoint --dry-run`으로 확인 → `--dry-run` 없이 실행.

주요 옵션: `--limit`(기본 90) `--safety-margin`(5) `--min-delay/--max-delay`(2/5초) `--epsilon`(0.0005) `--nav-timeout`(30000ms) `--cdp-url`(`http://localhost:9222`) `--server`(`https://localhost:8765`) `--checkpoint`(`<repo>/gto_tree_checkpoint.json`) `--reseed-checkpoint`.

**수동 1스팟 재검증** — 특정 스팟을 눈으로 대조할 때만: 백엔드 실행 → 크롬에서 `https://localhost:8765` 인증서 허용 → GTO Wizard에서 스팟 이동 → 콘솔에서 `extractAndSave(raiseSize)` 실행(레이즈 사이즈를 모르면 `null`). 노드 키는 현재 URL의 `preflop_actions` 앞 `history_spot`개 토큰을 그대로 `action_seq`로 보내고, 포지션·라벨은 서버가 유도한다. badSum>0이면 콘솔에서 저장하지 않고, 서버도 422로 거부한다. 스크립트: `tools/gto_extract_and_save.js`(콘솔에 붙여 넣기) — 강제 장치: 장치 없음(JS 테스트 없음)

**한도**: GTO Wizard 무료 계정은 프리플랍 **100스팟/일**(스팟 이동 1회 = 1). 회사 와이파이에서는 GTO Wizard 접속이 막혀 핫스팟이 필요하다.

## 알려진 한계

- 100bb 고정 — 딥/숏/헤즈업 모두 100bb 6-max 트리로 근사한다. 3~5인 테이블은 GTO 힌트·봇 GTO가 없다(휴리스틱).
- 라이브 사이즈는 수집된 형제로 스냅되므로 사이즈 오차가 근사로 남는다. 형제가 하나면 거리 제한 없이 매칭한다(라이브 올인은 올인 형제로만).
- 라벨 하나에 콜러 없는 노드가 아직 수집되지 않았으면 그 라벨의 간단 라벨 조회는 `None`이다(콜러 있는 노드는 라벨로 내주지 않는다).
- 노드는 있는데 그 핸드만 없는 경우(예: 오픈 레인지 밖 핸드로 3벳을 받음) advisor는 추천을 내지 않으므로 패널도 "GTO 데이터 없음"이다.
- 운영 DB의 노드 `R2.5-R8-F-F-F-F`(id 5, UTG vs HJ 3bet)는 부모 UTG RFI 레이즈 레인지(52핸드) 밖 117핸드를 fold=1.0으로 담고 있다 — audit의 부모 지지 집합 검사가 이 1건을 실패로 보고한다(처리는 DECISIONS D-32).
- 림프 팟(레이즈 없음)의 간단 라벨 경로는 없다 — 림프 노드는 액션 순서 키로 수집된 `vs_limp` 노드로만 받는다.
- `num_active`(= 6 − 폴드 토큰 수)는 아직 소비자가 없다.
- 수집은 무료 한도(100/일)에 묶여 트리 전체에 여러 날이 걸린다. 전체 규모는 미리 알 수 없다(현황 문서는 %를 쓰지 않는다).
- `audit_gto_preflop.py`는 수동 실행이다(자동 게이트 없음, ADR 0040).
