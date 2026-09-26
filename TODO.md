# TODO

실행할 Task만 둔다. **완료되면 삭제**한다(이력은 git, 남길 판단은 ADR). 흐름은 `docs/ai-dev-workflow-playbook.md` §4.
사람이 정해야 할 것은 여기 적지 않고 `DECISIONS.md`에 둔다. 야간 루틴 명령은 `README.md` "야간 루틴".

> 코드가 기존 ADR과 다르면 **버그**다 — 사람에게 묻지 않고 ADR대로 고치는 Task로 둔다(DECISIONS 머리말 기준).

### Task 템플릿
```markdown
### T-NNN — <제목>
- 왜: (한두 줄)
- 완료 조건 (사용자 언어):
  - [ ] <사람이 화면·결과로 확인할 수 있는 문장>
- 강제 장치: 위 조건마다 테스트 이름 (에이전트가 채움)
- 영향 spec/ADR: docs/spec/<domain>.md
- 의존: T-NNN / D-NN
```

---

### T-001 — GTO 노드 덮어쓰기·조회 불일치 수정
- 왜: 저장 API가 서로 다른 노드를 한 행에 덮어쓰고(vs_open 13행 전부 콜러 노드만 남음), 헤즈업 시퀀스가 6-max UTG 노드로 스냅된다. 힌트·봇이 엉뚱한 GTO 데이터를 쓴다. **수정 전에는 `collect_gto_tree.py`를 돌리지 않는다**(돌릴수록 더 덮어써짐).
- 방향(기존 ADR대로):
  - ADR 0008 "노드 키 = action_seq, 유일" → save는 `action_seq`로 행을 찾는다. enum 3종 UNIQUE는 제거(스키마 마이그레이션, 원본 `.bak`). 덮어써진 노드 키는 체크포인트 `visited`에서 빼서 재수집 대상으로 되돌린다
  - ADR 0009 "저장 키는 실측" → save의 레거시 enum 파생 폴백(`situation_to_node_key`) 제거, `action_seq` 필수. 수동 스크립트 `tools/gto_extract_and_save.js`는 URL의 `preflop_actions`를 `action_seq`로 보낸다
  - ADR 0005 "헤즈업은 6-max SB 재사용" → 시퀀스 경로에서도 헤즈업 시퀀스 앞에 `F-F-F-F`를 붙여 SB 결정 트리로 변환
  - ADR 0002 "손상 데이터는 저장하지 않는다" → 서버 저장 API도 빈도합 [0.9,1.1]을 검증해 4xx
  - audit에 "행의 3종 키 = `derive_node_meta(action_seq)`", "체크포인트 visited 결정 노드인데 DB·failed에 없음 = 0" 검사 추가(D-11 ★A 기준, D-11이 B로 정해지면 게이트 Task 추가)
  - enum 경로 조회 순서는 D-02 결정대로
- 완료 조건 (사용자 언어):
  - [ ] 헤즈업 팟 BB vs BTN 오픈에서 보이는 힌트가 "SB가 콜한 멀티웨이" 데이터가 아니다
  - [ ] 헤즈업에서 SB 레이즈 → BB 3벳을 받으면 6-max CO 노드가 아니라 SB 기준 노드(또는 "미수집")가 보인다
  - [ ] 수집 워커를 다시 돌려도 이미 저장된 다른 노드가 사라지지 않는다
  - [ ] 덮어써져 사라진 노드가 수집 대상으로 돌아와 있다
  - [ ] `action_seq` 없는 수동 저장이나 손상된 빈도로 저장을 시도하면 거부된다
- 강제 장치: `tests/test_poker_full.py` 영역 7에 "서로 다른 action_seq는 다른 행"(G1), "헤즈업 시퀀스는 UTG 노드로 스냅 안 됨"(G3), "빈도합 불량·action_seq 없음 저장 거부" 추가
- 영향 spec/ADR: docs/spec/gto-preflop.md, ADR 0005·0006·0008·0009 (D-02가 A/C면 ADR 0006 대체 ADR)
- 의존: D-02 (나머지는 ADR대로 착수 가능) · 스키마 변경 → 커밋 전 사용자 확인

