# 에퀴티 엔진·캐시·워커 — 현재 사양

> 최종 갱신: 2026-09-26 · 관련 결정: [0017](../decisions/0017-equity-canonical-key-exact-protection.md), [0018](../decisions/0018-equity-fast-paths.md), [0019](../decisions/0019-equity-worker-priority.md), [0020](../decisions/0020-sqlite-single-writer.md), [0021](../decisions/0021-equity-stats-incremental.md), [0022](../decisions/0022-equity-cache-rebuildable-vsrandom-ui.md)
> 봇이 equity를 어떻게 쓰는지: [bot.md](bot.md) · 테이블 운영: [db.md](db.md)

## 무엇을 하는가

`ai/equity.py`가 "내 홀카드 + 보드 vs 상대 N명" 승률을 계산한다. 결과는 `equity_cache`(poker.db)에 누적되어 봇이 칠수록, 워커가 돌수록 정확해진다.
`scripts/equity_worker.py`(단독) / `scripts/grind.py`(워커 + 아레나 동시)가 캐시를 채운다. 사람에게는 에퀴티 패널로 보여준다.

## 규칙 (지금 유효한 것만)

### 계산
- `smart_equity` 순서: 캐시에 exact 또는 고정밀(total ≥ 20,000) 값이 있으면 그것 → 리버 1:1이고 `exact_river`면 전수조사(990조합) → 아니면 MC. 부분 누적이 있으면 MC와 합산해 반환 — 강제 장치: `tests/test_equity.py::test_cache`, `::test_exact_river`, `::test_mc_sanity`
- 캐시 키는 수트 정규화(24개 수트 치환 중 최소 키) + `num_opponents`. A♥K♥와 A♠K♠는 같은 키 — 근거: [0017](../decisions/0017-equity-canonical-key-exact-protection.md) · 강제 장치: `tests/test_equity.py::test_canonical_key`
- `exact=1` 행에는 MC를 누적하지 않는다(저장 SQL `WHERE ... exact=0`) — 근거: [0017](../decisions/0017-equity-canonical-key-exact-protection.md) · 강제 장치: `tests/test_equity.py::test_cache`(exact 보호)
- 레인지 조건부 equity(`ranged_equity`)는 캐시에 쓰지 않는다(분포가 매번 다름) — 근거: [0017](../decisions/0017-equity-canonical-key-exact-protection.md) · 강제 장치: 장치 없음
- 봇·패널의 MC 기여는 메모리 버퍼에 모았다가 스팟 25개마다 플러시한다(처음 만난 스팟은 그렇게 워커 큐에 등록된다) — 강제 장치: `tests/test_equity.py::test_cache`
- 계산용 평가는 고속 `evaluate_rank`(랭크 카운트 + 수트 비트마스크), 쇼다운 표시용은 `HandEvaluator` — 근거: [0018](../decisions/0018-equity-fast-paths.md) · 강제 장치: `tests/test_equity.py::test_fast_evaluator`
- 턴 = 리버 자식 46개 합, 플랍 = 턴 자식 47개 합(스트리트 분해 DP). 캐시가 메모 테이블이라 플랍 1개 계산에 턴·리버 정확값 약 2,200행이 부산물로 남는다 — 근거: [0018](../decisions/0018-equity-fast-paths.md) · 강제 장치: `tests/test_equity.py::test_street_dp`
- 같은 보드의 리버 스팟은 `board_rank_table`(보드 밖 2장 조합 1,081개 랭크)을 한 번 만들어 이진탐색 + 블로커 보정으로 계산한다. 결과는 `exact_counts_river`와 같아야 한다 — 근거: [0018](../decisions/0018-equity-fast-paths.md) · 강제 장치: `tests/test_equity.py::test_board_rank_table`
- 프리플랍은 전수 불가(21억 조합) → 169핸드 × 상대 1~5명을 샘플 누적한다.
- `_db()`는 `DB_PATH`가 `None`이면 `get_connection(None)`으로 위임한다 — `_DEFAULT_DB_PATH`를
  직접 넘기면 `db/connection.py`의 `EV_PLUS_DB` 환경변수 규칙(테스트 격리)을 우회하게
  되므로 금지 — 강제 장치: `tests/test_equity.py`(EV_PLUS_DB 격리 하에서 실 DB 미접촉)
- `canonical_key`는 홀-보드 또는 보드 내부에 중복 카드가 있으면 `ValueError` — 강제 장치:
  `tests/test_guards.py::test_canonical_key_duplicate_cards`
- `scripts/equity_worker.py`·`scripts/grind.py`는 시작 시(단, `--status`는 조회만이라 예외)
  `db.connection.check_db_size_guard`로 DB 파일 크기가 임계치(기본 20GB, `--max-db-gb`로
  조정)를 넘으면 실행하지 않고 이유를 출력한다 — 강제 장치: `tests/test_guards.py::test_db_size_guard`

