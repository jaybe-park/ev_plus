# 0046. 림프 노드는 range_type='vs_limp'로 저장한다(open/RFI 아님)

- 상태: 유효
- 날짜: 2026-09-26 · 결정자: 구현 에이전트(T-016) — TODO.md 지시에 이미 방향이 있어
  기존 ADR(0006)을 따르는 버그 수정으로 판단, 사용자 확인 없이 진행

## 맥락
`gto/node_key.py::derive_node_meta`는 자발적 레이즈가 0회면 무조건 `range_type='open'`,
라벨 `"{H} RFI"`를 반환했다. 레이즈 앞에 콜(림프) 토큰이 있어도 구분하지 않아서, 예를 들어
SB가 림프하고 BB가 결정하는 노드(`action_seq="F-F-F-F-C"`)가 `"BB RFI"`로 저장됐다.
BB는 이미 강제 베팅 상태라 RFI(오픈)가 원천적으로 불가능하다는 것이 ADR 0006의 데이터
모델 밖 가드 취지이고, 이 저장 버그는 그 가드가 막으려던 상황을 라벨만 다르게(저장 경로에서)
만들어낸 것과 같다. 2026-09-26 운영 DB에 id 17 행이 이 버그의 실제 사례로 남아 있었다.

## 결정
- `derive_node_meta`에서 자발적 레이즈 0회 + 콜(림프) 토큰 1개 이상이면 `range_type='vs_limp'`,
  `vs_position`은 림퍼 좌석을 레이즈 라벨과 같은 규칙(`/`로 연결)으로 담고, 라벨은
  `"{hero} vs {limper(s)} limp"`(예 "BB vs SB limp", 멀티림프는 "BB vs UTG/HJ limp")로
  유도한다. 레이즈 0회 + 콜도 없으면(진짜 RFI) 기존대로 `open`/`"{H} RFI"`.
  (레이즈 전 콜은 정의상 항상 림프이므로 별도 조건 없이 "콜 토큰 존재"만으로 판별한다.)
- 이 판별은 저장(`/gto/preflop/save`)·조회(액션 순서 키 경로)·수집 워커·감사 스크립트가
  전부 공유하는 단일 소스(`gto/node_key.py`)에 있으므로, 코드 변경 하나로 네 경로가
  같이 고쳐진다.
- 기존 DB에 이미 `open`으로 잘못 저장된 행은 스키마 v14 마이그레이션
  (`db/schema.py::relabel_limp_nodes_v14`)이 앱 연결 시 자동으로 재라벨링한다.
  `range_type='open'`인 행만 훑고, 새 `derive_node_meta`가 `vs_limp`로 재계산하는 행만
  옮긴다 — 그 밖의 라벨·핸드 데이터는 손대지 않는다(추측 재라벨 금지).
- 간단 라벨 조회 경로(`gto/advisor.py`의 `get_open_range`/`get_vs_open_range`/
  `get_vs_3bet_range`)는 `vs_limp`를 새로 조회하지 않는다(범위 밖) — 림프 상황은 여전히
  `is_rfi and my_position != "BB"` 가드로 걸러지고(BB는 애초에 제외), 그 밖의 포지션이
  림프 뒤에 행동하는 경우는 액션 순서 키 경로(`derive_node_meta`가 이미 반영)로만 정확히
  조회된다. 라벨 예비 경로에 `vs_limp` 지원을 추가하는 것은 이번 Task 범위가 아니다.

## 버린 대안
- `vs_position`을 `None`으로 두고 `range_type`만 `vs_limp`로 바꾸기 — vs_open/vs_3bet과
  같은 규칙(레이저/림퍼 좌석을 vs_position에 담아 라벨과 함께 조회 가능하게)에서 벗어나
  일관성이 깨진다.
- 기존 행을 `--dry-run` 지원 스탠드얼론 스크립트로만 고치고 스키마 버전은 그대로 두기 —
  이 프로젝트는 이미 v12/v13에서 같은 성격의 결정론적 백필을 스키마 마이그레이션 콜러블로
  처리해 왔다(`backfill_v12`, `rebuild_gto_preflop_situations_v13`). 같은 패턴을 따르는 것이
  "앱이 다음에 그 DB에 연결하면 자동으로 고쳐져 있다"를 보장하기 쉽고, 운영 DB에 직접
  쓰지 않는 규칙과도 충돌하지 않는다(마이그레이션은 `db/connection.py`가 통제하는 경로).

## 결과
- 영향받는 spec: `docs/spec/gto-preflop.md`
- 이행: TODO T-016
- 강제 장치: `tests/test_gto_tree.py::test_derive_node_meta_labels`(림프 케이스),
  `tests/test_poker_full.py::test_7_15_migration_v14_relabels_limp_nodes`
