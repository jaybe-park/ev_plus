"""
테스트 러너 — 여러 테스트 파일을 순차 실행하고 통합 요약을 출력한다.

사용법:
    python3 tests/run_all.py            # --fast와 동일 (기본값)
    python3 tests/run_all.py --fast     # FAST_FILES (로직 검증, 수초)
    python3 tests/run_all.py --full     # FULL_FILES (에퀴티·플레이 평가 포함)

각 파일은 subprocess로 실행하며, 표준출력을 실시간으로 그대로 릴레이한다
(자식 프로세스의 print(flush=True) 덕분에 버퍼링 없이 즉시 보임).
마지막에 파일별 통과/실패와 총 소요 시간을 요약하고,
운영 poker.db의 (mtime, size)를 실행 전후로 비교해 바뀌었으면(테스트의
EV_PLUS_DB 격리 누락 신호) 실패로 처리한다. 하나라도 실패하면 exit code 1.
"""

import subprocess
import sys
import time
import os

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TESTS_DIR)
sys.path.insert(0, REPO_ROOT)

from db.connection import _DEFAULT_DB_PATH  # noqa: E402  (sys.path 조작 후 임포트)

FAST_FILES = ["test_poker_full.py", "test_gto_tree.py", "test_guards.py"]
FULL_FILES = ["test_poker_full.py", "test_equity.py", "test_grader.py", "test_gto_tree.py",
              "test_guards.py"]


def poker_db_snapshot(path: str = _DEFAULT_DB_PATH):
    """운영 poker.db의 (mtime, size) 스냅샷. 파일이 없으면 None(신규 환경)."""
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def poker_db_untouched(before, after) -> bool:
    """스냅샷이 같으면(둘 다 None이거나 값이 같으면) 운영 DB가 안 바뀐 것."""
    return before == after


def run_file(filename: str) -> tuple[bool, float]:
    """테스트 파일 하나를 subprocess로 실행하고 (성공여부, 소요시간)을 반환.
    자식 프로세스의 stdout/stderr를 실시간으로 그대로 릴레이한다."""
    path = os.path.join(TESTS_DIR, filename)
    print(f"\n{'#' * 60}", flush=True)
    print(f"# 실행: {filename}", flush=True)
    print(f"{'#' * 60}", flush=True)

    start = time.perf_counter()
    proc = subprocess.run([sys.executable, path])
    elapsed = time.perf_counter() - start

    ok = proc.returncode == 0
    return ok, elapsed


def main():
    args = sys.argv[1:]
    mode = "fast"
    if "--full" in args:
        mode = "full"
    elif "--fast" in args:
        mode = "fast"

    files = FULL_FILES if mode == "full" else FAST_FILES

    print("═" * 60, flush=True)
    print(f"  테스트 러너 — 모드: {mode} ({', '.join(files)})", flush=True)
    print("═" * 60, flush=True)

    db_before = poker_db_snapshot()

    suite_start = time.perf_counter()
    results: list[tuple[str, bool, float]] = []
    for filename in files:
        ok, elapsed = run_file(filename)
        results.append((filename, ok, elapsed))
    total_elapsed = time.perf_counter() - suite_start

    db_after = poker_db_snapshot()
    db_ok = poker_db_untouched(db_before, db_after)

    print("\n" + "═" * 60, flush=True)
    print("  통합 요약", flush=True)
    print("═" * 60, flush=True)
    for filename, ok, elapsed in results:
        icon = "✅" if ok else "❌"
        print(f"  {icon} {filename}  ({elapsed:.2f}s)", flush=True)
    print(f"\n  총 소요 시간: {total_elapsed:.2f}s", flush=True)
    if db_ok:
        print(f"  ✅ 운영 poker.db 무결성 (mtime·size 변화 없음): {_DEFAULT_DB_PATH}", flush=True)
    else:
        print(
            f"  ❌ 운영 poker.db가 테스트 도중 바뀌었습니다: {_DEFAULT_DB_PATH} "
            f"(before={db_before}, after={db_after})",
            flush=True,
        )
    print("═" * 60, flush=True)

    if any(not ok for _, ok, _ in results) or not db_ok:
        if not db_ok:
            print(
                "\n  ⚠️ 테스트가 운영 poker.db에 썼습니다 — EV_PLUS_DB 격리 누락을 의심하세요.",
                flush=True,
            )
        if any(not ok for _, ok, _ in results):
            print("\n  ⚠️ 실패한 테스트 파일이 있습니다.", flush=True)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
