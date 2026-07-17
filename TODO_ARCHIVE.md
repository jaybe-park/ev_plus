# TODO Archive

완료된 Task의 상세 이력(배경/조사/구현/검증 결과). `TODO.md`는 진행 중/예정 작업만 가볍게
유지하고, 완료된 Task는 여기로 이관한다 (`CLAUDE.md` "기획/개발 워크플로우" 참고).

---

## 🐛 버그 (완료)

- [x] **test_poker_full.py 실행 시간 조사**
  - 원인 ①: `db/recorder.py` `GameRecorder`가 세션마다 자체 sqlite3 커넥션을
    열고 절대 닫지 않음 → 모든 테스트가 같은 임시 DB 파일을 공유하면
    테스트가 누적될수록 살아있는 커넥션 수가 늘어나 SQLite 쓰기 락 경합이
    심해져 busy_timeout(30초)까지 블로킹 (예: 34개 테스트 후 세션 생성 1건이 31초)
  - 원인 ②: 로직 테스트가 실제 AI 봇(`ai.bot.PokerBot`)을 사용해
    매 액션마다 equity/GTO 계산을 수행함
  - 해결 ①: `run()` 헬퍼가 테스트 함수 실행 직전마다 `EV_PLUS_DB`를
    새 임시 파일로 갱신해 커넥션 충돌 자체를 제거 (recorder 버퍼화 커밋 358343a와 별개 이슈)
  - 해결 ②: `tests/test_poker_full.py`에 StubBot 도입 —
    `ai.bot.PokerBot.decide_action`을 모듈 임포트 시점에 콜/체크만 하는
    스텁으로 전역 패치 (equity/GTO 호출 0회 확인). 특정 액션 시퀀스가
    필요한 테스트는 `StubBot(player, scripted_actions=[...])`로 주입
  - 결과: 50개 전체 통과, 실행 시간 30초+ → 1초 미만
  - 대표 실행: `tests/run_all.py` 신규 (`--fast`/`--full`)

- [x] **사이드팟 미구현**
  - `server/session.py` `_calculate_side_pots()` 추가, `_do_showdown()` 개편
  - 테스트 6-5 ~ 6-8 추가 및 통과

- [x] **헤즈업 프리플랍 베팅 순서**
  - `core/game.py` `_post_blinds()`, `_betting_order()` 헤즈업 분기 추가
  - 테스트 6-1 ~ 6-4 추가 및 통과

---

## 🔧 미연결 기능 (완료)

- [x] **DB 기록 연결 (RL 학습 데이터 수집 시작)** — 스키마 v6
  - CHECK 제약 수정: HJ/BTN-SB 포지션 허용 (기존엔 INSERT 실패했음)
  - RL 컨텍스트 컬럼 추가: `equity`(봇 결정 시점), `bot_profile`, `players_state`(전원 스냅샷 JSON)
  - `session.py` ↔ `recorder.py` 연결: 핸드 시작/모든 액션/종료+reward 역산(bb 단위)
  - 아레나/그라인드도 자동 기록 → 시간당 수만 액션 학습 데이터 생산
  - 남은 것: 사람 액션의 GTO 빈도 기록(플레이 평가와 연계), state_vector 피처 설계

---

## ✨ GTO 개선 (완료)

- [x] **GTO 힌트 토글** — 에퀴티 패널 작업에 흡수되어 완료 (095315d)
  - 헤더 👁 마스터 토글 (기본 off, localStorage) — 힌트 탭(에퀴티+GTO) 전체를 게이트

- [x] **GTO 데이터 DB화**
  - `db/schema.py` v2: gto_preflop_situations/hands, gto_postflop_situations/hands 테이블 추가
  - `tools/migrate_gto.py`: JSON → DB 마이그레이션 스크립트 (10 situations, 1690 hands)
  - `gto/loader.py`: DB 기반으로 교체 (앱 시작 시 전체 로드 캐시)
  - `gto_data/` 디렉터리 삭제 (DB가 source of truth)
  - vs_open 일부 데이터 부정확 (AKs/AKo fold 50% 등) → 점진적 교정 필요 (후속 항목에서 해소됨)

- [x] **GTO Wizard → DB 연동 구축** (Claude in Chrome MCP)
  - 서버 HTTPS 전환 (ssl/ 자체 서명 인증서, Mixed Content 해결)
  - 추출 방식: CSS `background-size`의 누적 퍼센트로 각 핸드 action 빈도 파싱
  - URL 패턴: `history_spot=N` (N: UTG=0, HJ=1, CO=2, BTN=3, SB=4, BB=5)
  - GTO Wizard → `fetch('https://localhost:8000/gto/preflop/save')` 직접 호출
  - RFI 5개 스팟 GTO Wizard 데이터로 교체 완료

- [x] **RFI 데이터 GTO Wizard로 교체**
  - UTG(19%), MP/HJ(34%), CO(40%), BTN(52%), SB(59%) — 모두 AKo fold=0 확인
  - 구 JSON 데이터(오류 있음) → GTO Wizard 정확 데이터로 대체

- [x] **vs_open 15개 GTO Wizard로 수집 완료**
  - UI 클릭 방식으로 모든 포지션 조합 수집

- [x] **vs_3bet 31/35개 수집** (GTO Wizard 무료 한도 100스팟/일 초과로 중단, 이후 데이터 기반
  트리 워커로 완전히 대체됨)
  - 완료: UTG/HJ/CO 오픈 시리즈 전체, HJ 오픈 전체, CO 오픈 전체
  - 미완성 4개: BTN 오픈 시리즈 3개 + SB 오픈 1개

