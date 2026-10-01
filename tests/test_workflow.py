#!/usr/bin/env python3
"""
작업 흐름 강제 장치 테스트 — Claude Code hook(.claude/hooks/block_dangerous.py)

실행: python3 tests/test_workflow.py
"""

import importlib.util
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, ".claude", "hooks", "block_dangerous.py")

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


def run_hook(command: str) -> tuple[int, str]:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    proc = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True)
    return proc.returncode, proc.stderr


def load_hook_module():
    spec = importlib.util.spec_from_file_location("block_dangerous", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_block_patterns():
    print("\n[W-1] 명령 패턴 차단 (종료 코드 2 + stderr 이유)")
    for cmd in ["git add -A", "git add .", "git add --all", "git commit -am 'x'",
                "sqlite3 poker.db \"DELETE FROM gto_preflop_situations\"",
                "python3 -c \"import sqlite3; sqlite3.connect('poker.db').execute('drop table x')\""]:
        code, err = run_hook(cmd)
        check(f"차단: {cmd}", code == 2 and "차단" in err, f"code={code}")
    for cmd in ["git add -- TODO.md", "git add docs/spec/gto-preflop.md", "git status",
                "git commit -m 'fix' -m 'body'", "python3 tests/run_all.py",
                "sqlite3 poker.db \"SELECT COUNT(*) FROM games\""]:
        code, _ = run_hook(cmd)
        check(f"통과: {cmd}", code == 0, f"code={code}")


def test_bad_input_passes():
    print("\n[W-2] 입력이 깨져도 hook이 명령을 막지 않는다")
    proc = subprocess.run([sys.executable, HOOK], input="not json", capture_output=True, text=True)
    check("깨진 JSON → 통과", proc.returncode == 0, f"code={proc.returncode}")


def test_exclusive_runs():
    print("\n[W-3] 동시 실행 금지 조합")
    mod = load_hook_module()

    mod.running_commands = lambda: ["pypy3 scripts/grind.py"]
    check("그라인드 중 튜닝 차단", mod.check("python3 scripts/tune_bot.py --hands 10") is not None)
    check("그라인드 중 GTO 수집 차단", mod.check("python3 scripts/collect_gto_tree.py --limit 5") is not None)
    check("그라인드 중 그라인드 2개째 차단", mod.check("pypy3 scripts/grind.py") is not None)
    check("그라인드 중 수집 --help 허용", mod.check("python3 scripts/collect_gto_tree.py --help") is None)
    check("그라인드 중 다른 스크립트 허용", mod.check("python3 scripts/audit_gto_preflop.py") is None)

    mod.running_commands = lambda: ["python3 scripts/collect_gto_tree.py --limit 90"]
    check("수집 중 그라인드 차단", mod.check("pypy3 scripts/grind.py") is not None)
    check("수집 중 튜닝 차단", mod.check("python3 scripts/tune_bot.py") is not None)
    check("수집 중 수집 2개째 차단", mod.check("python3 scripts/collect_gto_tree.py") is not None)

    mod.running_commands = lambda: ["python3 scripts/tune_bot.py --hands 10"]
    check("튜닝 중 그라인드 차단", mod.check("pypy3 scripts/grind.py") is not None)

    check("폐기된 에퀴티 워커 규칙 없음",
          all("equity_worker" not in t and not any("equity_worker" in c for c in cs)
              for t, cs, _ in mod.EXCLUSIVE), str(mod.EXCLUSIVE))

    mod.running_commands = lambda: []
    check("아무것도 안 돌 때 그라인드 허용", mod.check("pypy3 scripts/grind.py") is None)
    check("아무것도 안 돌 때 수집 허용", mod.check("python3 scripts/collect_gto_tree.py") is None)


def test_hook_registered():
    print("\n[W-4] hook이 settings.json에 등록돼 있다")
    with open(os.path.join(ROOT, ".claude", "settings.json")) as f:
        settings = json.load(f)
    entries = settings.get("hooks", {}).get("PreToolUse", [])
    cmds = [h.get("command", "") for e in entries if e.get("matcher") == "Bash" for h in e.get("hooks", [])]
    check("PreToolUse/Bash에 block_dangerous.py", any("block_dangerous.py" in c for c in cmds), f"{cmds}")


if __name__ == "__main__":
    print("=" * 50)
    print("  작업 흐름 강제 장치 테스트")
    print("=" * 50)

    test_block_patterns()
    test_bad_input_passes()
    test_exclusive_runs()
    test_hook_registered()

    print(f"\n{'='*50}")
    print(f"  결과: {PASS} 통과 / {FAIL} 실패")
    print(f"{'='*50}")
    sys.exit(1 if FAIL else 0)
