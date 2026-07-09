# TODO

작업 상태: `[ ]` 미완료 · `[x]` 완료 · `[-]` 보류

---

## 🌙 퇴근 시 돌려놓기 (기획 불필요, 즉시 실행)

```bash
# 1순위: 그라인드 — 캐시 + RL 학습데이터 + 미수집 스팟 발견 동시 축적
python3 scripts/grind.py

# 또는: 프리플랍 equity 채우기 (845스팟, 순수 워커)
python3 scripts/equity_worker.py --preflop-first

# 또는: 파라미터 튜닝 캠페인 (봇이 스스로 강해짐, 결과는 tuning_results.json)
python3 scripts/tune_bot.py --profile hard --param aggression_margin --values 0.04,0.08,0.12 --hands 3000 --seeds 3
python3 scripts/tune_bot.py --profile hard --param semibluff_freq --evolve --start 0.55 --step 0.1 --rounds 5 --hands 2000

# 다음날 아침 확인
python3 scripts/equity_worker.py --status
ls -lh poker.db chip_violations.log 2>/dev/null   # 위반 로그가 있으면 시드로 재현 가능
```

⚠️ 동시 실행 금지 조합: 워커 2개(중복 계산), 그라인드+튜닝(CPU/DB 경합)

---

## 🐛 버그

- [ ] **BB일 때 첫 블라인드 애니메이션 순서 버그** — 실행 계획 (sonnet 에이전트 1개)
  - 증상: 내가 BB면 첫 핸드 시작 시 BB가 먼저 베팅하고 SB가 나중에 베팅하는 것처럼 보임
  - 원인 후보 (순서대로 조사):
    1. `server/session.py` `_start_new_hand()`의 blind 이벤트 발행 순서 —
       `for p in self.game.players` 순회라 좌석 순서대로 나감. 사람이 BB 좌석이면
       사람(BB)이 SB보다 먼저 발행될 수 있음 → **SB 먼저, BB 나중으로 정렬해 발행**하면 해결 (유력)
    2. 프론트 `web/src/hooks/useEventQueue.ts`의 blind 이벤트 처리 타이밍
  - 검증: 백엔드 수정이면 세션 유닛으로 — 사람을 BB 좌석에 놓고 events 배열에서
    blind 이벤트가 [SB, BB] 순인지 assert (tests/test_poker_full.py 영역 5에 추가).
    프론트까지 의심되면 `./start.sh` 후 새 게임 반복해 육안 확인
  - 커밋: 수정 파일 + 테스트 + TODO 이 항목 [x]. 한국어 메시지 + Co-Authored-By 트레일러, 푸시

- [x] **test_poker_full.py 실행 시간 조사**
  - 원인 ①: `db/recorder.py` `GameRecorder`가 세션마다 자체 sqlite3 커넥션을
    열고 절대 닫지 않음 → 모든 테스트가 같은 임시 DB 파일을 공유하면
    테스트가 누적될수록 살아있는 커넥션 수가 늘어나 SQLite 쓰기 락 경합이
    심해져 busy_timeout(30초)까지 블로킹 (예: 34개 테스트 후 세션 생성 1건이 31초)
  - 원인 ②: 로직 테스트가 실제 AI 봇(`ai.bot.PokerBot`)을 사용해
    매 액션마다 equity/GTO 계산을 수행함
  - 해결 ①: `run()` 헬퍼가 테스트 함수 실행 직전마다 `EV_PLUS_DB`를
    새 임시 파일로 갱신해 커넥션 충돌 자체를 제거 (recorder 버퍼화 커밋 358343a와 별개 이슈)
  - 해결 ②: `tests/test_poker_full.py`에 StubBot 도입 —
    `ai.bot.PokerBot.decide_action`을 모듈 임포트 시점에 콜/체크만 하는
    스텁으로 전역 패치 (equity/GTO 호출 0회 확인). 특정 액션 시퀀스가
    필요한 테스트는 `StubBot(player, scripted_actions=[...])`로 주입
  - 결과: 50개 전체 통과, 실행 시간 30초+ → 1초 미만
  - 대표 실행: `tests/run_all.py` 신규 (`--fast`/`--full`)

- [x] **사이드팟 미구현**
  - `server/session.py` `_calculate_side_pots()` 추가, `_do_showdown()` 개편
  - 테스트 6-5 ~ 6-8 추가 및 통과

- [x] **헤즈업 프리플랍 베팅 순서**
  - `core/game.py` `_post_blinds()`, `_betting_order()` 헤즈업 분기 추가
  - 테스트 6-1 ~ 6-4 추가 및 통과

---

## 🔧 미연결 기능