- [x] **미수집 스팟 자동 추적 시스템 구현** (`db/schema.py` v3)
  - `gto_missing_spots` 테이블: 게임 중 GTO 없는 스팟 자동 저장
  - `gto/url_generator.py`: 스팟별 GTO Wizard 직접 이동 URL 사전 계산
  - `gto/advisor.py`: RFI/vs_open/vs_3bet 데이터 없을 때 자동 기록
  - `scripts/show_missing_spots.py`: 미수집 현황 CLI 조회
  - 수집모드: "수집모드 실행해줘" → Claude가 Chrome MCP로 자동 수집

- [x] **gto_missing_spots 오탐 버그 수정 및 큐 정리** (2026-07-10)
  - 원인 1: `gto/advisor.py` RFI 판정(`current_bet <= big_blind`)이 포지션을 안 가려
    림프 팟에서 BB가 레이즈하면 "BB RFI"로 오판 → BB는 이미 강제 베팅한 상태라
    RFI 자체가 불가능한데 기록됨. 수정: RFI 블록에 `my_position != "BB"` 조건 추가.
  - 원인 2: vs_3bet 판정이 `my_position == 오프너(raisers[0])`인지 검증 안 해
    "CO vs CO 3bet", "BB vs BTN 3bet" 등 논리적으로 불가능한 조합이 대량 기록됨
    (우리 데이터 모델은 오프너가 3벳에 대응하는 레인지만 수집하므로 그 밖은 지원 안 함).
    수정: `my_position == opener_pos`일 때만 조회/기록, 아니면 `None` 반환.
  - 큐 정리: open/BB 1건, vs_3bet 오프너 불일치 53건 삭제 →
    open 2→1(BTN/SB 헤즈업 갭은 유지), vs_3bet 65→12, vs_open 18(변화 없음)
  - 큐는 아레나 볼륨과 무관하게 조합 공간(UNIQUE 제약)으로 빨리 saturate된다 —
    같은 미수집 스팟은 한 번만 기록되므로 볼륨을 늘려도 큐가 계속 늘진 않음.

- [x] **gto_missing_spots_preflop vs_open 오탐 버그 수정 및 큐 정리** (2026-07-12, 3번째 유사 버그)
  - 원인: `find_opener_position()`이 "BTN 림프 후 BB가 아이솔레이트 레이즈, 액션이
    BTN에게 돌아옴" 상황에서 opener_pos='BB'를 반환 — 우리 데이터 모델(open/vs_open/
    vs_3bet)이 "림프 후 아이솔레이트" 카테고리를 지원 안 하는데 조회/기록됨(BB RFI,
    vs_3bet 오프너 불일치와 같은 계열의 "모델 밖 상황" 버그).
  - 수정: `gto/advisor.py` vs_open 블록에서 오프너가 포지션 순서상 my_position보다
    뒤인 경우 조회/기록 없이 `None` 반환(`gto/url_generator.py`의 `POS_INDEX` 재사용,
    vs_3bet의 "my_position != opener_pos면 스킵" 패턴과 동일 원칙).
  - 큐 정리: 7개 → 6개 (BTN vs BB open 오탐 1건 삭제).

