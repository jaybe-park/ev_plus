# 결정 기록 (ADR)

한 번 쓰면 고치지 않고 대체만 한다(상태를 `대체됨 → 00NN`으로 바꾸고 새 ADR을 쓴다); 새 ADR은 다음 번호를 쓴다.

| 번호 | 제목 | 상태 | 도메인 |
|---|---|---|---|
| [0001](0001-adopt-playbook.md) | AI 에이전트 개발 운영 플레이북 도입 | 유효 | workflow |
| [0002](0002-gto-values-verbatim.md) | GTO Wizard 값은 화면 그대로만 저장(추측·보간 금지) | 유효 | gto-preflop |
| [0003](0003-layered-css-parser.md) | 레이어 기반 CSS 파서로 GTO Wizard 빈도 추출 | 유효 | gto-preflop |
| [0004](0004-raise-size-measured.md) | raise_size는 실측 bb(REAL), 공식은 폴백에만 | 유효 | gto-preflop |
| [0005](0005-100bb-and-headsup-sb.md) | 100bb 고정 근사, 헤즈업은 6-max SB 재사용, 3~5인은 제외 | 유효 | gto-preflop |
| [0006](0006-enum-first-and-model-guards.md) | enum 경로 우선·시퀀스 폴백 병렬 공존 + 데이터 모델 밖 가드 | 유효 | gto-preflop |
| [0007](0007-structured-preflop-seq.md) | advisor 입력은 구조화 프리플랍 시퀀스(한글 로그 파싱 금지) | 유효 | gto-preflop |
| [0008](0008-node-key-action-seq.md) | 노드 키 = GTO Wizard preflop_actions 문자열, 스키마 안 A, DB가 source of truth | 유효 | gto-preflop |
| [0009](0009-measured-size-node-key.md) | 저장 노드 키는 실측 사이즈 verbatim(깊이-캐노니컬 스냅 폐기) | 유효 | gto-preflop |
| [0010](0010-runtime-sibling-snap.md) | 런타임 스냅 = 수집된 레이즈 형제, 없으면 큐+휴리스틱 | 유효 | gto-preflop |
| [0011](0011-data-driven-tree-collection.md) | 데이터 기반 트리 수집(가정 금지, ε 분기, 도달확률 best-first) | 유효 | gto-preflop |
| [0012](0012-collector-operational-safety.md) | 수집 운영 안전장치 — 한도·환경오류·자격증명·지연 | 유효 | gto-preflop |
| [0013](0013-no-arena-gate-collection-as-routine.md) | 아레나 검증 게이트 폐기, 수집은 운영 루틴 | 유효 | gto-preflop |
