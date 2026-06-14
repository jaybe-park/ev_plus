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

- [ ] **GTO 데이터 확장**
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
  - 카드 딜 / 칩 이동 애니메이션
  - 모바일 레이아웃 최적화
  - 핸드 히스토리 패널

---

## ✅ 완료

- [x] 텍사스 홀덤 게임 엔진 (프리플랍~쇼다운)
- [x] AI 봇 3단계 (Easy / Medium / Hard)
- [x] 프리플랍 GTO 어드바이저 + 힌트 표시
- [x] FastAPI 백엔드 + React 웹 UI
- [x] 포커 로직 정밀 테스트 42개 전체 통과
- [x] 개발/프로덕션 실행 스크립트 분리
- [x] README + docs 작성
- [x] Git 초기화 및 GitHub 연결
