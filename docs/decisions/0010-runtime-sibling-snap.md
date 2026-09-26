# 0010. 런타임 스냅 = 수집된 레이즈 형제, 없으면 큐+휴리스틱

- 상태: 유효
- 날짜: 2026-07-16~17 · 결정자: jaybe-park

## 맥락
실전 베팅 사이즈는 연속값이지만, 솔브 트리는 노드마다 사이즈가 하나뿐이다(0009). 라이브 레이즈 금액을 트리 노드에 매핑할 방법이 필요했다.

## 결정
`canonical_node_key`가 라이브 레이즈마다 `loader.get_children_by_prefix`로 그 프리픽스에서 수집된 형제 노드를 읽는다. 형제가 1개면 그것을 쓰고, 여러 개면 bb 절대거리가 최소인 것으로 스냅한다. 수집된 형제가 하나도 없으면 `None`을 반환하고, 실측 키로 `gto_missing_spots_preflop(range_type='seq')`에 등록한 뒤 equity 휴리스틱으로 폴백한다. 허용 오차로 억지 매칭하거나 하드코딩 값으로 폴백하지 않는다.

## 버린 대안
- 허용 오차 임계값 매칭 — 추측이다.
- 하드코딩 폴백 — 0002·0009 원칙과 충돌한다.

## 결과
- 영향받는 spec: `docs/spec/gto-preflop.md`
- 강제 장치: `tests/test_poker_full.py::test_6_14_runtime_snap_maps_near_size_to_node`, `tests/test_poker_full.py::test_6_16_realsize_node_snaps_to_collected_sibling`, `tests/test_poker_full.py::test_6_17_uncollected_branch_returns_none_and_queues`, `tests/test_poker_full.py::test_6_18_two_siblings_snap_to_nearest_bb`
