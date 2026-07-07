#!/usr/bin/env python3
"""
그라인드 모드 — 아레나(실전 스팟 생산) + 워커(정확값 계산) 동시 실행

아레나가 실전 빈도대로 equity_cache 큐를 채우고,
워커가 그 스팟들을 리버→턴→플랍 순으로 전수조사한다.
아레나는 한 라운드(--hands-per-run) 끝날 때마다 새 시드로 무한 반복.

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
    parser = argparse.ArgumentParser(description="아레나 + 워커 동시 실행")
    parser.add_argument("--minutes", type=float, default=None, help="실행 시간 제한(분)")
    parser.add_argument("--seats", type=str,
                        default="hard,hard,medium,medium,easy,easy")
    parser.add_argument("--hands-per-run", type=int, default=500)
    args = parser.parse_args()

    print("그라인드 시작 — Ctrl+C로 안전 종료 (진행분은 모두 DB에 저장됨)\n", flush=True)

    worker = _spawn(["scripts/equity_worker.py"], "워커")
    arena_thread = threading.Thread(
        target=_arena_loop, args=(args.seats, args.hands_per_run), daemon=True)
    arena_thread.start()

    deadline = time.time() + args.minutes * 60 if args.minutes else None
    try:
        while True:
            if deadline and time.time() >= deadline:
                print("\n[그라인드] ⏰ 시간 제한 도달 — 종료 중", flush=True)
                break
            if worker.poll() is not None:
                # 워커가 스스로 끝나는 일은 사실상 없음 (스윕이 무한) — 재시작
                print("[그라인드] 워커 재시작", flush=True)
                worker = _spawn(["scripts/equity_worker.py"], "워커")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[그라인드] ⏸ 중단 요청 — 자식 프로세스 정리 중", flush=True)

    _stop.set()
    worker.send_signal(signal.SIGINT)
    arena_thread.join(timeout=15)
    try:
        worker.wait(timeout=10)
    except subprocess.TimeoutExpired:
        worker.kill()

    # 최종 현황
    subprocess.run([sys.executable, "scripts/equity_worker.py", "--status"], cwd=ROOT)


if __name__ == "__main__":
    main()