- [x] 🔴 **프리플랍 GTO 전면 재작업 — 근본 원인 확정 + 사이징 실측화 + 전량 재수집**
  (긴급, 2026-07-10 확정. 사용자 지시: "완벽하게 하고 가자")

  ### 근본 원인 (추측 아님 — 코드에서 확정)

  `docs/gto-data.md`에 저장된 실제 추출 스크립트(`extractAndSave`, Chrome DevTools용
  JS)의 `colorToAction()` RGB 임계값이 잘못됨:
  ```js
  if (r < 80 && g > 150 && b < 80) return 'call';   // 실제 콜 #22c55e = rgb(34,197,94)
  ```
  콜의 실제 파란값(b)은 **94**인데 조건은 `b < 80` → **항상 거짓, 콜 세그먼트 100% 유실**.
  ```js
  if (r > 80 && r < 150 && g < 50 && b < 50) return 'allin';  // 실제 올인 #991b1b = rgb(153,27,27)
  ```
  올인의 실제 r값은 **153**인데 조건은 `r < 150` → 경계값 근접, 안티앨리어싱으로
  픽셀값이 흔들리면 걸리기도 안 걸리기도 하는 **불안정한 버그**
  (vs_3bet에서만 간간이 올인이 잡힌 이유). raise/fold 임계값은 정상.

  DB 실측 (2026-07-10 전수 검증): call>0인 행 8,619개 중 **0개**.
  allin>0: open 0/845, vs_open 0/2535, vs_3bet 61/5239. 빈도합 비정상: open 9%,
  vs_open 15%, vs_3bet 2%. → `sample_action()` 폴스루로 손상 핸드가 실제와
  다른 액션으로 치환(방향은 핸드마다 다름) → 봇 프리플랍 판단 왜곡(올인 과다 체감),
  hard 봇 `get_call_range` 무력화, 플레이 평가 프리플랍 등급도 오염 데이터 기준.

  ### 추가 문제: 사이징도 실측이 아니라 가짜값

  `gto_preflop_situations.raise_size`가 vs_open/vs_3bet 전부 `"3x"` 플레이스홀더로
  저장돼 있음(RFI만 `"2.5bb"`로 맞음). 실측 확인(GTO Wizard 직접 조회, 2026-07-10):
  UTG(2.5bb 오픈) 기준 3벳 사이징이 HJ=8bb(3.2x)/SB=11bb(4.4x)/BB=13.5bb(5.4x)로
  배수가 일정하지 않음 — 공식으로 추론 불가, 반드시 실측해서 저장해야 함.
  `ai/bot.py` `_preflop_raise()`는 이 실측값 없이 자체 하드코딩 공식
  (오픈×3, 3벳×2.5)으로 추측 중이었음.

  ### 대원칙 (재발 방지)
  - GTO Wizard 값은 있는 그대로만 저장 — 계산/추측/보간 금지
  - 저장 전 반드시 검증 (빈도 합 ≈ 1.0, 사이징은 화면에서 읽은 실측값만)
  - 검증 실패 스팟은 "손상/미수집"으로 명시 처리

  ### 1~4번 완료 결과 (2026-07-12)
  - `SCHEMA_VERSION` 8→11. `raise_size` TEXT→REAL, `gto_missing_spots`→
    `gto_missing_spots_preflop` 개명(인덱스도 `idx_gto_missing_preflop_collected`로).
    v11 마이그레이션은 손상 데이터를 어차피 지울 예정이라 `gto_preflop_situations`/
    `gto_preflop_hands`를 DROP 후 새 정의로 재생성하는 방식 채택.
  - `poker.db.pre-gto-wipe-backup`(로컬 전용, 커밋 대상 아님)으로 백업 후
    `gto_preflop_situations`/`gto_preflop_hands`/`gto_missing_spots_preflop` 전량 0행 확인.
  - `ai/bot.py` `_preflop_raise()`: GTO 실측 `raise_size`(bb)가 있으면 그 값 우선
    사용, 없을 때만 기존 하드코딩 공식을 "폴백"으로 명시 구분해 사용.
  - `gto/advisor.py`: raise_size 문자열 플레이스홀더("2.5bb"/"3x"/"2.5x") 제거,
    실측값 또는 None만 반환. `gto/loader.py`: 핸드별 빈도합이 [0.9, 1.1] 밖이면
    해당 핸드를 스킵(경고 로그 남김) → `get_action_frequencies`가 None 반환해
    상위가 휴리스틱 폴백을 타도록 함(잔여를 fold 등에 몰아주지 않음).
  - `gto/url_generator.py`의 `THREE_BET_SIZE`는 대부분 미검증 추측치임을
    모듈 상단 주석으로 경고 추가(제거는 URL 생성 로직이 깨져 보류).
  - `python3 tests/run_all.py --full` 전체 통과 (test_poker_full/test_equity/test_grader 3개
    스위트 모두 ✅, 0 실패). `bot_arena.py --hands 5 --seats medium,easy --seed 3`
    GTO 데이터 없는 상태에서 에러 없이 정상 완주(전량 폴백/휴리스틱).

  ### 5~7번(실제 재수집/검증) 처리 경위
  - 5~6번(레이어 기반 파서 교체, RFI 5개 전량 재수집, vs_open/vs_3bet 큐 기반 수집)은
    아래 "헤즈업 GTO 매핑", "HJ RFI 데이터 오염 확인" 항목에서 실제로 진행/완료됨.
  - 남은 롱테일 재수집·검증(7번)은 이후 "프리플랍 전체 트리 커버리지" 이니셔티브의
    ④ 데이터 기반 트리 워커로 흡수·대체됨 — 별도 완료 처리 불필요.

  ### 5~6번 진행 중 추가 발견 (2026-07-12, 실제 재수집 착수 후)

  - **GTO Wizard CSS 인코딩 방식이 문서화된 것과 다름을 확인**: `docs/gto-data.md`의
    기존 파서는 "단일 gradient + % 색상 스탑" 구조를 가정했으나, 실제로는
    여러 개의 겹친 `linear-gradient` 레이어 + `background-size` 누적 폭(%)
    구조였다. call이 없는 순수 오픈 스팟(UTG/HJ/CO/BTN RFI, 레이어 1~2개)에서는
    우연히 값이 맞아 재검증 통과했지만, call/allin이 섞이는 스팟(SB RFI 등,
    레이어 2~3개)에서는 기존 파서로 169핸드 전량 파싱 실패(badSum=169, 전부 공백)함을
    확인. 레이어를 앞(포그라운드)→뒤(백그라운드) 순으로 `allin, raise, call, fold`
    색상으로 매칭하고 누적폭 차분(현재 레이어 bg-size % − 이전 레이어 %)으로
    빈도를 구하는 새 파서로 교체 후 재검증(badSum=0). `docs/gto-data.md`의
    저장된 추출 스크립트는 최신화됨.
  - **BTN/SB 헤즈업 RFI(id=105810)는 스킵 처리**: 6-max `POSITIONS` 목록에
    없어 `gto/url_generator.py`로 URL을 만들 수 없음(헤즈업은 GTO Wizard에서
    별도 게임타입 필요). 큐에는 `collected=0`으로 남겨둠 → "헤즈업 GTO 매핑" 항목으로 해결.
  - **재수집 진행 현황 (2026-07-12)**: RFI 5개 중 4개(UTG/HJ/CO/BTN) 이전 완료
    + SB 오늘 완료 → RFI 전량 완료. vs_open 3개(BB vs BTN/UTG open, SB vs BTN
    open) 완료. vs_3bet 1개(BTN vs BB 3bet, 사이징 실측 28.5bb) 완료 —
    옛 "vs_3bet 나머지 4개 수집" 고정 목록 항목은 이 큐 기반 수집으로 완전히
    대체되어 삭제(중복 정리, 2026-07-12). 남은 큐는
    `python3 scripts/show_missing_spots.py`로 계속 확인하며 소진.

