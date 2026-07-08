"""
테스트 러너 — 여러 테스트 파일을 순차 실행하고 통합 요약을 출력한다.

사용법:
    python3 tests/run_all.py            # --fast와 동일 (기본값)
    python3 tests/run_all.py --fast     # test_poker_full.py만 (로직 검증, 수초)
    python3 tests/run_all.py --full     # test_poker_full.py + test_equity.py

각 파일은 subprocess로 실행하며, 표준출력을 실시간으로 그대로 릴레이한다
(자식 프로세스의 print(flush=True) 덕분에 버퍼링 없이 즉시 보임).
마지막에 파일별 통과/실패와 총 소요 시간을 요약하고,
하나라도 실패하면 exit code 1을 반환한다.
"""

import subprocess
import sys
import time
import os

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

FAST_FILES = ["test_poker_full.py"]
FULL_FILES = ["test_poker_full.py", "test_equity.py", "test_grader.py"]


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

    suite_start = time.perf_counter()
    results: list[tuple[str, bool, float]] = []
    for filename in files:
        ok, elapsed = run_file(filename)
        results.append((filename, ok, elapsed))
    total_elapsed = time.perf_counter() - suite_start

    print("\n" + "═" * 60, flush=True)
    print("  통합 요약", flush=True)
    print("═" * 60, flush=True)
    for filename, ok, elapsed in results:
        icon = "✅" if ok else "❌"
        print(f"  {icon} {filename}  ({elapsed:.2f}s)", flush=True)
    print(f"\n  총 소요 시간: {total_elapsed:.2f}s", flush=True)
    print("═" * 60, flush=True)

    if any(not ok for _, ok, _ in results):
        print("\n  ⚠️ 실패한 테스트 파일이 있습니다.", flush=True)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