- [x] **DB 기록 연결 (RL 학습 데이터 수집 시작)** — 스키마 v6
  - CHECK 제약 수정: HJ/BTN-SB 포지션 허용 (기존엔 INSERT 실패했음)
  - RL 컨텍스트 컬럼 추가: `equity`(봇 결정 시점), `bot_profile`, `players_state`(전원 스냅샷 JSON)
  - `session.py` ↔ `recorder.py` 연결: 핸드 시작/모든 액션/종료+reward 역산(bb 단위)
  - 아레나/그라인드도 자동 기록 → 시간당 수만 액션 학습 데이터 생산
  - 남은 것: 사람 액션의 GTO 빈도 기록(플레이 평가와 연계), state_vector 피처 설계

---

## 🏗 인프라 정비

- [ ] **DB 인프라 정비 (SQLite 유지 + 파일 분리/보존/백업)** — 기획 확정 (2026-07)

  **결정 기록**: MySQL/Docker 전환은 **반려** — 로컬 단일 사용자·2~3 프로세스 패턴은
  SQLite WAL의 적정 영역이고, 1GB는 SQLite 한계(수십TB)에 한참 못 미침.
  겪었던 락 경합은 엔진 문제가 아니라 코드 패턴 문제였고 이미 해결
  (recorder 버퍼화 358343a, 배치 플러시, 인덱스 v7/v8). 향후 RL 분석 스캔이
  필요해지면 그때의 답은 MySQL이 아니라 **DuckDB/Parquet 내보내기** (OLTP는
  SQLite 유지, 분석만 컬럼형).

  **실행 트리거**: poker.db가 5GB를 넘거나, 그라인드 중 락 경합이 재발하거나,
  RL 학습 준비를 시작할 때 — 그 전엔 손대지 않음.

  **작업 1 — 용도별 DB 파일 분리** (sonnet 에이전트, 반나절)
  - 분리안: `gto.db`(gto_preflop_*, gto_missing_spots — 소중, 거의 읽기 전용)
    / `equity.db`(equity_cache, worker_meta — 워커가 주 쓰기)
    / `records.db`(games, preflop/postflop_actions — 아레나/세션이 주 쓰기)
  - 효과: 쓰기 주체가 파일 단위로 분리되어 경합 구조적 소멸, 파일별 백업/보존 정책 차등
  - 구현: `db/connection.py`에 용도별 `get_connection(kind="gto"|"equity"|"records")`
    도입, 호출부 치환 (equity.py/loader.py/advisor.py/recorder.py/worker/main.py).
    기존 poker.db는 1회 마이그레이션 스크립트로 3개 파일에 테이블 복사
    (`ATTACH DATABASE` + `INSERT INTO new.x SELECT * FROM main.x`), 원본은 .bak 보관
  - 주의: EV_PLUS_DB 테스트 격리 환경변수를 kind별로 확장 (EV_PLUS_DB_DIR 하나로
    디렉터리 지정하는 방식 권장), tests/run_all.py 89개 + 아레나 5핸드 라이브 검증
  - 커밋: db/ + 호출부 + docs/db-schema.md·architecture.md, 다중 -m 메시지

  **작업 2 — RL 기록 아카이브 정책** (sonnet 에이전트, 3~4시간) ← 용량 성장의 실제 주범
  - 문제: `players_state` JSON(~300B/액션) × 그라인드 시간당 수십만 액션 = 밤새 GB 단위
  - ⚠️ 정책 수정 (2026-07, 사용자 지적): 봇 전용 핸드는 **삭제하지 않는다** —
    셀프플레이 데이터가 RL의 주 학습 데이터이고, 난이도×페르소나×legacy가 섞인
    행동 다양성은 오프라인 RL에 자산. "삭제"가 아니라 "아카이브"가 맞음
  - 정책: N일(기본 14일) 지난 봇 전용 핸드(is_human=0만 있는 게임)의
    games+actions를 **Parquet(권장, pyarrow) 또는 JSONL.gz로 내보낸 후** DB에서 제거.
    사람 참여 핸드는 DB 영구 보존. 아카이브는 `archive/records/YYYY-MM.parquet`
    월 단위 파일 (RL 학습 시 그대로 읽음 — DuckDB로 SQL 조회도 가능)
  - 선행 소작업: games에 `bot_version TEXT` 컬럼(스키마 v9) — 기록 시점의
    git 커밋 해시 7자리. RL에서 "어느 버전 봇의 행동인지" 구분용
    (session 생성 시 1회 `git rev-parse --short HEAD` 캐시)
  - 구현: `scripts/db_maintenance.py` — 아카이브 내보내기 → 검증(행 수 대조)
    → DB에서 제거 → `VACUUM`. `--dry-run`(대상 통계만), `--days N`, `--no-vacuum`
  - 안전: 내보내기 파일의 행 수/체크섬 검증 후에만 삭제, 실행 전 자동 백업,
    워커/그라인드와 동시 실행 금지 (VACUUM은 배타 락)
  - 검증: dry-run → 소량 아카이브 → Parquet 재로드해 원본과 대조 → 파일 크기 before/after
  - 커밋: 스크립트 + 스키마 + docs/db-schema.md 정책 명시 (.gitignore에 archive/ 추가)

  **작업 3 — 백업 자동화** (haiku 에이전트, 30분)
  - `scripts/grind.py` 시작 시 `sqlite3 poker.db ".backup poker_backup.db"` 자동 실행
    (파일 분리 후엔 gto.db만 필수 백업 — 재수집 비용이 큰 유일 자산)
  - + `scripts/dump_gto.py`: GTO 테이블만 JSON 덤프 → git 커밋 가능하게
    (DB 전손 시에도 GTO 데이터 복원 가능) + 복원 스크립트
  - 검증: 덤프 → 임시 DB에 복원 → 원본과 행 수/샘플 값 대조
  - 커밋: 스크립트 + .gitignore(백업 파일 제외, gto 덤프 JSON은 포함)

  **권장 순서**: 3(백업, 즉시 해도 무방) → 2(보존) → 1(분리, 트리거 발동 시)

