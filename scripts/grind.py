#!/usr/bin/env python3
"""
그라인드 모드 — 봇 대결(아레나)을 새 시드로 무한 반복

아레나는 한 라운드(--hands-per-run) 끝날 때마다 새 시드로 다시 시작한다.
아레나는 DB에 핸드를 기록하지 않는다(ADR 0051) — 콘솔 출력(bb/100)만 남는다.
에퀴티 캐시와 그것을 채우던 워커는 폐기됐다(ADR 0034).

사용법:
  python3 scripts/grind.py                      # 무한 실행 (Ctrl+C 안전 종료)
  python3 scripts/grind.py --minutes 60         # 1시간만
  python3 scripts/grind.py --seats hard,hard,medium,legacy --hands-per-run 300
"""

import argparse
import os
import random
import signal
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from db.connection import check_db_size_guard, DEFAULT_MAX_DB_GB

_stop = threading.Event()


def _stream(proc, tag):
    """자식 프로세스 출력에 태그 붙여 릴레이"""
    try:
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                print(f"[{tag}] {line}", flush=True)
    except (ValueError, OSError):
        pass  # 파이프 닫힘


def _spawn(args, tag):
    proc = subprocess.Popen(
        [sys.executable, "-u"] + args,
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    t = threading.Thread(target=_stream, args=(proc, tag), daemon=True)
    t.start()
    return proc


def _arena_loop(seats: str, hands_per_run: int):
    """아레나를 새 시드로 무한 반복 실행"""
    run = 0
    while not _stop.is_set():
        run += 1
        seed = random.randrange(1, 10**9)
        print(f"[그라인드] 아레나 라운드 {run} 시작 (seed={seed})", flush=True)
        proc = _spawn(
            ["scripts/bot_arena.py", "--hands", str(hands_per_run),
             "--seats", seats, "--seed", str(seed)],
            "아레나",
        )
        while proc.poll() is None:
            if _stop.is_set():
                proc.send_signal(signal.SIGINT)
                proc.wait(timeout=10)
                return
            time.sleep(0.5)


def main():
    parser = argparse.ArgumentParser(description="아레나 무한 반복 실행")
    parser.add_argument("--minutes", type=float, default=None, help="실행 시간 제한(분)")
    parser.add_argument("--seats", type=str,
                        default="hard,hard,medium,medium,easy,easy")
    parser.add_argument("--hands-per-run", type=int, default=500)
    parser.add_argument(
        "--max-db-gb", type=float, default=DEFAULT_MAX_DB_GB,
        help=f"DB 파일 크기가 이 값(GB)을 넘으면 시작하지 않음 (기본 {DEFAULT_MAX_DB_GB:g})"
    )
    args = parser.parse_args()

    reason = check_db_size_guard(max_gb=args.max_db_gb)
    if reason:
        print(f"🛑 {reason}")
        sys.exit(1)

    print("그라인드 시작 — Ctrl+C로 안전 종료 (진행분은 모두 DB에 저장됨)\n", flush=True)

    arena_thread = threading.Thread(
        target=_arena_loop, args=(args.seats, args.hands_per_run), daemon=True)
    arena_thread.start()

    deadline = time.time() + args.minutes * 60 if args.minutes else None
    try:
        while arena_thread.is_alive():
            if deadline and time.time() >= deadline:
                print("\n[그라인드] ⏰ 시간 제한 도달 — 종료 중", flush=True)
                break
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[그라인드] ⏸ 중단 요청 — 아레나 정리 중", flush=True)

    _stop.set()
    arena_thread.join(timeout=15)


if __name__ == "__main__":
    main()
