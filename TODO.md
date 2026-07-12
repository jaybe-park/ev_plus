# TODO

작업 상태: `[ ]` 미완료 · `[x]` 완료 · `[-]` 보류

---

## 🌙 퇴근 시 돌려놓기 (기획 불필요, 즉시 실행)

```bash
# 1순위: 그라인드 — 캐시 + RL 학습데이터 + 미수집 스팟 발견 동시 축적
# pypy3로 실행하면 grind.py가 sys.executable로 워커/아레나를 서브프로세스로
# 띄우므로 워커도 자동으로 PyPy를 씀 (워커 처리량 3.7배, PyPy 미설치면 python3로 대체)
# 워커는 --workers 옵션 없이도 기본 max(1, cpu_count()-2)로 멀티프로세싱 병렬화됨
# (턴 처리 ~4.3배, 플랍 ~4.7배, 아레나 프로세스 몫 코어 2개는 자동으로 남겨둠)
pypy3 scripts/grind.py

# 또는: 프리플랍 equity 채우기 (845스팟, 순수 워커) — pypy3 권장
# 아레나가 없어 코어를 더 써도 되므로 --workers로 늘려도 됨 (예: --workers 10)
pypy3 scripts/equity_worker.py --preflop-first

# 또는: 파라미터 튜닝 캠페인 (봇이 스스로 강해짐, 결과는 tuning_results.json)
# 튜닝은 아레나 다수 실행이라 PyPy 이득이 크지 않음 — python3 유지
python3 scripts/tune_bot.py --profile hard --param aggression_margin --values 0.04,0.08,0.12 --hands 3000 --seeds 3
python3 scripts/tune_bot.py --profile hard --param semibluff_freq --evolve --start 0.55 --step 0.1 --rounds 5 --hands 2000

# 다음날 아침 확인 (--status는 python3/pypy3 상관없음)
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
  - 분리안: `gto.db`(gto_preflop_*, gto_missing_spots_preflop/_postflop — 소중, 거의 읽기 전용)
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

- [x] **gto_missing_spots 오탐 버그 수정 및 큐 정리** (2026-07-10)
  - 원인 1: `gto/advisor.py` RFI 판정(`current_bet <= big_blind`)이 포지션을 안 가려
    림프 팟에서 BB가 레이즈하면 "BB RFI"로 오판 → BB는 이미 강제 베팅한 상태라
    RFI 자체가 불가능한데 기록됨. 수정: RFI 블록에 `my_position != "BB"` 조건 추가.
  - 원인 2: vs_3bet 판정이 `my_position == 오프너(raisers[0])`인지 검증 안 해
    "CO vs CO 3bet", "BB vs BTN 3bet" 등 논리적으로 불가능한 조합이 대량 기록됨
    (우리 데이터 모델은 오프너가 3벳에 대응하는 레인지만 수집하므로 그 밖은 지원 안 함).
    수정: `my_position == opener_pos`일 때만 조회/기록, 아니면 `None` 반환.
  - 큐 정리: open/BB 1건, vs_3bet 오프너 불일치 53건 삭제 →
    open 2→1(BTN/SB 헤즈업 갭은 유지), vs_3bet 65→12, vs_open 18(변화 없음)
  - 큐는 아레나 볼륨과 무관하게 조합 공간(UNIQUE 제약)으로 빨리 saturate된다 —
    같은 미수집 스팟은 한 번만 기록되므로 볼륨을 늘려도 큐가 계속 늘진 않음.

- [x] **gto_missing_spots_preflop vs_open 오탐 버그 수정 및 큐 정리** (2026-07-12, 3번째 유사 버그)
  - 원인: `find_opener_position()`이 "BTN 림프 후 BB가 아이솔레이트 레이즈, 액션이
    BTN에게 돌아옴" 상황에서 opener_pos='BB'를 반환 — 우리 데이터 모델(open/vs_open/
    vs_3bet)이 "림프 후 아이솔레이트" 카테고리를 지원 안 하는데 조회/기록됨(BB RFI,
    vs_3bet 오프너 불일치와 같은 계열의 "모델 밖 상황" 버그).
  - 수정: `gto/advisor.py` vs_open 블록에서 오프너가 포지션 순서상 my_position보다
    뒤인 경우 조회/기록 없이 `None` 반환(`gto/url_generator.py`의 `POS_INDEX` 재사용,
    vs_3bet의 "my_position != opener_pos면 스킵" 패턴과 동일 원칙).
  - 큐 정리: 7개 → 6개 (BTN vs BB open 오탐 1건 삭제).

- [ ] 🔴 **프리플랍 GTO 전면 재작업 — 근본 원인 확정 + 사이징 실측화 + 전량 재수집**
  (긴급, 2026-07-10 확정. 사용자 지시: "완벽하게 하고 가자")

  ### 근본 원인 (추측 아님 — 코드에서 확정)

  `docs/gto-data.md`에 저장된 실제 추출 스크립트(`extractAndSave`, Chrome DevTools용
  JS)의 `colorToAction()` RGB 임계값이 잘못됨:
  ```js
  if (r < 80 && g > 150 && b < 80) return 'call';   // 실제 콜 #22c55e = rgb(34,197,94)
  ```
  콜의 실제 파란값(b)은 **94**인데 조건은 `b < 80` → **항상 거짓, 콜 세그먼트 100% 유실**.
  ```js
  if (r > 80 && r < 150 && g < 50 && b < 50) return 'allin';  // 실제 올인 #991b1b = rgb(153,27,27)
  ```
  올인의 실제 r값은 **153**인데 조건은 `r < 150` → 경계값 근접, 안티앨리어싱으로
  픽셀값이 흔들리면 걸리기도 안 걸리기도 하는 **불안정한 버그**
  (vs_3bet에서만 간간이 올인이 잡힌 이유). raise/fold 임계값은 정상.

  DB 실측 (2026-07-10 전수 검증): call>0인 행 8,619개 중 **0개**.
  allin>0: open 0/845, vs_open 0/2535, vs_3bet 61/5239. 빈도합 비정상: open 9%,
  **vs_open 15%**, vs_3bet 2%. → `sample_action()` 폴스루로 손상 핸드가 실제와
  다른 액션으로 치환(방향은 핸드마다 다름) → 봇 프리플랍 판단 왜곡(올인 과다 체감),
  hard 봇 `get_call_range` 무력화, 플레이 평가 프리플랍 등급도 오염 데이터 기준.

  ### 추가 문제: 사이징도 실측이 아니라 가짜값

  `gto_preflop_situations.raise_size`가 vs_open/vs_3bet 전부 `"3x"` 플레이스홀더로
  저장돼 있음(RFI만 `"2.5bb"`로 맞음). 실측 확인(GTO Wizard 직접 조회, 2026-07-10):
  UTG(2.5bb 오픈) 기준 3벳 사이징이 HJ=8bb(3.2x)/SB=11bb(4.4x)/BB=13.5bb(5.4x)로
  **배수가 일정하지 않음** — 공식으로 추론 불가, 반드시 실측해서 저장해야 함.
  `ai/bot.py` `_preflop_raise()`는 이 실측값 없이 자체 하드코딩 공식
  (오픈×3, 3벳×2.5)으로 추측 중 — 근거 없는 값. `gto/url_generator.py`의
  `THREE_BET_SIZE` 테이블도 추측치라 다음 스팟 URL 자체가 틀릴 위험(예:
  실측 UTG/SB=11인데 테이블엔 9.0으로 저장돼 있어 엉뚱한 노드로 이동할 뻔함).

  ### 대원칙 (재발 방지)
  - GTO Wizard 값은 있는 그대로만 저장 — 계산/추측/보간 금지
  - 저장 전 반드시 검증 (빈도 합 ≈ 1.0, 사이징은 화면에서 읽은 실측값만)
  - 검증 실패 스팟은 "손상/미수집"으로 명시 처리 — 절대 특정 액션(fold 등)에
    잔여를 몰아주지 않음 (원인 불명 상태에서 새 가정을 얹는 것과 같음)

  ### 실행 계획

  1. [x] [스키마 변경 — sonnet 에이전트] `gto_preflop_situations.raise_size`를
     TEXT("3x" 플레이스홀더) → 실측 숫자(REAL, bb 단위 raise-to 금액)로 변경.
     `gto_missing_spots` 테이블을 **`gto_missing_spots_preflop`으로 개명**
     (포스트플랍 GTO 추상화 작업 시 별도 `gto_missing_spots_postflop`이
     필요해질 것을 대비 — 미리 이름공간 분리). 스키마 버전 증가 + 마이그레이션.
     참조하는 모든 코드(`gto/advisor.py`, `scripts/show_missing_spots.py`) 및
     문서(`docs/architecture.md`, `docs/db-schema.md`, `docs/gto-data.md`,
     `docs/gto-postflop.md`, 본 TODO 내 다른 항목들)의 테이블명 갱신.
  2. [x] [기존 데이터 전량 무효화 — 같은 에이전트] `gto_preflop_situations`/
     `gto_preflop_hands`/`gto_missing_spots_preflop` 전체 삭제 (실행 전
     poker.db 백업). 손상 데이터를 신뢰도 있는 값처럼 남겨두는 게 없는 것보다 위험.
  3. [x] [코드 정리 — 같은 에이전트] `ai/bot.py` `_preflop_raise()`의 하드코딩
     배수 공식(오픈×3, 3벳×2.5) 제거 → 수집된 `raise_size`(실측 bb) 조회로 대체,
     데이터 없을 때만 명확히 구분된 폴백 사용. `gto/url_generator.py`의
     `THREE_BET_SIZE` 추측 테이블 제거 또는 "미검증" 명시 — 사이징을 미리
     추측해 URL을 만들지 않고, 수집 시 실제 화면에서 읽은 사이징으로 다음
     단계를 진행하는 방식으로 전환.
  4. [x] [로더 방어 — 같은 에이전트] `gto/loader.py`에 로드 시점 빈도합 재검증
     (이중 방어). 비정상이면 해당 핸드/스팟을 "데이터 없음"으로 처리해
     휴리스틱 폴백 — fold로 잔여를 몰아주는 로직은 만들지 않음.
  5. [수집기 설계 반영 — Playwright 자동화 구현 시] 4개 액션 색상을 동등하게,
     정확한 RGB 값으로 파싱(위 확정된 버그 재발 방지 — 임계값 부등식 대신
     정확한 hex 매칭 권장). 사이징은 화면에 표시된 숫자를 그대로 읽어 저장.
     핸드별 빈도합 ≈ 1.0(±0.02) 검증 통과한 것만 저장, 실패 시 거부+로그.
  6. [재수집 — Playwright 자동화 또는 수동 Chrome MCP] RFI 5개 포지션 전량
     우선 재수집(빠짐없이). vs_open/vs_3bet은 `gto_missing_spots_preflop`
     큐로 실전 우선순위 수집(그라인드/아레나가 자동으로 채움).
  7. [검증] 재수집 후 콜/올인 분포가 포지션별로 합리적인지, 사이징이 실측값인지
     DB 전수 조회로 육안 검증. 아레나 A/B로 봇 판단 정상화(올인 과다 완화) 확인.
     `python3 tests/run_all.py --full` 통과.

  ### 5~6번 진행 중 추가 발견 (2026-07-12, 실제 재수집 착수 후)

  - **GTO Wizard CSS 인코딩 방식이 문서화된 것과 다름을 확인**: `docs/gto-data.md`의
    기존 파서는 "단일 gradient + % 색상 스탑" 구조를 가정했으나, 실제로는
    **여러 개의 겹친 `linear-gradient` 레이어 + `background-size` 누적 폭(%)**
    구조였다. call이 없는 순수 오픈 스팟(UTG/HJ/CO/BTN RFI, 레이어 1~2개)에서는
    우연히 값이 맞아 재검증 통과했지만, call/allin이 섞이는 스팟(SB RFI 등,
    레이어 2~3개)에서는 기존 파서로 169핸드 전량 파싱 실패(badSum=169, 전부 공백)함을
    확인. 레이어를 앞(포그라운드)→뒤(백그라운드) 순으로 `allin, raise, call, fold`
    색상으로 매칭하고 누적폭 차분(현재 레이어 bg-size % − 이전 레이어 %)으로
    빈도를 구하는 새 파서로 교체 후 재검증(badSum=0). **`docs/gto-data.md`의
    저장된 추출 스크립트는 최신화 필요** — 다음 문서 갱신 시 반영.
  - **BTN/SB 헤즈업 RFI(id=105810)는 스킵 처리**: 6-max `POSITIONS` 목록에
    없어 `gto/url_generator.py`로 URL을 만들 수 없음(헤즈업은 GTO Wizard에서
    별도 게임타입 필요). 큐에는 `collected=0`으로 남겨둠 — 강제 수집하지
    않고 여기 기록만 해둠(→ 아래 "헤즈업 GTO 매핑" 항목으로 해결 예정).
  - **재수집 진행 현황 (2026-07-12)**: RFI 5개 중 4개(UTG/HJ/CO/BTN) 이전 완료
    + SB 오늘 완료 → RFI 전량 완료. vs_open 3개(BB vs BTN/UTG open, SB vs BTN
    open) 완료. vs_3bet 1개(BTN vs BB 3bet, 사이징 실측 28.5bb) 완료 —
    옛 "vs_3bet 나머지 4개 수집" 고정 목록 항목은 이 큐 기반 수집으로 완전히
    대체되어 삭제(중복 정리, 2026-07-12). 남은 큐는
    `python3 scripts/show_missing_spots.py`로 계속 확인하며 소진.

  **커밋 분할**: 1~4번(스키마+무효화+코드정리+로더방어)은 코드 작업이라 즉시
  진행 가능 — 묶어서 커밋. 5~7번(실제 수집)은 Playwright 자동화 완성 또는
  GTO Wizard 브라우저 세션이 필요해 별도 후속.

  ### 1~4번 완료 결과 (2026-07-12)
  - `SCHEMA_VERSION` 8→11. `raise_size` TEXT→REAL, `gto_missing_spots`→
    `gto_missing_spots_preflop` 개명(인덱스도 `idx_gto_missing_preflop_collected`로).
    v11 마이그레이션은 손상 데이터를 어차피 지울 예정이라 `gto_preflop_situations`/
    `gto_preflop_hands`를 DROP 후 새 정의로 재생성하는 방식 채택.
  - `poker.db.pre-gto-wipe-backup`(로컬 전용, 커밋 대상 아님)으로 백업 후
    `gto_preflop_situations`/`gto_preflop_hands`/`gto_missing_spots_preflop` 전량 0행 확인.
  - `ai/bot.py` `_preflop_raise()`: GTO 실측 `raise_size`(bb)가 있으면 그 값 우선
    사용, 없을 때만 기존 하드코딩 공식을 "폴백"으로 명시 구분해 사용.
  - `gto/advisor.py`: raise_size 문자열 플레이스홀더("2.5bb"/"3x"/"2.5x") 제거,
    실측값 또는 None만 반환. `gto/loader.py`: 핸드별 빈도합이 [0.9, 1.1] 밖이면
    해당 핸드를 스킵(경고 로그 남김) → `get_action_frequencies`가 None 반환해
    상위가 휴리스틱 폴백을 타도록 함(잔여를 fold 등에 몰아주지 않음).
  - `gto/url_generator.py`의 `THREE_BET_SIZE`는 대부분 미검증 추측치임을
    모듈 상단 주석으로 경고 추가(제거는 URL 생성 로직이 깨져 보류).
  - `python3 tests/run_all.py --full` 전체 통과 (test_poker_full/test_equity/test_grader 3개
    스위트 모두 ✅, 0 실패). `bot_arena.py --hands 5 --seats medium,easy --seed 3`
    GTO 데이터 없는 상태에서 에러 없이 정상 완주(전량 폴백/휴리스틱).

- [x] **헤즈업(2인) GTO 스팟 — 6-max SB/BB 포지션으로 매핑** (2026-07-12 확정, 완료)
  - 배경: 세션 진행 중 봇이 파산하면 `server/session.py` `_start_new_hand()`가
    `chips>0`인 플레이어만 남겨 테이블 인원이 실제로 6→...→2명까지 줄어듦.
    2인이 되면 `core/game.py` `get_positions()`가 딜러 자리를 `"BTN/SB"`로
    정상 표기하는데, GTO 레인지 DB는 6-max 포지션 키만 있어 조회 실패 →
    `gto_missing_spots_preflop`에 `position="BTN/SB"` 같은 미해결 스팟이 계속 쌓임
    (예: id=105810 BTN/SB RFI, 현재 스킵 처리됨)
  - 결정된 방식: 헤즈업 트리는 "SB(딜러) vs BB 단둘"인 6-max SB RFI/vs_open/
    vs_3bet 스팟과 게임 트리가 구조적으로 동일 → `my_position=="BTN/SB"`는
    `"SB"`로, 상대가 `"BTN/SB"`면 `vs_position`도 `"SB"`로 치환해 기존
    6-max 데이터를 그대로 재사용(레인지 재수집 불필요)
  - 스택 딥스 근사 명시: 6-max GTO 데이터는 원래부터 항상 100bb 기준(캐시게임
    특성상 매 핸드 스택이 벌어져도 별도 스택별 솔브 없이 100bb로 근사해왔음).
    헤즈업(파산으로 도달, 스택이 100bb에서 크게 벗어날 수 있음)도 같은 원칙
    으로 **항상 100bb 가정**을 그대로 적용하기로 결정(스택별 재계산은 비현실적)
  - 범위 한정: 이 매핑은 **2인(헤즈업)에만** 적용. 3~5인은 포지션 구성 자체가
    달라(예: 5인은 HJ 누락으로 CO의 성격이 6-max CO와 다름) 같은 논리의
    "가장 가까운 6-max 유사 스팟 대응"이 성립하지 않으므로 범위에서 제외
  - 실행 계획 (sonnet 에이전트 1개)
    1. `gto/advisor.py`의 GTO 조회 진입점에서 `my_position`/`vs_position`이
       `"BTN/SB"`면 `"SB"`로 치환 후 조회 (조회 실패 시 큐 기록도 이 치환된
       값으로 남도록 — 치환 지점이 큐 기록 이전이어야 함)
    2. `core/game.py`의 원본 라벨(`"BTN/SB"`)은 그대로 유지 — UI/핸드 히스토리
       표시용이므로 변경 금지, advisor 내부 조회 시점에서만 국소적으로 치환
    3. `docs/gto-data.md` 또는 관련 문서에 "100bb 고정 가정(헤즈업 포함)은
       의도된 근사"라고 한 줄 명시
    4. 기존 스킵된 id=105810(BTN/SB RFI) 큐 항목 처리(치환 로직으로 정상
       조회되는지 확인 후 재수집 또는 자동 매칭 확인) + 유닛테스트(2인
       테이블에서 advisor가 SB RFI 데이터로 정상 응답하는지)
    5. `python3 tests/run_all.py --fast` 통과 확인 후 커밋

  ### 완료 결과 (2026-07-12)
  - `gto/advisor.py` `get_recommendation()`: 진입 시 `my_position=="BTN/SB"`면
    `"SB"`로 치환(이후 모든 조회/큐 기록이 치환된 값 기준). vs_open의
    `opener_pos`, vs_3bet의 `opener_pos`/`three_bettor_pos`도 각각 `"BTN/SB"`면
    `"SB"`로 동일 치환. `core/game.py`의 원본 `"BTN/SB"` 라벨은 미변경(UI/핸드
    히스토리용 유지) — 치환은 advisor 내부 조회 시점에만 국소 적용.
  - 실측 확인: 헤즈업 BTN/SB RFI 조회(예: 72o)가 실제 DB의 SB RFI 데이터
    (`situation="SB RFI"`)로 정상 응답함을 확인. 스킵돼 있던 큐 항목
    id=105810(BTN/SB RFI)을 `collected=1`로 갱신(치환 매핑으로 실시간 해결되어
    더 이상 미해결 스팟이 아님, 별도 재수집 불필요).
  - `docs/gto-data.md`에 "100bb 고정 가정(헤즈업 포함)은 의도된 근사"와 헤즈업
    BTN/SB→SB 매핑을 한 줄 명시.
  - `tests/test_poker_full.py`에 `test_6_9_headsup_gto_btnSB_mapped_to_sb_rfi`
    추가(격리 임시 DB에 SB RFI 시추에이션을 직접 시딩 후 `gto/loader.py`의
    프로세스 캐시를 무효화해 헤즈업 2인 테이블에서 advisor가 SB RFI 데이터로
    정상 응답하는지 검증). `python3 tests/run_all.py --fast` 54개 전체 통과.

- [x] 🔴 **HJ RFI 데이터 오염 확인 + 전체 프리플랍 GTO 스팟 전수 검사** (memo 피드백, 2026-07-12, 완료)
  - 확인됨(직접 DB 조회, 2026-07-12): `HJ RFI`는 169핸드 **전부 fold=100%**로
    저장돼 있음(비교: UTG fold100%=117/169, CO=102, BTN=81, SB=61 — 포지션이
    늦을수록 오픈이 넓어지는 정상 패턴인데 HJ만 유일하게 전부 폴드로 깨져있음).
    재수집 작업(TODO "프리플랍 GTO 전면 재작업") 도중 HJ RFI를 다른 스팟들과
    다른 시점/방식으로 저장했을 가능성 — 원인 특정 필요

  ### 완료 결과 (2026-07-12)
  - **원인 확정**: Chrome MCP로 GTO Wizard HJ RFI 스팟(`preflop_actions=F&
    history_spot=1`)을 직접 재확인 — 실제 GTO 솔루션은 raise 21.7% / fold
    78.3% / allin 0%. 저장돼 있던 "전부 fold"는 실제 GTO 값이 아니라 재수집
    (v11 스키마 전환) 과정의 **저장 버그**였음이 확정됨(추측 아님, 화면 확인).
  - 레이어 기반 파서(allin/raise/call/fold 색상 매칭 + 누적폭 차분)로
    169핸드 재추출(`badSum=0`, Overview 패널의 21.7%/78.3%와 일치) 후
    `/gto/preflop/save`로 재저장. 재저장 후 fold100=111/169로 UTG(117)와
    CO(102) 사이에 정상 위치.
  - **전수 검사 스크립트** `scripts/audit_gto_preflop.py` 작성: 핸드별 빈도합
    [0.9,1.1] 검증, RFI 포지션 간 오픈 비율 순서 검증(UTG<HJ<CO<BTN<SB),
    특정 액션 100%/0% 쏠림 탐지. 현재 DB의 `gto_preflop_situations` 11개
    전체(RFI 5, vs_open 4, vs_3bet 2)에 대해 실행 — **HJ RFI 수정 후 11개
    전체 통과, 추가 이상 스팟 없음**.
  - `docs/gto-data.md`에 전수검사 결과, HJ RFI 오염 경위, 레이어 기반 파서
    최신판(`extractAndSave`) 반영.
  - `python3 tests/run_all.py --fast` 통과 확인 후 커밋.

- [ ] **조건부 에퀴티 적용 확대** (memo 피드백, 2026-07-10)
  - 배경: equity_cache는 "vs 랜덤" 기저 지표(캐시 가능, 유지가 맞음).
    조건부(3벳팟이면 쓰레기 핸드는 폴드된 분포)는 `ranged_equity`가 담당 —
    hard 봇과 에퀴티 패널 "vs 레인지"에 이미 적용됨
  - 남은 갭: ① medium 봇 미적용 ② 플레이 평가 EV 계산이 vs 랜덤 기준
    ③ 포스트플랍 벳/레이즈 기반 추가 좁히기(기존 B-2 항목)
  - 선행 조건: 위 콜 빈도 재수집 (콜러 레인지가 비어 있으면 조건부 자체가 반쪽)
  - 재수집 완료 후 ①②를 sonnet 에이전트 1개로 진행, 아레나 A/B 검증 포함

- [ ] **포스트플랍 GTO 추상화** — 설계 확정 (2026-07-10, 상세: docs/gto-postflop.md)
  - 요약: 전부 수집 불가(플랍 텍스처 1,755, 정확 보드 수백만) →
    ① 텍스처 클래스 추상화(포지션×팟타입×보드클래스 ≈ 최대 192개)가 스팟 키 정의
    ② 실전 우선순위 큐(신규 `gto_missing_spots_postflop` 테이블) ③ 미수집 클래스는 equity 폴백(현행)
  - 수집: 클래스당 대표 보드 2~3개를 GTO Wizard에서 수집해 블렌드 (카드 추상화 표준 기법)
  - 목표: 완전 GTO가 아니라 "equity 휴리스틱보다 확실히 나은 근사" — 아레나 bb/100로 검증

  **실행 단계** (순서대로, 각각 sonnet 에이전트)
  1. [분류기] `gto/board_class.py`: classify_board(플랍 3장) → 클래스 키
     (페어드×수트×하이카드×연결성). 유닛테스트(경계 케이스: 모노톤+페어드 등).
     board_wetness와 별개 함수로 (그건 연속값, 이건 이산 클래스)
  2. [큐 신설] advisor에 플랍 훅 추가: 플랍 데이터 없으면 신규
     `gto_missing_spots_postflop` 테이블(preflop과 별도 — street='flop' +
     클래스 키 스키마)에 기록 (UNIQUE saturate 가능해짐).
     v1 범위: 플랍 첫 액션(C벳 상황)만, 턴/리버·액션라인은 equity 폴백 유지
  3. [수집] 클래스당 대표 보드 2~3개 선정 로직 + Playwright 수집 + 블렌드 저장
     (gto_postflop_situations/hands 기존 테이블 활용). 프리플랍 재수집과 같은
     Playwright 인프라 사용 — 그 자동화 완성 이후 진행
  4. [통합/검증] 봇·힌트가 클래스 전략 조회하도록 연결 → 아레나 A/B
     (vs equity 휴리스틱). 개선 없으면 롤백, 개선 있는 클래스만 세분화 v2

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
     - 대상: gto_missing_spots_preflop(collected=0) + vs_3bet 잔여 4개 시딩, gto_wizard_url 재사용
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

- [x] **`--status` 집계를 증분 통계 테이블로 전환** — 완료 (2026-07-10)

  **배경**: `--status`의 카테고리별 진행률 쿼리(`SELECT street, num_opponents,
  COUNT(*), SUM(exact), AVG(total) FROM equity_cache GROUP BY street, num_opponents`)가
  equity_cache 전체를 풀스캔한다. 실측(9,600만 행): **59초**. 뒷받침 인덱스가 없어
  `SCAN equity_cache` + `TEMP B-TREE FOR GROUP BY`. 다른 쿼리(대기 큐 등)는
  부분 인덱스로 이미 0초 — 이 쿼리 하나만 문제.
  - 대안 검토: 커버링 인덱스 `(street, num_opponents, total, exact)` 추가 시
    59초→6.8초(8.7배) 실측 확인했으나, 테이블이 계속 자라므로(목표 리버 24억 행,
    현재 2,800만) 근본 해결이 아니라 **채택하지 않음** — 대신 아래 증분 방식으로.

  **설계**: `equity_cache_stats` 요약 테이블(street, num_opponents, spots,
  exact_done, total_sum) 신규. equity_cache에 쓰는 모든 경로에서 델타만큼
  즉시 갱신 → `--status`는 이 작은 테이블만 읽어 **행 수 무관하게 항상 즉시 응답**.

  **작업** (sonnet 에이전트, ~half day)
  - 스키마 v10: `equity_cache_stats(street TEXT, num_opponents INTEGER, spots INTEGER,
    exact_done INTEGER, total_sum INTEGER, PRIMARY KEY(street, num_opponents))`
  - 기존 equity_cache 쓰기 경로 전부 찾아 갱신 로직 추가 (누락 없이):
    `ai/equity.py`의 `cache_contribute`/`_flush_contributions`(MC 기여, total 증가),
    `scripts/equity_worker.py`의 `_upsert_exact`/`_batch_upsert_exact`(exact 승격),
    `seed_preflop_spots`/`sweep_flop_batch`(신규 스팟 INSERT, spots+1)
  - 신규 스팟 INSERT 시 `INSERT ... ON CONFLICT(street,num_opponents) DO UPDATE
    SET spots=spots+1` 형태로 원자적 증가 (같은 트랜잭션 내에서)
  - **1회 백필 스크립트**: 기존 equity_cache 전체를 한 번 집계해 초기값 채우기
    (이번만 풀스캔 발생, 이후로는 불필요 — `scripts/equity_worker.py --rebuild-stats`
    같은 일회성 서브커맨드로)
  - `show_status`를 `equity_cache_stats` 조회로 교체 (진행률 바 로직은 유지,
    데이터 소스만 변경)
  - **정합성 보장이 핵심** — 증분 카운터가 실제 값과 어긋나면 조용히 틀린 통계를
    보여주는 게 더 위험하다. 검증에서 반드시 실제 COUNT/SUM과 대조할 것

  **검증**
  - 백필 후 `equity_cache_stats` 합계가 실제 `equity_cache` 풀스캔 집계와 완전 일치
  - 그라인드/워커를 몇 분 돌린 뒤 다시 대조 — 증분 갱신이 실제 쓰기와 어긋나지
    않는지 (드리프트 없는지) 확인
  - `--status` 응답 시간 (목표: 행 수 무관 <1초)
  - `python3 tests/run_all.py --full` 통과, 그라인드 동시 실행 시 락 경합 없는지
    (멱등/트랜잭션 처리 확인 — 기존 배치 커밋 구조와 충돌 없게)

  **커밋**: db/schema.py, ai/equity.py, scripts/equity_worker.py, docs/db-schema.md,
  docs/ai-bot.md, 이 항목 [x]. 다중 -m 메시지, push

  **실측 결과 (2026-07-10)**: 스키마 v9로 `equity_cache_stats` 추가.
  `--status` 응답 시간 **59초 → 0.09초** (656배). `--rebuild-stats` 백필 직후
  실제 풀스캔 `GROUP BY`와 20개 카테고리 전부 완전 일치 확인. 워커 2분 실행 후
  재대조에서 드리프트 1건 발견 — `_batch_upsert_exact`가 같은 배치 내 캐노니컬
  키 중복(수트 정규화로 다른 실제 카드가 같은 키로 겹치는 경우, 리버 자식
  배치에서 흔함) 시 델타를 이중 반영하던 버그. 배치 내 마지막 값 기준으로만
  델타를 계산하도록 수정 후 재검증 → 이후 워커 추가 실행 + 실시간 봇 MC/exact
  기여 경로 직접 실행 모두 드리프트 없음. `tests/run_all.py --full` 31/31 통과.

- [x] **프리플랍 대기 체크 쿼리 풀스캔 버그 수정** — 완료 (2026-07-10)

  **배경**: `--workers` 병렬 압축계산(2초대)은 정상인데 실제 배치 처리 로그는
  10초+ 걸리는 것처럼 보임. 실측해보니 `next_mc_job`/`next_mc_batch`의 프리플랍
  대기 체크 쿼리(`WHERE exact=0 AND street='preflop' AND total < ?`)가 매 배치
  호출마다 `SCAN equity_cache`(1억 행+) 풀스캔 — 실측 **3.1초**. 프리플랍은 이미
  100% 완료라 항상 0건 반환하는데도 매번 이 지연이 추가됐다.

  **원인**: v8에서 `idx_equity_street`를 "잉여"로 판단해 제거했는데, 이 쿼리
  하나가 그 인덱스에 의존하고 있었던 걸 놓쳤음.

  **수정**: 스키마 v10 — 프리플랍 대기 행만 담는(최대 845행) 부분 인덱스 추가.
  ```sql
  CREATE INDEX IF NOT EXISTS idx_equity_preflop_pending
  ON equity_cache(total) WHERE exact = 0 AND street = 'preflop';
  ```

  **실측 결과**: `EXPLAIN QUERY PLAN` → `SEARCH equity_cache USING INDEX
  idx_equity_preflop_pending`로 전환 확인. 해당 쿼리 3.1초 → 마이크로초 단위.
  `next_mc_job`/`next_mc_batch` 직접 호출도 정상. 워커 30초 실행 시 배치 처리
  시간이 압축계산 시간(8초대/200스팟)에 근접, 숨은 지연 사라짐. `--status`,
  `--rebuild-stats` 회귀 없음. `tests/run_all.py --full` 31/31 통과.

  **커밋**: db/schema.py, docs/db-schema.md, 이 항목 [x]. 다중 -m 메시지, push

- [x] **에퀴티 워커 멀티프로세싱** — 완료 (2026-07-10)

  **배경**: 그라인드/워커 실행 중 CPU 사용률이 낮음(유휴 ~80%) — 워커가 단일
  프로세스·단일 스레드(GIL)로 계산하는데, 맥은 멀티코어라 대부분의 코어가 논다.

  **설계 원칙**: SQLite는 동시 쓰기가 근본 제약이므로 "쓰기는 메인 프로세스 1개,
  계산(순수 CPU 작업, DB 접근 없음)은 워커 프로세스 N개"로 분리한다.
  다행히 이미 배치 인출 구조(`next_exact_batch`, `next_mc_batch` 등)가 있어서
  "인출은 메인이 하고 계산 함수(`exact_counts_river`, `exact_flop_dp`,
  `equity_via_board_table`, `mc_counts` 등)는 DB 커넥션을 안 받는 순수 함수"라
  `multiprocessing.Pool`에 바로 넣을 수 있는 구조다.

  **구현** (sonnet 에이전트, ~1일)
  - `scripts/equity_worker.py`에 `multiprocessing.Pool(processes=os.cpu_count()-1)` 도입
  - 메인 루프: DB에서 배치 인출(리버/턴/플랍/MC 각각) → `pool.map` 또는
    `pool.starmap`으로 각 잡을 순수 계산 함수에 분배(잡 dict/튜플로 필요한 값만 전달,
    커넥션 객체는 절대 넘기지 않음) → 결과 수집 → 메인 프로세스가 단독으로
    `executemany` 커밋 (기존 `_flush_exact_updates`/`process_mc_batch` 재사용)
  - 플랍 전수조사(`exact_flop_dp`)는 내부에서 캐시(`_lookup_exact`/`_upsert_exact`)를
    DB에 직접 읽고 쓰므로 그대로 워커 프로세스에 넘기면 안 됨 — 이 함수는
    DB 접근 없는 순수 버전으로 먼저 분리하거나(자식이 캐시 조회 없이 항상 계산),
    또는 플랍은 이번 병렬화 범위에서 제외하고 리버/턴/MC만 병렬화 (실용적 절충)
  - PyPy 궁합: PyPy도 `multiprocessing` 지원하므로 pypy3 + 멀티프로세싱 곱연산 가능.
    다만 프로세스 생성 오버헤드가 CPython보다 상대적으로 크면 워커 수 튜닝 필요
  - `--workers N` 옵션 추가 (기본 `cpu_count()-1`), `--workers 1`이면 기존 순차 방식
    (회귀 안전, 디버깅용)
  - 그라인드(`scripts/grind.py`)와의 CPU 경합 고려: 아레나 프로세스 몫 코어를
    남기도록 워커 기본값을 `max(1, cpu_count()-2)` 정도로 보수적으로 잡을 것

  **검증**
  - 정합성: `--workers 1`과 `--workers N` 결과가 동일 스팟에 대해 완전히 같은
    (wins,ties,total) 산출하는지 (같은 스팟을 양쪽에 넣어 대조)
  - 성능: 코어 수 대비 처리량 스케일링 확인 (`--minutes 1`, workers 1/2/4/8 비교),
    CPU 사용률이 실제로 올라가는지(`top`/`ps` 또는 activity monitor로 체감 확인)
  - `python3 tests/run_all.py --full` 통과
  - PyPy 조합도 `--workers` 옵션과 함께 동작 확인

  **결과 (2026-07-10)**: "캐시 접근은 메인 전용, 순수 계산(`exact_counts_river`
  등)만 Pool 분배" 원칙으로 리버·턴·플랍·MC 전부 병렬화. 턴/플랍은 자식 스팟의
  DB 캐시 조회/저장을 메인이 배치로 처리(`_batch_lookup_exact`/
  `_batch_upsert_exact`)하고, 캐시 미적중 자식만 Pool로 계산해 캐시 이득과
  병렬성을 동시에 확보(`exact_turn_dp_parallel`/`exact_flop_dp_parallel`,
  기존 순차 버전은 `--workers 1` 경로로 그대로 유지).

  정합성: 리버5+턴3+플랍1 스팟을 `--workers 1`/`4`로 각각 처리해
  (wins,ties,total) 완전 일치 확인. 성능(12코어, 캐시 없는 신선한 DB):
  턴 40스팟 1→5.68s, 4→1.82s(x3.13), 10→1.33s(x4.28); 플랍 2스팟
  1→13.6s, 4→4.2s(x3.25), 10→2.9s(x4.71). `python3 tests/run_all.py --full`
  31개 전부 통과. PyPy(`pypy3 scripts/equity_worker.py --workers 2`) 에러 없이
  동작 확인 — multiprocessing.Pool은 PyPy에서도 그대로 지원됨.

  자세한 구조/실측 표는 docs/ai-bot.md "워커 멀티프로세싱" 섹션 참고.

- [x] **워커 멀티웨이 우선순위 조정 (vs4/vs5 후순위)** — 완료 (2026-07-09)

  `next_mc_job`/`next_mc_batch`의 멀티웨이 조회를 `ORDER BY num_opponents ASC, total ASC`로
  변경. 검증: `--minutes 1`(400건 처리) 실행 결과 처리된 400건 전부 vs2 — flop/turn/river
  vs2 평균 샘플이 18,946/18,699/18,342 → 20,882/20,768/20,334로 증가한 반면 vs3/vs4/vs5는
  거의 변동 없음(vs4·vs5는 이번 배치에서 아예 처리되지 않음). 변경 전(무정렬 시절)에는
  vs2~vs5가 섞여 처리됐던 것과 대조. `tests/run_all.py --full` 31개 전부 통과.

  **배경**: `--status` 점검 결과 vs1(정확값 100%)·vs2/vs3(평균 1.2~1.5만 샘플,
  오차 ±0.8~0.9%)는 실전에서 충분. vs4(평균 ~8천, ±1.1~1.2%)·vs5(평균 ~1,600,
  ±2.4~2.5%)는 아직 거칠고, 4~5인 멀티웨이가 리버까지 가는 빈도 자체가 낮음.
  → 목표 샘플 수(하향 조정) 대신 **처리 우선순위**를 낮춰 vs1~vs3에 자원 집중.

  **작업** (sonnet 에이전트, ~1시간)
  - `scripts/equity_worker.py`의 `next_mc_job`(및 `next_mc_batch`)에서
    멀티웨이 조회 시 `num_opponents`가 작은 것부터 처리하도록 정렬 추가
    (현재는 `ORDER BY total ASC`만 — num_opponents 무관하게 샘플 적은 것 우선이라
    vs4/vs5도 뒤섞여 처리됨). `ORDER BY num_opponents ASC, total ASC`로 변경
  - 프리플랍(vs1~5)은 별도 큐(`next_preflop_job`)라 영향 없음 — 이미 전부 완료 상태
  - 포스트플랍 exact(vs1) 큐는 그대로 최우선 유지, 이번 변경은 `next_mc_job`
    (멀티웨이 샘플링, num_opponents>1) 전용
  - 목표 샘플 수(`MULTIWAY_TARGET`)는 그대로 10만 유지 — 하향 조정 안 함
  - 검증: 정렬 변경 전/후 `--minutes 1` 실행해 vs2/vs3/vs4/vs5 샘플 증가량 분포
    비교 (vs2·vs3 증가량이 커지고 vs4·vs5는 거의 증가하지 않아야 정상)
  - `python3 tests/run_all.py --full` 통과
  - 커밋: scripts/equity_worker.py + docs/ai-bot.md(우선순위 규칙 명시) + 이 항목 [x]
    다중 -m 메시지, push

- [x] **에퀴티 계산 2차 고속화** — 작업 1·2·3 전부 완료 (2026-07).
  현재까지: 7카드 비트마스크 평가기(14.8배), 스트리트 분해 DP, 부분 인덱스
  + PyPy(3.7배) + board_rank_table(N=50 기준 28배) + 워커 배치 인출/저장(약 1.8배).
  목표(플랍 스윕 130만 스팟 "수개월 → 수일")를 향한 곱연산 최적화 완료.

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

  - [x] **작업 3 — 워커 배치 인출/저장** (2026-07 완료)
    - `next_exact_batch`/`next_mc_batch`가 pending id를 최대 500개(플랍 20개)
      배치로 인출, 결과는 `_flush_exact_updates`/`process_mc_batch`가 100건
      단위 executemany로 커밋 (중단 손실 최대 그 배치 분량)
    - **A. 리버 배치**: `process_river_batch()`가 배치 스팟을 디코딩한 실제
      보드로 그룹화해 `board_rank_table`을 그룹당 1회만 구축 후
      `equity_via_board_table` 적용. 조사: exact 리버 20만 건 샘플에서 실제
      보드 기준 그룹 크기 평균 ~2(최대 7, distinct board 10.2만/20만행) —
      유의미한 재사용 확인, 그룹화 적용. 합성 테스트(77건→72그룹)로
      `exact_counts_river`와 완전 일치 검증.
    - **B. 플랍 스윕 보드중심화**: `exact_flop_dp`/`exact_turn_dp` 내부의
      47×46개 리버 자식은 매번 다른 5장 보드라 `board_rank_table` 재사용
      여지가 없음을 확인 — **효과 없음, 스킵** (조사만 하고 코드 변경 없음)
    - **C. 배치 인프라**: 멱등 `WHERE id=? AND exact=0` 전 경로 적용,
      `bot_arena.py` 동시 실행으로 그라인드 안전성 확인 (에러 없음)
    - 실측: --minutes 1 완료 작업 수 배치 전 11개 → 배치 후 20개 (약 1.8배,
      큐 구성 차이로 완전 통제 비교는 아님). PyPy에서도 에러 없이 동작.
      `tests/run_all.py --full` 전체 통과.
    - 커밋: scripts/equity_worker.py, docs/ai-bot.md, TODO.md

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
