# 테스트

---

## 실행 방법

대표 명령은 `tests/run_all.py`. subprocess로 각 파일을 순차 실행하며
실시간 출력 릴레이 + 통합 요약(파일별 통과/실패, 총 소요 시간)을 제공하고,
하나라도 실패하면 exit code 1을 반환한다.

```bash
# 대표 명령 — 로직 검증만 (기본값, 수초 이내)
python3 tests/run_all.py
python3 tests/run_all.py --fast     # 위와 동일 (test_poker_full.py만, 63개)

# 대표 명령 — 로직 + 에퀴티/봇 + 플레이평가 검증 (148개, 2026-07-17 기준)
python3 tests/run_all.py --full     # test_poker_full.py + test_equity.py + test_grader.py
```

`run_all.py`의 `FAST_FILES`/`FULL_FILES` 상수가 대상 파일을 정의(신규 테스트 파일
추가 시 여기 등록해야 `--full`에 포함됨).

개별 실행도 가능하다 (디버깅 시 특정 파일만 빠르게 돌릴 때 유용):

```bash
python3 tests/test_poker_full.py    # 정밀 검사 (63개 — 헤즈업/트리 데이터 기반 시퀀스 테스트 포함)
python3 tests/test_equity.py        # 에퀴티 엔진 + 봇 테스트 (54개)
python3 tests/test_grader.py        # 플레이 평가(Play Grader) 판정 엔진 (31개, run_all --full에 포함)
python3 tests/test_poker.py         # 기본 유닛 테스트 (14개, run_all에는 미포함 — 독립 레거시 스위트)
```

### StubBot 방침

`test_poker_full.py`는 포커 **로직**(핸드 평가/베팅/팟 분배/게임 흐름)을
검증하는 것이지 봇의 실력을 검증하는 게 아니다. 그래서 `ai.bot.PokerBot`을
모듈 임포트 시점에 패치해 모든 봇 결정을 "콜 금액 있으면 콜, 없으면 체크"의
단순 스텁으로 대체한다 (equity 계산/GTO DB 조회/실제 AI 판단 전혀 없음).
폴드 등 특정 액션 시퀀스가 필요한 테스트는 `StubBot(player, scripted_actions=[...])`로
행동을 직접 주입한다.

AI 봇의 실제 판단력 검증(equity 정확도, GTO 준수, 페르소나별 성향 등)은
`test_equity.py`와 `scripts/ai_regression.py`가 담당한다. 즉:

- **로직 테스트** (`test_poker_full.py`) → AI 없이 스텁 봇, 목표는 게임 엔진 정합성
- **AI 검증** (`test_equity.py`, `ai_regression.py`) → 실제 equity/GTO 로직 검증

### 시간 버짓

`test_poker_full.py`는 총 실행 시간이 `TIME_BUDGET_SEC`(30초)를 넘으면
실패 처리하지 않고 "⚠️ 시간 버짓 초과" 경고만 출력한다 — 성능 회귀를
조기에 알아차리기 위한 가드다. StubBot 적용 후 정상 실행 시간은 1초 미만.

또한 테스트마다 독립된 임시 SQLite DB 파일을 사용한다. `WebGameSession`
생성 시마다 `GameRecorder`가 자체 커넥션을 열고 닫지 않기 때문에, 모든
테스트가 DB 파일 하나를 공유하면 테스트가 누적될수록 SQLite 쓰기 락
경합이 심해져 결국 busy_timeout(30초)까지 블로킹된다. 그래서 `run()`
헬퍼가 테스트 함수 실행 직전마다 `EV_PLUS_DB` 환경변수를 새 임시 파일로
갱신해 커넥션이 서로 충돌하지 않게 격리한다.

---

## 테스트 항목 (test_poker_full.py)

### 영역 1 — 핸드 평가 (13개)

| 번호 | 항목 |
|---|---|
| 1-1 | Flush 타이브레이커 (A-high vs K-high) |
| 1-2 | Straight 타이브레이커 |
| 1-3 | Wheel Straight Flush (A-2-3-4-5, high=5) |
| 1-4 | Royal Flush vs Straight Flush 경계 |
| 1-5 | 7장 중 숨어있는 Straight Flush 탐지 |
| 1-6 | Full House 타이브레이커 (트리플 우선, 같으면 페어) |
| 1-7 | Four of a Kind 키커 비교 |
| 1-8 | Two Pair 키커 비교 |
| 1-9 | One Pair 키커 3장 비교 |
| 1-10 | 완전 동률 (보드 Royal Flush로 플레이) |
| 1-11 | High Card 타이브레이커 |
| 1-12 | Flush > Straight 랭킹 |
| 1-13 | 7장에서 SF vs 단순 Flush/Straight 최적 선택 |

### 영역 2 — 베팅 라운드 (7개)

| 번호 | 항목 |
|---|---|
| 2-1 | 게임 시작 후 사람 액션 대기 상태 |
| 2-2 | BB 콜 후 체크 옵션 |
| 2-3 | 3-bet 시 이전 액션자 재기회 |
| 2-4 | 모두 폴드 → 1명 남음 |
| 2-5 | 3인 프리플랍 베팅 순서 |
| 2-6 | 헤즈업 BTN/SB 포지션 |
| 2-7 | 포스트플랍 SB 선행동 |

### 영역 3 — 팟 분배 (5개)