### T-013 — GTO 패널을 advisor 결과에 묶기
- 왜: `server/session.py` `_get_gto_key`가 한글 `action_log`를 따로 파싱한다(올인 무시, 헤즈업 치환 없음, 4벳을 vs_3bet로). ADR 0007 "한글 로그 파싱 금지" 위반 → 힌트와 패널이 다른 노드를 보여준다.
- 방향: advisor 추천에 `node_key`를 싣고, 패널은 `/gto/preflop/range?action_seq=`로 조회(판정기는 advisor 하나)
- 완료 조건 (사용자 언어):
  - [ ] 힌트에 표시된 상황 라벨과 GTO 패널의 레인지가 항상 같은 노드다(헤즈업, 4벳 포함)
  - [ ] 시퀀스로만 수집된 노드(스퀴즈, 4벳)도 패널에 레인지가 보인다
- 강제 장치: (에이전트가 채움)
- 영향 spec/ADR: docs/spec/gto-preflop.md, docs/api.md · UI 영향 → 커밋 전 사용자 확인
- 의존: T-001

### T-014 — 봇·힌트의 GTO 올인 처리
- 왜: GTO가 `allin`을 샘플하면 봇은 처리 못 해 휴리스틱으로 떨어지고(`ai/bot.py:210-228`), 힌트 문자열에서 올인이 번역되지 않는다. ADR 0002(GTO 값 그대로) 위반. 라이브 올인이 비올인 레이즈 형제로 스냅되기도 한다.
- 방향: 봇은 `Action.ALL_IN` 실행. 올인 토큰은 `R100` 유지하고, 라이브 올인은 올인 형제에만 스냅(없으면 큐+휴리스틱, ADR 0010과 같은 원칙)
- 완료 조건 (사용자 언어):
  - [ ] GTO가 올인 100%인 스팟에서 hard 봇이 (준수율만큼) 올인한다
  - [ ] 그 스팟의 힌트에 "올인 N%"가 보인다
  - [ ] 숏스택 올인이 일반 레이즈 노드로 잘못 매핑되지 않는다
- 강제 장치: `tests/test_equity.py` 봇 영역 — `sample_action`="allin" 고정 시 `Action.ALL_IN`
- 영향 spec/ADR: docs/spec/gto-preflop.md
- 의존: 없음

### T-015 — 미수집 큐를 수집 워커가 소비
- 왜: `gto_missing_spots_preflop`은 쌓이기만 한다(38행, `collected`를 갱신하는 코드 없음). ADR 0011은 "트리 밖 스팟 큐 = 2순위"로 정했는데 구현이 없다.
- 완료 조건 (사용자 언어):
  - [ ] 게임에서 "미수집"으로 기록된 스팟이 다음 수집 때 우선 수집되고, 수집되면 큐에서 완료 처리된다
  - [ ] `show_missing_spots.py`에 완료된 스팟이 더 이상 미수집으로 나오지 않는다
- 강제 장치: `tests/test_gto_tree.py` — 큐 항목이 frontier에 들어가고, 저장 후 `collected=1`
- 영향 spec/ADR: docs/spec/gto-preflop.md
- 의존: T-001

### T-016 — 림프 노드를 "BB RFI"로 저장하지 않기
- 왜: 워커가 SB 림프 후 BB 결정을 `open`/"BB RFI"로 저장한다(DB id 17). ADR 0006 "BB는 RFI 불가" 위반, 패널이 림프 팟에서 "BB RFI"를 보여준다.
- 방향: `derive_node_meta`가 림프(레이저 0명 + 콜 있음)를 `range_type='vs_limp'`, 라벨 "BB vs SB limp"로 유도. 기존 행은 라벨만 이전
- 완료 조건 (사용자 언어):
  - [ ] SB가 림프한 팟에서 BB에게 "BB RFI"가 보이지 않고 "BB vs SB limp"가 보인다
