# ev_plus

혼자 AI 봇과 Texas Hold'em 포커를 플레이하기 위한 개인 프로젝트.

Python(FastAPI) 백엔드 + React 프론트엔드로 구성되어 있으며,
GTO 기반 프리플랍 어드바이저와 3단계 AI 봇을 포함한다.

---

## 빠른 시작

```bash
# 의존성 설치 (최초 1회)
pip install -r requirements-server.txt
cd web && npm install && cd ..

# 개발 모드 실행
./start.sh
# → 브라우저: http://localhost:5766
```

> 백엔드 `http://localhost:8765`, 프론트 `http://localhost:5766` 동시 실행  
> 프로덕션(단일 포트)은 `./prod.sh` 사용

---

## 프로젝트 구조

```
ev_plus/
├── core/          # 게임 엔진 (카드, 덱, 핸드 평가, 게임 로직)
├── ai/            # AI 봇 (Easy / Medium / Hard)
├── gto/           # GTO 어드바이저
├── server/        # FastAPI 백엔드
├── web/           # React + Vite + Tailwind 프론트엔드
├── db/            # SQLite (게임 기록 + GTO 데이터 + 에퀴티 캐시)
├── scripts/       # 에퀴티 워커, 봇 아레나, 그라인드 모드, 프리플랍 GTO 트리 수집 워커
├── tests/         # 테스트 (포커 로직, GTO 트리, 에퀴티/봇, 플레이 평가 — tests/run_all.py)
├── start.sh       # 개발 모드 실행 (= dev.sh)
├── dev.sh         # 개발 모드 실행
└── prod.sh        # 프로덕션 모드 실행
```

---

## 현재 상태

| 기능 | 상태 |
|---|---|
| 텍사스 홀덤 게임 엔진 | ✅ 완료 |
| 웹 UI + 단계별 애니메이션 | ✅ 완료 |
| AI 봇 3단계 | ✅ 난이도 = MC 샘플 수(판단 해상도) |
| 프리플랍 GTO 힌트 | ⚠️ 데이터 기반 트리(수집된 노드, 4벳·스퀴즈 포함) — 노드 덮어쓰기·헤즈업 스냅 버그 수정 대기(TODO T-001) |
| GTO 패널 (레인지 그리드) | ⚠️ 오른쪽 탭 — 힌트와 별도 판정기라 다른 노드를 보일 수 있음(DECISIONS D-04) |
| 테스트 스위트 | ✅ `tests/run_all.py --full` |
| 프리플랍 GTO 수집 | ✅ 체계 완료, 수집은 운영 루틴(Playwright 자동 워커) — [사양](docs/spec/gto-preflop.md), [현황](docs/gto-preflop-progress.md) |
| AI 봇 equity 기반 재작성 | ✅ MC/전수조사 + 레인지 반영 + 페르소나 |
| 에퀴티 전수조사 워커 | ✅ `scripts/equity_worker.py` (중단/재개 안전) |
| 봇 아레나 / 그라인드 | ✅ bb/100 검증 + 캐시·학습데이터 동시 축적 |
| RL 학습 데이터 기록 | ✅ 전 액션 DB 기록 (equity/reward 포함) |
| 에퀴티 패널 + 플레이 평가 | ✅ 실시간 상대별 에퀴티, 핸드 복기 등급/EV |
| 포스트플랍 GTO | ❌ 실측 수집 폐기 → 레인지 기반 핸드 리딩으로 근사 예정(TODO E-2) |

---

## 야간 루틴

```bash
# 1순위: 그라인드 — 에퀴티 캐시 + RL 학습데이터 + 미수집 스팟 발견 동시 축적.
# pypy3로 실행하면 워커·아레나 서브프로세스도 PyPy(처리량 약 3.7배). 워커는 기본 cpu_count()-2 병렬.
pypy3 scripts/grind.py

# 또는: 프리플랍 equity 채우기(순수 워커)
pypy3 scripts/equity_worker.py --preflop-first

# 또는: 파라미터 튜닝 캠페인(결과는 tuning_results.json, 반영은 사람이 수동)
python3 scripts/tune_bot.py --profile hard --param aggression_margin --values 0.04,0.08,0.12 --hands 3000 --seeds 3
python3 scripts/tune_bot.py --profile hard --param semibluff_freq --evolve --start 0.55 --step 0.1 --rounds 5 --hands 2000

# 다음날 아침 확인
python3 scripts/equity_worker.py --status
ls -lh poker.db chip_violations.log   # 위반 로그가 있으면 시드로 재현 가능

# 프리플랍 GTO 트리 수집(선택, 디버그 크롬 + GTO Wizard 로그인 필요) — 절차: docs/spec/gto-preflop.md
# ⚠ TODO T-001 수정 전에는 돌리지 않는다(노드 덮어쓰기)
python3 scripts/collect_gto_tree.py --limit 90
python3 scripts/gto_tree_report.py
```

⚠️ 동시 실행 금지: 워커 2개(중복 계산), 그라인드+워커, 그라인드+튜닝(CPU/DB 경합)

---

## 상세 문서

| 문서 | 내용 |
|---|---|
| [아키텍처](docs/architecture.md) | 전체 구조, 모듈 의존성, 데이터 흐름 |
| [게임 엔진](docs/game-engine.md) | core/ 상세, 게임 흐름, 베팅 라운드 규칙 |
| [API](docs/api.md) | FastAPI 엔드포인트 명세 |
| [프리플랍 GTO 사양](docs/spec/gto-preflop.md) | 수집·저장·조회 규칙, 운영 방법, 알려진 한계 |
| [프리플랍 GTO 수집 현황](docs/gto-preflop-progress.md) | 자동 생성 리포트(mermaid 트리, `scripts/gto_tree_report.py`) |
| [AI 봇](docs/ai-bot.md) | 난이도별 전략, GTO 준수율 |
| [DB 스키마](docs/db-schema.md) | 테이블 구조, 기록 설계 |
| [테스트](docs/testing.md) | 테스트 항목, 실행 방법 |
| [결정 기록](docs/decisions/README.md) | 왜 이렇게 정했나 (ADR) |
| [결정 대기](DECISIONS.md) | 사람이 내려야 할 결정 |
| [TODO](TODO.md) | 실행할 작업 (완료 이력은 git log) |
| [운영 플레이북](docs/ai-dev-workflow-playbook.md) | AI 에이전트 개발 운영 표준 |
