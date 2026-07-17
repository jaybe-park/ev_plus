# TODO

작업 상태: `[ ]` Pending · `[~]` In Progress · `[x]` Done · `[-]` 보류

이 문서는 **진행 중/예정 작업만** 가볍게 유지한다. 완료된 Task는 상세 이력과 함께
`TODO_ARCHIVE.md`로 이관한다 (워크플로우: `CLAUDE.md` "기획/개발 워크플로우" 참고).

### Task 작성 템플릿
```markdown
### Task: [기능/작업 이름]
- **Status:** `[ ] Pending` / `[~] In Progress` / `[x] Done` / `[-] 보류`
- **Context:** 이 작업을 왜 하는지, 배경/근거를 서술.
- **Sub-tasks:**
  - [ ] 구현 항목
  - [ ] 검증 항목
  - [ ] **Docs Update:** 관련 docs/*.md 반영 (필수, 해당 없으면 명시)
```

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
pypy3 scripts/equity_worker.py --preflop-first

# 또는: 파라미터 튜닝 캠페인 (봇이 스스로 강해짐, 결과는 tuning_results.json)
python3 scripts/tune_bot.py --profile hard --param aggression_margin --values 0.04,0.08,0.12 --hands 3000 --seeds 3
python3 scripts/tune_bot.py --profile hard --param semibluff_freq --evolve --start 0.55 --step 0.1 --rounds 5 --hands 2000

# 다음날 아침 확인 (--status는 python3/pypy3 상관없음)
python3 scripts/equity_worker.py --status
ls -lh poker.db chip_violations.log 2>/dev/null   # 위반 로그가 있으면 시드로 재현 가능

