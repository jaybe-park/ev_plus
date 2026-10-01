# TODO

실행할 Task만 둔다. **완료되면 삭제**(이력은 git, 남길 판단은 ADR). 흐름: 플레이북 §4.
사람만 정할 수 있는 것은 `DECISIONS.md`. 코드가 기존 ADR과 다르면 버그 — 묻지 않고 ADR대로 고친다.
2026-10-01 전체 리뷰 발견은 `self-reviews/2026-10-01.md`(RC1~RC6) 참고. 버그 수정을 새 기능보다 먼저 한다.

```markdown
### T-NNN — <제목>
- 왜: (한두 줄)
- 완료 조건 (사용자 언어):
  - [ ] <사람이 화면·결과로 확인할 수 있는 문장>
- 강제 장치: 조건마다 테스트 이름 · 영향: spec/ADR · 의존: T-NNN / D-NN
```

## 🚨 먼저 — 2026-10-01 리뷰 수정 (병렬 워크트리 4개 + 문서 1개)

### T-040 — 복기·봇 판단 기준 수정 (RC1) — 영역: gto/grader.py, ai/bot.py, server/session.py의 _grade_human_action, tests/test_grader.py, tests/test_equity.py, docs/spec/bot.md
- 왜: 복기와 medium 봇이 vs 랜덤 에퀴티로 판단해 벳 받은 상황에서 13~22%p 과대 → 올바른 폴드가 🔴. 폴드 채점은 5%p 여유로 타이트 폴드 리크를 못 잡고, 전수 경로는 0.3%p 차이로 🔴. 봇 `is_draw`는 오버카드 전부 드로우.
- 완료 조건:
  - [ ] 상대 레인지가 있는 스팟(`range_applied`)에서 복기 콜·폴드 판정이 패널과 같은 vs_range 에퀴티(와 그 표준오차)로 나온다. 레인지가 없으면 사유에 "상대 레인지 모름(랜덤 기준)"이 붙는다
  - [ ] 폴드와 콜 판정이 대칭이다: 폴드 마진 0.05 폐지, 둘 다 경계 구간만. 경계폭은 max(2σ, 1%p)라 전수(σ=0) 경로도 1%p 안은 ⬜ "경계". 사유 문구 "표본 오차 0(전수)"
  - [ ] grader 통계 테스트: 정규분포 시뮬로 "−3%p 콜 🔴 ≥70%", "+3%p를 버린 폴드 🔴 ≥70%", "본전 ⬜ ≥90%"
  - [ ] 봇 `is_draw`가 아웃 기반이다: 플러시 드로우(같은 수트 4장) / OESD / 거트샷(랭크 비트마스크). 테스트: AK on Q72r 드로우 아님, 98s on 762 드로우, A5s on K93 거트샷
  - [ ] 봇은 콜할 금액이 0이면 폴드 대신 체크한다(오픈 폴드 금지, 룰 F2)
  - [ ] 상대 레인지 정보가 없으면 `opponent_range_info`의 role이 "caller"가 아니라 "unknown"이다
  - [ ] ADR 0049(판정 대칭·최소 경계폭·vs_range 입력) 작성, ADR 0039 README 상태 "일부 대체됨 → 0049". bot.md·equity.md 해당 절 덮어쓰기. `ai/bot.py`·`gto/grader.py`·`server/session.py`의 Task 번호 꼬리표 주석("T-033" 등) 삭제, "apply_action 전에" → "act 전에"
- 범위 밖: medium 봇의 레인지 사용(T-005, 아레나 측정 필요). 포스트플랍 레인지 좁히기(E-2)

