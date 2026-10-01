# 0051. RL용 기록(players_state·equity·reward) 중단과 삭제 — 아레나는 기록하지 않는다 (옛 D-31)

- 상태: 유효
- 날짜: 2026-10-02 · 결정자: jaybe-park (DECISIONS D-31, 2026-10-01 리뷰 RC5)

## 맥락
- 액션 테이블(`preflop_actions`·`postflop_actions`)의 RL용 컬럼 `players_state`(결정 직전 전원 상태
  JSON)·`equity`(봇·사람 판정 에퀴티)·`reward`(핸드 종료 후 역산 손익)와 postflop `state_vector`(항상
  비어 있음)를 읽는 코드가 하나도 없다. 조회 계층(`db/queries.py`)은 이미 삭제됐다.
- 이 컬럼들이 DB 2.1GB 중 약 1.6GB(`players_state`만 약 1.2GB)이고, 그라인드를 돌릴 때마다 커졌다.
- 아레나(`scripts/bot_arena.py`)가 `WebGameSession`을 쓰면서 봇이 모는 Seat0을 사람 좌석(`is_human=1`)으로
  기록해, 265,029게임 중 241,015게임이 "사람 참여"로 남았다(실제 사람 핸드는 약 155). 그래서 ADR 0031의
  "사람 참여 핸드는 보존, 봇 전용은 아카이브" 분류가 데이터로는 불가능했다.
- 감독자 판단: RL 학습 계획이 없고, 이 데이터는 가치가 없다.

## 결정
- 기록기(`db/recorder.py`)는 `players_state`·`equity`·`reward`를 더 쓰지 않는다(매개변수·INSERT 컬럼·
  reward 역산 UPDATE 제거). 핸드·액션 기록 자체(games, 액션의 액션·금액·포지션·`bot_profile`·GTO 빈도)는
  통계(T-004)용으로 유지한다.
- 스키마 v15: 두 액션 테이블에서 위 컬럼(postflop은 `state_vector` 포함)을 `ALTER TABLE … DROP COLUMN`으로
  삭제한다. 신규 DB DDL에서도 뺐다. 지운 페이지는 `scripts/vacuum_db.py --apply`(VACUUM)로 회수한다.
- `WebGameSession(record=True)` 인자를 두고, 아레나(그것을 쓰는 grind·tune_bot·ai_regression 포함)는
  `record=False`로 세션을 만든다 — 봇 전용 핸드는 DB에 쌓지 않는다. 앞으로 쌓이는 games는 사람이 앉은
  웹 세션 핸드뿐이다.

## 버린 대안
- 압축 보관(JSON을 gzip BLOB으로) — 읽는 코드가 없는 데이터를 작게 들고 있는 것일 뿐이다.
- 아카이브 테이블/파일(Parquet·JSONL.gz)로 내보낸 뒤 삭제 — RL 계획이 없어 내보낸 파일도 읽을 사람이 없다.
- 기록 중단만 하고 기존 데이터는 둠 — 1.6GB가 백업·복사 비용으로 계속 남는다.

## 결과
- 영향받는 spec: `docs/spec/db.md`(기록 흐름·스키마 15·보존), `docs/spec/bot.md`(기록 equity 행 삭제)
- ADR 0031: 아레나가 기록하지 않으므로 이후 데이터의 "사람 참여" 분류가 맞게 된다. 이미 쌓인 아레나 games
  행(`is_human=1`로 잘못 표시된 약 24만 게임)은 이 결정으로 지우지 않았다.
- 강제 장치: `tests/test_poker_full.py::test_7_23_migration_v15_drops_rl_columns`(v14→v15 컬럼 삭제·데이터
  보존·신규 DB에 컬럼 없음), `::test_7_24_record_false_session_writes_nothing`(record=False·`run_arena`는
  games 0행, 기록 행에 RL 컬럼 없음), `::test_7_25_vacuum_db_dry_run_and_apply`(dry-run 무변경, apply 회수)