# 프리플랍 GTO 트리 확장 (선택, 크롬 디버그 모드+GTO Wizard 로그인 필요)
# 관리 대상 Task 아님 — 일일 한도 내에서 내킬 때 돌리면 됨 (docs/gto-preflop-tree.md)
python3 scripts/collect_gto_tree.py --limit 90
python3 scripts/gto_tree_report.py   # 수집 현황 갱신
```

⚠️ 동시 실행 금지 조합: 워커 2개(중복 계산), 그라인드+튜닝(CPU/DB 경합)

---

## 진행 중 / 예정 작업

### Task: BB일 때 첫 블라인드 애니메이션 순서 버그
- **Status:** `[ ] Pending`
- **Context:** 내가 BB면 첫 핸드 시작 시 BB가 먼저 베팅하고 SB가 나중에 베팅하는 것처럼 보임.
- **Sub-tasks:**
  - [ ] `server/session.py` `_start_new_hand()`의 blind 이벤트 발행 순서 확인 —
    `for p in self.game.players` 순회라 좌석 순서대로 나감. 사람이 BB 좌석이면
    사람(BB)이 SB보다 먼저 발행될 수 있음 → **SB 먼저, BB 나중으로 정렬해 발행**하면
    해결 가능성 높음 (1순위 조사 대상)
  - [ ] 안 되면 `web/src/hooks/useEventQueue.ts`의 blind 이벤트 처리 타이밍 확인
  - [ ] 검증: 사람을 BB 좌석에 놓고 events 배열에서 blind 이벤트가 [SB, BB] 순인지
    assert (`tests/test_poker_full.py` 영역 6에 추가). 프론트까지 의심되면
    `./start.sh` 후 새 게임 반복 육안 확인
  - [ ] **Docs Update:** 해당 없음 (버그 수정, 별도 설계 문서 변경 없음)
  - 커밋: 한국어 메시지 + Co-Authored-By 트레일러, 푸시 (버그 수정은 즉시 커밋 가능)

### Task: DB 인프라 정비 (SQLite 유지 + 파일 분리/보존/백업)
- **Status:** `[ ] Pending` — 트리거 발동, 원인 재조사 진행 중 (2026-07-17)
- **Context:** `poker.db` 실측 15GB로 트리거(5GB) 초과. 행 수 기준 재조사 결과
  `equity_cache`(1억 3,977만 행)가 `games`+`preflop_actions`+`postflop_actions`
  합계(약 314만 행)보다 50배 많음 — 대략 15GB 중 10GB+가 equity_cache, 플레이
  기록은 ~1.5GB 추정(확정 아님, 바이트 단위 정확 측정 아직 안 함). MySQL/Docker
  전환은 반려 확정(로컬 단일 사용자 패턴은 SQLite WAL 적정 영역, 향후 분석
  필요해지면 DuckDB/Parquet 내보내기가 답).
- **Sub-tasks:**
  - [ ] **원인 정확 측정** (다음에 이것부터): equity_cache 실제 디스크 점유 측정
    (`dbstat` 컴파일된 sqlite3로 재확인, 또는 테이블별 VACUUM INTO 후 파일 크기 비교)
  - [ ] equity_cache는 재계산 가능한 캐시(원본 아님) — 삭제/축소 리스크가 플레이
    기록보다 낮음. 정리 전략 설계(오래된 MC 근사치 정리, 불필요한 num_opponents
    조합 정리 등)
  - [ ] 위 결과에 따라 "파일 분리"를 equity.db 중심으로 먼저 할지, 별도
    equity_cache 전용 정리 작업을 새로 기획할지 결정
  - [ ] **작업 1 — 용도별 DB 파일 분리** (sonnet 에이전트, 반나절): `gto.db`/`equity.db`/
    `records.db` 분리. `db/connection.py`에 `get_connection(kind=...)` 도입,
    호출부 치환. 1회 마이그레이션 스크립트(`ATTACH DATABASE`), 원본 .bak 보관.
    EV_PLUS_DB 테스트 격리 환경변수 kind별 확장 필요
  - [ ] **작업 2 — RL 기록 아카이브 정책** (sonnet 에이전트, 3~4시간, 우선순위 낮춤 —
    예상보다 효과 작을 수 있음): 봇 전용 핸드(사람 참여 없음)는 삭제하지 않고
    N일(기본 14일) 지나면 Parquet/JSONL.gz로 아카이브 후 DB에서 제거. 사람 참여
    핸드는 영구 보존. 선행: `games.bot_version` 컬럼(스키마 v9). 구현:
    `scripts/db_maintenance.py`(--dry-run/--days N/--no-vacuum)
  - [ ] **작업 3 — 백업 자동화** (haiku 에이전트, 30분): `scripts/grind.py` 시작 시
    자동 `.backup`, `scripts/dump_gto.py`(GTO 테이블 JSON 덤프, git 커밋 가능)
  - [ ] 권장 순서: 원인 정확 측정 → 3(백업) → 2(보존) → 1(분리, 트리거 발동 시)
  - [ ] **Docs Update:** `docs/db-schema.md`, `docs/architecture.md`

### Task: 조건부 에퀴티 적용 확대
- **Status:** `[ ] Pending`
- **Context:** equity_cache는 "vs 랜덤" 기저 지표. 조건부(3벳팟이면 쓰레기 핸드는
  폴드된 분포)는 `ranged_equity`가 담당 — hard 봇과 에퀴티 패널 "vs 레인지"에는
  이미 적용됨. 남은 갭: ① medium 봇 미적용 ② 플레이 평가 EV 계산이 vs 랜덤 기준
  ③ 포스트플랍 벳/레이즈 기반 추가 좁히기(아래 "Epic: 포스트플랍 전략" 범위와 겹침, 그쪽에서 흡수 검토).
- **Sub-tasks:**
  - [ ] medium 봇에 ranged_equity 적용
  - [ ] 플레이 평가 EV 계산을 vs_range 기준으로 전환
  - [ ] 아레나 A/B 검증
  - [ ] **Docs Update:** `docs/ai-bot.md`

### Epic: 포스트플랍 전략 — 프리플랍 GTO 기반 레인지 좁히기 확장
- **Status:** `[ ] 설계 논의 중` — 아직 실행 계획 아님, 대화로 설계 확정 중 (2026-07-17 시작)
- **Context (폐기 배경):** 기존 3개 Task("포스트플랍 GTO 추상화", "포스트플랍 베팅
  레인지 반영(B-2)", "포스트플랍 GTO 어드바이저")를 통폐합. "포스트플랍 GTO 추상화"
  (`docs/gto-postflop.md`, 텍스처 클래스별 대표 보드 수집)는 **폐기** — 포스트플랍
  실측 솔브가 유료 하루 1스팟 제한이라 클래스 ≈192개 수집이 현실적으로 불가능(문서
  삭제, 상세 사유는 `TODO_ARCHIVE.md`).
- **핵심 아이디어**: 이미 부분 구현된 `RangeSampler`/`ranged_equity`(프리플랍 액션
  기반 상대 레인지 좁히기, hard 봇에 적용 중, **equity_cache DB 미사용 — 매번 새
  MC 시뮬레이션**)를 **포스트플랍 베팅까지 확장**. 상대가 벳/레이즈하면 "이 보드에서
  그 정도 베팅할 만한 핸드만 레인지에 남기기" 식으로 계속 좁혀나가는 근사.
  `equity_cache`(vs 랜덤)가 3벳/4벳 팟에서도 72o 같은 핸드까지 포함해 EV를 과하게
  후하게 계산하는 문제의 근본 해결책. 용어: **"게임이론(GTO)"이 아니라 "레인지 기반
  핸드 리딩/range vs range equity"** — 상대가 프리플랍까지 GTO대로 플레이했다는
  가정 위에서 베이지안하게 레인지를 좁히는 근사 기법이지, 포스트플랍 균형(사이징/
  블러프 빈도 포함)을 실제로 푸는 것은 아님.
- **아키텍처 (2-레이어 분리, 확정)**:
  1. **랭킹 엔진**(A/B 공통, 안 바뀜): 레인지 안 각 핸드를 구체적 보드에서 평가/순위
  2. **컷오프 정책**(교체 가능): A안=사이즈 무관 고정 컷오프(예: 상위 40%) /
     B안(최종 목표)=베팅 사이즈별 다른 컷오프(작은 벳=넓게, 오버벳=폴라라이즈).
     정책을 함수/설정으로 주입 가능하게 만들면 A→B 전환 시 랭킹 엔진·연결부·
     검증 루프는 그대로 재사용, 정책만 교체
- **1차 범위 확정**: **플랍 첫 벳/레이즈만** (턴/리버, 체크레이즈 등 복잡한 라인은
  이후 확장 — 사용자 결정, 2026-07-17)
- **진행 순서 확정**: **A안부터 착수**, B안(사이즈별 폴라라이즈)은 이후 단계
- **B안 튜닝 방식(향후, 설계만 확정)**: 사람 플레이 기록 기반 아님 — 컷오프 정책
  후보 여러 개를 정의 → `bot_arena.py` 자가대국으로 bb/100 비교(`scripts/tune_bot.py`
  그리드/evolve 패턴 재사용) → 승률 좋은 후보로 수렴. 노트북 컴퓨팅으로 충분(이미
  `tune_bot.py`가 같은 패턴으로 nightly 루틴에 있음)
- **equity_cache(vs 랜덤) 처리 확정**: 삭제 안 함 — easy/medium 봇 판단, hard 봇
  레인지 정보 없을 때 폴백으로 계속 사용(레인지 반영 계산과 별개 경로, 안 겹침).
  다만 **UI(에퀴티 패널)에는 vs_random 표시를 뺀다** — 헷갈리기만 함 (아래
  "에퀴티 표시/해석" Task에 반영). 무한정 커지는 것에 대한 우려는 별도로
  "DB 인프라 정비" Task에서 "성장 상한 정책 필요 여부"로 다룰 것(플랍 전수조사가
  현재 "무한 작업"으로 설계돼 있음)
- **모델 전략(확정)**: 까다로운 설계/스펙 확정 단계는 상위 모델(Opus), 스펙이
  명확해진 뒤의 코드 구현은 하위 모델(Sonnet/Haiku) + 테스트/아레나 검증으로 커버
  (메모리 `delegate-coding-to-subagents.md`에 일반 원칙으로 반영됨)
- **Sub-tasks:** (설계 미완 — 다음 논의에서 채울 것)
  - [ ] 랭킹 엔진의 정확한 강도 지표 확정 (made_hand_rank vs 보드 대비 equity 등)
  - [ ] A안 컷오프 값/필터 적용 시점(어느 스트리트/액션에 훅 거는지), `_opponent_ranges`
    확장 인터페이스 설계
  - [ ] 필터링 후 RangeSampler 가중치 재정규화 방식
  - [ ] 검증 기준(아레나 bb/100, 최소 핸드 수) 구체화
  - [ ] **Docs Update:** `docs/postflop-range-strategy.md` 신규 작성 검토 (설계 확정 시)

### Task: 사이드팟별 승자 표시
- **Status:** `[ ] Pending` — 실행 계획 승인됨 (sonnet 에이전트 1개)
- **Context:** 팟별(메인/사이드) 승자를 구분해서 UI에 표시. 단독 eligible 팟(초과
  베팅 반환)은 승자 아님 처리 버그 수정분은 이미 커밋됨.
- **Sub-tasks:**
  - [ ] 백엔드: `server/session.py` `_do_showdown()`에서 `_calculate_side_pots()`
    결과를 `{"label", "amount", "winners"}` 목록으로 winner 이벤트/get_state에 포함
    (`pots_breakdown` 필드)
  - [ ] 프론트: `web/src/components/HandResult.tsx`에 팟별 줄 표시,
    `web/src/types.ts` GameState에 pots_breakdown 타입 추가
  - [ ] 검증: 기존 사이드팟 테스트(6-5~6-8) 통과 + 3인 올인 시나리오 테스트 1개 추가
    + `npm run build`
  - [ ] 커밋 전 사용자 확인 (UI 변경 규칙)
  - [ ] **Docs Update:** `docs/api.md` (pots_breakdown 필드)

### Task: 통계 화면
- **Status:** `[ ] Pending`
- **Context:** RL 기록 연결로 데이터는 이미 준비됨. 플레이 평가와 화면·데이터 공유가
  커서 플레이 평가 이후 진행이 효율적.
- **Sub-tasks:**
  - [ ] 백엔드: `/stats/summary`(핸드 수, 포지션별 VPIP/PFR, bb/100) +
    `/stats/hands?limit=50`
  - [ ] 프론트: 우측 패널 "통계" 탭 추가 (GtoPanel과 탭 전환)
  - [ ] 검증: 아레나 몇 판 돌린 DB로 API 응답 눈검증 + `npm run build`
  - [ ] 커밋 전 사용자 확인 (UI)
  - [ ] **Docs Update:** `docs/api.md`

### Task: UI 개선 — 스킵 모드 + 자동 진행
- **Status:** `[ ] Pending` — 실행 계획 승인됨 (sonnet 에이전트 1개, 프론트 전용)
- **Context:** 스킵 모드(폴드한 핸드는 이벤트 재생 건너뛰고 바로 결과), 결과 팝업
  자동 진행(기본 5초 후 자동 다음 핸드, 호버 시 일시정지).
- **Sub-tasks:**
  - [ ] 스킵 모드: 우상단 토글(⏭, localStorage) — on이면 `useEventQueue` 이벤트
    재생 스킵, 바로 결과 모달
  - [ ] 자동 진행: HandResult 모달 타이머(기본 5초, 카운트다운 라벨, 호버 시 정지),
    game_over(파산/클리어)에서는 자동 진행 금지, 스킵 모드와 독립 토글
  - [ ] 검증: `npm run build` + 실플레이 3케이스(스킵/자동진행/호버정지)
  - [ ] 커밋 전 사용자 확인 (UI)
  - [ ] **Docs Update:** 해당 없음(프론트 UI 세부)

### Task: UI 개선 — 기타 (필요 시 개별 기획)
- **Status:** `[ ] Pending`
- **Context:** 모바일 레이아웃 최적화, 핸드 히스토리 패널(통계 화면의
  `/stats/hands` 재사용 가능).
- **Sub-tasks:**
  - [ ] 모바일 레이아웃 최적화 세부 기획
  - [ ] 핸드 히스토리 패널 세부 기획
  - [ ] **Docs Update:** 해당 없음(착수 시 개별 기획)

### Task: 게임 로그 UI 개선 (memo 피드백, 2026-07-17)
- **Status:** `[ ] Pending`
- **Context:** 현재 로그에 핸드/보드 카드 정보가 없어 로그만 복사해 다른 AI에게
  물어보기 어려움. 로그 영역이 fixed height라 스크롤이 답답함.
- **Sub-tasks:**
  - [ ] 로그 각 항목에 내 핸드 카드 + 현재 보드 카드 정보 포함해서 렌더링
    (`web/src/components/` 로그 관련 컴포넌트 확인)
  - [ ] 로그 영역 fixed height 제거 → 컨텐츠만큼 자연 확장(계속 아래로 추가)
  - [ ] 로그 복사 버튼을 로그 영역 우상단으로 이동/추가 (해당 로그 텍스트만 복사)
  - [ ] `npm run build` + `./start.sh` 실플레이로 3가지 확인
  - [ ] 커밋 전 사용자 확인 (UI 변경 규칙)
  - [ ] **Docs Update:** 해당 없음 (순수 프론트 UI)

### Task: 힌트 패널 UI 재구성 (memo 피드백, 2026-07-17)
- **Status:** `[ ] Pending`
- **Context:** 힌트(GTO+에퀴티) 패널 height가 화면을 넘어가 액션 버튼이 밀려나고
  스크롤 다운이 필요한 문제.
- **Sub-tasks:**
  - [ ] 힌트 패널 구성을 다음 순서로 축소: ① 핸드 라벨(예: "SB RFI(3.5)") →
    ② GTO 빈도 → ③ 내 패의 액션 퍼센트 → ④ 에퀴티. 그 외 항목은 UI에서 제거
  - [ ] 액션 버튼이 항상 뷰포트 안에 보이도록 레이아웃 조정
  - [ ] `npm run build` + 실플레이(정보 많은 vs_3bet 등)로 확인
  - [ ] 커밋 전 사용자 확인 (UI 변경 규칙)
  - [ ] **Docs Update:** 해당 없음(구조 변경 있으면 `docs/architecture.md`)

### Task: 에퀴티 표시/해석 조사 및 문서화 (memo 피드백, 2026-07-17)
- **Status:** `[ ] Pending`
- **Context:** 세 가지 의문 — ① 프리플랍에서 에퀴티가 거의 안 보임(의도된 동작인지)
  ② 에퀴티(콜 EV 마이너스)와 GTO 추천(콜/레이즈) 불일치 원인 ③ 표시 중인 에퀴티가
  정확히 무엇(콜만? vs_random/vs_range?)인지 불명확.
- **Sub-tasks:**
  - [ ] ① `server/session.py`의 `_get_equity_info()`/`waiting_for_action` 조건 확인
  - [ ] ② 불일치가 정상(GTO는 폴드에퀴티/멀티스트리트 반영)인지 사례로 검증,
    필요시 UI에 설명 문구 추가 검토
  - [ ] ③ (2026-07-17 결정) vs_random은 헷갈리기만 하니 **UI에서 제거** —
    vs_range(레인지 반영)만 표시. vs_random 계산/DB는 유지(easy/medium 판단·
    hard 폴백에 계속 쓰임), UI 노출만 뺌
  - [ ] `npm run build`(UI 변경 시) + `tests/run_all.py --fast` 통과
  - [ ] UI 변경 있으면 커밋 전 사용자 확인
  - [ ] **Docs Update:** `docs/ai-bot.md` "에퀴티 패널" 섹션에 해석 가이드 추가 (필수)

---

## ✅ 완료 요약

전체 상세 이력은 `TODO_ARCHIVE.md` 참고.

- 게임 엔진/AI 봇/GTO 어드바이저/에퀴티 엔진/플레이 평가 v1/에퀴티 패널 등 핵심 기능 구현
- 프리플랍 GTO 데이터 수집 체계 (①~④, 데이터 기반 트리 워커 포함) 구축
- 에퀴티 계산 고속화 (비트마스크 평가기, 보드 중심 DP, 멀티프로세싱, 증분 통계)
- 기획/개발 워크플로우 체계화 (memo.md ↔ TODO.md ↔ TODO_ARCHIVE.md, `CLAUDE.md` 반영)