### 워커
- 우선순위: 리버 → 턴 → 플랍 전수조사(게임에서 만난 스팟) → 프리플랍/멀티웨이 샘플 누적(상대 수 적은 것부터) → 체계적 플랍 스윕(큐가 빌 때만, 커서는 `worker_meta`) — 근거: [0019](../decisions/0019-equity-worker-priority.md) · 강제 장치: 장치 없음
- DB 쓰기는 메인 프로세스 1개, 순수 계산만 `multiprocessing.Pool`(기본 `max(1, cpu_count()-2)`). 캐시 조회·저장은 메인에서 배치로. `--workers 1` 순차 경로는 병렬 결과와 같아야 하는 회귀 기준 — 근거: [0020](../decisions/0020-sqlite-single-writer.md) · 강제 장치: 장치 없음(1회 수동 대조)
- 배치 인출(최대 500, 플랍 20) → 최대 100건씩 `executemany` 커밋. 중단 시 손실은 그 배치뿐 — 강제 장치: 장치 없음
- 모든 저장은 멱등(`WHERE id=? AND exact=0`) — 그라인드와 워커가 같은 스팟을 겹쳐 처리해도 조용히 건너뛴다 — 근거: [0020](../decisions/0020-sqlite-single-writer.md) · 강제 장치: 장치 없음
- 커서는 명시적으로 닫는다(PyPy sqlite3는 미소비 커서가 있으면 commit 실패) — 강제 장치: 장치 없음
- 동시 실행 금지: 워커 2개, 그라인드 + 워커, 그라인드/튜닝 — 강제 장치: hook `.claude/hooks/block_dangerous.py`(에이전트 실행분만)

### 현황 통계
- `--status`는 `equity_cache_stats`(카테고리별 요약)만 읽는다. equity_cache에 쓰는 **모든** 경로가 같은 트랜잭션에서 `bump_equity_stats`로 델타를 반영한다. 한 배치 안 중복 키는 마지막 값 기준으로만 델타를 계산한다. `--rebuild-stats`는 백필·복구용 — 근거: [0021](../decisions/0021-equity-stats-incremental.md) · 강제 장치: 장치 없음(드리프트 사고 이력 있음)

### 에퀴티 패널 (`server/session.py::_get_equity_info`)
- 사람 차례(`waiting_for_action`)이고 `equity_enabled`일 때만 계산한다(아레나는 끔). 같은 결정 지점(스트리트 + 현재 벳)은 재계산하지 않는다 — 강제 장치: `tests/test_poker_full.py` 5-10, 5-12
- `vs_random`: 살아 있는 상대 수만큼 랜덤 핸드 상대(`smart_equity`, 1000샘플, 리버 1:1은 전수). `vs_range`: 상대별 추정 레인지 반영(`ranged_equity`, 레인지 정보가 없으면 vs_random과 같음). 상대별 브레이크다운과 콜 EV(bb, vs_random 기준)도 준다 — 강제 장치: `tests/test_grader.py::test_session_equity_and_review`
- 스트리트별 추이(history)는 vs_random만 기록한다 — D-16
- vs_random은 UI에서 빼고 vs_range만 보이기로 결정됐다(계산은 유지, 봇·플레이 평가가 씀) — 근거: [0022](../decisions/0022-equity-cache-rebuildable-vsrandom-ui.md) · 미구현 T-006

## 화면·경로·데이터

| 대상 | 무엇 |
|---|---|
| `ai/equity.py` | 계산·캐시 접근·레인지 샘플러 (`smart_equity`, `ranged_equity`, `canonical_key`, `bump_equity_stats`) |
| `scripts/equity_worker.py` | 캐시 채우기 워커 |
| `scripts/grind.py` | 워커 + 아레나 동시 실행(`sys.executable`로 서브프로세스 — pypy3로 띄우면 둘 다 PyPy) |
| `equity_cache` / `equity_cache_stats` / `worker_meta` | 캐시 / 요약 통계 / 스윕 커서 (컬럼 원본 `db/schema.py`) |

### 운영 방법
```bash
pypy3 scripts/equity_worker.py                   # 무한 실행(Ctrl+C 안전), 장시간은 PyPy 권장(약 3.7배)
pypy3 scripts/equity_worker.py --minutes 30      # 시간 제한
python3 scripts/equity_worker.py --workers 1     # 순차(회귀 대조·디버깅)
pypy3 scripts/equity_worker.py --preflop-first   # 프리플랍 샘플부터
python3 scripts/equity_worker.py --status        # 현황(즉시)
python3 scripts/equity_worker.py --rebuild-stats # 통계 백필·복구
```

## 알려진 한계

- equity_cache는 상한 없이 커진다(플랍 스윕이 무한 작업). DB 15GB의 대부분으로 추정 — D-12, E-1
- vs_random은 상대가 아무 핸드나 든다는 가정이라 3벳팟 등에서 과대평가 — 봇은 어그레션 마진으로 보정(ADR 0015), 근본 해결은 E-2
- 병렬/순차 결과 일치, 증분 통계 드리프트 없음은 1회 수동 검증뿐 — 테스트 없음
