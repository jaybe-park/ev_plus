# 0038. 노드 행의 유일 키는 action_seq 하나, 3종 키는 action_seq에서 유도

- 상태: 유효
- 날짜: 2026-09-26 · 결정자: 구현 에이전트(T-001) — 스키마 변경이라 main 병합 전 사용자 확인
- 대체: [0008](0008-node-key-action-seq.md)의 "기존 enum 컬럼·UNIQUE는 그대로 유지" 부분(노드 키 = `preflop_actions` 문자열, DB가 source of truth는 유효)

## 맥락
0008은 `action_seq` 컬럼을 더하면서 `UNIQUE(position, vs_position, range_type)`도 남겼다. 저장 API는 이 3종 키로 기존 행을 찾아 덮어썼다. 그래서 3종 키가 같은 다른 노드(예 `R2.5-F-F-F-F`와 `R2.5-C-F-F-F`, 둘 다 "BB vs UTG open")는 한 행에 번갈아 덮어써졌다. 2026-09-26 운영 DB의 vs_open 13행은 전부 콜러 있는 노드만 남아 있었다.
0035는 조회를 "액션 순서 키 먼저, 간단 라벨은 근사 예비"로 바꿨다. 그러면 라벨 하나에 노드가 여럿인 상태가 정상이 된다.

## 결정
- `gto_preflop_situations`의 유일 키는 `action_seq` 하나다(`NOT NULL`, 유니크 인덱스 `idx_gto_pre_seq`). 3종 UNIQUE는 없앤다. 스키마 v13, 테이블 재생성으로 옮기고 행·id·핸드는 그대로 둔다. `action_seq`가 NULL인 행이 있으면 마이그레이션을 멈춘다(추측으로 채우거나 버리지 않음).
- 저장 API(`POST /gto/preflop/save`)는 `action_seq` 필수다. 행은 `action_seq`로만 찾는다. 3종 키·`hero_position`은 서버가 `gto.node_key.derive_node_meta(action_seq)`로 유도해 저장한다. 요청에 3종 키가 오면 유도값과 대조해 다르면 422. 결정 노드가 아닌 키도 422.
- 저장 API도 핸드별 빈도합 [0.9, 1.1]을 검증한다(0002). 한 핸드라도 벗어나거나 핸드가 0개면 422, 저장하지 않는다.
- 간단 라벨(3종 키) 조회는 그 라벨의 **콜러 없는 노드**만 가리킨다. 콜러 없는 노드가 없으면 라벨 조회는 None이다. 콜러 있는 노드는 액션 순서 키로만 조회된다.
- 헤즈업 시퀀스는 앞에 `F-F-F-F`를 붙여 6-max SB vs BB 트리의 노드 키로 조회한다(0005를 시퀀스 경로에도 적용). 3~5인 테이블은 시퀀스 경로를 쓰지 않는다(0005 — 포지션 구성이 달라 대응시키지 않음). 노드 키가 가리키는 히어로가 실제 히어로와 다르면 정확한 노드로 쓰지 않고 큐에도 넣지 않는다.

## 버린 대안
- 라벨 하나에 노드가 하나뿐이면 콜러가 있어도 라벨 결과로 쓰기(0035 문구의 "여럿이면"만 적용) — 지금 운영 DB에선 "BB vs BTN open"이 SB 콜 노드 하나뿐이라, 헤즈업 팟 BB가 멀티웨이 데이터를 받는다(T-001 완료 조건 1 위반).
- 3종 키를 요청 값 그대로 저장 — 라벨과 노드 키가 어긋난 행이 다시 생길 수 있다. 수집 워커·수동 스크립트가 보내는 값도 결국 같은 유도 함수에서 나온다.
- 새 `gto_preflop_nodes` 테이블(0008의 안 B) — 조회부·FK 재배선 비용이 크고, 지금 필요한 건 유일 키 교체뿐이다.

## 결과
- 영향받는 spec: `docs/spec/gto-preflop.md`, `docs/spec/db.md`
- 이행: TODO T-001
- 강제 장치: `tests/test_poker_full.py::test_7_7_distinct_action_seq_distinct_rows`, `::test_7_8_save_requires_action_seq_and_consistent_keys`, `::test_7_9_save_rejects_corrupt_frequencies`, `::test_7_12_headsup_pot_not_given_caller_node`, `::test_7_13_headsup_not_snapped_to_utg_tree`, `::test_7_14_migration_v13_preserves_data`, `tests/test_gto_tree.py::test_audit_key_and_lost_checks`
