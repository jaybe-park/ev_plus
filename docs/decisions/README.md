# 결정 기록 (ADR)

한 번 쓰면 고치지 않고 대체만 한다(옛 ADR 상태를 `대체됨 → NNNN`으로 바꾸고 새 ADR을 쓴다). 새 ADR은 다음 번호를 쓴다(비어 있는 번호는 재사용하지 않는다).

| 번호 | 제목 | 상태 | 도메인 |
|---|---|---|---|
| [0001](0001-adopt-playbook.md) | AI 에이전트 개발 운영 플레이북 도입 | 유효 | workflow |
| [0002](0002-gto-values-verbatim.md) | GTO Wizard 값은 화면 그대로만 저장(추측·보간 금지) | 유효 | gto-preflop |
| [0003](0003-layered-css-parser.md) | 레이어 기반 CSS 파서로 GTO Wizard 빈도 추출 | 유효 | gto-preflop |
| [0004](0004-raise-size-measured.md) | raise_size는 실측 bb(REAL), 공식은 폴백에만 | 유효 | gto-preflop |
| [0005](0005-100bb-and-headsup-sb.md) | 100bb 고정 근사, 헤즈업은 6-max SB 재사용, 3~5인은 제외 | 유효 (결과 절의 "시퀀스 경로 미구현"은 0044로 해소됨) | gto-preflop |
| [0006](0006-enum-first-and-model-guards.md) | enum 경로 우선·시퀀스 폴백 병렬 공존 + 데이터 모델 밖 가드 | 일부 대체됨 → 0035 (조회 순서. 데이터 모델 밖 가드는 유효) | gto-preflop |
| [0007](0007-structured-preflop-seq.md) | advisor 입력은 구조화 프리플랍 시퀀스(한글 로그 파싱 금지) | 유효 | gto-preflop |
| [0008](0008-node-key-action-seq.md) | 노드 키 = GTO Wizard preflop_actions 문자열, 스키마 안 A, DB가 source of truth | 일부 대체됨 → 0044 (enum 3종 UNIQUE 유지 부분. 노드 키 포맷·DB source of truth는 유효) | gto-preflop |
| [0009](0009-measured-size-node-key.md) | 저장 노드 키는 실측 사이즈 verbatim(깊이-캐노니컬 스냅 폐기) | 유효 | gto-preflop |
| [0010](0010-runtime-sibling-snap.md) | 런타임 스냅 = 수집된 레이즈 형제, 없으면 큐+휴리스틱 | 유효 | gto-preflop |
| [0011](0011-data-driven-tree-collection.md) | 데이터 기반 트리 수집(가정 금지, ε 분기, 도달확률 best-first) | 유효 | gto-preflop |
| [0012](0012-collector-operational-safety.md) | 수집 운영 안전장치 — 한도·환경오류·자격증명·지연 | 유효 | gto-preflop |
| [0013](0013-no-arena-gate-collection-as-routine.md) | 아레나 검증 게이트 폐기, 수집은 운영 루틴 | 유효 (결과 절의 DECISIONS 참조는 0040으로 해소됨) | gto-preflop |
| [0014](0014-difficulty-is-mc-resolution.md) | 봇 난이도 = MC 샘플 수(판단 해상도), 일부러 약하게 코딩하지 않는다 | 일부 대체됨 → [0045](0045-equity-precision-1pp-adaptive-mc.md) (샘플 수치·"hard만 리버 전수". "난이도 = 해상도, 일부러 약하게 코딩하지 않는다" 원칙은 유효) | bot |
| [0015](0015-aggression-margin.md) | 어그레션 마진 — 벳을 받으면 콜 기준을 벳 크기에 비례해 올린다 | 유효 | bot |
| [0016](0016-bot-validation-arena-legacy.md) | 봇 검증 = 아레나 bb/100 + legacy 베이스라인, 튜닝 결과는 사람이 반영 | 유효 | bot |
| [0017](0017-equity-canonical-key-exact-protection.md) | equity_cache 키 = 수트 정규화, exact 값은 보호, 레인지 조건부 equity는 저장하지 않는다 | 대체됨 → 0034 | equity |
| [0018](0018-equity-fast-paths.md) | 에퀴티 계산 고속화 경로 — 계산용 평가기, 스트리트 분해 DP, 보드 중심 리버 테이블, PyPy | 일부 대체됨 → 0034 (캐시·DP 메모 부분) · board table은 2026-10-01 런타임 미사용으로 삭제(T-041). 고속 평가기 이원화만 유효 | equity |
| [0019](0019-equity-worker-priority.md) | 에퀴티 워커 우선순위 — 게임에서 만난 스팟 먼저, 싼 스트리트 먼저, 스윕은 마지막 | 대체됨 → 0034 | equity |
| [0020](0020-sqlite-single-writer.md) | SQLite 쓰기 원칙 — 쓰기는 메인 프로세스, 계산만 Pool, 짧은 트랜잭션, 멱등 저장 | 일부 대체됨 → 0034 (워커·계산 Pool 부분. 쓰기는 메인 프로세스 1개·짧은 트랜잭션·멱등 저장은 유효) | equity |
| [0021](0021-equity-stats-incremental.md) | `--status`는 증분 통계 테이블을 읽는다 — 모든 쓰기가 같은 트랜잭션에서 델타 반영 | 대체됨 → 0034 | equity |
| [0022](0022-equity-cache-rebuildable-vsrandom-ui.md) | equity_cache는 재계산 가능한 캐시로 유지, vs_random은 계산만 유지하고 UI에서는 뺀다 | 일부 대체됨 → 0034 (캐시 유지 부분. vs_random은 계산만 유지하고 UI에서 뺀다는 유효) | equity |
| [0023](0023-postflop-range-narrowing.md) | 포스트플랍 GTO 수집 폐기 → 프리플랍 GTO 기반 레인지 좁히기, Epic 설계 확정분 | 유효 | bot |
| [0024](0024-hj-position-naming.md) | 포지션 네이밍은 GTO Wizard 기준(HJ, MP 아님) | 유효 | game |
| [0025](0025-ports-and-https.md) | 포트 고정(8765/5766) + 백엔드 HTTPS 필수 | 유효 | game |
| [0026](0026-stubbot-and-isolated-test-db.md) | 로직 테스트는 StubBot + 테스트별 임시 DB로 격리 | 유효 | testing |
| [0030](0030-sqlite-over-server-db.md) | SQLite 유지, 서버형 DB(MySQL 등) 전환 반려 | 유효 | db |
| [0031](0031-bot-hand-archive-human-hand-retain.md) | 봇 전용 핸드는 아카이브 후 삭제, 사람 참여 핸드는 영구 보존 | 유효 | db |
| [0032](0032-partial-index-only-for-pending-queues.md) | 대기 큐 인덱스는 부분 인덱스로만, 인덱스 삭제 전 EXPLAIN QUERY PLAN 확인 | 대체됨 → 0034 | db |
| [0033](0033-no-direct-writes-to-shared-db.md) | 공유 운영 DB에 직접 쓰지 않는다 — 스크립트 경유 | 유효 | db |
| [0034](0034-abolish-equity-cache.md) | 에퀴티 캐시 폐기 — 프리플랍 상수 테이블 + 실시간 계산, 정밀도 목표 ±0.5%p | 일부 대체됨 → [0045](0045-equity-precision-1pp-adaptive-mc.md) (정밀도 목표 ±0.5%p·샘플 수. 캐시 폐기·계산 경로는 유효) | equity |
| [0035](0035-gto-lookup-sequence-first.md) | GTO 조회는 액션 순서 키 먼저, 간단 라벨은 "근사" 예비 | 유효 | gto-preflop |
| [0036](0036-moving-button.md) | 파산으로 좌석이 빠질 때는 무빙 버튼 | 유효 | game |
| [0037](0037-allin-only-snaps-to-allin-sibling.md) | 라이브 올인은 올인 형제에만 스냅한다(레이즈 형제와 구분) | 유효 | gto-preflop |
| [0038](0038-action-validation-and-real-amounts.md) | 액션 판정은 core 한 곳 — 사람 불법 액션은 거절, 봇은 안전 폴백, 금액은 실제 칩 이동 | 유효 (재오픈 판정 기준은 [0048](0048-cumulative-short-allins-reopen.md)에서 보완) | game |
| [0039](0039-grader-uncertainty-band.md) | Play Grader 콜·폴드 판정에 추정 오차 기반 "경계" 구간 | 일부 대체됨 → 0049 (경계폭 2σ만·폴드 마진 유지. 경계 구간 자체는 유효) | bot |
| [0040](0040-no-arena-gate-audit-checks.md) | GTO 수집 뒤 아레나 게이트는 되살리지 않고 audit 무결성 검사로 대신한다 | 유효 | gto-preflop |
| [0041](0041-bot-adoption-criterion.md) | 봇 개선 채택 기준 — 아레나 차이가 표준오차의 2배 이상 | 유효 | bot |
| [0042](0042-drop-grader-stage2.md) | Play Grader 2단계(GTO Wizard EV값 수집) 폐기 | 유효 | bot |
| [0043](0043-restore-session-on-reload.md) | 새로고침하면 진행 중인 게임을 이어간다(서버 재시작은 복구하지 않음) | 유효 | game |
| [0044](0044-node-row-key-is-action-seq.md) | 노드 행의 유일 키는 action_seq 하나, 3종 키는 action_seq에서 유도 | 유효 | gto-preflop |
| [0045](0045-equity-precision-1pp-adaptive-mc.md) | 에퀴티 정밀도 목표 ±1%p(1σ) — vs 랜덤·레인지 반영 모두 적응형 MC(500~2,500샘플), easy만 고정 40 | 유효 | equity |
| [0046](0046-limp-nodes-are-vs-limp-not-open.md) | 림프 노드는 range_type='vs_limp'로 저장한다(open/RFI 아님) | 유효 | gto-preflop |
| [0047](0047-rules-live-in-core.md) | 포커 룰은 core 한 곳에 — 웹 세션·CLI는 호출만, 세션 경로는 참조 모델 퍼저로 지킨다 | 유효 | game |
| [0048](0048-cumulative-short-allins-reopen.md) | 불완전 올인 여러 개의 합이 풀 레이즈면 재오픈한다 (TDA Rule 47) | 유효 | game |
| [0049](0049-grader-vs-range-symmetric-band.md) | 복기 콜·폴드 판정은 vs_range 입력·대칭 경계(max(2σ, 1%p)) | 유효 | bot |
