# 0050. 운영 DB를 에퀴티 캐시를 뺀 슬림 사본으로 교체하고 15GB 원본은 삭제한다 (옛 D-15)

- 상태: 유효
- 날짜: 2026-09-26 결정(DECISIONS D-15, 커밋 6026fe1) · 2026-10-01 ADR로 기록 · 결정자: jaybe-park

## 맥락
에퀴티 캐시 폐기([0034](0034-abolish-equity-cache.md)) 뒤에도 `poker.db`는 15GB였고 그중 85%가
`equity_cache`였다. 백업 파일 `poker.db.pre-gto-wipe-backup`(2026-07-12)도 같은 크기였다. 데이터
삭제라 사람 결정이 필요했는데, 결정이 DECISIONS 항목과 커밋 메시지에만 남아 spec·코드 주석이
"D-15"라는 사라진 번호를 참조하고 있었다.

## 결정
- `scripts/slim_db.py`로 `equity_cache`·`worker_meta`를 뺀 사본을 만들어 행 수 대조·`integrity_check`
  뒤 `poker.db`로 교체했다(2.1GB). 원본 15GB와 2026-07-12 백업은 삭제했다.
- 원본에만 있던 행은 테스트 격리 누수로 생긴 봇 전용 2핸드뿐이라 버렸다.
- 슬림 스크립트는 일회성 도구라 역할이 끝나면 삭제한다(ADR이 이력을 대신한다).

## 버린 대안
- 원본을 보관 — 15GB 두 벌을 둘 이유(재계산 가능한 캐시)가 없다.
- `DELETE` + `VACUUM` 제자리 정리 — 15GB 풀스캔·임시 공간이 필요하고 실패 시 복구가 어렵다.

## 결과
- 영향받는 spec: `docs/spec/db.md`
- 강제 장치: 없음(완료된 일회성 작업). 운영 DB 무결성은 `tests/run_all.py`의 (mtime, size) 스냅샷 가드가 지킨다.
