# 0008. 노드 키 = GTO Wizard preflop_actions 문자열, 스키마 안 A, DB가 source of truth

- 상태: 일부 대체됨 → 0044 (enum 3종 UNIQUE 유지 부분. 노드 키 포맷·DB source of truth는 유효)
- 날짜: 2026-06-14, 2026-07-15 · 결정자: jaybe-park

## 맥락
enum 3종 키(35개 조합)로는 스퀴즈·멀티웨이·4벳+ 노드를 표현할 수 없었다. 한편 초기에는 GTO 데이터를 `gto_data/` 폴더의 JSON 파일로도 들고 있었는데, 이중 관리는 어느 쪽이 맞는지 판단할 수 없게 만들었다.

## 결정
노드 키는 GTO Wizard의 `preflop_actions` 문자열(예: `R2.5-C-F-F-F`)을 그대로 쓴다. `gto_preflop_situations` 테이블에 `action_seq`/`hero_position`/`num_active` 컬럼을 추가하는 "스키마 안 A"를 택해, 기존 enum 컬럼·UNIQUE·조회 경로는 그대로 유지한 채 시퀀스 컬럼을 병렬로 더한다. 노드 키 유니크는 부분 유니크 인덱스 `idx_gto_pre_seq`로 강제한다. GTO 데이터의 source of truth는 DB로 단일화하고 `gto_data/` JSON은 삭제한다.

## 버린 대안
- 안 B: 신규 `gto_preflop_nodes` 테이블 — FK 재배선과 조회부 이중화 비용이 크고, 봇·테스트에 닿는 범위가 넓다.
- JSON과 DB 이중 관리 유지 — 어느 쪽이 최신인지 판단할 수 없다.

## 결과
- 영향받는 spec: `docs/spec/gto-preflop.md`, `docs/spec/db.md`
- 강제 장치: `tests/test_poker_full.py::test_6_13_seq_key_and_enum_key_same_range`, `tests/test_poker_full.py::test_6_15_migration_normalizes_vs3bet_format`
- 저장 API(`server/main.py`)가 실제로는 `action_seq`가 아니라 enum 3종(position/vs_position/range_type)만으로 기존 행을 찾아 UPDATE하고 있어, 서로 다른 시퀀스 노드가 한 행에 덮어써진다 — DECISIONS.md 참고.
