#!/usr/bin/env python3
"""
프리플랍 에퀴티 상수 테이블 추출 (ADR 0034, T-036)

폐기된 `equity_cache`에 100만 샘플씩 쌓여 있던 프리플랍 845값
(169핸드 × 상대 1~5명)을 코드 상수 모듈 `ai/preflop_equity_table.py`로 옮긴다.
원천 DB는 **읽기 전용**(`?immutable=1&mode=ro` URI)으로만 연다 — 원천 파일에는
아무것도 쓰지 않는다. 결과는 파이썬 모듈 파일 하나이며 DB가 아니다.

사용법:
  python3 scripts/export_preflop_equity.py --source /path/to/poker.db.old-15gb --dry-run
  python3 scripts/export_preflop_equity.py --source /path/to/poker.db.old-15gb

  --source   equity_cache 테이블이 남아 있는 옛 DB 경로 (필수)
  --out      출력 모듈 경로 (기본: ai/preflop_equity_table.py)
  --dry-run  검증·요약만 출력하고 파일을 쓰지 않는다
"""

import argparse
import os
import sqlite3
import sys
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(ROOT, "ai", "preflop_equity_table.py")

# 옛 canonical_key의 랭크 코드(2~9, a=T … e=A) → 표기 문자
_CODE_TO_CHAR = {"2": "2", "3": "3", "4": "4", "5": "5", "6": "6", "7": "7", "8": "8",
                 "9": "9", "a": "T", "b": "J", "c": "Q", "d": "K", "e": "A"}
_ORDER = "23456789TJQKA"

# 알려진 기준값(vs1·vs5) — 추출 결과가 이 범위를 벗어나면 원천이 잘못된 것
_SANITY = {("AA", 1): 0.852, ("AKs", 1): 0.670, ("72o", 1): 0.346, ("AA", 5): 0.492}
_SANITY_TOL = 0.002


def notation_of(hole_key: str) -> str:
    """옛 canonical 홀 키(예: 'e1e0', 'e0d0', 'e1d0') → 'AA' / 'AKs' / 'AKo'."""
    if len(hole_key) != 4:
        raise ValueError(f"프리플랍 홀 키 형식 오류: {hole_key!r}")
    r1, s1, r2, s2 = hole_key[0], hole_key[1], hole_key[2], hole_key[3]
    c1, c2 = _CODE_TO_CHAR[r1], _CODE_TO_CHAR[r2]
    if _ORDER.index(c1) < _ORDER.index(c2):
        c1, c2 = c2, c1
    if c1 == c2:
        return c1 + c2
    return c1 + c2 + ("s" if s1 == s2 else "o")


def read_rows(source: str):
    uri = "file:" + urllib.parse.quote(os.path.abspath(source)) + "?immutable=1&mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        # 부분 인덱스 idx_equity_preflop_pending(WHERE exact=0 AND street='preflop')를
        # 타도록 같은 조건을 쓴다 — 1억 4천만 행 풀스캔 회피. 프리플랍은 MC 누적이라 전부 exact=0.
        rows = conn.execute(
            "SELECT spot_key, num_opponents, wins, ties, total FROM equity_cache "
            "WHERE exact = 0 AND street = 'preflop'"
        ).fetchall()
    finally:
        conn.close()
    return rows


def build_table(rows):
    table = {}
    samples = []
    for spot_key, n_opp, wins, ties, total in rows:
        hole_key = spot_key.split("|")[0]
        note = notation_of(hole_key)
        if not (1 <= n_opp <= 5):
            raise ValueError(f"상대 수 범위 밖: {n_opp}")
        if total <= 0:
            raise ValueError(f"샘플 0인 행: {spot_key} vs{n_opp}")
        if (note, n_opp) in table:
            raise ValueError(f"중복 행: {note} vs{n_opp}")
        table[(note, n_opp)] = (wins + 0.5 * ties) / total
        samples.append(total)
    notes = {n for n, _ in table}
    if len(notes) != 169 or len(table) != 845:
        raise ValueError(f"845값이 아님: 핸드 {len(notes)}종, 값 {len(table)}개")
    for (note, n_opp), expect in _SANITY.items():
        got = table[(note, n_opp)]
        if abs(got - expect) > _SANITY_TOL:
            raise ValueError(f"기준값 불일치: {note} vs{n_opp} = {got:.4f} (기대 {expect})")
    return table, min(samples)


def _sort_key(note: str):
    hi, lo = _ORDER.index(note[0]), _ORDER.index(note[1])
    kind = 0 if hi == lo else (1 if note.endswith("s") else 2)
    return (-hi, kind, -lo)


def render(table, min_samples: int, source: str) -> str:
    notes = sorted({n for n, _ in table}, key=_sort_key)
    lines = [
        '"""',
        "프리플랍 vs 랜덤 핸드 에퀴티 상수 테이블 — 자동 생성, 수동 편집 금지",
        "",
        "생성: python3 scripts/export_preflop_equity.py --source <옛 poker.db>",
        f"원천: 폐기된 equity_cache 프리플랍 845행 ({os.path.basename(source)}, 읽기 전용)",
        f"샘플: 값마다 {min_samples:,}회 이상 MC (표준오차 ≤ 0.05%p)",
        "",
        "PREFLOP_EQUITY[표기] = (vs1, vs2, vs3, vs4, vs5) — 표기는 'AA'/'AKs'/'AKo'.",
        "vs2 이상은 멀티웨이 동률을 1/2로 세던 시절(T-032 이전) 계산이라 동률 과대분",
        "(+0.05~0.15%p)이 섞여 있다 — 정밀도 목표 ±1%p(ADR 0045) 안이라 그대로 쓴다.",
        '"""',
        "",
        f"PREFLOP_SAMPLES = {min_samples}",
        "",
        "PREFLOP_EQUITY = {",
    ]
    for note in notes:
        vals = ", ".join(f"{table[(note, k)]:.6f}" for k in range(1, 6))
        lines.append(f'    "{note}": ({vals}),')
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="프리플랍 에퀴티 845값 상수 모듈 추출")
    ap.add_argument("--source", required=True, help="equity_cache가 남아 있는 옛 DB (읽기 전용)")
    ap.add_argument("--out", default=DEFAULT_OUT, help="출력 모듈 경로")
    ap.add_argument("--dry-run", action="store_true", help="검증·요약만, 파일 쓰기 없음")
    args = ap.parse_args()

    if not os.path.exists(args.source):
        print(f"원천 DB 없음: {args.source}")
        sys.exit(1)

    table, min_samples = build_table(read_rows(args.source))
    print(f"845값 추출 완료 (최소 샘플 {min_samples:,})")
    for (note, n_opp) in _SANITY:
        print(f"  {note} vs{n_opp} = {table[(note, n_opp)]:.4f}")

    if args.dry_run:
        print(f"[dry-run] {args.out}에 쓰지 않음")
        return
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(render(table, min_samples, args.source))
    print(f"저장: {args.out}")


if __name__ == "__main__":
    main()
