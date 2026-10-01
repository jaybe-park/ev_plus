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

## 🚨 먼저 — 2026-10-01 리뷰 수정

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
  - [x] game.md를 `game-rules.md`·`web-flow.md`로 분할(2026-10-01)
  - [ ] 장황 후보(self-review RC6) 삭제, CLAUDE.md 프로젝트 값에 "spec 1개 ≤ 6천 토큰"
  - [ ] ADR: README 상태 정정(0020·0022·0032 "일부 대체됨", 0005·0006·0008·0013 비고 "해소됨 → …"), 0050 "슬림 사본으로 운영 DB 교체(옛 D-15)" 작성, 없는 `ai-dev-workflow-migration.md` 링크 제거(playbook·ADR 0001은 불변이므로 README 비고로)
  - [ ] CLAUDE.md: 절대 규칙 강제 장치 정정(격리 = `run_all.py` 스냅샷 가드 + `test_guards`), 문서 지도에서 git 제외 파일 표기, `.claude/agents/implementer.md` UI 커밋 규칙을 CLAUDE.md와 일치
  - [ ] DECISIONS: 머리말을 "기준은 CLAUDE.md" 한 줄로. TODO: 빈 섹션·완료 Task 의존 메모 제거, E-2에서 ADR 0007 위반을 독립 Task로 분리
  - [ ] self-reviews/README·review 스킬의 "캐시 드리프트" 문구 정정

## 게임 룰 (spec/game-rules.md)

### T-046 — ADR 0007 위반: 봇 상대 레인지·3벳 판정의 한글 로그 파싱 제거
- 왜: `ai/bot.py`의 `opponent_range_info`·`_count_raises`가 한글 `action_log` 문자열 매칭. 코드가 ADR과 다르면 버그. CLI는 `action_log`를 넘기지 않아 CLI 봇이 웹 봇과 다르게 행동한다.
- 완료 조건: [ ] 봇이 `preflop_seq`(구조화)만으로 레이저·콜러·레이즈 횟수를 판정한다 [ ] CLI와 웹에서 같은 상황의 hard 봇 레인지 판정이 같다 [ ] 3벳한 상대는 RFI가 아니라 수집된 vs_open 노드의 레이즈 레인지(없으면 랜덤)
- 의존: T-040(bot.py 소유) 완료 뒤

## 웹 (spec/web-flow.md)

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