| 번호 | 항목 |
|---|---|
| 3-1 | 100핸드 시뮬 — 칩 총량 보존 (`chips + pot = 초기값`) |
| 3-2 | Split pot 균등 분배 |
| 3-3 | 홀수 팟 나머지 1칩 처리 |
| 3-4 | 1명 남았을 때 팟 전액 수령 |
| 3-5 | 올인 플레이어 팟 수령 한도 |

### 영역 4 — 게임 흐름 (8개)

| 번호 | 항목 |
|---|---|
| 4-1 | 딜러 버튼 매 핸드 로테이션 |
| 4-2 | 파산 플레이어 다음 핸드 제거 |
| 4-3 | 프리플랍 전부 폴드 → 쇼다운 없이 승자 결정 |
| 4-4 | 스트리트 전환 시 current_bet / player.current_bet 리셋 |
| 4-5 | 사람 파산 → game_over |
| 4-6 | 최소 레이즈 룰 자동 보정 |
| 4-7 | 스트리트별 커뮤니티 카드 수 (플랍 3, 턴 4, 리버 5) |
| 4-8 | 딜된 카드 중복 없음 (6인 풀 핸드) |

### 영역 5 — 웹 세션 (12개)

| 번호 | 항목 |
|---|---|
| 5-1 | 사람 폴드 후 봇들이 핸드 자동 완료 |
| 5-2 | 핸드 종료 후 submit_action 무시 |
| 5-3 | waiting_for_action=true → 항상 human 차례 |
| 5-4 | 콜 시 칩 실제 감소 |
| 5-5 | 레이즈 최소금액 미달 시 보정 |
| 5-6 | get_state() 필수 필드 존재 여부 |
| 5-7 | 사람 홀카드 항상 공개 |
| 5-8 | 핸드 진행 중 봇 홀카드 숨김 |
| 5-9 | 쇼다운 시 봇 홀카드 공개 |
| 5-10 | 에퀴티 패널 — 넛급 핸드 |
| 5-11 | 핸드 종료 후 hand_review 포함 |
| 5-12 | equity_enabled=False 스위치 |

### 영역 6 — 헤즈업/사이드팟/프리플랍 GTO 트리 (18개)

| 번호 | 항목 |
|---|---|
| 6-1 | 헤즈업 블라인드 포스팅 (BTN/SB=SB) |
| 6-2 | 헤즈업 프리플랍 BTN/SB 선행동 |
| 6-3 | 헤즈업 포스트플랍 BB 선행동 |
| 6-4 | 헤즈업 20핸드 칩 총량 보존 |
| 6-5 | 사이드팟 — 숏스택 메인팟만 수령 |
| 6-6 | 사이드팟 — 동일 올인 팟 1개 |
| 6-7 | 사이드팟 — 폴드 기여분 처리 |
| 6-8 | 사이드팟 분배 후 칩 보존 |
| 6-9 | 헤즈업 GTO BTN/SB→SB RFI 매핑 |
| 6-10 | 스퀴즈 구조화 시퀀스에 콜 포함(① 구조화 액션 히스토리) |
| 6-11 | 헤즈업 시퀀스 BTN/SB 라벨 유지 |
| 6-12 | vs_open 시퀀스 라우팅 스팟체크 |
| 6-13 | 시퀀스 키=enum 키 동일 레인지(② 시퀀스 키 스키마) |
| 6-14 | 런타임 사이즈 스냅→노드 매핑 |
| 6-15 | 마이그레이션 vs_3bet 포맷 정규화 |
| 6-16 | 실측 사이즈 노드 형제 스냅(②' 데이터 기반 키/스냅) |
| 6-17 | 미수집 브랜치 None+큐 등록 |
| 6-18 | 형제 2개 bb 최소거리 스냅 |

프리플랍 GTO 트리 커버리지(6-9~6-18) 관련 배경: [`docs/gto-preflop-tree.md`](gto-preflop-tree.md).

---

## 에퀴티 테스트 (test_equity.py, 54개)

| 영역 | 항목 |
|---|---|
| E-1 | 수트 정규화 키 — 치환 불변 / AKs≠AKo / 순서 불변 / 디코딩 왕복 |
| E-2 | 리버 전수조사 — 쿼드 equity=1.0, 990조합, 보드플레이 스플릿 |
| E-3 | MC 근사 — AA≈0.85, 72o≈0.35, 멀티웨이 하락, 플러시드로우≈0.65 |
| E-4 | equity_cache — 누적 저장, exact 플래그, exact 보호 |
| E-5 | 보드 텍스처 — 드라이 < 웻, 모노톤 판정 |
| E-6 | 봇 의사결정 — 넛 노폴드, 트래시 폴드/체크, 드로우 콜, 세미블러프, 포지션 점수 |
| E-7 | made hand rank — 드로우 판별 |
| E-8 | 레인지 기반 equity — RangeSampler 콤보/블록 회피, 레인지 조건부 하락 |
| E-9 | 고속 7카드 평가기 — 기존 평가기와 랜덤 3000세트 완전 일치 |
| E-10 | 스트리트 분해 DP — 턴 DP == 직접 열거, 웜 캐시 46/46 적중 |

---

## 기본 테스트 (test_poker.py, 14개)

Royal Flush ~ High Card 기본 판정, Wheel Straight, 7장 최고 핸드 선택, Deck deal.
