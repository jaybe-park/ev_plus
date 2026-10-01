# 0005. 100bb 고정 근사, 헤즈업은 6-max SB 재사용, 3~5인은 제외

- 상태: 유효 (결과 절의 "시퀀스 경로 미구현"은 0044로 해소됨)
- 날짜: 2026-07-12 · 결정자: jaybe-park

## 맥락
캐시게임은 핸드마다 스택이 벌어지고, 봇이 파산해 헤즈업까지 줄면 스택이 100bb에서 크게 벗어난다. 무료 계정 수집 한도(0012) 때문에 스택 깊이별로 재솔브하는 것은 현실적이지 않다. 또 테이블이 2인까지 줄면 포지션 "BTN/SB"가 DB에 없어 미해결 스팟이 쌓였다.

## 결정
모든 GTO 데이터와 조회는 GTO Wizard 6-max 100bb 트리로 근사한다. 스택별 재계산은 하지 않는다. 헤즈업은 advisor 내부 조회 시점에만 `BTN/SB`를 `SB`로 치환한다(상대 포지션도 동일하게 치환). 헤즈업 트리는 SB vs BB 스팟과 구조가 같으므로 재수집이 필요 없다고 보고, 엔진의 원본 라벨 "BTN/SB"는 UI·히스토리용으로 그대로 유지한다. 3~5인 테이블은 포지션 구성 자체가 달라(예: 5인은 HJ가 없어 CO의 성격이 다름) 대응시키지 않고 매핑에서 제외한다.

## 버린 대안
- 스택 깊이별 솔브 수집 — 무료 계정 한도 때문에 불가능.
- 헤즈업 전용 게임타입 수집 — 6-max SB 재사용으로 충분해 불필요.
- 3~5인 "가장 가까운 스팟" 매핑 — 포지션 논리가 성립하지 않는다.

## 결과
- 영향받는 spec: `docs/spec/gto-preflop.md`
- 강제 장치: `tests/test_poker_full.py::test_6_9_headsup_gto_btnSB_mapped_to_sb_rfi`, `tests/test_poker_full.py::test_6_11_headsup_seq_labels_btnSB`
- 다만 `BTN/SB`→`SB` 치환은 현재 enum 조회 경로(`_recommend_by_enum`)에만 구현돼 있고, 시퀀스 경로(`_recommend_by_seq`, `canonical_node_key`)에는 없어 헤즈업 시퀀스가 6-max UTG 노드로 잘못 스냅될 수 있다 — DECISIONS.md 참고.