## ✨ 기능 추가

### GTO 개선

- [x] **GTO 힌트 토글** — 에퀴티 패널 작업에 흡수되어 완료 (095315d)
  - 헤더 👁 마스터 토글 (기본 off, localStorage) — 힌트 탭(에퀴티+GTO) 전체를 게이트

- [x] **GTO 데이터 DB화**
  - `db/schema.py` v2: gto_preflop_situations/hands, gto_postflop_situations/hands 테이블 추가
  - `tools/migrate_gto.py`: JSON → DB 마이그레이션 스크립트 (10 situations, 1690 hands)
  - `gto/loader.py`: DB 기반으로 교체 (앱 시작 시 전체 로드 캐시)
  - `gto_data/` 디렉터리 삭제 (DB가 source of truth)
  - ⚠️ vs_open 일부 데이터 부정확 (AKs/AKo fold 50% 등) → 점진적 교정 필요

- [x] **GTO Wizard → DB 연동 구축** (Claude in Chrome MCP)
  - 서버 HTTPS 전환 (ssl/ 자체 서명 인증서, Mixed Content 해결)
  - 추출 방식: CSS `background-size`의 누적 퍼센트로 각 핸드 action 빈도 파싱
  - URL 패턴: `history_spot=N` (N: UTG=0, HJ=1, CO=2, BTN=3, SB=4, BB=5)
  - GTO Wizard → `fetch('https://localhost:8000/gto/preflop/save')` 직접 호출
  - RFI 5개 스팟 GTO Wizard 데이터로 교체 완료

- [x] **RFI 데이터 GTO Wizard로 교체**
  - UTG(19%), MP/HJ(34%), CO(40%), BTN(52%), SB(59%) — 모두 AKo fold=0 확인
  - 구 JSON 데이터(오류 있음) → GTO Wizard 정확 데이터로 대체

- [x] **vs_open 15개 GTO Wizard로 수집 완료**
  - UI 클릭 방식으로 모든 포지션 조합 수집

- [x] **vs_3bet 31/35개 수집** (GTO Wizard 무료 한도 100스팟/일 초과로 중단)
  - 완료: UTG/HJ/CO 오픈 시리즈 전체, HJ 오픈 전체, CO 오픈 전체
  - 미완성 4개: BTN 오픈 시리즈 3개 + SB 오픈 1개

- [x] **미수집 스팟 자동 추적 시스템 구현** (`db/schema.py` v3)
  - `gto_missing_spots` 테이블: 게임 중 GTO 없는 스팟 자동 저장
  - `gto/url_generator.py`: 스팟별 GTO Wizard 직접 이동 URL 사전 계산
  - `gto/advisor.py`: RFI/vs_open/vs_3bet 데이터 없을 때 자동 기록
  - `scripts/show_missing_spots.py`: 미수집 현황 CLI 조회
  - 수집모드: "수집모드 실행해줘" → Claude가 Chrome MCP로 자동 수집

- [ ] **vs_3bet 나머지 4개 수집** — 아래 "Playwright 완전 자동화" 3단계에서 함께 소진 예정
  (자동화 전에 급하면: GTO Wizard 열고 "수집모드 실행해줘" — Chrome MCP 수동 수집)
  - BB vs [BTN open / SB 3bet]
  - BTN vs SB 3bet
  - BTN vs BB 3bet
  - SB vs BB 3bet

- [ ] **GTO 데이터 확장** (미존재 스팟)
  - 포스트플랍 레인지 (장기)

