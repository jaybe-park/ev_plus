# CLAUDE.md

## 프로젝트 컨텍스트

- 혼자 AI 봇과 Texas Hold'em(6-max 캐시게임)을 플레이하는 개인 프로젝트. FastAPI 백엔드 + React(Vite) 프론트 + SQLite(`poker.db`).
- GTO Wizard 프리플랍 데이터로 힌트·봇 판단, 에퀴티 엔진(MC/전수조사), 3단계 봇, 플레이 평가.
- **유지 모델: AI 에이전트가 코드를 쓰고, 감독자(jaybe-park) 1명은 코드를 거의 읽지 않는다.** 결정하고 결과를 확인한다.
- 로컬 전용: 백엔드 `https://localhost:8765`(HTTPS 필수 — GTO Wizard Mixed Content 방지), 프론트 `http://localhost:5766`. GitHub `jaybe-park/ev_plus`.

```bash
./start.sh                         # 개발 모드 (./prod.sh = 프로덕션 단일 포트)
python3 tests/run_all.py           # 빠른 테스트 (--full: 전체, 커밋 전 1회)
cd web && npm run build            # 프론트 빌드 확인
```

## 절대 규칙 (위반 시 사고)

- 커밋은 바꾼 파일만 경로 지정(`git add -- <경로>`). 전체 add·`commit -a` 금지 — 강제 장치: hook `.claude/hooks/block_dangerous.py`
- `poker.db`에 직접 쓰기(sqlite3/`python -c`) 금지 — `--dry-run`을 지원하는 스크립트로만 — 강제 장치: hook
- 그라인드·튜닝 동시 실행 금지(CPU/DB 경합) — 강제 장치: hook(에이전트 실행분만)
- 테스트는 `EV_PLUS_DB` 임시 DB로 격리한다. 공유 `poker.db`를 테스트에서 쓰지 않는다 — 강제 장치: `tests/run_all.py`의 운영 DB (mtime, size) 스냅샷 가드(바뀌면 실패) + `tests/test_guards.py`
- GTO 값은 화면에서 읽은 그대로만. 추측·보간·잔여를 fold로 채우기 금지 — 강제 장치: `tests/test_poker_full.py` 영역 6·7, `tests/test_gto_tree.py` · 근거 ADR 0002
- 사용자 확인은 **결정할 거리가 있을 때만**: 되돌리기 어려운 변경(스키마·데이터 삭제·구조 폐기)이나 방향이 갈리는 화면·기능 변경. 버그 수정 성격의 UI 변경·문서·설정·테스트는 바로 커밋·병합하고 보고한다 — 장치 없음

## 문서 지도

| 층 | 문서 |
|---|---|
| 현재 상태 | `docs/spec/` — `game-rules.md`(포커 룰, core) · `web-flow.md`(세션·이벤트·화면·API) · `bot.md`(봇·플레이 평가) · `equity.md`(에퀴티 엔진·워커·패널) · `gto-preflop.md`(GTO 수집·저장·조회) · `db.md`(연결·마이그레이션·기록·보존) · `testing.md`(테스트 체계) |
| 로컬 생성 (git 제외, 문서가 아니라 리포트) | `docs/gto-preflop-progress.md` — `python3 scripts/gto_tree_report.py`가 만든다. 규칙을 적지 않는다 |
| 결정 | `docs/decisions/` (목록: `README.md`) |
| 결정 대기 | `DECISIONS.md` |
| 할 일 | `TODO.md` |
| 리뷰 기록 | `self-reviews/` |
| 입력함 | `memo.md` (사람이 씀) |
| 운영 표준 | `docs/ai-dev-workflow-playbook.md` |
| 소개 | `README.md` |

- 이 지도에 없는 문서를 현재 규칙으로 읽지 않는다. 완료 이력은 git log(누적 파일을 만들지 않는다).
- 에이전트가 매 세션 읽는 문서는 이 파일 + 작업 도메인의 현재 상태 문서뿐이다.

## 작업 규칙

- **흐름** (플레이북 §4): `memo.md` → 결정 필요는 `DECISIONS.md`, 실행 가능은 `TODO.md`(Task 템플릿) → 구현 → 검증 → 커밋 + spec 덮어쓰기 + (필요하면) ADR 1개 → TODO에서 **삭제**.
- **DECISIONS에는 되돌리기 어렵거나 방향을 바꾸는 결정만**(데이터 삭제, 구조 폐기·도입, 방향이 갈리는 ADR 뒤집기, 큰 기능 범위). 되돌리기 쉬운 화면 취향·보류·기존 방향 안의 기본값·판정 기준은 에이전트가 추천대로 정하고 ADR·커밋 메시지로 남긴 뒤 보고한다. 기존 ADR에서 답이 나오면(코드가 ADR과 다르면 버그) ADR대로 고치는 TODO로.
- **사람에게 결정을 물을 때**: 선택 카드로 요약하지 말고, 배경·현재 상태·선택지별 결과·추천 이유를 글로 풀어 한 건씩 묻는다(이전 맥락을 기억한다고 가정하지 않는다).
- **결정 대기가 WIP 한도를 넘으면** 새 기능 Task에 착수하지 않고 결정을 먼저 요청한다. 사람이 정할 곳을 "가정"으로 구현하지 않는다.
- **위임**: 코딩은 서브에이전트. `implementer`(`.claude/agents/`, 스펙이 확정된 구현) → `verifier`(완료 보고를 믿지 않는 검증). 까다로운 설계·디버깅은 상위 모델로 스펙부터 확정하고, 확정된 스펙의 구현은 하위 모델에 맡긴다. 병렬 구현은 `isolation: "worktree"`. 검증의 치명·높음 주장은 메인이 직접 재확인.
- **문서**: `update-docs` 스킬(`.claude/skills/`). 현재 상태 문서는 덮어쓴다 — "(정정)"·과거 서술 금지.
- **리뷰**: `review` 스킬("리뷰해줘"). 결과는 `self-reviews/<날짜>.md` 관찰 기록이며 착수하지 않는다.
- **검증**: 관련 테스트 → 커밋 전 `python3 tests/run_all.py --full` 1회 → 프론트면 `npm run build` → verifier.
- **커밋**: 한국어, 무엇을·왜. 여러 줄은 `git commit -m "제목" -m "본문" -m "Co-Authored-By: ..."`(heredoc·파이프·리다이렉션은 권한 프롬프트를 부르므로 쓰지 않는다). 파일 수정은 Edit/Write 도구, 긴 스크립트는 스크래치패드에 저장 후 실행.
- **서버**: 띄운 서버는 프리뷰 도구의 stop으로 끈다.

## 프로젝트 값 (플레이북 기본값에서 조정한 것 — 근거 ADR 0001)

- 결정 대기 WIP 한도: 10
- 리뷰 주기: Task 20개 또는 2주 이상 공백 뒤 작업 재개 시 · 관점 4개(게임 정확성·봇/힌트 신뢰성·원칙↔구현·지속가능성)
- hook 런타임: python3
- CI: 없음 — 커밋 전 `run_all --full`로 대체 · 운영 DB 테스트: 해당 없음(둘 다 SQLite)
- 매 세션 필수 문서량: 1만 토큰 이내 · CLAUDE.md 200줄 이내 · spec 1개 6천 토큰(한글 약 7천 자, 또는 300줄)에서 분할 신호
