"""
PreToolUse(Bash) hook — 에이전트가 위험한 명령을 실행하기 전에 차단한다.

규약: stdin JSON의 tool_input.command 검사 → 차단은 exit 2 + stderr 이유, 통과는 exit 0.
차단 목록은 이 프로젝트의 규칙·사고 이력에서 채운다(docs/decisions/ 0001·0033 참고).
같은 종류 사고가 두 번 나면 여기에 추가한다.
"""

import json
import re
import subprocess
import sys

# (패턴, 이유) — 명령 문자열만으로 판단
BLOCK = [
    (r"\bgit\s+add\s+(-A|--all|\.)(\s|$)",
     "전체 add 금지 — 바꾼 파일만 `git add -- <경로>`로 지정한다"),
    (r"\bgit\s+commit\b[^\n]*\s-a\b|\bgit\s+commit\s+-am\b",
     "commit -a 금지 — 바꾼 파일만 경로 지정 add 후 커밋한다"),
    (r"(?i)\bsqlite3\b[^\n]*poker\.db[^\n]*\b(DELETE|UPDATE|DROP|TRUNCATE|ALTER|INSERT|VACUUM)\b",
     "운영 DB(poker.db) 직접 쓰기 금지 — --dry-run을 지원하는 스크립트로만 쓴다"),
    (r"(?i)\bpython3?\s+-c\b[^\n]*poker\.db[^\n]*\b(DELETE|UPDATE|DROP|TRUNCATE|ALTER|INSERT)\b",
     "운영 DB(poker.db) 인라인 쓰기 금지 — --dry-run을 지원하는 스크립트로만 쓴다"),
]

# 동시 실행 금지 조합 — (실행하려는 스크립트, 이미 떠 있으면 안 되는 스크립트들, 이유)
# 그라인드·튜닝·GTO 수집은 서로(같은 것 2개 포함) 동시에 돌리지 않는다 — CPU/DB 경합,
# 수집기는 체크포인트 파일도 하나뿐이다.
_HEAVY = ["scripts/grind.py", "scripts/tune_bot.py", "scripts/collect_gto_tree.py"]
EXCLUSIVE = [
    ("scripts/grind.py", _HEAVY, "그라인드는 튜닝·수집·다른 그라인드와 동시 실행 금지 — CPU/DB 경합"),
    ("scripts/tune_bot.py", _HEAVY, "튜닝은 그라인드·수집·다른 튜닝과 동시 실행 금지 — CPU/DB 경합"),
    ("scripts/collect_gto_tree.py", _HEAVY,
     "GTO 수집은 그라인드·튜닝·다른 수집과 동시 실행 금지 — DB 경합·체크포인트 하나"),
]
# 이 옵션이 붙으면 조회 전용이라 동시 실행 검사 대상이 아니다
READ_ONLY_FLAGS = ("--status", "--help", "-h")


def running_commands() -> list[str]:
    try:
        out = subprocess.run(["ps", "-Ao", "command"], capture_output=True, text=True, timeout=5)
        return out.stdout.splitlines()[1:]
    except Exception:
        return []


def check(cmd: str) -> str | None:
    for pattern, reason in BLOCK:
        if re.search(pattern, cmd):
            return reason
    if any(flag in cmd.split() for flag in READ_ONLY_FLAGS):
        return None
    for target, conflicts, reason in EXCLUSIVE:
        if target in cmd:
            procs = running_commands()
            for c in conflicts:
                if any(c in p and "block_dangerous" not in p for p in procs):
                    return f"{reason} (실행 중: {c})"
    return None


def main() -> None:
    try:
        cmd = json.load(sys.stdin).get("tool_input", {}).get("command", "") or ""
    except Exception:
        sys.exit(0)
    reason = check(cmd)
    if reason:
        print(f"차단: {reason}", file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
