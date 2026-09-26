# 0001. AI 에이전트 개발 운영 플레이북 도입

- 상태: 유효
- 날짜: 2026-09-26 · 결정자: jaybe-park

## 맥락
ev_plus는 사람 1명이 AI 에이전트로 만들고 유지한다. 몇 달 운영하면서 다음 문제가 쌓였다.
- 현재 상태·결정·이력이 한 문서에 섞였다(`docs/gto-data.md`의 "(당시 이력)", `docs/gto-preflop-tree.md`에 대체된 결정이 표시 없이 남음).
- 완료 이력 누적 파일 `TODO_ARCHIVE.md`(514줄)를 에이전트가 현재 규칙으로 오해할 위험이 있다.
- 사람이 내릴 결정이 TODO Epic·문서 "미결 질문"에 흩어져 있다(수확 결과 13건, WIP 10 초과).
- 작업 규칙 일부(위임 정책, 명시적 git add, 문서 최신화 스킬)가 저장소 밖(`~/.claude/`)에만 있다.
- 같은 종류 사고(미수집 큐 오탐 3회, GTO 데이터 오염 3회)가 문장 규칙만으로 반복됐다.

## 결정
`docs/ai-dev-workflow-playbook.md`를 도입하고 `docs/ai-dev-workflow-migration.md` 절차로 이관한다.
- 문서 세 층: 현재 상태 `docs/spec/` · 결정 `docs/decisions/` · 이력 git. 결정 대기는 `DECISIONS.md` 한 곳.
- 이관 순서(도메인 단위, 도메인마다 커밋 분리):
  1. **gto-preflop (시범)** — 문서 변경이 가장 잦고 모순이 가장 많다(`gto-data.md` 13회, `gto-preflop-tree.md` 12회 변경).
  2. equity + ai-bot
  3. db (스키마·운영)
  4. game-engine + api + architecture
  5. testing
- `TODO_ARCHIVE.md`는 지금부터 **누적을 멈춘다**. 도메인 이관마다 그 도메인의 유효한 결정을 ADR로 추출하고, 마지막 도메인이 끝난 뒤 삭제한다.
- 저장소 밖 규칙은 저장소로 옮긴다: `.claude/skills/update-docs`(전역 스킬 통합), `.claude/skills/review`, `.claude/agents/{implementer,verifier}`, `.claude/hooks/block_dangerous.py`.

### 조정한 기본값 (플레이북 §9)
| 항목 | 기본값 | 이 프로젝트 | 이유 |
|---|---|---|---|
| 리뷰 주기 | Task 20개 또는 2주 | Task 20개 또는 **2주 이상 공백 뒤 작업 재개 시** | 개인 프로젝트라 작업이 몰아서 일어난다. 달력 2주는 의미가 약하다 |
| 리뷰 관점 수 | 4~6 | 4 (게임 정확성·봇/힌트 신뢰성·원칙↔구현·지속가능성) | 외부 사용자·권한·운영 전환이 없다 |
| hook 런타임 | 프로젝트 런타임 | python3 | 백엔드가 Python |
| CI | push 시 전체 테스트 | **없음** — 커밋 전 `python3 tests/run_all.py --full`로 대체 | 로컬 전용, 테스트가 로컬 DB·PyPy 환경에 의존 |
| 운영 DB 테스트 | 커밋 전 1회 | 해당 없음 | 테스트·운영 모두 SQLite |
| hook 차단 목록 | 비어 있음 | 명시적 add 규칙, 운영 DB 직접 쓰기, 동시 실행 금지 조합 | 아래 "결과" |

## 버린 대안
- 한 번에 전 도메인 이관 — 사람이 검토할 양이 감당되지 않고, 옮기는 동안 모순이 새로 생긴다.
- `TODO_ARCHIVE.md` 즉시 삭제 — 514줄 안에 아직 ADR로 뽑지 않은 유효한 결정(에퀴티·DB·봇)이 있다.
- 기존 TODO 템플릿(Docs Update 서브태스크) 유지 — 완료 여부를 사람 문장으로 판정할 수 없다.

## 결과
- 영향 문서: `CLAUDE.md`(문서 지도·프로젝트 값), `TODO.md`(Task 형식), `DECISIONS.md`(신규), `README.md`
- 강제 장치: `.claude/hooks/block_dangerous.py` — `tests/test_workflow.py`
  - 전체 `git add`/`commit -a` 차단: 사고 이력은 없지만 "명시적 git add"는 기존 작업 규칙(메모리)이었고, 병렬 서브에이전트 운영을 전제로 예방한다
  - `poker.db` 직접 쓰기 차단: 체크포인트·큐·GTO 테이블을 수동으로 고친 일이 여러 번 있었다
  - 에퀴티 워커·그라인드·튜닝 동시 실행 차단: TODO의 "동시 실행 금지 조합" 문장 규칙을 장치로 옮김
