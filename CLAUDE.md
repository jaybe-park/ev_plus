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
python3 scripts/equity_worker.py --status   # 에퀴티 캐시 현황
```

## 절대 규칙 (위반 시 사고)

- 커밋은 바꾼 파일만 경로 지정(`git add -- <경로>`). 전체 add·`commit -a` 금지 — 강제 장치: hook `.claude/hooks/block_dangerous.py`
- `poker.db`에 직접 쓰기(sqlite3/`python -c`) 금지 — `--dry-run`을 지원하는 스크립트로만 — 강제 장치: hook
- 에퀴티 워커 2개, 그라인드+워커, 그라인드/튜닝 동시 실행 금지 — 강제 장치: hook(에이전트 실행분만)
- 테스트는 `EV_PLUS_DB` 임시 DB로 격리한다. 공유 `poker.db`를 테스트에서 쓰지 않는다 — 강제 장치: `tests/test_poker_full.py` 픽스처(부분)
- GTO 값은 화면에서 읽은 그대로만. 추측·보간·잔여를 fold로 채우기 금지 — 강제 장치: `tests/test_poker_full.py` 영역 6·7, `tests/test_gto_tree.py` · 근거 ADR 0002
- `docs/gto-preflop-progress.md`는 수동 편집 금지 — `python3 scripts/gto_tree_report.py`로만 — 장치 없음
- UI 변경·새 기능·아키텍처 변경은 **사용자 확인 후** 커밋. 버그 수정·문서·설정은 바로 커밋 가능 — 장치 없음

## 문서 지도

**플레이북 이관 중**(ADR 0001) — 이관된 도메인은 `docs/spec/`, 아직인 도메인은 아래 기존 문서가 현재 상태다.

| 층 | 문서 |
|---|---|
| 현재 상태 (이관 완료) | `docs/spec/gto-preflop.md` — 프리플랍 GTO 수집·저장·조회 |
| 현재 상태 (이관 전) | `docs/ai-bot.md`(봇·에퀴티) · `docs/db-schema.md` · `docs/game-engine.md` · `docs/api.md` · `docs/architecture.md` · `docs/testing.md` |
| 자동 생성 | `docs/gto-preflop-progress.md` (프리플랍 수집 현황) |
| 결정 | `docs/decisions/` (목록: `README.md`) |
| 결정 대기 | `DECISIONS.md` |
| 할 일 | `TODO.md` |
| 리뷰 기록 | `self-reviews/` |
| 입력함 | `memo.md` (사람이 씀) |
| 운영 표준 | `docs/ai-dev-workflow-playbook.md`, 이관 절차 `docs/ai-dev-workflow-migration.md`(이관 끝나면 삭제) |
| 소개 | `README.md` |

- 이 지도에 없는 문서를 현재 규칙으로 읽지 않는다. `TODO_ARCHIVE.md`는 이관 중 결정 추출용으로만 남아 있다(더 쌓지 않는다, 이관 완료 시 삭제).
- 에이전트가 매 세션 읽는 문서는 이 파일 + 작업 도메인의 현재 상태 문서뿐이다.

## 작업 규칙

- **흐름** (플레이북 §4): `memo.md` → 결정 필요는 `DECISIONS.md`, 실행 가능은 `TODO.md`(Task 템플릿) → 구현 → 검증 → 커밋 + spec 덮어쓰기 + (필요하면) ADR 1개 → TODO에서 **삭제**.
- **결정 대기가 WIP 한도를 넘으면** 새 기능 Task에 착수하지 않고 결정을 먼저 요청한다. 결정이 필요한 곳을 "가정"으로 구현하지 않는다.
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
- 매 세션 필수 문서량: 1만 토큰 이내 · CLAUDE.md 200줄 이내 · spec 300줄에서 분할 신호