- [ ] **GTO 수집 Playwright 완전 자동화** — 기획 확정 (2026-07), 이 항목만 보고 실행 가능

  **목표**: 수집을 Claude 개입(토큰) 없는 로컬 스크립트로 전환.
  기존 방식은 Chrome MCP로 스팟마다 이동/추출 → 토큰 비쌈.

  **핵심 설계 결정**
  - 로그인 재사용: 사용자가 크롬을 디버그 포트로 실행 → 스크립트가 CDP로 접속
    `/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222`
    (`playwright.chromium.connect_over_cdp("http://localhost:9222")`)
  - 추출 이중화: XHR 솔루션 JSON 가로채기 1순위(정확 + EV 포함 가능성 → 플레이 평가
    2단계와 직결) / 검증된 CSS background-size 파싱 폴백

  **단계별 실행 계획** (코딩은 서브에이전트, 메모리 정책 참고)
  1. [정찰 — sonnet 에이전트 + Chrome MCP, GTO Wizard 열린 상태 필요]
     - 스팟 로드 시 XHR 응답 구조 조사: endpoint URL 패턴, JSON 스키마, EV 포함 여부
     - CSS 셀렉터 현행 확인(폴백용), SPA 라우팅 시 리로드 여부
     - 일일 한도(100스팟) 도달 신호(배너/응답코드) 확인 → 스크립트 중단 조건
     - 산출물: docs/gto-data.md에 "자동 수집 정찰 노트" 섹션 커밋
  2. [구현 — sonnet 에이전트] `scripts/collect_gto.py` 작성+커밋
     - CDP 연결 (실패 시 크롬 실행법 안내 출력)
     - 대상: gto_missing_spots(collected=0) + vs_3bet 잔여 4개 시딩, gto_wizard_url 재사용
     - 추출(XHR 우선/CSS 폴백) → gto_preflop_situations/hands upsert → collected=1
       (스팟 단위 커밋 = 중단 안전)
     - 안전장치: --limit N(기본 95, 일일 한도 보호) / --dry-run / 한도 감지 자동 중단
     - XHR에 EV 있으면 스키마 v7: gto_preflop_hands에 ev_* 컬럼 추가
     - 파싱 함수 픽스처 테스트, requirements에 playwright 추가
  3. [소량 검증 — 메인 + 사용자]
     - 사용자: 디버그 크롬 실행 + GTO Wizard 로그인 확인
     - --limit 3 --dry-run 눈검증 → **회귀 대조**: 이미 수집된 스팟(UTG RFI 등)
       재수집해서 DB 기존 값과 비교 = 파서 정확성 자동 증명
     - 통과 시 --limit 95 실전 1회 (vs_3bet 4개 + 미수집 큐 소진)
  4. [운영 통합 — haiku 에이전트]
     - 프로젝트 스킬 `.claude/skills/collect-gto/SKILL.md` (/collect-gto):
       크롬 실행 안내 → 스크립트 실행 → 결과 보고 절차
     - docs/gto-data.md 수집 방법 갱신, 이 TODO 항목 완료 처리, 커밋

  **리스크**: GTO Wizard 렌더 구조 변경 시 CSS 폴백 취약(그래서 XHR 우선),
  CDP는 크롬을 디버그 플래그로 재시작해야 하는 1회 불편.
  브라우저 밖 API 직접 호출(토큰 탈취)은 약관 리스크로 금지.

### AI 봇 개선

- [ ] **에퀴티 계산 2차 고속화** — 기획 확정 (2026-07). 곱연산 순서로 진행.
  현재까지: 7카드 비트마스크 평가기(14.8배), 스트리트 분해 DP, 부분 인덱스.
  목표: 플랍 스윕 130만 스팟을 "수개월 → 수일"로.

  - [x] **작업 1 — PyPy 실행 시험** (2026-07-09 완료)
    - 결과: 플랍 전수조사 1스팟(캐시적중 1) 평균 CPython 6.4s → PyPy 1.7s,
      **약 3.7배** 빨라짐 → PyPy 채택, docs/ai-bot.md 워커 섹션에 실행법 추가
    - PyPy의 `sqlite3`가 CPython보다 엄격해 `conn.execute()` 반환 커서를
      닫지 않고 `commit()`하면 `cannot commit transaction - SQL statements
      in progress` 에러 발생 → `scripts/equity_worker.py`, `db/connection.py`,
      `db/recorder.py`, `ai/equity.py`에서 커서를 명시적으로 닫도록 수정
      (CPython 회귀 없음, `tests/run_all.py --full` 전체 통과 확인)

  - [x] **작업 2 — 보드 중심 리버 계산 재구조화** (2026-07)
    - 아이디어: 같은 보드를 공유하는 스팟들이 상대 990조합 랭크 판정을 매번 반복.
      보드 B당 가능한 홀 C(47,2)=1081개 랭크를 **한 번만** 계산해 정렬 테이블화 →
      각 홀 equity = 이진탐색으로 "나보다 낮은 랭크 수" 카운트 (블로커 91조합 보정)
    - 구현: `ai/equity.py`에 `board_rank_table(board)` + `equity_via_board_table(hole, board, table)`.
      기존 `exact_counts_river`와 **동일 결과** — 랜덤 보드 100 × 홀 5 = 500케이스 완전 일치 (E-12)
    - 실측: 같은 보드에서 홀카드 N개 계산 시 테이블 1회+N번 lookup이 exact_counts_river
      N번 직접호출보다 N=10에서 **약 6.3배**, N=50에서 **약 28배** 빠름
    - 워커 통합(배칭)은 작업 3에서 이어짐 — 이번 범위는 함수 정합성·단일 스팟 성능까지
    - 커밋: ai/equity.py + tests/test_equity.py(E-12) + docs/ai-bot.md

  - [ ] **작업 3 — 워커 배치 인출/저장** (sonnet 에이전트, 반나절, 작업 1·2 이후)
    - 1·2로 계산이 빨라지면 스팟당 쿼리(6.4ms)가 다시 병목. 큐에서 500개씩 인출,
      결과 100개 단위 executemany 커밋 (중단 손실 최대 ~0.3초어치)
    - 그라인드 동시 실행 대비 멱등 유지 (UPDATE ... WHERE exact=0)
    - 검증: --minutes 1 처리량 before/after, run_all --full 통과
    - 커밋: scripts/equity_worker.py, 다중 -m, push

