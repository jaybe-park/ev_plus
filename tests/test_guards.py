#!/usr/bin/env python3
"""
테스트 인프라 가드 테스트

- run_all.py의 poker.db 무결성 검사(스냅샷 비교) 로직
- ai/equity.py canonical_key의 중복 카드 입력 검증
- scripts/equity_worker.py · scripts/grind.py가 공유하는 DB 크기 임계치 판정 함수

실행: python3 tests/test_guards.py
"""

import sys
import os
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS_DIR)  # run_all 임포트용
sys.path.insert(0, os.path.dirname(TESTS_DIR))  # 리포 루트 (db, ai 등)

# ── 테스트 격리 ──────────────────────────────────────────
# 이 파일은 실제로 EV_PLUS_DB/poker.db에 쓰지 않지만, 다른 테스트 파일과
# 동일한 관례를 지키기 위해 임포트 시점에 격리해둔다.
os.environ["EV_PLUS_DB"] = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name

import run_all
from core.card import Card, Suit, Rank
from ai.equity import canonical_key
from db.connection import check_db_size_guard, db_size_gb

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


def test_run_all_db_snapshot_guard():
    print("\n[GD-1] run_all — poker.db mtime·size 스냅샷 가드")

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.write(b"0123456789")
    tmp.close()
    path = tmp.name
    try:
        before = run_all.poker_db_snapshot(path)
        after_same = run_all.poker_db_snapshot(path)
        check("변화 없으면 untouched=True",
              run_all.poker_db_untouched(before, after_same))

        # 크기 변경 시뮬레이션
        with open(path, "ab") as f:
            f.write(b"more bytes")
        after_grown = run_all.poker_db_snapshot(path)
        check("크기가 바뀌면 untouched=False",
              not run_all.poker_db_untouched(before, after_grown),
              f"before={before} after={after_grown}")

        # mtime만 바뀌어도(같은 크기) 감지
        os.utime(path, (before[0] / 1e9 + 100, before[0] / 1e9 + 100))
        after_touched = run_all.poker_db_snapshot(path)
        check("mtime만 바뀌어도 untouched=False",
              not run_all.poker_db_untouched(before, after_touched),
              f"before={before} after={after_touched}")

        # 파일이 아예 없는 두 경우는 둘 다 None → untouched=True(신규 환경)
        check("둘 다 미존재(None) → untouched=True",
              run_all.poker_db_untouched(None, None))
    finally:
        os.remove(path)

    check("FAST_FILES에 신규 가드 파일 등록됨",
          "test_guards.py" in run_all.FAST_FILES, f"={run_all.FAST_FILES}")
    check("FULL_FILES에 신규 가드 파일 등록됨",
          "test_guards.py" in run_all.FULL_FILES, f"={run_all.FULL_FILES}")


def test_db_size_guard():
    print("\n[GD-2] equity_worker/grind 공용 DB 크기 임계치 가드")

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.write(b"x" * (2 * 1024 * 1024))  # 2MB
    tmp.close()
    path = tmp.name
    try:
        size_gb = db_size_gb(path)
        check("db_size_gb가 파일 크기를 GB로 반환", 0.0018 < size_gb < 0.0021,
              f"={size_gb}")

        reason = check_db_size_guard(path, max_gb=1.0)
        check("임계치 이내면 None(통과)", reason is None, f"={reason}")

        reason = check_db_size_guard(path, max_gb=0.001)
        check("임계치 초과면 이유 문자열 반환", reason is not None and "임계치" in reason,
              f"={reason}")

        # 기본 임계치(20GB) 확인 — 2MB짜리는 당연히 통과
        reason_default = check_db_size_guard(path)
        check("기본 임계치(20GB) 통과", reason_default is None, f"={reason_default}")

        # 파일이 없는 경로는 크기 0 → 항상 통과
        check("미존재 경로는 크기 0", db_size_gb("/no/such/path.db") == 0.0)
    finally:
        os.remove(path)


def test_canonical_key_duplicate_cards():
    print("\n[GD-3] canonical_key — 카드 중복 입력 검증")
    Ah = Card(Rank.ACE, Suit.HEARTS)
    Kd = Card(Rank.KING, Suit.DIAMONDS)
    Qs = Card(Rank.QUEEN, Suit.SPADES)

    # 정상 입력은 예외 없음
    try:
        canonical_key([Ah, Kd], [Qs])
        check("정상 입력은 통과", True)
    except ValueError as e:
        check("정상 입력은 통과", False, f"예상치 못한 ValueError: {e}")

    # 홀카드끼리 중복
    try:
        canonical_key([Ah, Ah], [])
        check("홀카드 중복 → ValueError", False)
    except ValueError:
        check("홀카드 중복 → ValueError", True)

    # 홀카드-보드 중복
    try:
        canonical_key([Ah, Kd], [Ah, Qs, Kd])
        check("홀-보드 중복 → ValueError", False)
    except ValueError:
        check("홀-보드 중복 → ValueError", True)

    # 보드끼리 중복
    try:
        canonical_key([Ah, Kd], [Qs, Qs])
        check("보드 내부 중복 → ValueError", False)
    except ValueError:
        check("보드 내부 중복 → ValueError", True)


if __name__ == "__main__":
    print("=" * 50)
    print("  테스트 인프라 가드 테스트")
    print("=" * 50)

    test_run_all_db_snapshot_guard()
    test_db_size_guard()
    test_canonical_key_duplicate_cards()

    print(f"\n{'='*50}")
    print(f"  결과: {PASS} 통과 / {FAIL} 실패")
    print(f"{'='*50}")
    sys.exit(1 if FAIL else 0)
