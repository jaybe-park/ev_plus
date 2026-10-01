# ev_plus

혼자 AI 봇과 Texas Hold'em(6-max 캐시게임)을 플레이하고 공부하기 위한 개인 프로젝트.
FastAPI 백엔드 + React(Vite) 프론트 + SQLite(`poker.db`). GTO Wizard 프리플랍 데이터로 힌트·봇 판단,
에퀴티 엔진(전수조사·적응형 MC), 3단계 봇, 플레이 복기.

## 빠른 시작

```bash
pip install -r requirements.txt      # 최초 1회
cd web && npm install && cd ..       # 최초 1회
./start.sh                           # 개발 모드 → 브라우저 http://localhost:5766
```

백엔드 `https://localhost:8765`(HTTPS 필수, 자체 서명 인증서는 처음 실행 때 `ssl/`에 생성), 프론트 `http://localhost:5766`.
프로덕션(단일 포트)은 `./prod.sh`.

```bash
python3 tests/run_all.py             # 빠른 테스트(수 초)
python3 tests/run_all.py --full      # 전체 + 프론트 build·lint·vitest (커밋 전 1회)
```

## 프로젝트 구조

```
ev_plus/
├── core/      # 포커 룰 엔진 (카드·덱·핸드 평가·베팅·사이드팟) — 룰은 여기 한 곳
├── ai/        # 봇(easy/medium/hard, 페르소나) · 에퀴티 엔진 · 프리플랍 에퀴티 상수 테이블
├── gto/       # 프리플랍 GTO 로더·어드바이저·노드 키·플레이 복기(grader)
├── server/    # FastAPI — 웹 세션(봇 자동 진행·이벤트)·GTO 관리 API
├── web/       # React + Vite + Tailwind 프론트 (vitest)
├── db/        # SQLite 연결·스키마·마이그레이션·핸드 기록
├── cli/       # 터미널 플레이 (core 콜백 방식, 룰은 웹과 동일)
├── scripts/   # bot_arena · grind · tune_bot · ai_regression · bench_equity · gen_preflop_table
│              # collect_gto_tree · gto_tree_worker · gto_tree_report · audit_gto_preflop
│              # show_missing_spots · prune_missing_spots · server_env.sh
├── tools/     # gto_extract_and_save.js (GTO Wizard 콘솔에서 수동 저장)
├── tests/     # run_all.py 진입점 · 독립 평가기/분배기 대조 · 세션 퍼저
└── docs/      # spec(현재 사양) · decisions(ADR) · 운영 플레이북
```

## 현재 상태

| 기능 | 상태 |
|---|---|
| 포커 룰 엔진 | ✅ 독립 평가기·분배기와 전수 대조 일치, 세션 퍼저가 참조 모델과 대조 |
| 웹 UI + 이벤트 재생 | ✅ 재생 표시 상태 하나, 사이드팟·반환 계층 표시, 복기 EV 손실 표시 |
| AI 봇 3단계 | ✅ 난이도 = MC 해상도(easy 40샘플 / medium·hard 적응형 ±1%p), hard는 상대 레인지 반영 |
| 프리플랍 GTO 힌트 | ✅ 정확한 노드(액션 순서) 먼저, 없으면 라벨 노드 "(근사)" — 올인·림프·3~5인은 근사 없음 |
| 에퀴티 패널 + 플레이 복기 | ✅ 패널·복기 모두 vs_range 기준, 대칭 경계 판정(ADR 0049) |
| 확률 검증 장치 | ✅ 공개 기준값 23개, 독립 평가기 대조, 레인지 샘플러 전수 대조, 정밀도·응답 시간 회귀 |
| 프리플랍 GTO 수집 | ✅ 운영 루틴(Playwright 워커) — 절차는 [gto-preflop.md](docs/spec/gto-preflop.md) |
| 핸드 기록(RL용) | ⚠️ 기록은 되지만 읽는 코드가 없다 — 계속할지는 결정 대기(D-31) |
| 포스트플랍 GTO | ❌ 수집 폐기 → 레인지 기반 핸드 리딩으로 근사 예정(E-2) |

## 운영 명령

```bash
python3 scripts/bot_arena.py --hands 600 --seats hard,medium,legacy --seed 99   # 봇 비교(bb/100)
python3 scripts/ai_regression.py          # legacy 대비 후퇴 검사(exit 1)
pypy3 scripts/grind.py                    # 아레나 반복(핸드 기록이 쌓인다 — D-31 참고)
python3 scripts/collect_gto_tree.py --limit 90   # GTO 수집(디버그 크롬 + 로그인 필요)
python3 scripts/audit_gto_preflop.py      # GTO 데이터 무결성(부모-자식 레인지·frontier 포함)
python3 scripts/gto_tree_report.py        # 수집 현황 → docs/gto-preflop-progress.md(git 제외)
```

그라인드·튜닝·수집은 서로 동시에 돌리지 않는다(hook이 에이전트 실행분을 막는다). 아레나·튜닝은
세션 기록을 DB에 남기므로 실험은 `EV_PLUS_DB=<임시 파일>`로 격리한다.

## 문서

| 문서 | 내용 |
|---|---|
| [포커 룰](docs/spec/game-rules.md) | 좌석·버튼, 행동 순서, 재오픈, 사이드팟·반환, 칩 보존 (core) |
| [웹 흐름·API](docs/spec/web-flow.md) | 세션·이벤트 재생·화면 규칙, API 목록 — 필드 상세는 `https://localhost:8765/docs` |
| [AI 봇](docs/spec/bot.md) | 난이도·페르소나, 의사결정, 플레이 복기, 아레나·튜닝 |
| [에퀴티](docs/spec/equity.md) | 에퀴티 엔진(프리플랍 테이블·전수·적응형 MC), 패널, 검증 장치 |
| [프리플랍 GTO](docs/spec/gto-preflop.md) | 수집·저장·조회 규칙, 운영 방법 |
| [DB](docs/spec/db.md) | 연결·마이그레이션·기록·보존 — 컬럼은 `db/schema.py` |
| [테스트](docs/spec/testing.md) | 실행 방법, 테스트 규약 |
| [결정 기록](docs/decisions/README.md) | 왜 이렇게 정했나 (ADR) |
| [결정 대기](DECISIONS.md) | 사람이 내려야 할 결정 |
| [TODO](TODO.md) | 실행할 작업 (완료 이력은 git log) |
| [운영 플레이북](docs/ai-dev-workflow-playbook.md) | AI 에이전트 개발 운영 표준 |