- [x] **에퀴티 엔진 알고리즘 최적화** (2026-06)
  - 고속 7카드 평가기 `evaluate_rank()`: 21개 부분집합 브루트포스 → 비트마스크 직접 판정
    14.8배 (20만 세트 등가성 불일치 0). equity 전 경로 적용
  - 스트리트 분해 DP: turn=리버46 합 / flop=턴47 합, equity_cache가 메모 테이블
    리버 3ms / 턴 0.14s(웜 2ms) / 플랍 6.5s(웜 수ms) — 기존 대비 30~70배
  - 플랍 1개 계산 시 자식 정확값 ~2,200행 부산물 → 캐시 커버리지 폭증
  - 테스트 E-9(등가성)/E-10(DP 정합성) 추가 — 39개

- [x] **포스트플랍 equity 기반 재작성** (A-1~A-5)
  - `ai/equity.py`: MC 샘플링 + 리버/턴/플랍 전수조사 + equity_cache DB 누적
  - 수트 정규화 키(24치환 최소)로 스팟 중복 제거
  - 봇: equity vs 팟오즈, 세미블러프, 등급형 포지션 점수, 보드 텍스처 사이징(33% 스몰벳 포함), 체크 믹스
  - 난이도 = MC 샘플 수(판단 해상도): easy 40 / medium 300 / hard 1200+리버 전수조사
  - 테스트 36개 (`tests/test_equity.py`)

- [x] **에퀴티 전수조사 워커** (`scripts/equity_worker.py`)
  - 중단/재개 안전 (스팟 단위 커밋), 리버→턴→플랍 우선순위
  - 프리플랍 169핸드 × 상대 1~5명 = 845스팟 고정밀 샘플링 (목표 100만/스팟)
  - 봇이 플레이 중 만난 스팟 자동 큐잉 → 워커가 정확값으로 승격
  - 사용: `python3 scripts/equity_worker.py [--minutes N | --status]`
  - 체계적 플랍 스윕: 큐가 비면 전체 플랍 공간(~130만 스팟)을 AA부터 순서대로
    전수조사 — 무한 작업. 커서 저장(worker_meta, DB v5)으로 재개 안전
  - `scripts/grind.py`: 아레나(실전 스팟 생산) + 워커(전수조사) 동시 실행 모드
    `python3 scripts/grind.py [--minutes N]` — 실전 빈도 순으로 캐시 축적
  - [x] **성능**: equity_cache 760만 행에서 작업 선택 쿼리가 병목(276ms/250ms,
    전체 스캔+정렬)이던 문제 수정 — 부분 인덱스 2개 추가(DB v7) +
    쿼리를 스트리트/조건별 단순 쿼리로 분리. 선택 시간 0.06~6ms로 개선

- [x] **상대 레인지 반영 equity** (B단계, hard 봇)
  - 프리플랍 로그 파싱 → 레이저는 RFI 레인지, 콜러는 콜 레인지로 시뮬레이션
  - `RangeSampler` + `ranged_equity()` (`ai/equity.py`), `gto/loader.py`에 레인지 추출 함수
  - 어그레션 마진: 벳 직면 시 벳/팟 비례 콜 기준 상향 (medium 0.06 / hard 0.08)

- [x] **봇 성향(페르소나) 부여** (D단계)
  - tight/loose/aggressive/passive/balanced — Alpha~Epsilon 고정 배정
  - 난이도 프로파일 위에 가산/배율 보정 (`PERSONAS`, `_effective_profile()`)