- 강제 장치: `tests/test_gto_tree.py::test_derive_node_meta_labels`에 림프 케이스 추가
- 영향 spec/ADR: docs/spec/gto-preflop.md, docs/db-schema.md(range_type 값)
- 의존: T-001

### T-002 — 내가 BB일 때 첫 블라인드 애니메이션 순서
- 왜: 내가 BB면 첫 핸드에서 BB가 먼저, SB가 나중에 베팅하는 것처럼 보인다. 1순위 의심: `server/session.py` `_start_new_hand()`가 좌석 순서로 blind 이벤트를 낸다(SB→BB로 정렬해 발행하면 해결 가능성 높음), 2순위: `web/src/hooks/useEventQueue.ts`.
- 완료 조건 (사용자 언어):
  - [ ] 내가 BB 좌석일 때 새 게임을 5번 시작해도 항상 SB가 먼저, BB가 나중에 칩을 낸다
- 강제 장치: `tests/test_poker_full.py` 영역 6 — 사람이 BB일 때 events의 blind 순서가 [SB, BB]
- 영향 spec/ADR: 없음(버그 수정)
- 의존: 없음

### T-012 — 수집 워커: 저장 실패가 계속되면 한도를 소진할 때까지 반복
- 왜: `scripts/collect_gto_tree.py` `run()`은 저장 실패 시 `processed -= 1` 후 노드를 frontier에 되돌리는데, 연속 실패 카운터가 없다(환경오류 카운터는 저장 직전에 리셋됨). 로컬 백엔드가 죽어 있으면 같은 노드를 계속 이동·추출해 GTO Wizard 일일 한도(100)를 헛되이 소진한 뒤에야 멈춘다.
- 완료 조건 (사용자 언어):
  - [ ] 백엔드를 끈 채 수집을 시작하면 몇 번(환경오류와 같은 기준) 안에 "서버 확인" 메시지와 함께 멈추고, 한도를 거의 쓰지 않는다
- 강제 장치: `tests/test_gto_tree.py`에 "저장이 계속 실패하면 N회 안에 중단, 노드는 frontier에 보존" 추가
- 영향 spec/ADR: docs/spec/gto-preflop.md, ADR 0012
- 의존: 없음

### T-003 — 사이드팟별 승자 표시
- 왜: 메인/사이드 팟별 승자를 구분해 보여준다. 백엔드 `_do_showdown()`에서 `_calculate_side_pots()` 결과를 `pots_breakdown`(`label, amount, winners`)으로 winner 이벤트·get_state에 포함, 프론트 `HandResult.tsx`·`types.ts`.
- 완료 조건 (사용자 언어):
  - [ ] 3명이 서로 다른 스택으로 올인하면 결과 창에 "메인 팟 / 사이드 팟 1…"이 각각 금액과 승자와 함께 보인다
  - [ ] 초과 베팅 반환분은 승자로 표시되지 않는다
- 강제 장치: 기존 사이드팟 테스트(6-5~6-8) + 3인 올인 시나리오 1개, `npm run build`
- 영향 spec/ADR: docs/api.md(`pots_breakdown`) · UI 변경 → 커밋 전 사용자 확인
- 의존: 없음

### T-004 — 통계 화면
- 왜: RL 기록으로 데이터는 준비됨. `/stats/summary`(핸드 수, 포지션별 VPIP/PFR, bb/100) + `/stats/hands?limit=50`, 우측 패널 "통계" 탭.
- 완료 조건 (사용자 언어):
  - [ ] 우측 패널에서 "통계" 탭을 누르면 내 핸드 수, 포지션별 VPIP/PFR, bb/100이 보인다
  - [ ] 최근 50핸드 목록이 보인다
- 강제 장치: API 응답 테스트, `npm run build`
- 영향 spec/ADR: docs/api.md · UI 변경 → 커밋 전 사용자 확인
- 의존: D-22