### T-041 — 확률 검증 장치 + 에퀴티 군살 정리 (RC1·RC5) — 영역: ai/equity.py, ai/preflop_equity_table.py 헤더, tests/test_equity.py, tests/indep_eval.py(신규), scripts/gen_preflop_table.py(신규), scripts/export_preflop_equity.py(삭제), scripts/bench_equity.py, docs/spec/equity.md
- 왜: 확률이 맞는지 상시 확인하는 장치가 기준값 4개뿐. 테이블은 원천 DB가 없어 재현 불가. 런타임이 안 쓰는 계산 경로가 남아 있다.
- 완료 조건:
  - [ ] 공개 기준값 15개 이상(vs1: AA 85.2·KK 82.4·QQ 79.9·AKs 67.0·AKo 65.3·22 50.3·72o 34.6·32o 32.3 / vs2 AA 73.4 / vs5 AA 49.3·72o 등)을 ±0.3%p로 대조하는 테스트
  - [ ] 프로젝트 코드를 import하지 않는 독립 평가기(`tests/indep_eval.py`, 브루트포스)로 `evaluate_rank`·`HandEvaluator` 랜덤 7장 5,000핸드 동일성 + 리버 전수 20스팟 동일성 테스트(1초 이내)
  - [ ] 레인지 결합 샘플러 전수 대조 3케이스(가중치·블로커 교차·랜덤 상대 혼합, 리버) 3σ 테스트
  - [ ] `--full` 전용 정밀도 회귀: 고정 시드 턴 10스팟×10회 전수 대비 rmse ≤ 1.3%p, ±2%p 안 ≥ 93%
  - [ ] `--full` 전용 응답 시간 상한: 패널 1회(상대 2명 플랍) < 150ms, hard 봇 판단 < 60ms
  - [ ] `scripts/gen_preflop_table.py`: 현재 엔진(동률 1/k)으로 845값을 재생성(`--dry-run`은 기존 테이블과 3σ 비교만 출력). 실행은 하지 않는다(CPU 1~2시간, 사람이 돌림). `export_preflop_equity.py` 삭제. 테이블 헤더의 편향 수치를 실측(+0.13%p 평균, 최대 +0.40%p)으로 정정
  - [ ] 런타임·테스트 어디서도 안 쓰는 `board_rank_table`/`equity_via_board_table`/`calculate_equity`/`mc_counts_ranged` 삭제(테스트가 쓰면 `_ratio` 등으로 대체). `exact_counts_turn/flop`은 기준값용으로 유지
  - [ ] equity.md 덮어쓰기: 응답 시간 표를 "판단 ≈15~23ms, 패널 최대 ≈70ms, 측정 `bench_equity.py`" 두 줄로, 추정 원인 ①②③ 서술·"T-032 이전"·캐시 시절 비교 삭제, 알려진 한계에 F5 테이블 편향 수치
- 의존: 없음(T-040과 파일 겹침 없음 — bot.py·grader.py는 T-040 소유, `tests/test_equity.py`의 봇 테스트 부분은 T-040이 추가하므로 이 Task는 에퀴티 테스트 섹션만 건드린다)