- [x] **봇 vs 봇 자동 시뮬레이션** (E단계, `scripts/bot_arena.py`)
  - legacy(개선 전) 베이스라인 내장, bb/100 비교, 매 핸드 100bb 리셋
  - 검증: 개선 전 hard -39.1 → 개선 후 +19.4 bb/100 (600핸드, seed=99)
  - 대규모: 1500핸드에서 hard 평균 +94.1 vs legacy -44.7 bb/100 (두 hard 좌석 모두 플러스)

- [x] **아레나 활용 인프라** (튜닝/회귀/퍼징)
  - `scripts/tune_bot.py`: 파라미터 그리드 A/B + 진화(hill-climb) 튜닝 → tuning_results.json
  - `scripts/ai_regression.py`: 신버전 vs legacy 고정 벤치마크 (FAIL 시 exit 1)
  - 아레나 시트 문법 확장: `hard:persona=aggressive`, `hard:aggression_margin=0.12+bluff_freq=0.3`
  - 아레나에 핸드별 칩 총량 보존 assert (엔진 퍼징)
  - 남은 것: 튜닝 장시간 실행으로 실제 최적값 찾기 (수치는 아직 이론값)

- [x] **프리플랍 equity 우선 계산 옵션** (memo 요청)
  - 워커 `--preflop-first`: 프리플랍 845스팟 샘플링을 전수조사보다 우선
  - 검증: AA 0.8507 / AKs 0.6691 — 공개 equity 표와 일치
  - 남은 것: vs1 목표 1000만 상향 + 공개 정확 테이블 대조 검증 (선택)
  - 프리플랍 equity의 역할: GTO 레인지(주 전략)의 보조 —
    GTO 없는 스팟 폴백 / 4벳+ 판단 / 플레이 평가 EV 계산에 사용

- [ ] **포스트플랍 베팅 레인지 반영** (B-2, 장기) — 실행 노트
  - 현재는 프리플랍 레인지 + 어그레션 마진 근사
  - 접근: 상대가 스트리트에서 벳/레이즈하면 RangeSampler 가중치에
    "보드에서 made rank/equity 상위 X%만 남기기" 필터 적용 (간이 베이지안).
    구현 위치: ai/bot.py `_opponent_ranges` 확장 + ai/equity.py 필터 함수
  - 검증 필수: 아레나 A/B (필터 on vs off, 3000핸드+) — 개선 안 되면 되돌릴 것
  - 선행: 없음. 난이도 높음 → opus급 에이전트 권장

- [ ] **포스트플랍 GTO 어드바이저** (장기) — 실행 노트
  - 선행 조건: 포스트플랍 GTO 데이터 (GTO Wizard 유료 플랜 검토와 연결)
    또는 equity_cache 기반 근사 힌트로 대체 가능 (플레이 평가의 EV 로직 재사용)
  - 데이터 없이 시작한다면: "equity + 팟오즈 + 드로우 여부"를 힌트로 표시하는
    경량판부터 (플레이 평가 1단계 산출물을 실시간 패널로 재노출)

- [x] **에퀴티 패널 (웹 실시간 표시)** — 완료 (2026-07). 플레이 평가와 함께 구현,
  연달아 진행 시 총 작업량 ~30% 절감 (같은 서버 훅/데이터)

  **화면** (오른쪽 사이드바, GTO 패널 위 섹션)
  1. 에퀴티 게이지: 가로 막대(내 승률만큼 채움) + 팟 오즈 세로 눈금선 —
     채움 끝이 눈금 오른쪽이면 콜 이득이 한눈에 보임. 큰 숫자 + 팟오즈 병기
  2. 상대별 에퀴티 브레이크다운 (사용자 설계):
     - 종합 한 줄 (팟 전체 이길 확률 — 모두 상대, ranged_equity)
     - 상대마다 한 줄: 이름 + 역할 태그(레이저/콜러/랜덤) + 1:1 레인지 에퀴티, 위협 순 정렬
     - 주의: 상대별 1:1 값은 곱해서 종합이 되지 않음 — 종합은 별도 유지 (혼동 방지)
     - 교육 효과: "누구 때문에 낮은지" 가시화 → 세미블러프/타겟팅 판단 근거
  3. 콜 EV 한 줄: equity×(팟+콜)−콜, +초록/−빨강, 벳 직면 시만
  4. 메타 한 줄: 값 출처(정확값/MC N샘플±오차) + 상대 수
  - 스트리트 히스토리: 프리플랍 55% → 플랍 62% → ... (플레이 평가 입력으로 재사용)

  **스포일러 정책**: 헤더 "힌트" 토글 하나로 GTO 패널+에퀴티 패널 통합 on/off (기본 off).
  off여도 서버는 계산·기록 → 핸드 종료 후 플레이 평가에서 소급 표시
  (기존 "GTO 힌트 토글" 항목은 이 기획에 흡수)

  **API**: get_state에 equity 필드 —
  `{vs_random, vs_range, pot_odds, call_ev_bb, source, samples, num_opponents,
    opponents: [{name, position, role: raiser|caller|unknown, equity}],
    history: [{street, vs_random}]}`
  - 계산: waiting_for_action=true일 때만. 캐시 exact 우선 → MC 1,000샘플 (~50ms)
  - 상대별: RangeSampler를 상대별 단독으로 1:1 MC (상대 3명 ≈ +150ms, 허용)
  - vs_range/상대별은 _opponent_ranges 재사용, 레인지 정보 없으면 role=unknown

  **실행 계획**
  1. [백엔드 — sonnet, ~2h] session._get_equity_info() + schemas + 유닛테스트
     (넛 핸드 equity>0.9 assert). run_all 통과 후 커밋
  2. [프론트 — sonnet, ~2h] EquityPanel.tsx (게이지/브레이크다운/EV/메타) +
     통합 힌트 토글 + types.ts. npm run build + 실플레이. 커밋 전 사용자 확인 (UI 규칙)
  3. 이어서 플레이 평가 1단계 진행 권장 (history 재사용)