### T-005 — 조건부 에퀴티 적용 확대 (medium 봇 + 플레이 평가)
- 왜: equity_cache는 "vs 랜덤" 기준이라 3벳팟에서 쓰레기 핸드까지 포함한다. hard 봇·에퀴티 패널은 `ranged_equity` 적용됨, medium 봇과 플레이 평가 EV가 남았다. (포스트플랍 베팅 기반 좁히기는 포스트플랍 Epic 소관)
- 완료 조건 (사용자 언어):
  - [ ] medium 봇이 3벳팟에서 상대 레인지를 반영해 판단한다(`use_ranges`, hard와 같은 경로)
  - [ ] 핸드 복기의 EV가 vs_range 기준으로 계산된다
  - [ ] 아레나에서 medium 봇이 D-20 기준으로 나빠지지 않았다
- 강제 장치: (에이전트가 채움)
- 영향 spec/ADR: docs/ai-bot.md
- 의존: D-20

### T-006 — 에퀴티 표시/해석 정리
- 왜: ① 프리플랍에서 에퀴티가 거의 안 보임 ② 콜 EV −인데 GTO는 콜/레이즈 ③ 표시 값이 무엇인지 불명확. 결정(2026-07-17): vs_random은 UI에서 빼고 vs_range만 표시(계산·DB는 유지).
- 완료 조건 (사용자 언어):
  - [ ] 에퀴티 패널에 vs_random이 보이지 않고 vs_range만 보인다
  - [ ] 프리플랍에서 에퀴티가 안 보이는 이유를 문서 한 줄로 설명할 수 있다(의도라면 spec에, 버그라면 수정)
  - [ ] 에퀴티와 GTO 추천이 어긋나는 대표 사례 1개의 원인이 문서에 있다
- 강제 장치: `tests/run_all.py --fast`, `npm run build`
- 영향 spec/ADR: docs/ai-bot.md "에퀴티 패널" · UI 변경 → 커밋 전 사용자 확인
- 의존: D-16, D-17

### T-007 — 스킵 모드 + 자동 진행
- 왜: 폴드한 핸드의 이벤트 재생을 건너뛰고, 결과 팝업이 5초 뒤 자동으로 다음 핸드로.
- 완료 조건 (사용자 언어):
  - [ ] 우상단 ⏭ 토글을 켜면 폴드한 핸드는 애니메이션 없이 바로 결과가 뜬다(새로고침해도 유지)
  - [ ] 결과 창에 5초 카운트다운이 보이고 끝나면 다음 핸드가 시작된다
  - [ ] 결과 창에 마우스를 올리면 카운트다운이 멈춘다
  - [ ] 파산/클리어 화면은 자동으로 넘어가지 않는다
- 강제 장치: `npm run build` + 실플레이 확인
- 영향 spec/ADR: 없음 · UI 변경 → 커밋 전 사용자 확인
- 의존: 없음

### T-008 — 게임 로그 UI 개선
- 왜: 로그에 핸드/보드 정보가 없어 복사해서 다른 AI에게 묻기 어렵고, 고정 높이라 답답하다.
- 완료 조건 (사용자 언어):
  - [ ] 로그 각 줄에 내 핸드와 그 시점 보드 카드가 보인다
  - [ ] 로그 영역이 내용만큼 아래로 늘어난다(고정 높이 스크롤 없음)
  - [ ] 로그 영역 우상단 복사 버튼으로 로그 텍스트만 복사된다
- 강제 장치: `npm run build` + 실플레이 확인
- 영향 spec/ADR: 없음 · UI 변경 → 커밋 전 사용자 확인
- 의존: 없음

### T-009 — 힌트 패널 UI 재구성
- 왜: 힌트 패널이 길어 액션 버튼이 화면 밖으로 밀린다.
- 완료 조건 (사용자 언어):
  - [ ] 힌트 패널에 ① 핸드 라벨(예 "SB RFI(3.5)") ② GTO 빈도 ③ 내 패의 액션 % ④ 에퀴티만 이 순서로 보인다
  - [ ] vs_3bet처럼 정보가 많은 상황에서도 스크롤 없이 액션 버튼이 보인다
- 강제 장치: `npm run build` + 실플레이 확인
- 영향 spec/ADR: 없음 · UI 변경 → 커밋 전 사용자 확인
- 의존: T-013(패널 판정기)과 함께 하면 효율적