- [x] **헤즈업(2인) GTO 스팟 — 6-max SB/BB 포지션으로 매핑** (2026-07-12 확정, 완료)
  - 배경: 세션 진행 중 봇이 파산하면 `server/session.py` `_start_new_hand()`가
    `chips>0`인 플레이어만 남겨 테이블 인원이 실제로 6→...→2명까지 줄어듦.
    2인이 되면 `core/game.py` `get_positions()`가 딜러 자리를 `"BTN/SB"`로
    정상 표기하는데, GTO 레인지 DB는 6-max 포지션 키만 있어 조회 실패 →
    `gto_missing_spots_preflop`에 `position="BTN/SB"` 같은 미해결 스팟이 계속 쌓임
    (예: id=105810 BTN/SB RFI, 현재 스킵 처리됨)
  - 결정된 방식: 헤즈업 트리는 "SB(딜러) vs BB 단둘"인 6-max SB RFI/vs_open/
    vs_3bet 스팟과 게임 트리가 구조적으로 동일 → `my_position=="BTN/SB"`는
    `"SB"`로, 상대가 `"BTN/SB"`면 `vs_position`도 `"SB"`로 치환해 기존
    6-max 데이터를 그대로 재사용(레인지 재수집 불필요)
  - 스택 딥스 근사 명시: 6-max GTO 데이터는 원래부터 항상 100bb 기준(캐시게임
    특성상 매 핸드 스택이 벌어져도 별도 스택별 솔브 없이 100bb로 근사해왔음).
    헤즈업(파산으로 도달, 스택이 100bb에서 크게 벗어날 수 있음)도 같은 원칙
    으로 항상 100bb 가정을 그대로 적용하기로 결정(스택별 재계산은 비현실적)
  - 범위 한정: 이 매핑은 2인(헤즈업)에만 적용. 3~5인은 포지션 구성 자체가
    달라(예: 5인은 HJ 누락으로 CO의 성격이 6-max CO와 다름) 같은 논리의
    "가장 가까운 6-max 유사 스팟 대응"이 성립하지 않으므로 범위에서 제외

  ### 완료 결과 (2026-07-12)
  - `gto/advisor.py` `get_recommendation()`: 진입 시 `my_position=="BTN/SB"`면
    `"SB"`로 치환(이후 모든 조회/큐 기록이 치환된 값 기준). vs_open의
    `opener_pos`, vs_3bet의 `opener_pos`/`three_bettor_pos`도 각각 `"BTN/SB"`면
    `"SB"`로 동일 치환. `core/game.py`의 원본 `"BTN/SB"` 라벨은 미변경(UI/핸드
    히스토리용 유지) — 치환은 advisor 내부 조회 시점에만 국소 적용.
  - 실측 확인: 헤즈업 BTN/SB RFI 조회(예: 72o)가 실제 DB의 SB RFI 데이터
    (`situation="SB RFI"`)로 정상 응답함을 확인. 스킵돼 있던 큐 항목
    id=105810(BTN/SB RFI)을 `collected=1`로 갱신(치환 매핑으로 실시간 해결되어
    더 이상 미해결 스팟이 아님, 별도 재수집 불필요).
  - `docs/gto-data.md`에 "100bb 고정 가정(헤즈업 포함)은 의도된 근사"와 헤즈업
    BTN/SB→SB 매핑을 한 줄 명시.
  - `tests/test_poker_full.py`에 `test_6_9_headsup_gto_btnSB_mapped_to_sb_rfi`
    추가(격리 임시 DB에 SB RFI 시추에이션을 직접 시딩 후 `gto/loader.py`의
    프로세스 캐시를 무효화해 헤즈업 2인 테이블에서 advisor가 SB RFI 데이터로
    정상 응답하는지 검증). `python3 tests/run_all.py --fast` 54개 전체 통과.

- [x] 🔴 **HJ RFI 데이터 오염 확인 + 전체 프리플랍 GTO 스팟 전수 검사** (memo 피드백, 2026-07-12, 완료)
  - 확인됨(직접 DB 조회, 2026-07-12): `HJ RFI`는 169핸드 전부 fold=100%로
    저장돼 있음(비교: UTG fold100%=117/169, CO=102, BTN=81, SB=61 — 포지션이
    늦을수록 오픈이 넓어지는 정상 패턴인데 HJ만 유일하게 전부 폴드로 깨져있음).

  ### 완료 결과 (2026-07-12)
  - **원인 확정**: Chrome MCP로 GTO Wizard HJ RFI 스팟(`preflop_actions=F&
    history_spot=1`)을 직접 재확인 — 실제 GTO 솔루션은 raise 21.7% / fold
    78.3% / allin 0%. 저장돼 있던 "전부 fold"는 실제 GTO 값이 아니라 재수집
    (v11 스키마 전환) 과정의 저장 버그였음이 확정됨(추측 아님, 화면 확인).
  - 레이어 기반 파서(allin/raise/call/fold 색상 매칭 + 누적폭 차분)로
    169핸드 재추출(`badSum=0`, Overview 패널의 21.7%/78.3%와 일치) 후
    `/gto/preflop/save`로 재저장. 재저장 후 fold100=111/169로 UTG(117)와
    CO(102) 사이에 정상 위치.
  - **전수 검사 스크립트** `scripts/audit_gto_preflop.py` 작성: 핸드별 빈도합
    [0.9,1.1] 검증, RFI 포지션 간 오픈 비율 순서 검증(UTG<HJ<CO<BTN<SB),
    특정 액션 100%/0% 쏠림 탐지. HJ RFI 수정 후 11개 전체 통과, 추가 이상 스팟 없음.
  - `docs/gto-data.md`에 전수검사 결과, HJ RFI 오염 경위, 레이어 기반 파서
    최신판(`extractAndSave`) 반영. `python3 tests/run_all.py --fast` 통과 확인 후 커밋.

