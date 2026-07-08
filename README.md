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
├── server/        # FastAPI 백엔드
├── web/           # React + Vite + Tailwind 프론트엔드
├── db/            # SQLite (게임 기록 + GTO 데이터 + 에퀴티 캐시)
├── scripts/       # 에퀴티 워커, 봇 아레나, 그라인드 모드
├── tests/         # 테스트 (포커 로직 50 + 에퀴티/봇 36)
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
| 프리플랍 GTO 힌트 | ✅ GTO Wizard 데이터 (RFI+vs_open+vs_3bet) |
| GTO 패널 (레인지 그리드) | ✅ 오른쪽 탭 — 핸드별 색상 + 비교 |
| 포커 로직 테스트 50개 | ✅ 전체 통과 |
| GTO 데이터 DB화 | ✅ 완료 (SQLite, 55개 스팟) |
| GTO Wizard Chrome 연동 | ✅ HTTPS API 직접 저장 |
| AI 봇 equity 기반 재작성 | ✅ MC/전수조사 + 레인지 반영 + 페르소나 |
| 에퀴티 전수조사 워커 | ✅ `scripts/equity_worker.py` (중단/재개 안전) |
| 봇 아레나 / 그라인드 | ✅ bb/100 검증 + 캐시·학습데이터 동시 축적 |
| RL 학습 데이터 기록 | ✅ 전 액션 DB 기록 (equity/reward 포함) |
| 에퀴티 패널 + 플레이 평가 | ✅ 실시간 상대별 에퀴티, 핸드 복기 등급/EV |
| 포스트플랍 GTO | ❌ 미구현 (봇은 equity 휴리스틱) |

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