### T-010 — UI 개선 기타 (기획 필요)
- 왜: 모바일 레이아웃 최적화, 핸드 히스토리 패널(T-004의 `/stats/hands` 재사용). 착수 전 memo로 기획을 받아 완료 조건을 채운다.
- 완료 조건 (사용자 언어): (기획 후 작성)
- 의존: T-004

### T-011 — 플레이북 이관 계속
- 왜: 2026-09-26 시범 도메인(gto-preflop)만 이관했다(ADR 0001). 1~2주 시범 운영 후 나머지를 옮긴다.
- 완료 조건 (사용자 언어):
  - [ ] equity·ai-bot, db, game-engine·api·architecture, testing이 각각 `docs/spec/`에 있고 옛 문서는 삭제됐다(도메인마다 커밋)
  - [ ] `TODO_ARCHIVE.md`의 유효한 결정이 ADR로 옮겨졌고 파일이 삭제됐다(커밋 메시지에 복구 방법)
  - [ ] `docs/ai-dev-workflow-migration.md` §8 완료 조건이 모두 참이고, 그 문서가 삭제됐다
- 영향 spec/ADR: ADR 0001
- 의존: 시범 운영 1~2주(2026-10-10 전후)

---

## Epic

### E-1 — DB 인프라 정비 (SQLite 유지 + 파일 분리/보존/백업)
- 왜: `poker.db` 실측 15GB(트리거 5GB). 행 수로는 `equity_cache`(약 1억 4천만 행)가 플레이 기록(약 314만 행)의 50배 — 바이트 단위 측정은 아직. MySQL/Docker는 반려(로컬 단일 사용자는 SQLite WAL 적정).
- 다음 할 일: **equity_cache 실제 디스크 점유 측정**(`dbstat` 또는 테이블별 `VACUUM INTO` 후 크기 비교). 측정 결과로 에이전트가 순서를 정한다(기본: 백업 → equity_cache 정리 → 파일 분리 — 기존 권장 순서는 원인이 equity_cache로 바뀌기 전 기준).
- 후보 작업: 백업 자동화(`grind.py` 시작 시 `.backup`, `scripts/dump_gto.py`) · equity_cache 정리(D-12) · 용도별 DB 파일 분리(`get_connection(kind=...)`, `EV_PLUS_DB` kind별 확장) · RL 기록 아카이브(D-14, 선행 `games.bot_version`)
- 의존: D-12, D-14

### E-2 — 포스트플랍 전략: 프리플랍 GTO 기반 레인지 좁히기 확장
- 왜: `RangeSampler`/`ranged_equity`(프리플랍 액션 기반 상대 레인지, hard 봇 적용, equity_cache 미사용)를 포스트플랍 베팅까지 확장해 3벳/4벳 팟의 과대 EV를 근본적으로 바로잡는다. "GTO"가 아니라 레인지 기반 핸드 리딩 근사다.
- 확정된 설계: 2-레이어(랭킹 엔진 공통 / 컷오프 정책 교체 가능), 1차 범위는 플랍 첫 벳/레이즈만, A안(사이즈 무관 고정 컷오프)부터, B안(사이즈별 폴라라이즈)은 컷오프 후보를 아레나 자가대국(`tune_bot.py` 패턴)으로 튜닝. 이 결정들은 도메인 이관(T-011) 때 ADR로 옮긴다.
- 남은 설계(에이전트가 설계 리뷰 + 아레나 실험으로 확정, D-20 기준으로 판정 후 보고): 랭킹 지표(레인지 내 핸드별 보드 대비 equity 우선 검토), A안 컷오프 값(후보 여러 개를 아레나로 비교)·훅 시점, 필터 후 가중치 재정규화, 상대 레인지 출발점(enum RFI/콜 레인지 → 수집된 시퀀스 노드로 전환하고 `ai/bot.py`의 한글 로그 매칭 제거 — ADR 0007)
- 설계 확정 시 `docs/spec/postflop-range.md` 작성
