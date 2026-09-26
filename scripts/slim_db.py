#!/usr/bin/env python3
"""
poker.db 슬림 사본 생성 스크립트

배경: ADR 0034(에퀴티 캐시 폐기)로 `equity_cache`(1억 4천만 행, ~12.7GB)가
더 이상 쓰이지 않는다. SQLite는 freelist가 0이면 행을 지워도 VACUUM 없이는
파일이 줄지 않으므로(DECISIONS D-15), 폐기 테이블을 뺀 새 파일을 만들고
사람이 원본·백업 파일을 확인 후 직접 삭제하는 방식을 택한다(D-15 옵션 D).

이 스크립트는 **운영 DB(`--src`)를 읽기 전용으로만 연다.** 원본을 지우거나
바꾸는 동작은 전혀 하지 않으며, 그런 판단은 사람이 한다.

사용법:
    python3 scripts/slim_db.py --dry-run                 # 무엇이 남고 빠지는지만 확인
    python3 scripts/slim_db.py                            # poker.db.slim 생성
    python3 scripts/slim_db.py --src A.db --dst B.db.slim --exclude t1,t2

인자:
    --src       원본 DB 경로 (기본: <repo>/poker.db)
    --dst       슬림 사본 경로 (기본: <repo>/poker.db.slim)
    --dry-run   아무것도 쓰지 않고 테이블/행 수만 보고
    --exclude   제외할 테이블 이름(콤마 구분, 기본: equity_cache,equity_cache_stats,worker_meta)
"""

import argparse
import os
import sqlite3
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SRC = os.path.join(REPO_ROOT, "poker.db")
DEFAULT_DST = os.path.join(REPO_ROOT, "poker.db.slim")
DEFAULT_EXCLUDE = "equity_cache,equity_cache_stats,worker_meta"


