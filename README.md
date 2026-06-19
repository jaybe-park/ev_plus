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
# → 브라우저: http://localhost:5765
```

> 백엔드 `http://localhost:8765`, 프론트 `http://localhost:5765` 동시 실행  
> 프로덕션(단일 포트)은 `./prod.sh` 사용

---

## 프로젝트 구조

```
ev_plus/
├── core/          # 게임 엔진 (카드, 덱, 핸드 평가, 게임 로직)
├── ai/            # AI 봇 (Easy / Medium / Hard)
├── gto/           # GTO 어드바이저
├── gto_data/      # 프리플랍 레인지 JSON 데이터
├── server/        # FastAPI 백엔드
├── web/           # React + Vite + Tailwind 프론트엔드
├── db/            # SQLite 기록 모듈 (미연결)
├── tests/         # 포커 로직 정밀 테스트 (42개)
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
| AI 봇 3단계 | ✅ 완료 |
| 프리플랍 GTO 힌트 | ✅ GTO Wizard 데이터 (RFI+vs_open+vs_3bet) |
| GTO 패널 (레인지 그리드) | ✅ 오른쪽 탭 — 핸드별 색상 + 비교 |
| 포커 로직 테스트 50개 | ✅ 전체 통과 |
| GTO 데이터 DB화 | ✅ 완료 (SQLite, 55개 스팟) |
| GTO Wizard Chrome 연동 | ✅ HTTPS API 직접 저장 |
| 포스트플랍 GTO | ❌ 미구현 |
| DB 기록 연결 | ❌ 미연결 |

---

## 상세 문서

| 문서 | 내용 |
|---|---|
| [아키텍처](docs/architecture.md) | 전체 구조, 모듈 의존성, 데이터 흐름 |
| [게임 엔진](docs/game-engine.md) | core/ 상세, 게임 흐름, 베팅 라운드 규칙 |
| [API](docs/api.md) | FastAPI 엔드포인트 명세 |
| [GTO 데이터](docs/gto-data.md) | 레인지 데이터 형식, 입력 방법 |
| [AI 봇](docs/ai-bot.md) | 난이도별 전략, GTO 준수율 |
| [DB 스키마](docs/db-schema.md) | 테이블 구조, 기록 설계 |
| [테스트](docs/testing.md) | 테스트 항목, 실행 방법 |
| [TODO](TODO.md) | 버그, 미연결 기능, 작업 목록 |