### T-042 — 룰 허용 범위·사이드팟 표시·약한 테스트 (RC4) — 영역: core/game.py, server/session.py(_do_showdown·get_state·can_raise), server/schemas.py, cli/main.py, tests/test_poker_full.py, docs/spec/game.md 룰 절
- 왜: 상대 전원 올인인데 레이즈가 허용돼 기록·채점·프리플랍 시퀀스가 오염된다. 미콜 초과 베팅이 쇼다운까지 팟으로 보인다. 사이드팟 결과가 화면에 없다(T-003). 항상 통과하는 테스트가 있다.
- 완료 조건:
  - [ ] 콜할 상대가 아무도 없으면(나 외 행동 가능한 플레이어 0) 레이즈·올인-레이즈가 불법이고 `can_raise=false`다(core `raise_allowed` + 퍼저 `_RefTable.may_raise` 동일 규칙). 테스트: 3인 BTN 폴드·SB 올인 → BB 레이즈 거절·콜/폴드만
  - [ ] 서버가 `GameState.pots: list[{amount:int, eligible:list[str], winners:list[str], returned:bool}] | null`(hand_over일 때)을 내려준다. `returned=true`는 eligible 1명 계층(초과 베팅 반환). `winner` 이벤트와 "🏆 승리" 로그의 pot은 실제 수령 합(반환분 제외)이다. 테스트: 3명 다른 스택 올인 → 메인/사이드/반환 계층 금액·승자
  - [ ] CLI 레이즈 안내가 음수 칩을 보이지 않는다(웹과 같은 `maxRaise >= min_raise_to` 조건)
  - [ ] 독립 사이드팟 계산기(코드 공유 없음)로 랜덤 올인 시나리오 2,000개를 `showdown()`과 대조하는 테스트(2초 이내)
  - [ ] 항상 통과하거나 이름보다 약한 테스트를 실제 검사로 바꾼다: test_2_4(round_over/next_to_act 호출), test_2_6(순서 검사), test_4_4(advance_street 경유), test_6_6(기여 다른 3명 → 팟 3개), test_4_6(보정 검사), test_3_1(시드 고정 + 레이즈·올인 포함, 3초 이내)
  - [ ] game.md 룰 절 덮어쓰기: 포스트플랍 최소 벳 = BB, 숏스택 BB의 콜 금액 = BB 전액(표준 관행), 오픈 폴드는 룰상 합법이나 사람 UI·봇은 쓰지 않음, 콜할 상대 없으면 레이즈 불가, 초과 베팅은 쇼다운에서 반환(결과 창 "반환 N"). `test_2_5` 예시 정정, `_is_round_over`→`round_over`, "T-036 예정" 한계 삭제, 일회성 확인 기록(84-85행) 삭제. `core/game.py:375` ADR 번호 0046→0048. core·server·cli의 Task 번호 꼬리표 주석 삭제(T-040이 맡은 `_grade_human_action` 주변은 제외)
- 프론트 표시는 T-043이 같은 `pots` 계약으로 구현한다

### T-043 — 프론트 정확성·정리 (RC3·RC5) — 영역: web/ 전부
- 왜: EV 손실이 안 보이고 헤더는 손실을 "+"로 보인다. 팟 프리셋이 틀린 금액을 보낸다. GTO 조회 실패가 "로딩 중"으로 고착. Vite 템플릿 잔재·중복.
- 완료 조건:
  - [ ] 결과 창 복기 줄에 손실이 "−N.Nbb"(빨강)로 보이고 헤더 세션 요약은 "EV 손실 N.Nbb"다. 판정은 순수 함수 + vitest
  - [ ] 팟 프리셋(1/3·1/2·3/4·팟)이 `current_bet + round(f × (pot + call))`이다. `actionBarLogic.ts`로 옮기고 vitest(벳 없음 / 벳 마주함 2사례)
  - [ ] GTO 조회가 실패하면 패널이 "조회 실패"를 보이고 로딩과 구분된다(상태 loading/ok/error)
  - [ ] GTO 그리드에서 데이터 없는 핸드와 빈도 합이 1 미만인 잔여는 중립 회색이다(폴드 색 아님). 범례에 "데이터 없음"
  - [ ] 헤더 세션 요약(GTO%·EV)과 핸드 번호는 재생이 끝난 뒤에 바뀐다
  - [ ] 결과 창에 사이드팟이 보인다(T-003): `GameState.pots`(T-042 계약: amount·eligible·winners·returned) 계층별 "메인/사이드 N — 금액 — 승자", `returned`는 "반환 N → 이름". 승자 줄 봇 이름 접두사 "🤖 " 제거 통일
  - [ ] 서버 로그 30줄 제한과 어긋나지 않게 재생 중 로그를 끝 기준으로 자른다(또는 서버 전체 로그 — T-042 소유 파일이므로 프론트에서 해결)
  - [ ] 삭제: `toGtoHand`·`myHand` prop, `App.css`, `assets/hero.png`·`react.svg`·`vite.svg`·`public/icons.svg`, `index.html` title "ev_plus"·lang "ko", `web/README.md`는 실행 방법 10줄로 교체. 중복 통합: ACTION_COLORS/ORDER 1곳, "🤖 " 제거 1곳, SB/BB 판정 1곳, 프리셋 JSX 1블록, canRaise 1곳, pct 포맷 1곳. Task 번호 꼬리표 주석 삭제(ADR 참조는 유지). `localStorage` 접근 try/catch
  - [ ] `npm run build`·`lint`·`test` 통과. game.md "웹 게임 흐름"의 해당 문장(헤더 요약·사이드팟 표시·알려진 한계 T-003 삭제)만 덮어쓰기