- [x] **플레이 평가 기능 (Play Grader) v1** — 1단계 완료 (2026-07, c6ba45d/7eebc13 + 프론트)
  - 완료: 프리플랍 GTO 빈도 4등급 + 포스트플랍 콜/폴드 EV 판정, 결과 모달 "내 플레이",
    세션 배지(/session/review), human 액션 equity·GTO빈도 DB 기록(장기 트래킹 기반)
  - 남은 것: 2단계(GTO Wizard EV값 수집 후 진짜 EV손실), 벳/레이즈 정밀 판정, 통계 화면 연계

  **평가 기준 (스트리트별)**
  - 프리플랍: GTO 빈도 기반 — 내 액션의 GTO 빈도로 4등급 판정
    (✅최선=최고빈도 액션 / 🟡무난=빈도>25% / 🟠의문=5~25% / 🔴블런더=<5%)
    데이터 없는 스팟은 ⬜"데이터 없음" 명시
  - 포스트플랍: equity 기반 근사 EV — 사람 액션 시점에 서버가 equity 계산
    (equity_cache 정확값 우선, 없으면 MC ~1000샘플)
    · 콜: EV(콜) = equity×(팟+콜) − 콜 → 음수면 감점 + bb 손실 추정치 표시
    · 폴드: equity > 팟오즈+마진이었으면 "놓친 EV" 감점
    · 벳/레이즈: 폴드 에퀴티를 몰라 정확 평가 불가 → v1은 제한 판정만
      (equity 높은데 체크 반복=밸류 놓침 경고, 저equity 대형벳=블러프로 중립 표시)
    · 상대 레인지 반영: hard 봇의 _opponent_ranges 재사용 (프리플랍 액션 기반)

  **산출물**
  - 액션별: {스트리트, 액션, 팟오즈/equity/GTO빈도, 판정, EV손실(bb)}
  - 핸드 요약: 핸드 결과 모달 하단 "내 플레이" 섹션 (액션 타임라인 + 판정 칩)
  - 세션 요약: 총 EV손실(bb), 블런더 수, 스트리트별 정확도, GTO 일치율
    → 헤더 배지 (예: "GTO 78% / EV -12bb")

  **UX 원칙**: 평가는 핸드 종료 후에만 노출 (플레이 중 노출 = 힌트가 되어버림)

  **구현 스케치** (백엔드 → 프론트 순, 총 3~4시간 예상)
  1. `gto/grader.py`: 판정 규칙 엔진 (프리플랍 빈도 / 포스트플랍 EV)
  2. `session._apply`: human 액션이면 equity+GTO빈도 계산 → 평가 생성,
     세션 hand_reviews 누적 + **기존 DB 기록 행의 equity/gto_* 컬럼 채움**
     (→ 3단계 장기 트래킹이 자동으로 준비됨. human 액션도 이미 기록 중이므로)
  3. API: get_state에 hand_over 시 hand_review 포함, /session/review (세션 누적)
  4. web: HandResult 모달 확장 + 세션 통계 뷰

  **한계 (정직하게)**: 포스트플랍 벳/레이즈는 근사 평가.
  GTO Wizard EV값 수집(2단계) 후 프리플랍부터 진짜 EV 손실로 업그레이드

  **에이전트 실행 계획** (승인된 기획, 바로 위임 가능)
  1. [백엔드 — sonnet] `gto/grader.py`(판정 엔진) + `server/session.py` human 액션 훅
     + hand_review를 get_state에 포함 + DB 행의 equity/gto_* 채움
     - 검증: 유닛 테스트(판정 규칙 픽스처) + `tests/run_all.py --full` 통과
     - 커밋: 백엔드분만, 푸시
  2. [프론트 — sonnet] HandResult 모달 "내 플레이" 섹션 + 헤더 세션 배지
     - 검증: `npm run build` + `./start.sh` 실플레이 스크린샷
     - 커밋 전 사용자 확인 (UI 변경 규칙)
  3. [메인] 실플레이 검수 후 docs/ai-bot.md·api.md 갱신 여부 확인