def open_readonly(path: str) -> sqlite3.Connection:
    """운영 DB를 읽기 전용으로 연다. immutable은 쓰지 않는다 —
    WAL 파일이 있으면(체크포인트 안 된 최신 데이터) 그걸 봐야 하기 때문이다."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"원본 DB가 없습니다: {path}")
    uri = f"file:{os.path.abspath(path)}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def list_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()
    return [r["name"] for r in rows]


def estimate_row_count(conn: sqlite3.Connection, table: str) -> int:
    """제외 테이블은 전수 COUNT(*)가 비싸므로(equity_cache ~1.4억 행)
    max(rowid)로 저렴하게 추정한다."""
    try:
        row = conn.execute(f"SELECT MAX(rowid) AS m FROM \"{table}\"").fetchone()
        return row["m"] or 0
    except sqlite3.Error:
        return -1


def exact_row_count(conn: sqlite3.Connection, table: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) AS c FROM \"{table}\"").fetchone()
    return row["c"]


def try_dbstat_size(conn: sqlite3.Connection, tables: list[str]) -> dict | None:
    """dbstat 가상 테이블로 테이블별 대략적 크기(바이트)를 구한다.
    컴파일에 포함 안 돼 있으면 None을 반환하고 건너뛴다."""
    try:
        placeholders = ",".join("?" for _ in tables)
        rows = conn.execute(
            f"SELECT name, SUM(pgsize) AS sz FROM dbstat "
            f"WHERE name IN ({placeholders}) GROUP BY name",
            tables,
        ).fetchall()
        return {r["name"]: r["sz"] for r in rows}
    except sqlite3.Error:
        return None


def do_dry_run(src: str, exclude: set[str]) -> None:
    conn = open_readonly(src)
    tables = list_tables(conn)
    kept = [t for t in tables if t not in exclude]
    excluded = [t for t in tables if t in exclude]

    print(f"원본: {src}")
    print(f"제외 대상: {sorted(exclude)}")
    print()

    sizes = try_dbstat_size(conn, kept)

    print("[유지될 테이블]")
    for t in kept:
        cnt = exact_row_count(conn, t)
        sz = f", 약 {sizes[t]/1024/1024:.1f}MB" if sizes and t in sizes else ""
        print(f"  {t}: {cnt}행{sz}")

    print()
    print("[제외될 테이블] (COUNT(*) 생략, max(rowid) 추정치만)")
    for t in excluded:
        est = estimate_row_count(conn, t)
        print(f"  {t}: 제외 (추정 최대 rowid={est})")

    print()
    print("(dry-run) 아무것도 쓰지 않았습니다.")
    conn.close()


def copy_schema_objects(src_conn: sqlite3.Connection, dst_conn: sqlite3.Connection, kept: set[str]) -> None:
    """kept 테이블에 속하는 CREATE 문(테이블/인덱스/트리거/뷰)을 원본
    sqlite_master에서 그대로 가져와 dst에 실행한다."""
    rows = src_conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' "
        "ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'view' THEN 1 "
        "WHEN 'index' THEN 2 WHEN 'trigger' THEN 3 ELSE 4 END"
    ).fetchall()
    for r in rows:
        if r["tbl_name"] not in kept:
            continue
        dst_conn.execute(r["sql"])


def do_real_run(src: str, dst: str, exclude: set[str]) -> None:
    if os.path.exists(dst):
        raise FileExistsError(f"대상 파일이 이미 있습니다(덮어쓰지 않음): {dst}")

    src_conn = open_readonly(src)
    tables = list_tables(src_conn)
    kept = [t for t in tables if t not in exclude]
    if not kept:
        raise RuntimeError("유지할 테이블이 없습니다 — exclude 설정을 확인하세요.")

    print(f"원본: {src}")
    print(f"대상: {dst}")
    print(f"제외: {sorted(exclude)}")
    print(f"유지: {kept}")

    # 복사 전 원본 행 수 기록(검증용)
    expected_counts = {t: exact_row_count(src_conn, t) for t in kept}

    # ATTACH DATABASE에 file: URI(mode=ro)를 쓰려면 dst 연결도 URI 모드로
    # 열어야 한다(그래야 SQLite가 ATTACH 인자를 URI로 해석한다).
    dst_uri = f"file:{os.path.abspath(dst)}"
    dst_conn = sqlite3.connect(dst_uri, uri=True)
    dst_conn.row_factory = sqlite3.Row
    try:
        copy_schema_objects(src_conn, dst_conn, set(kept))

        # ATTACH로 src를 읽기 전용 연결하여 INSERT...SELECT로 행 복사
        src_uri = f"file:{os.path.abspath(src)}?mode=ro"
        dst_conn.execute("ATTACH DATABASE ? AS src", (src_uri,))
        dst_conn.execute("BEGIN")
        try:
            for t in kept:
                dst_conn.execute(f'INSERT INTO main."{t}" SELECT * FROM src."{t}"')

            # sqlite_sequence: kept 테이블의 AUTOINCREMENT 카운터만 복사
            has_seq = dst_conn.execute(
                "SELECT name FROM sqlite_master WHERE name='sqlite_sequence'"
            ).fetchone()
            if has_seq:
                seq_rows = dst_conn.execute(
                    "SELECT name, seq FROM src.sqlite_sequence"
                ).fetchall()
                for r in seq_rows:
                    if r["name"] in kept:
                        dst_conn.execute(
                            "UPDATE main.sqlite_sequence SET seq=? WHERE name=?",
                            (r["seq"], r["name"]),
                        )

            dst_conn.commit()
        except Exception:
            dst_conn.rollback()
            raise
        finally:
            dst_conn.execute("DETACH DATABASE src")

        # PRAGMA user_version 복사
        user_version = src_conn.execute("PRAGMA user_version").fetchone()[0]
        dst_conn.execute(f"PRAGMA user_version = {int(user_version)}")

        # 검증 1: 행 수 일치
        print()
        print("[검증] 행 수")
        for t in kept:
            actual = exact_row_count(dst_conn, t)
            expected = expected_counts[t]
            status = "OK" if actual == expected else "FAIL"
            print(f"  {t}: 원본={expected} 사본={actual} [{status}]")
            if actual != expected:
                raise RuntimeError(
                    f"행 수 불일치: {t} 원본={expected} 사본={actual}"
                )

        # 검증 2: integrity_check
        integrity = dst_conn.execute("PRAGMA integrity_check").fetchone()[0]
        print(f"[검증] integrity_check: {integrity}")
        if integrity != "ok":
            raise RuntimeError(f"integrity_check 실패: {integrity}")

    finally:
        dst_conn.close()
        src_conn.close()

    size_bytes = os.path.getsize(dst)
    print()
    print(f"완료: {dst} ({size_bytes/1024/1024:.1f}MB)")


def apply_app_migration(dst: str) -> None:
    """앱의 get_connection()으로 dst를 한 번 열어 _migrate가 받아들이는지
    확인한다. 현재 스키마(ADR 0034 이후)는 equity_cache 등 에퀴티 테이블을
    만들지 않으므로 제외한 테이블이 다시 생기지 않는다."""
    sys.path.insert(0, REPO_ROOT)
    from db.connection import get_connection  # noqa: E402

    conn = get_connection(dst)
    tables_after = list_tables(conn)
    conn.close()
    print()
    print("[앱 마이그레이션] db.connection.get_connection()으로 1회 오픈 완료")
    print(f"  오픈 후 테이블 목록: {tables_after}")


def main() -> int:
    parser = argparse.ArgumentParser(description="poker.db 슬림 사본 생성")
    parser.add_argument("--src", default=DEFAULT_SRC)
    parser.add_argument("--dst", default=DEFAULT_DST)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--exclude", default=DEFAULT_EXCLUDE)
    args = parser.parse_args()

    exclude = {t.strip() for t in args.exclude.split(",") if t.strip()}

    start = time.perf_counter()
    if args.dry_run:
        do_dry_run(args.src, exclude)
    else:
        do_real_run(args.src, args.dst, exclude)
        apply_app_migration(args.dst)
    elapsed = time.perf_counter() - start
    print(f"\n소요 시간: {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