### T-044 — GTO 조회 경로 가드 + 파이썬 군살 정리 (RC2·RC5) — 영역: gto/, db/, scripts/, tools/, tests/test_gto_tree.py, tests/test_workflow.py, tests/run_all.py, .claude/hooks/block_dangerous.py, requirements*.txt, dev.sh/prod.sh/start.sh, docs/spec/gto-preflop.md·db.md·testing.md
- 왜: 간단 라벨 예비 경로가 올인·림프·3~5인에서 ADR 0035·0037·0046·0005를 우회한다. 죽은 코드·일회성 도구·폐기된 워커 잔재가 남아 있다.
- 완료 조건:
  - [ ] 프리플랍 시퀀스에 올인이 있으면 라벨 예비 경로는 None(힌트 "데이터 없음")이고 미수집 큐에 시퀀스 키가 기록된다. 테스트: UTG 올인 → HJ 힌트 None / UTG 오픈·HJ 3벳·CO 올인 → UTG 힌트 None
  - [ ] 림프가 있는 팟은 RFI로 판정하지 않는다(`is_rfi`는 시퀀스에 콜·레이즈가 없을 때만). 테스트: UTG 림프 → HJ 힌트가 RFI 노드가 아님
  - [ ] 3~5인 테이블에서는 라벨 예비 경로도 None(ADR 0005). 테스트 1건
  - [ ] `audit_gto_preflop.py`에 두 검사 추가: ① 자식 노드 핸드 집합 = 부모의 직전 액션 지지 집합(노드 5의 117핸드를 잡아야 함, 현재 DB에서 1건 실패로 보고) ② DB에서 재구성한 frontier ⊆ 체크포인트 frontier ∪ visited(유실 `F-F-R2.5`를 잡아야 함). `requeue_lost_gto_nodes.py`와 그 테스트 삭제(역할을 audit이 흡수, 되돌리기는 frontier 재시드)
  - [ ] 체크포인트 frontier 유실 복구: `failed=[]`를 확인한 뒤 `gto_tree_checkpoint.json`을 DB에서 재시드(수집기의 시드 경로 사용, 백업 `.json.bak` 남김). 재시드 후 frontier에 `F-F-R2.5`가 있다
  - [ ] 미수집 큐 정화: 수집기가 큐 항목을 frontier에 넣을 때 수집된 조상에서 다음 액션 빈도가 ε 이하인 키(트리 밖)는 건너뛴다. 옛 enum 행 23개 삭제는 `--dry-run` 지원 스크립트(`scripts/prune_missing_spots.py`)로만 — 실행은 하지 않고 dry-run 결과만 보고
  - [ ] 삭제: `db/queries.py`(+`db/__init__.py` 재노출), `gto/url_generator.py`의 `rfi_url`/`vs_open_url`/`vs_3bet_url`/`get_url`/`OPEN_SIZE`/`THREE_BET_SIZE`(`situation_to_node_key`·레거시 사이즈 표는 v12 마이그레이션이 쓰면 유지), `tools/migrate_gto.py`, `scripts/slim_db.py`+`tests/test_slim_db.py`(FULL에서 제외), `gto/loader.py:108` 도달 불가 fold 줄, `server/main.py`의 `__main__` HTTP 실행 블록(ADR 0025), `db/recorder.py::close`, `tests/test_poker.py`(영역 1과 중복)
  - [ ] hook `EXCLUSIVE`에서 `equity_worker` 규칙 제거(grind/tune/collect만), hook 모듈 docstring의 ADR 참조 0002→0001·0033. `tests/test_workflow.py`를 그에 맞게 고치고 `run_all.py` FAST에 등록
  - [ ] `requirements.txt` 하나로 통합(httpx 포함, `requirements-server.txt` 삭제, README·start 스크립트 참조 갱신). `dev.sh`/`prod.sh` SSL 블록을 공용 함수 파일로 빼고 `start.sh`는 유지(`test_8_23`이 `dev.sh`를 파싱하므로 그 형식 보존)
  - [ ] 로더에 공개 `invalidate()`를 두고 `server/main.py`가 내부 캐시 변수를 직접 지우지 않는다. GTO 노드+핸드 로딩을 `gto/loader.py` 한 함수로 모으고 collect·audit이 그것을 쓴다(빈도합 허용 상수 1곳)
  - [ ] 주석 정리: ADR 번호 0038→0044 6곳(db/schema.py:164,445 · gto/node_key.py:9,12 · server/main.py:167 · tools/gto_extract_and_save.js:13), 날짜·사고 경위·Task 꼬리표(`collect_gto_tree.py`·`url_generator.py`·`schema.py`·`advisor.py`·`gto_tree_worker.py`) 삭제, `collect_gto_tree.py` 모듈 docstring을 10줄 이내로
  - [ ] gto-preflop.md·db.md·testing.md 덮어쓰기: 스키마 현재 버전 14(운영 DB 2026-10-01 적용), 부분 인덱스 절 삭제(ADR 0032 대체됨), "장치 없음"→hook, FAST/FULL 목록은 "원본 `run_all.py`"로, 실행 시간 실측, 격리 이유 정정, v13 적용 서술·vs_open 스냅샷·"T-013/T-014/T-012" 근거 삭제, 삭제한 도구 참조 제거