- [ ] **사이드팟별 승자 표시** — 실행 계획 (sonnet 에이전트 1개, 방향 승인됨)
  - 백엔드: `server/session.py` `_do_showdown()`에서 `_calculate_side_pots()` 결과를
    팟별로 `{"label": "메인팟"|"사이드팟N", "amount", "winners": [...]}` 목록으로
    winner 이벤트와 get_state에 포함 (`pots_breakdown` 필드).
    **단독 eligible 팟(초과 베팅 반환)은 winners를 빈 배열로** — 승자 아님
    (이 버그 수정분은 이미 커밋됨 — winners 집계에서 len(eligible)>1 조건)
  - 프론트: `web/src/components/HandResult.tsx`에 팟별 줄 표시
    (예: "메인팟 800 → Player / 사이드팟 600 → 반환"), 사이드팟 없으면 기존 표시 유지
  - `web/src/types.ts` GameState에 pots_breakdown 타입 추가
  - 검증: 기존 사이드팟 테스트(6-5~6-8) 통과 + 3인 올인 시나리오 세션 테스트 1개 추가
    + `npm run build`
  - 커밋: UI 포함이므로 커밋 전 사용자 확인

- [ ] **통계 화면** — 실행 계획 (백엔드 sonnet + 프론트 sonnet, RL 기록 연결로 데이터 준비됨)
  - 백엔드: `server/main.py`에 `/stats/summary` (핸드 수, 포지션별 VPIP/PFR,
    수익 bb/100 — preflop_actions/games 집계 쿼리) + `/stats/hands?limit=50`
    (최근 핸드 목록: 보드/승자/내 손익)
  - 프론트: 우측 패널에 "통계" 탭 추가 (GtoPanel과 탭 전환), 요약 카드 + 핸드 리스트
  - VPIP = 자발적 팟 참여율(콜/레이즈), PFR = 프리플랍 레이즈율 — is_human=1 기준
  - 플레이 평가(위)와 화면·데이터 공유가 크므로 **플레이 평가 다음에 하는 게 효율적**
  - 검증: 아레나 몇 판 돌린 DB로 API 응답 눈검증 + `npm run build`
  - 커밋 전 사용자 확인 (UI)

- [ ] **UI 개선 — 스킵 모드 + 자동 진행** — 실행 계획 (sonnet 에이전트 1개, 프론트 전용)
  - **스킵 모드** (memo 요청): 우상단 토글(⏭, localStorage 저장).
    on일 때 내가 폴드한 핸드는 `useEventQueue`의 이벤트 재생을 건너뛰고
    (큐 즉시 소진 = 기존 스킵 버튼 로직 재사용) 바로 결과 모달 표시
  - **결과 팝업 자동 진행** (memo 요청): HandResult 모달에 타이머 —
    기본 5초 후 자동 onNextHand, 버튼 라벨 "다음 핸드 (5s 후 자동 진행)" 카운트다운,
    모달에 마우스 오버 중엔 타이머 일시정지, 스킵 모드와 독립 토글(설정 묶음 고려)
  - game_over(파산/클리어)에서는 자동 진행 금지
  - 검증: `npm run build` + 실플레이로 스킵/자동진행/호버정지 3케이스 확인
  - 커밋 전 사용자 확인 (UI)

- [ ] **UI 개선 — 기타** (필요 시 개별 기획)
  - 모바일 레이아웃 최적화
  - 핸드 히스토리 패널 (통계 화면의 /stats/hands 재사용 가능)

---

## ✅ 완료

- [x] 텍사스 홀덤 게임 엔진 (프리플랍~쇼다운)
- [x] AI 봇 3단계 (Easy / Medium / Hard)
- [x] 프리플랍 GTO 어드바이저 + 힌트 표시
- [x] FastAPI 백엔드 + React 웹 UI
- [x] 포커 로직 정밀 테스트 50개 전체 통과
- [x] 개발/프로덕션 실행 스크립트 분리
- [x] README + docs 작성
- [x] Git 초기화 및 GitHub 연결
- [x] 단계별 액션 애니메이션 시스템
  - SB→BB→UTG 순 한 장씩 2라운드 카드 딜링
  - 블라인드 베팅, 봇 액션 (생각 중 → 배지) 단계별 표시
  - 스트리트별 봇 딜레이 (프리플랍 1.2s ~ 리버 2.5s + 랜덤)
  - 커뮤니티 카드 한 장씩 공개
  - 액션 로그 애니메이션과 동기화
  - 내 카드 클릭으로 공개/숨기기
  - 베팅 칩 애니메이션, 폴드 딤 처리 타이밍 수정
  - 스킵 버튼
