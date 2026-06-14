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

- [ ] **GTO 데이터 DB화** ← 다음 작업
  - 현재 JSON 데이터는 vs_open 일부가 부정확 (AKs/AKo 폴드 50% 등 명백한 오류 포함)
  - **1단계: DB 스키마 생성**
    - `gto_preflop_situations` (position, vs_position, range_type, raise_size)
    - `gto_preflop_hands` (situation_id, hand, freq_fold, freq_call, freq_raise, freq_allin)
    - `gto_postflop_situations` / `gto_postflop_hands` — 별도 테이블로 분리
  - **2단계: 마이그레이션 스크립트** (`tools/migrate_gto.py`)
    - 기존 JSON → DB INSERT
    - 완료 후 `gto_data/` 디렉터리 삭제 (DB가 source of truth)
  - **3단계: `gto/loader.py` 교체**
    - 파일 읽기 → DB 쿼리 방식으로 전환
    - 앱 시작 시 전체 프리플랍 데이터 메모리 로드 (캐시)
  - **4단계: 데이터 점진적 교체**
    - 오류 있는 vs_open 레인지 공개 GTO 차트 참고해서 교정
    - Chrome 연동 완성 후 자동 수집으로 확장
  - 선행 조건: 없음 (독립 작업 가능)

- [ ] **Chrome 연동 — 실시간 GTO 스팟 저장**
  - 실제 포커 사이트(GTO Wizard 등)에서 플레이하면서
  - 누락된 스팟(포지션 조합)을 브라우저에서 감지 → 자동 저장
  - 구현 방향: Chrome Extension or Claude in Chrome MCP 활용
  - 저장 대상: 현재 없는 포지션 조합 (vs_3bet, 포스트플랍 등)

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