- 의존: 운영 DB 마이그레이션(완료, 2026-10-01)

### T-045 — 문서 전면 정합 (RC6) — 메인 세션이 T-040~044 병합 뒤 수행
- 완료 조건:
  - [ ] README: https, 끝난 T-013 제거, 구조 표 갱신, 야간 루틴은 spec 링크로, 현재 상태 표 사실 정정
  - [ ] game.md를 "룰(core)"과 "웹 흐름·API" 두 파일로 분할하고 장황 후보(self-review RC6) 삭제. 각 spec 토큰 추정을 testing.md 대신 CLAUDE.md 프로젝트 값에 "spec 1개 ≤ 6천 토큰"으로
  - [ ] ADR: README 상태 정정(0020·0022·0032 "일부 대체됨", 0005·0006·0008·0013 비고 "해소됨 → …"), 0050 "슬림 사본으로 운영 DB 교체(옛 D-15)" 작성, 없는 `ai-dev-workflow-migration.md` 링크 제거(playbook·ADR 0001은 불변이므로 README 비고로)
  - [ ] CLAUDE.md: 절대 규칙 강제 장치 정정(격리 = `run_all.py` 스냅샷 가드 + `test_guards`), 문서 지도에서 git 제외 파일 표기, `.claude/agents/implementer.md` UI 커밋 규칙을 CLAUDE.md와 일치
  - [ ] DECISIONS: 머리말을 "기준은 CLAUDE.md" 한 줄로. TODO: 빈 섹션·완료 Task 의존 메모 제거, E-2에서 ADR 0007 위반을 독립 Task로 분리
  - [ ] self-reviews/README·review 스킬의 "캐시 드리프트" 문구 정정

## 게임 룰 (spec/game.md)