- [x/superseded] **GTO 수집 Playwright 완전 자동화** — ④ 데이터 기반 트리 워커로 대체/흡수됨
  (2026-07-17). 아래 레거시 열거 방식 설계 대신 `scripts/collect_gto_tree.py`(데이터 기반,
  실측 사이즈 키, 빈도>ε 분기, 도달확률 best-first)가 실제 구현체다. CDP 연결/한도 감지/
  --dry-run/--limit/스팟단위 저장 등 핵심 설계는 그 드라이버에 반영됨.

  **목표**: 수집을 Claude 개입(토큰) 없는 로컬 스크립트로 전환.

  **핵심 설계 결정**
  - 로그인 재사용: 사용자가 크롬을 디버그 포트로 실행 → 스크립트가 CDP로 접속
    `/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222`
    (`playwright.chromium.connect_over_cdp("http://localhost:9222")`)
  - 추출 이중화: XHR 솔루션 JSON 가로채기 1순위(정확 + EV 포함 가능성) / 검증된
    CSS background-size 파싱 폴백

  리스크: GTO Wizard 렌더 구조 변경 시 CSS 폴백 취약(그래서 XHR 우선),
  CDP는 크롬을 디버그 플래그로 재시작해야 하는 1회 불편.
  브라우저 밖 API 직접 호출(토큰 탈취)은 약관 리스크로 금지.

### 프리플랍 전체 트리 커버리지 — ①~④ 완료분 (2026-07-13 ~ 2026-07-17)

전체 배경/설계: `docs/gto-preflop-tree.md`. 진행 중인 ⑤⑥은 `TODO.md` 참고.
단계 순서: ① 구조화 액션 히스토리 → ② 시퀀스 키 스키마 → ③ 트리 정찰 →
④ Playwright 자동화 → ⑤ 파일럿 수집+검증(진행중) → ⑥ 본격 확장(예정).

- [x] **③ 트리 규모 정찰** (2026-07-13, Browser 페인으로 실측)
  - 노드당 논-올인 레이즈 사이즈 정확히 1개(+allin+call+fold) 확인.
  - 사이즈 에스컬레이션 2.5→8→17.5→35→올인(100bb, 약 4단계). 스퀴즈/콜드-4벳
    노드 존재·solvable 확인. 사이즈는 노드/포지션 의존(공식 추론 불가, 실측 필수).
  - `preflop_actions=...&history_spot=N` URL이 그대로 캐노니컬 노드 키.

- [x] **① 구조화된 프리플랍 액션 히스토리** (완료 2026-07-15, 순수 코드)
  - **구현 방식(택1: event_log 이벤트 강화)**: `core/game.py`의 `apply_action`이
    발행하는 "action" 이벤트에 `position`(get_positions, 헤즈업 "BTN/SB" 원본
    유지) + `street` + `to_amount`(해당 라운드 도달 총 베팅액; fold/check는 None)를
    추가. 별도 메서드 `preflop_action_seq()`가 event_log를 street=="프리플랍"으로
    필터링해 `[{position, action: fold|call|raise|allin|check, amount_bb}]`
    (amount_bb = to_amount/big_blind)를 반환.
  - `_get_game_state()`에 `preflop_seq` 노출 → `server/session.py`의 advisor
    호출 경로가 자동 전달됨. UI용 한글 `action_log`는 유지.
  - `gto/advisor.py`: `_count_preflop_raises`/`_find_raisers_in_log`(한글 파싱)을
    `_count_raises`/`_raisers`(preflop_seq 기반)로 교체.
  - **검증**: `run_all.py --full` 전체 통과(poker_full 57 + equity 39 + grader 31).
    유닛테스트 3종 추가(6-10 스퀴즈 콜 구조화 확인/6-11 헤즈업 BTN/SB 라벨 유지/
    6-12 vs_open 시퀀스 라우팅).

