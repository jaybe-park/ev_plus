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
python3 tests/test_poker_full.py  # 포커 로직 테스트 (50개)
python3 tests/test_equity.py       # 에퀴티/봇 테스트 (36개)
python3 scripts/grind.py           # 아레나+워커 동시 실행 (캐시/학습데이터 축적)
python3 scripts/equity_worker.py --status  # 에퀴티 캐시 현황
cd web && npm run build            # 프론트 빌드 확인
```

---

## 커밋 규칙

### 1. 커밋 전 MD 파일 업데이트

변경 시 관련 MD 파일을 **항상 함께 커밋**한다.

| 파일 | 역할 | 업데이트 시점 |
|---|---|---|
| `README.md` | 프로젝트 소개, 현재 상태 표 | 기능 추가/완료 시 |
| `TODO.md` | 작업 목록, 버그/완료 체크 | 작업 시작/완료/발견 시 |
| `docs/architecture.md` | 전체 구조, 모듈 의존성, 데이터 흐름 | 아키텍처 변경 시 |
| `docs/api.md` | FastAPI 엔드포인트 명세 | API 추가/변경 시 |
| `docs/game-engine.md` | core/ 게임 로직 상세 | 게임 엔진 변경 시 |
| `docs/gto-data.md` | GTO DB 현황, 수집 방법 | GTO 데이터 추가/변경 시 |
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
