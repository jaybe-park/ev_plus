# TODO

작업 상태: `[ ]` 미완료 · `[x]` 완료 · `[-]` 보류

---

## 🐛 버그

- [x] **사이드팟 미구현**
  - `server/session.py` `_calculate_side_pots()` 추가, `_do_showdown()` 개편
  - 테스트 6-5 ~ 6-8 추가 및 통과

- [x] **헤즈업 프리플랍 베팅 순서**
  - `core/game.py` `_post_blinds()`, `_betting_order()` 헤즈업 분기 추가
  - 테스트 6-1 ~ 6-4 추가 및 통과

---

## 🔧 미연결 기능

- [ ] **DB 기록 연결**
  - 스키마(`db/schema.py`)와 `recorder.py`는 완성됨
  - `server/session.py`의 `_apply()` 메서드에 호출 추가하면 됨
  - 연결 후: 핸드별 액션 기록, GTO 대비 플레이 분석 가능

---

## ✨ 기능 추가

### GTO 개선

- [ ] **GTO 힌트 토글**
  - 현재: 항상 표시됨
  - 변경: 버튼으로 on/off 전환 (기본값: off)
  - 위치: ActionBar 또는 헤더에 토글 버튼 추가

- [x] **GTO 데이터 DB화**
  - `db/schema.py` v2: gto_preflop_situations/hands, gto_postflop_situations/hands 테이블 추가
  - `tools/migrate_gto.py`: JSON → DB 마이그레이션 스크립트 (10 situations, 1690 hands)
  - `gto/loader.py`: DB 기반으로 교체 (앱 시작 시 전체 로드 캐시)
  - `gto_data/` 디렉터리 삭제 (DB가 source of truth)
  - ⚠️ vs_open 일부 데이터 부정확 (AKs/AKo fold 50% 등) → 점진적 교정 필요

- [x] **GTO Wizard → DB 연동 구축** (Claude in Chrome MCP)
  - 서버 HTTPS 전환 (ssl/ 자체 서명 인증서, Mixed Content 해결)
  - 추출 방식: CSS `background-size`의 누적 퍼센트로 각 핸드 action 빈도 파싱
  - URL 패턴: `history_spot=N` (N: UTG=0, HJ=1, CO=2, BTN=3, SB=4, BB=5)
  - GTO Wizard → `fetch('https://localhost:8000/gto/preflop/save')` 직접 호출
  - RFI 5개 스팟 GTO Wizard 데이터로 교체 완료

- [x] **RFI 데이터 GTO Wizard로 교체**
  - UTG(19%), MP/HJ(34%), CO(40%), BTN(52%), SB(59%) — 모두 AKo fold=0 확인
  - 구 JSON 데이터(오류 있음) → GTO Wizard 정확 데이터로 대체

- [ ] **vs_open / vs_3bet 데이터 GTO Wizard로 교체** ← 다음 작업
  - 현재 구 JSON 데이터 (오류 있음): BB vs BTN/CO/MP/UTG, SB vs BTN
  - 동일한 방법으로 GTO Wizard에서 스팟별 추출 후 저장
  - URL: `preflop_actions=F-F-F-R&history_spot=5` (BB vs BTN 등)

- [ ] **GTO 데이터 확장** (미존재 스팟)
  - vs_3bet 레인지 (BTN_vs_BB 등)
  - SB vs CO, SB vs MP, SB vs UTG 등 빠진 vs_open 상황
  - 포스트플랍 레인지 (장기)

- [ ] **GTO 데이터 확장** (수동 입력)
  - vs_3bet 레인지 (BTN_vs_BB 등)
  - SB vs CO, SB vs MP, SB vs UTG 등 빠진 vs_open 상황
  - 포스트플랍 레인지 (장기)

- [ ] **포스트플랍 GTO 어드바이저**
  - 현재 포스트플랍은 봇/힌트 모두 휴리스틱
  - 보드 텍스처, 포지션, 팟 오즈 기반 기본 레인지 추가

- [ ] **통계 화면**
  - DB 연결 후 가능: 핸드 히스토리, VPIP/PFR
  - GTO 권장 빈도 vs 실제 플레이 빈도 비교

- [ ] **UI 개선**
  - 모바일 레이아웃 최적화
  - 핸드 히스토리 패널

---

## ✅ 완료

- [x] 텍사스 홀덤 게임 엔진 (프리플랍~쇼다운)
- [x] AI 봇 3단계 (Easy / Medium / Hard)
- [x] 프리플랍 GTO 어드바이저 + 힌트 표시
- [x] FastAPI 백엔드 + React 웹 UI
- [x] 포커 로직 정밀 테스트 50개 전체 통과
- [x] 개발/프로덕션 실행 스크립트 분리
- [x] README + docs 작성
- [x] Git 초기화 및 GitHub 연결
- [x] 단계별 액션 애니메이션 시스템
  - SB→BB→UTG 순 한 장씩 2라운드 카드 딜링
  - 블라인드 베팅, 봇 액션 (생각 중 → 배지) 단계별 표시
  - 스트리트별 봇 딜레이 (프리플랍 1.2s ~ 리버 2.5s + 랜덤)
  - 커뮤니티 카드 한 장씩 공개
  - 액션 로그 애니메이션과 동기화
  - 내 카드 클릭으로 공개/숨기기
  - 베팅 칩 애니메이션, 폴드 딤 처리 타이밍 수정
  - 스킵 버튼
