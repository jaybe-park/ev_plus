# TODO

작업 상태: `[ ]` 미완료 · `[x]` 완료 · `[-]` 보류

---

## 🐛 버그

- [ ] **BB일 때 첫 블라인드 애니메이션 순서 버그**
  - 내가 BB면 BB가 먼저 베팅하고 SB가 나중에 베팅하는 것처럼 보임
  - SB → BB 순서로 나와야 함 (useEventQueue 블라인드 이벤트 순서 확인)

- [ ] **test_poker_full.py 실행 시간 조사**
  - 봇 경량화(sims=20) + 임시 DB 적용 후에도 여전히 느림 — 원인 프로파일링 필요
  - 후보: 프리플랍 advisor의 스팟당 DB 커넥션 생성, 미수집 스팟 INSERT

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

## ✨ 기능 추가

### GTO 개선

- [ ] **GTO 힌트 토글**
  - 현재: 항상 표시됨
  - 변경: 버튼으로 on/off 전환 (기본값: off)
  - 위치: ActionBar 또는 헤더에 토글 버튼 추가

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

- [ ] **vs_3bet 나머지 4개 수집** (GTO Wizard 한도 리셋 후)
  - BB vs [BTN open / SB 3bet]
  - BTN vs SB 3bet
  - BTN vs BB 3bet
  - SB vs BB 3bet

- [ ] **GTO 데이터 확장** (미존재 스팟)
  - 포스트플랍 레인지 (장기)

### AI 봇 개선

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

- [ ] **포스트플랍 베팅 레인지 반영** (B-2, 장기)
  - 현재는 프리플랍 레인지 + 어그레션 마진 근사
  - 포스트플랍 벳/레이즈 액션으로 레인지 추가 좁히기

- [ ] **포스트플랍 GTO 어드바이저**
  - 현재 포스트플랍은 봇/힌트 모두 휴리스틱
  - 보드 텍스처, 포지션, 팟 오즈 기반 기본 레인지 추가

- [ ] **플레이 평가 기능 (Play Grader)** — 기획 확정 (2026-06)

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

- [ ] **사이드팟별 승자 표시**
  - 핸드 결과 모달에 메인팟/사이드팟 구분 표시 (금액 + 승자)
  - 단독 eligible 팟(초과 베팅 반환)은 승자 아님 — session.py 수정분 워킹트리에 있음

- [ ] **통계 화면**
  - DB 연결 후 가능: 핸드 히스토리, VPIP/PFR
  - GTO 권장 빈도 vs 실제 플레이 빈도 비교

- [ ] **UI 개선**
  - **스킵 모드** (토글 버튼, 오른쪽 위): 내가 폴드하면 바로 결과로 넘어감
  - **결과 팝업 자동 진행**: 일정 시간 후 자동 다음 핸드
    - 남은 시간 표시 (예: 다음 핸드 버튼에 "(3s 후 자동 진행)" 카운트다운)
    - 마우스 오버 시 타이머 정지 (확인할 시간 확보)
  - 모바일 레이아웃 최적화
  - 핸드 히스토리 패널

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