### T-046 — ADR 0007 위반: 봇 상대 레인지·3벳 판정의 한글 로그 파싱 제거
- 왜: `ai/bot.py`의 `opponent_range_info`·`_count_raises`가 한글 `action_log` 문자열 매칭. 코드가 ADR과 다르면 버그. CLI는 `action_log`를 넘기지 않아 CLI 봇이 웹 봇과 다르게 행동한다.
- 완료 조건: [ ] 봇이 `preflop_seq`(구조화)만으로 레이저·콜러·레이즈 횟수를 판정한다 [ ] CLI와 웹에서 같은 상황의 hard 봇 레인지 판정이 같다 [ ] 3벳한 상대는 RFI가 아니라 수집된 vs_open 노드의 레이즈 레인지(없으면 랜덤)
- 의존: T-040(bot.py 소유) 완료 뒤

## 웹 (spec/game.md)

### T-004 — 통계 화면
- 완료 조건: [ ] "통계" 탭에 핸드 수, 포지션별 VPIP/PFR, bb/100이 보인다 [ ] 최근 50핸드 목록이 보인다
- 범위: EV 손실 정밀 집계는 제외(ADR 0042). `db/queries.py`는 삭제됐으므로 새로 쓴다(사람 참여 핸드만, D-31 결정 뒤)

### T-007 — 스킵 모드 + 자동 진행
- 완료 조건: [ ] 우상단 ⏭ 토글을 켜면 폴드한 핸드는 바로 결과가 뜬다(새로고침해도 유지) [ ] 결과 창 5초 카운트다운 후 다음 핸드 [ ] 마우스를 올리면 멈춘다 [ ] 파산/클리어 화면은 자동으로 넘어가지 않는다

### T-008 — 게임 로그 개선
- 완료 조건: [ ] 로그 각 줄에 내 핸드와 그 시점 보드가 보인다 [ ] 로그 영역이 내용만큼 늘어난다 [ ] 우상단 복사 버튼으로 로그 텍스트만 복사된다

### T-009 — 힌트 패널 재구성
- 완료 조건: [ ] ① 상황 라벨 ② GTO 빈도 ③ 내 패 액션 % ④ 에퀴티만 이 순서로 보인다 [ ] vs_3bet에서도 스크롤 없이 액션 버튼이 보인다

### T-010 — UI 기타 (기획 필요)
- 모바일 레이아웃, 핸드 히스토리 패널(T-004 재사용). 착수 전 memo로 기획을 받아 완료 조건을 채운다.

## 에퀴티 → 판단·평가 (spec/equity.md, spec/bot.md)

### T-005 — medium 봇 레인지 반영
- 왜: medium 봇 포스트플랍 EV가 vs 랜덤 기준(복기는 T-040에서 vs_range로 바뀜).
- 완료 조건: [ ] medium 봇이 3벳팟에서 상대 레인지를 반영한다 [ ] 아레나에서 medium 봇이 ADR 0041 기준으로 나빠지지 않았다
- 채택 기준: ADR 0041

### T-047 — 봇 상수 1회 측정
- 왜: 임플라이드 −0.04, 멀티웨이 +0.04/명, aggression_margin 0.06/0.08의 근거가 60핸드 1회 튜닝뿐.
- 완료 조건: [ ] T-040(is_draw) 뒤 `tune_bot.py`로 aggression_margin·임플라이드 보정을 3,000핸드×3시드 측정, 결과를 bot.md에 수치로 [ ] 채택은 ADR 0041 기준
- 의존: T-040

## Epic

### E-2 — 포스트플랍: 프리플랍 GTO 기반 레인지 좁히기
- 왜: `ranged_equity`를 포스트플랍 베팅까지 확장해 3벳/4벳 팟의 과대 EV를 바로잡는다(레인지 기반 핸드 리딩 근사, GTO 아님).
- 남은 설계(에이전트가 설계 리뷰 + 아레나 실험으로 확정, ADR 0041로 판정 후 보고): 랭킹 지표, A안 컷오프 값·훅 시점, 가중치 재정규화. 상대 레인지 출발점은 T-046
