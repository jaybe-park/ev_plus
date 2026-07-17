# CLAUDE.md

## 프로젝트

혼자 AI 봇과 Texas Hold'em 포커를 플레이하는 개인 프로젝트.
FastAPI 백엔드 + React 프론트엔드.

- 백엔드: `https://localhost:8765`
- 프론트: `http://localhost:5765`
- GitHub: `https://github.com/jaybe-park/ev_plus`

```bash
./start.sh          # 개발 모드
./prod.sh           # 프로덕션 모드
python3 tests/run_all.py           # 테스트 대표 명령 (--fast 기본/--full)
python3 tests/test_poker_full.py   # 포커 로직 테스트만 (50개)
python3 tests/test_equity.py       # 에퀴티/봇 테스트만 (39개)
python3 scripts/grind.py           # 아레나+워커 동시 실행 (캐시/학습데이터 축적)
python3 scripts/equity_worker.py --status  # 에퀴티 캐시 현황
cd web && npm run build            # 프론트 빌드 확인
```

---

## 기획/개발 워크플로우 (Planner ↔ Agent)

너는 이 프로젝트의 '기획자(Planner)'이자 '개발자(Agent)'다. 지시에 따라 두 모드 중 하나로 동작한다.

### Phase 1: Planning Mode (기획)
사용자가 `memo.md`를 처리하라고 지시하면:
1. `memo.md`의 `[Feedbacks]` 내용을 읽고 분석한다.
2. `TODO.md`에 아래 **Task 템플릿**으로 구체 작업을 기획해 추가한다 (진행 중/예정 작업 섹션에).
3. 각 Task의 마지막 서브태스크로 반드시 **"Docs Update"** 항목을 명시한다 (해당 없으면 명시적으로 "해당 없음" 기록).
4. 기획을 TODO.md에 옮긴 항목은 `memo.md`의 `[Feedbacks]`에서 즉시 삭제한다 (헤더는 유지).

### Phase 2: Execution Mode (실행)
사용자가 작업을 진행하라고 지시하면:
1. `TODO.md`에서 `[ ] Pending` 또는 `[~] In Progress` Task를 파악한다.
2. 코드를 수정하고 기능을 구현한다.
3. **[필수]** 구현이 끝나면 Task의 "Docs Update" 서브태스크를 먼저 완료한다 — 문서 최신화 없이 커밋 불가.
4. `TODO.md`의 해당 Task를 `[x] Done`으로 바꾸고, **완료된 Task는 상세 이력과 함께 `TODO_ARCHIVE.md`로 옮긴다** (TODO.md는 진행 중/예정 작업만 유지 — 토큰 절약).
5. 이후 커밋한다 (형식은 아래 "커밋/푸시 타이밍" 규칙 따름).

### Task 템플릿 (TODO.md 신규 작업 작성 시 형식)
```markdown
### Task: [기능/작업 이름]
- **Status:** `[ ] Pending` / `[~] In Progress` / `[x] Done` / `[-] 보류`
- **Context:** 이 작업을 왜 하는지, 배경/근거를 서술.
- **Sub-tasks:**
  - [ ] 구현 항목 1
  - [ ] 검증 항목 (테스트/실플레이 등)
  - [ ] **Docs Update:** 관련 `docs/*.md` 파일에 반영 (필수, 해당 없으면 명시)
```

---

## 커밋 규칙

### 1. 커밋 전 MD 파일 업데이트

변경 시 관련 MD 파일을 **항상 함께 커밋**한다.

| 파일 | 역할 | 업데이트 시점 |
|---|---|---|
| `README.md` | 프로젝트 소개, 현재 상태 표 | 기능 추가/완료 시 |
| `TODO.md` | 진행 중/예정 작업만 (Task 템플릿) | 작업 시작/완료/발견 시 |
| `TODO_ARCHIVE.md` | 완료된 Task 상세 이력 (TODO.md는 가볍게 유지) | Task 완료 시 TODO.md에서 이관 |
| `docs/architecture.md` | 전체 구조, 모듈 의존성, 데이터 흐름 | 아키텍처 변경 시 |
| `docs/api.md` | FastAPI 엔드포인트 명세 | API 추가/변경 시 |
| `docs/game-engine.md` | core/ 게임 로직 상세 | 게임 엔진 변경 시 |
| `docs/gto-data.md` | GTO DB 현황, 수집 방법 | GTO 데이터 추가/변경 시 |
| `docs/gto-postflop.md` | 포스트플랍 GTO 추상화 설계 (텍스처 클래스) | 포스트플랍 GTO 방식 변경 시 |
| `docs/gto-preflop-tree.md` | 프리플랍 전체 트리 커버리지 설계 (액션 시퀀스 키) | 프리플랍 트리 확장 작업 시 |
| `docs/gto-preflop-progress.md` | 프리플랍 트리 수집 현황 (자동 생성, `scripts/gto_tree_report.py`) | 수동 편집 금지 — 스크립트로만 갱신 |
| `docs/ai-bot.md` | AI 봇 전략 | AI 로직 변경 시 |
| `docs/db-schema.md` | DB 테이블 구조 | 스키마 변경 시 |
| `docs/testing.md` | 테스트 항목 목록 | 테스트 추가/변경 시 |
| `CLAUDE.md` | 이 파일 | 개발 규칙/구조 변경 시 |

> **MD 파일이 추가되면** 이 표에 즉시 반영한다.
> 커밋 전 `find . -name "*.md" | grep -v node_modules` 로 누락 파일 확인.

### 2. 커밋/푸시 타이밍

- **바로 커밋 가능**: 버그 수정, 문서 업데이트, 설정 변경
- **사용자 확인 후 커밋**: UI 변경, 새 기능, 아키텍처 변경 등 메이저 변경

---

## 핵심 패턴

### 게임 흐름
```
POST /game/{id}/action → 봇 자동 처리 → events[] 반환
→ useEventQueue 단계별 애니메이션 → 사용자 액션 활성화
```

### GTO 데이터 저장 (Chrome MCP)
1. GTO Wizard UI에서 스팟 이동
2. `extractAndSave()` 실행 → `https://localhost:8765/gto/preflop/save`
3. CSS `background-size` 누적 퍼센트로 핸드별 빈도 추출
4. 무료 계정 100스팟/일 제한 주의

### 포트
- 백엔드 8765, 프론트 5765 (다른 프로젝트와 충돌 방지)
- HTTPS 필수 (GTO Wizard Mixed Content 방지)