- [x] **② 시퀀스 키 스키마 + 마이그레이션** (완료 2026-07-15, 순수 코드)
  - **택한 스키마 = 안 A**(저위험, additive): `gto_preflop_situations`에 `action_seq`
    (캐노니컬 노드 키) + `hero_position` + `num_active` 컬럼 추가. 기존
    `(position,vs_position,range_type)` enum 키/UNIQUE는 그대로 유지. `SCHEMA_VERSION`
    11→12.
  - **스냅 규칙 = 레이즈 깊이 기준**: `url_generator.canonical_raise_size`
    단일 소스(`CANONICAL_OPEN_SIZE` SB 3.5, 그 외 오픈 2.5 / `CANONICAL_RAISE_BY_DEPTH`
    3벳 8·4벳 17.5·5벳 35). (이후 ②'에서 실측 기반으로 전환됨.)
  - **마이그레이션 결과**: 11 situations / 1778 hands 보존(손실 0). action_seq 11/11 백필.
    vs_3bet `vs_position` 반쪽 포맷 `"BB"`→`"BTN/BB"` 정규화.
  - **조회 경로**: `loader.get_range_by_seq(node_key)` 추가. `advisor.get_recommendation`은
    enum 경로 우선 + enum None일 때 시퀀스 키 폴백.
  - **검증(통과)**: `run_all.py --full` 전체 통과(poker_full 60 + equity 39 + grader 31).
    유닛테스트 3종 추가(6-13/6-14/6-15).

- [x] **②' 데이터 기반 키/스냅 전환** (2026-07-16 확정 → 2026-07-17 구현 완료, 순수 코드)
  상세 설계: `docs/gto-preflop-tree.md` "데이터 기반 트리 수집 방식" + "②' 구현 완료" 섹션.
  - **완료 요약**: D1(하드코딩 캐노니컬 테이블을 노드 키 생성에서 제거 — 레거시
    `situation_to_node_key` 전용으로 격리) + D3(런타임 `canonical_node_key`를
    트리-인지 스냅으로 재작성: `loader.get_children_by_prefix`로 수집된 형제
    노드의 실측 사이즈에 스냅, 미수집 브랜치는 None→실측 키로 큐 등록) 구현.
    저장 키는 실측 사이즈 verbatim. D2(레거시 11노드 재수집)는 ④ 워커 몫으로 남김.
  - **검증(통과)**: `run_all.py --full` 전체 통과(poker_full 63 + equity 54 + grader 31).
    유닛테스트 3종 추가(6-16/6-17/6-18). `audit_gto_preflop.py` 통과. 실 DB 스팟체크:
    라이브 3벳 11bb가 수집 형제 R8로 스냅돼 레거시 11노드 정상 조회(회귀 없음).

- [x] **④ 데이터 기반 트리 워커 + 수집 — 드라이버 구현 완료** (2026-07-17, GTO Wizard 필요)
  - 순수 로직: `scripts/gto_tree_worker.py`(집계/분기ε/토큰/도달확률 큐).
  - **드라이버: `scripts/collect_gto_tree.py`** — 순수 로직에 Playwright(CDP)
    navigate + CSS 레이어 추출 + badSum 검증 + 실측 사이즈 읽기 + `/gto/preflop/save`
    POST + 자식 확장(도달확률 가중 push)을 붙인 얇은 드라이버.
    - 저장 키 = 실측 사이즈 verbatim(D1), 분기 = `branch_actions`(ε=0.05%),
      우선순위 = `FrontierQueue`(도달확률 내림차순), badSum∉[0.9,1.1]이면 저장 안 함.
    - 베팅순서 시뮬레이터(`_replay`)로 히어로/레이저 포지션·라벨 결정론적 유도 +
      베팅 종료(터미널) 노드 자동 제외. 유닛 대조: DB 13노드 라벨과 100% 일치.
    - 중단-재개: `gto_tree_checkpoint.json`(visited/frontier/failed) + DB action_seq로 재개.
    - 일일 한도 감지: 실측 확정(2026-07-17) — 상단 `X/100` 카운터가 유일한 권위 신호.
      `--safety-margin`(기본 5) 이하로 떨어지면 안전 종료. `--limit`(기본 90).
    - CLI: `--limit/--dry-run/--cdp-url/--server/--checkpoint/--epsilon/--nav-timeout`
      `/--min-delay/--max-delay`(랜덤 지연, 기본 2~5초).
    - CDP 연결 실패(크롬 미실행) 시 크래시 아니라 안내 출력 후 exit 0 (검증 완료).
  - **실전 라이브 실행 완료(2026-07-17)**: 사용자가 크롬 디버그+로그인 후 여러 차례
    `--limit`으로 실행, 실제 버그 3건 발견·수정(모두 `docs/gto-preflop-tree.md`
    "두 번째 라이브 실행 확정" 참조):
    1. raise/allin 실측 사이즈가 헤더의 다른 포지션 과거 액션과 뒤섞이던 오탐 → 히어로
       Actions 패널 버튼(`[data-tst="study_action_btns"]`)으로만 읽도록 수정
    2. 렌더 대기가 "색칠된 셀 ≥150개" 절대 임계값이라 4벳+ 등 원래 좁은 레인지 노드에서
       무한 타임아웃 → "600ms 이상 개수 안 바뀌면 완료"(안정화 기반)로 수정
    3. 일일 한도 도달 시 처리 중이던 노드가 visited/frontier 어디에도 없이 유실되던
       버그(사용자 지적) → 한도 감지 시 `frontier.push(node)`로 되돌린 뒤 중단하도록 수정
    - 실행 결과: DB 13→24개 스팟 수집, `audit_gto_preflop.py`/`tests/run_all.py --fast`
      전부 통과. D2(레거시 11노드)는 워커가 실측 키로 자연히 덮어씀.
    4. (세 번째 실행, `--limit 200`) 100번+ 반복 navigate로 크롬 렌더러 크래시
       발생(`chrome://crashes`로 확인) → 이후 20개 연속 실패, 크래시로 실패한 노드가
       badSum과 동일 취급돼 `failed`/`visited`에 영구 기록될 뻔함(84개, 세션 중 DB
       기준 체크포인트 재구성으로 긴급 복구). **코드 수정**: `is_env_failure()`로
       환경오류(크래시/타임아웃/저장실패)와 진짜 데이터이상(badSum) 분리 → 환경오류는
       frontier로 되돌려 자동 재시도, 연속 2회면 탭 자동 재생성(로그인 세션 유지),
       연속 6회면 안전 중단(서킷브레이커), 25개마다 예방적 탭 재생성. 상세:
       `docs/gto-preflop-tree.md` "세 번째 라이브 실행" 섹션.
  - 사용법 상세(사전 조건 체크리스트 포함): `docs/gto-preflop-tree.md` "사용자 실행 방법" 섹션.

- [x] **수집 현황 리포트** (2026-07-17) — `scripts/gto_tree_report.py` 신규.
  DB(확정 수집)+체크포인트(frontier/failed)를 읽어 `docs/gto-preflop-progress.md`
  생성(포지션별/깊이별 통계 + mermaid 트리 다이어그램 + 수집목록/다음후보 테이블).
  "전체 대비 %"는 의도적으로 미표시(데이터 기반 원칙상 전체 규모 미리 알 수 없음).
  사용자가 직접 재실행 가능: `python3 scripts/gto_tree_report.py`.

- [x/retired] **⑤ 파일럿 + ⑥ 본격 확장 — 별도 Task 관리 종료** (2026-07-17)
  사용자가 실플레이로 체감 개선을 이미 확인했고, 앞으로도 `collect_gto_tree.py`를
  계속 돌릴 예정이라 "아레나 bb/100 검증 게이트"를 formal Task로 유지하는 게
  실익이 없다고 판단(수치도 계속 바뀌어 TODO에 박아두면 매번 outdated).
  `audit_gto_preflop.py` + 테스트가 이미 나쁜 데이터 유입을 막는 게이트 역할을 하므로
  별도 검증 Task 없이도 안전. 이후로는 "퇴근 시 돌려놓기" 루틴에 선택 실행 명령으로만
  남기고 TODO.md에서 제거. (당시 기준 DB 13→24→58개 스팟 수집, frontier 63, failed 0.)

- [x/deprecated] **포스트플랍 GTO 추상화 계획 폐기** (`docs/gto-postflop.md`, 2026-07-17)
  텍스처 클래스(≈192개)별 대표 보드 2~3개씩 GTO Wizard로 수집해 블렌드하는 설계였음.
  전제(수집 가능성)가 무너짐 — 포스트플랍 실측 솔브는 무료 100스팟/일(프리플랍 기준)이
  아니라 **유료 계정, 하루 1스팟 제한**임을 사용자가 확인. 192클래스×2~3보드
  = 400~576스팟을 모으려면 1년+ 소요 → 현실적으로 불가능 판정, 문서 삭제.
  대체 방향: `RangeSampler`/`ranged_equity`(이미 부분 구현된 프리플랍 기반 레인지
  좁히기)를 포스트플랍 베팅까지 확장하는 "Epic: 포스트플랍 전략" — 상세는
  `TODO.md` 및 (설계 확정 시) `docs/postflop-range-strategy.md` 참고.
  "포스트플랍 GTO 어드바이저"(실측 GTO 데이터 의존 전제였던 Task)도 같은 이유로
  이 Epic에 흡수·폐기. "GTO 데이터 확장(미존재 스팟)" Task도 내용이 포스트플랍
  추상화와 중복이라 함께 정리.

---

## AI 봇 개선 (완료)

- [x] **`--status` 집계를 증분 통계 테이블로 전환** — 완료 (2026-07-10)

  **배경**: `--status`의 카테고리별 진행률 쿼리가 equity_cache 전체를 풀스캔(59초,
  9,600만 행 실측). 커버링 인덱스로 6.8초까지 개선 가능했으나 테이블이 계속 자라므로
  채택하지 않고 증분 방식 채택.

  **설계**: `equity_cache_stats` 요약 테이블 신규. 모든 쓰기 경로에서 델타만큼 즉시 갱신.

  **실측 결과**: 스키마 v9로 `equity_cache_stats` 추가. `--status` 응답 시간
  **59초 → 0.09초**(656배). `--rebuild-stats` 백필 직후 풀스캔 `GROUP BY`와 20개
  카테고리 전부 완전 일치 확인. 워커 2분 실행 후 재대조에서 드리프트 1건 발견 —
  `_batch_upsert_exact`가 같은 배치 내 캐노니컬 키 중복 시 델타 이중 반영하던 버그,
  수정 후 재검증. `tests/run_all.py --full` 31/31 통과.

- [x] **프리플랍 대기 체크 쿼리 풀스캔 버그 수정** — 완료 (2026-07-10)

  **배경**: `next_mc_job`/`next_mc_batch`의 프리플랍 대기 체크 쿼리가 매 배치 호출마다
  `SCAN equity_cache`(1억 행+) 풀스캔(3.1초). 프리플랍은 이미 100% 완료라 항상 0건
  반환하는데도 매번 지연 발생.

  **원인**: v8에서 `idx_equity_street`를 잉여로 판단해 제거했는데 이 쿼리가 의존 중이었음.

  **수정**: 스키마 v10 — 프리플랍 대기 행만 담는 부분 인덱스 추가.
  ```sql
  CREATE INDEX IF NOT EXISTS idx_equity_preflop_pending
  ON equity_cache(total) WHERE exact = 0 AND street = 'preflop';
  ```

  **실측 결과**: `EXPLAIN QUERY PLAN` → 인덱스 사용 전환 확인. 3.1초 → 마이크로초 단위.
  `tests/run_all.py --full` 31/31 통과.

- [x] **에퀴티 워커 멀티프로세싱** — 완료 (2026-07-10)

  **배경**: 그라인드/워커 실행 중 CPU 사용률이 낮음(유휴 ~80%).

  **설계 원칙**: "쓰기는 메인 프로세스 1개, 계산(순수 CPU 작업)은 워커 프로세스 N개".

  **결과**: "캐시 접근은 메인 전용, 순수 계산만 Pool 분배" 원칙으로 리버·턴·플랍·MC
  전부 병렬화(`exact_turn_dp_parallel`/`exact_flop_dp_parallel`, 기존 순차 버전은
  `--workers 1` 경로로 유지). 정합성: `--workers 1`/`4` 완전 일치 확인. 성능(12코어):
  턴 40스팟 1→5.68s, 4→1.82s(x3.13), 10→1.33s(x4.28); 플랍 2스팟 1→13.6s, 4→4.2s(x3.25),
  10→2.9s(x4.71). `tests/run_all.py --full` 31개 전부 통과. PyPy 조합도 확인.

- [x] **워커 멀티웨이 우선순위 조정 (vs4/vs5 후순위)** — 완료 (2026-07-09)

  `next_mc_job`/`next_mc_batch`를 `ORDER BY num_opponents ASC, total ASC`로 변경.
  검증: `--minutes 1`(400건) 실행 결과 처리된 400건 전부 vs2 — vs4·vs5는 이번
  배치에서 처리되지 않음(의도대로 후순위). `tests/run_all.py --full` 31개 통과.

- [x] **에퀴티 계산 2차 고속화** — 작업 1·2·3 전부 완료 (2026-07).
  현재까지: 7카드 비트마스크 평가기(14.8배), 스트리트 분해 DP, 부분 인덱스
  + PyPy(3.7배) + board_rank_table(N=50 기준 28배) + 워커 배치 인출/저장(약 1.8배).

  - [x] **작업 1 — PyPy 실행 시험** (2026-07-09): 플랍 전수조사 CPython 6.4s → PyPy 1.7s
    (약 3.7배). PyPy `sqlite3`의 커서 미닫힘 커밋 에러 수정(CPython 회귀 없음).
  - [x] **작업 2 — 보드 중심 리버 계산 재구조화** (2026-07): `board_rank_table(board)`
    + `equity_via_board_table`. N=10 약 6.3배, N=50 약 28배 빠름.
  - [x] **작업 3 — 워커 배치 인출/저장** (2026-07): 리버 배치 보드 그룹화(`process_river_batch`),
    플랍 스윕은 보드중심화 효과 없음 확인(스킵). --minutes 1 완료 작업 11→20개(약 1.8배).

- [x] **에퀴티 엔진 알고리즘 최적화** (2026-06)
  - 고속 7카드 평가기 `evaluate_rank()`: 비트마스크 직접 판정 14.8배
  - 스트리트 분해 DP: 리버 3ms / 턴 0.14s / 플랍 6.5s (기존 대비 30~70배)
  - 테스트 E-9/E-10 추가 — 39개

- [x] **포스트플랍 equity 기반 재작성** (A-1~A-5)
  - `ai/equity.py`: MC 샘플링 + 리버/턴/플랍 전수조사 + equity_cache DB 누적
  - 수트 정규화 키(24치환 최소)로 스팟 중복 제거
  - 봇: equity vs 팟오즈, 세미블러프, 등급형 포지션 점수, 보드 텍스처 사이징, 체크 믹스
  - 난이도 = MC 샘플 수: easy 40 / medium 300 / hard 1200+리버 전수조사
  - 테스트 36개 (`tests/test_equity.py`)

- [x] **에퀴티 전수조사 워커** (`scripts/equity_worker.py`)
  - 중단/재개 안전, 리버→턴→플랍 우선순위
  - 프리플랍 169핸드 × 상대 1~5명 = 845스팟 고정밀 샘플링
  - `scripts/grind.py`: 아레나+워커 동시 실행 모드
  - 부분 인덱스 2개 추가(DB v7) + 쿼리 분리로 선택 시간 276ms→0.06~6ms

- [x] **상대 레인지 반영 equity** (B단계, hard 봇)
  - 프리플랍 로그 파싱 → 레이저는 RFI 레인지, 콜러는 콜 레인지로 시뮬레이션
  - `RangeSampler` + `ranged_equity()`, `gto/loader.py`에 레인지 추출 함수

- [x] **봇 성향(페르소나) 부여** (D단계)
  - tight/loose/aggressive/passive/balanced — Alpha~Epsilon 고정 배정

- [x] **봇 vs 봇 자동 시뮬레이션** (E단계, `scripts/bot_arena.py`)
  - 검증: 개선 전 hard -39.1 → 개선 후 +19.4 bb/100 (600핸드). 1500핸드에서
    hard 평균 +94.1 vs legacy -44.7 bb/100

- [x] **아레나 활용 인프라** (튜닝/회귀/퍼징)
  - `scripts/tune_bot.py`, `scripts/ai_regression.py`, 페르소나 시트 문법 확장,
    핸드별 칩 총량 보존 assert

- [x] **프리플랍 equity 우선 계산 옵션** (memo 요청)
  - 워커 `--preflop-first`: 검증 AA 0.8507 / AKs 0.6691 — 공개 equity 표와 일치

- [x] **에퀴티 패널 (웹 실시간 표시)** — 완료 (2026-07)
  - 에퀴티 게이지(팟오즈 눈금선), 상대별 브레이크다운(레이저/콜러/랜덤 태그),
    콜 EV 한 줄, 메타(값 출처/샘플수). 스포일러 정책: 헤더 힌트 토글로 통합.
  - API: get_state의 equity 필드(vs_random/vs_range/pot_odds/call_ev_bb/source/
    samples/num_opponents/opponents[]/history[])

- [x] **플레이 평가 기능 (Play Grader) v1** — 1단계 완료 (2026-07, c6ba45d/7eebc13)
  - 완료: 프리플랍 GTO 빈도 4등급 + 포스트플랍 콜/폴드 EV 판정, 결과 모달 "내 플레이",
    세션 배지(/session/review), human 액션 equity·GTO빈도 DB 기록
  - 남은 것(2단계, 별도 장기 항목으로 TODO.md에 유지): GTO Wizard EV값 수집 후
    진짜 EV손실, 벳/레이즈 정밀 판정, 통계 화면 연계

---

## ✅ 완료 (초기 기능, 상세 기록 없음)

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
  - 블라인드 베팅, 봇 액션(생각 중 → 배지) 단계별 표시
  - 스트리트별 봇 딜레이(프리플랍 1.2s ~ 리버 2.5s + 랜덤)
  - 커뮤니티 카드 한 장씩 공개
  - 액션 로그 애니메이션과 동기화
  - 내 카드 클릭으로 공개/숨기기
  - 베팅 칩 애니메이션, 폴드 딤 처리 타이밍 수정
  - 스킵 버튼
