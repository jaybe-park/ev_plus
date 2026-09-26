#!/usr/bin/env python3
"""
프리플랍 GTO 트리 워커(scripts/gto_tree_worker.py, scripts/collect_gto_tree.py)
순수 로직 원칙 테스트 — 브라우저/네트워크 없이 현재 동작을 핀(pin)한다.

배경: /private/tmp/.../scratchpad/gto-findings.md "절대 규칙 중 장치 없는 것" G7~G13.
여기서는 사람 결정이 필요 없는(현재 코드 동작 그대로 검증 가능한) 항목만 구현한다.

실행: python3 tests/test_gto_tree.py
"""

import json
import os
import sys
import tempfile
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

# 테스트 격리: gto_tree_worker.run()이 내부에서 db.connection.get_connection()으로
# 실 DB를 읽으므로(load_collected_from_db), 그라인드 데이터와 격리한다.
os.environ["EV_PLUS_DB"] = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name

PASS = 0
FAIL = 0

_SKIP_BROWSER_DRIVER = False
_SKIP_REASON = ""

try:
    import gto_tree_worker as tw
except Exception as e:  # pragma: no cover - 방어적
    print(f"[치명] gto_tree_worker import 실패: {e}")
    sys.exit(1)

try:
    import collect_gto_tree as ct
except Exception as e:
    # 설계상 collect_gto_tree는 모듈 로드 시점에 playwright를 import하지 않지만
    # (connect_cdp 내부에서 지연 import), 환경에 따라 실패할 수 있어 방어적으로 가드.
    _SKIP_BROWSER_DRIVER = True
    _SKIP_REASON = str(e)
    ct = None


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


# ═════════════════════════════════════════════════════════════
# [T-1] G7 — compute_children: 실측 사이즈 verbatim, 사이즈 없으면 레이즈 자식 없음,
#            action_to_token("raise")는 사이즈 없이 호출하면 ValueError
# ═════════════════════════════════════════════════════════════
def test_compute_children_uses_measured_size():
    hands = {"AA": {"raise": 1.0}, "72o": {"fold": 1.0}}

    children = ct.compute_children("", hands, {"raise": 13.5}, 1.0)
    keys = [k for k, _, _ in children]
    check("측정 사이즈 13.5가 자식 키에 verbatim 포함(R13.5)", "R13.5" in keys, f"={keys}")
    check("fold 자식(F)도 포함", "F" in keys, f"={keys}")

    children_no_size = ct.compute_children("", hands, {"raise": None}, 1.0)
    keys_no_size = [k for k, _, _ in children_no_size]
    check("사이즈 None이면 레이즈 자식 생성 안 함", "R13.5" not in keys_no_size and
          not any(k.startswith("R") for k in keys_no_size), f"={keys_no_size}")
    check("사이즈 없어도 fold 자식은 그대로 있음", "F" in keys_no_size, f"={keys_no_size}")

    try:
        tw.action_to_token("raise")
        check("action_to_token('raise') 사이즈 없이 호출 시 ValueError", False, "예외 발생 안 함")
    except ValueError:
        check("action_to_token('raise') 사이즈 없이 호출 시 ValueError", True)


# ═════════════════════════════════════════════════════════════
# [T-2] G8 — branch_actions: epsilon(0.0005) 컷 + 내림차순 정렬
# ═════════════════════════════════════════════════════════════
def test_branch_actions_epsilon():
    agg = {"fold": 0.0004, "call": 0.0006, "raise": 0.5}
    result = tw.branch_actions(agg)
    actions = [a for a, _ in result]
    check("0.0004(≤ε)은 제외", "fold" not in actions, f"={actions}")
    check("0.0006(>ε)은 포함", "call" in actions, f"={actions}")
    check("빈도 내림차순 정렬(raise 먼저, call 나중)", actions == ["raise", "call"], f"={actions}")


# ═════════════════════════════════════════════════════════════
# [T-3] G9 — _replay: 베팅 종료 판정(결정 노드 아님) + 다음 행동 좌석
# ═════════════════════════════════════════════════════════════
def test_replay_terminal_nodes():
    _, next_actor = ct._replay(["F"] * 5)
    check("전원(UTG~SB) 폴드 → BB만 남아 결정 노드 아님(None)", next_actor is None, f"={next_actor}")

    _, next_actor2 = ct._replay(["R2.5", "F", "F", "F", "F", "F"])
    check("R2.5-F-F-F-F-F(레이저 제외 전원 폴드)는 결정 노드 아님(None)",
          next_actor2 is None, f"={next_actor2}")

    _, next_actor3 = ct._replay(["R2.5", "C"])
    check("R2.5-C 다음 행동자는 CO", ct.POSITIONS[next_actor3] == "CO",
          f"={ct.POSITIONS[next_actor3] if next_actor3 is not None else None}")


# ═════════════════════════════════════════════════════════════
# [T-4] G10 — derive_node_meta: 노드 키 → 라벨/3종 키 결정론적 유도
#             (RFI, vs_open, squeeze/vs_3bet, vs_4bet. 림프 케이스는 결정 보류로 스킵)
# ═════════════════════════════════════════════════════════════
def test_derive_node_meta_labels():
    rfi = ct.derive_node_meta("")
    check("RFI(빈 키) → UTG RFI",
          rfi == {"hero_position": "UTG", "vs_position": None, "range_type": "open",
                  "situation_label": "UTG RFI"},
          f"={rfi}")

    vs_open = ct.derive_node_meta("R2.5")
    check("vs_open(R2.5) → HJ vs UTG open",
          vs_open == {"hero_position": "HJ", "vs_position": "UTG", "range_type": "vs_open",
                      "situation_label": "HJ vs UTG open"},
          f"={vs_open}")

    squeeze = ct.derive_node_meta("R2.5-C-R8")
    check("squeeze/vs_3bet(R2.5-C-R8, HJ 콜드콜 후 CO 3벳) → BTN vs CO 3bet",
          squeeze == {"hero_position": "BTN", "vs_position": "UTG/CO", "range_type": "vs_3bet",
                      "situation_label": "BTN vs CO 3bet"},
          f"={squeeze}")

    vs_4bet = ct.derive_node_meta("R2.5-R8-R20")
    check("vs_4bet(R2.5-R8-R20) → BTN vs CO 4bet",
          vs_4bet == {"hero_position": "BTN", "vs_position": "UTG/HJ/CO",
                      "range_type": "vs_4bet", "situation_label": "BTN vs CO 4bet"},
          f"={vs_4bet}")


# ═════════════════════════════════════════════════════════════
# [T-5] G11 — is_env_failure: 환경 오류(재시도 대상) vs 진짜 데이터 이상(사람 확인 필요) 구분
# ═════════════════════════════════════════════════════════════
def test_env_failure_classification():
    check("'navigate 실패: ...' → 환경 오류", ct.is_env_failure("navigate 실패: 타임아웃"))
    check("'렌더 대기 타임아웃' → 환경 오류", ct.is_env_failure("렌더 대기 타임아웃"))
    check("'badSum 검증 실패(3핸드)' → 데이터 이상(환경 오류 아님)",
          not ct.is_env_failure("badSum 검증 실패(3핸드)"))
    check("'파싱된 핸드 0개' → 데이터 이상(환경 오류 아님)",
          not ct.is_env_failure("파싱된 핸드 0개"))


# ═════════════════════════════════════════════════════════════
# [T-6] G13 — _limit_hit / _parse_usage: 한도 판단은 카운터 우선
# ═════════════════════════════════════════════════════════════
def test_limit_hit_counter_authority():
    # 주의: gto-findings.md 제안 값은 used=99였으나 DAILY_LIMIT=100 기준
    # `used >= DAILY_LIMIT`이 조건이라 99는 미도달(False)이다. 카운터가 한도값
    # 자체에 도달한 100으로 검증한다(제안과 실제 API 확인 후 값 보정, 원칙은 동일).
    check("used=100(카운터=한도) → 한도 도달", ct._limit_hit(100, True, True) is True)
    check("used=50(카운터 신뢰, 경고 문구 무시) → 한도 아님",
          ct._limit_hit(50, True, False) is False)
    check("used=None + 경고문구 + 렌더 실패 → 폴백으로 한도 도달 간주",
          ct._limit_hit(None, True, False) is True)
    check("_parse_usage('... 42/100 ...') == 42", ct._parse_usage("blah 42/100 blah") == 42)


# ═════════════════════════════════════════════════════════════
# [T-7] G12 — run(): 한도 도달 / 환경 오류 / 저장 실패 시 꺼낸 노드를 잃지 않는다
#             (frontier에 되돌리고 visited·failed에는 넣지 않음)
# ═════════════════════════════════════════════════════════════
def _make_args(checkpoint_path, limit=1):
    ap = ct.build_parser()
    return ap.parse_args([
        "--limit", str(limit),
        "--checkpoint", checkpoint_path,
        "--min-delay", "0", "--max-delay", "0",
    ])


def _fresh_checkpoint_path():
    f = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f.close()
    os.unlink(f.name)  # run()이 "체크포인트 없음" 경로(DB에서 시드)를 타도록 파일 자체를 없앤다
    return f.name


def _fake_cdp_handles():
    """connect_cdp가 반환하는 (p, browser, ctx, page) 4종을 흉내낸다.
    page/ctx/browser/p는 run()이 호출하는 메서드(close/stop/new_page 등)만 있으면 된다."""
    page = MagicMock()
    page.inner_text.side_effect = Exception("no body in fake page")  # read_usage → None 유도
    ctx = MagicMock()
    ctx.new_page.return_value = MagicMock()
    browser = MagicMock()
    p = MagicMock()
    return p, browser, ctx, page


def _read_checkpoint(path):
    with open(path) as f:
        return json.load(f)


def test_run_requeues_node_on_limit_and_env_failure():
    if _SKIP_BROWSER_DRIVER:
        print(f"  [스킵] collect_gto_tree import 실패(playwright 등 환경 문제): {_SKIP_REASON}")
        return

    orig_connect_cdp = ct.connect_cdp
    orig_extract_node = ct.extract_node
    orig_save_node = ct.save_node

    # ── 시나리오 A: 일일 한도 도달 → 즉시 중단, 노드는 frontier로 복귀 ──
    try:
        ckpt_path = _fresh_checkpoint_path()
        ct.connect_cdp = lambda cdp_url: _fake_cdp_handles()
        ct.extract_node = lambda page, node_key, nav_timeout: ct.ExtractResult(
            False, reason="일일 한도 도달(사용량 99/100)", limit_hit=True, used=99
        )
        args = _make_args(ckpt_path)
        rc = ct.run(args)
        check("한도 도달 시 run()이 정상 종료(rc=0)", rc == 0, f"rc={rc}")

        data = _read_checkpoint(ckpt_path)
        frontier_keys = ["-".join(f["tokens"]) for f in data["frontier"]]
        check("한도 도달: 루트 노드(RFI, key='')가 frontier에 남아있음",
              "" in frontier_keys, f"frontier={frontier_keys}")
        check("한도 도달: 루트 노드가 visited에는 없음(유실 아님)",
              "" not in data["visited"], f"visited={data['visited']}")
        check("한도 도달: 루트 노드가 failed에도 없음",
              "" not in data["failed"], f"failed={data['failed']}")
    finally:
        os.path.exists(ckpt_path) and os.unlink(ckpt_path)

    # ── 시나리오 B: 연속 환경 오류(크래시/타임아웃) → 임계치 도달 시 안전 중단,
    #    영구 실패(failed) 아니라 frontier로 복귀 ──
    try:
        ckpt_path = _fresh_checkpoint_path()
        ct.connect_cdp = lambda cdp_url: _fake_cdp_handles()
        ct.extract_node = lambda page, node_key, nav_timeout: ct.ExtractResult(
            False, reason="navigate 실패: 네트워크 오류"
        )
        args = _make_args(ckpt_path, limit=90)  # limit은 도달 전에 환경오류 중단이 먼저 걸림
        rc = ct.run(args)
        check("연속 환경오류 시 run()이 정상 종료(rc=0)", rc == 0, f"rc={rc}")

        data = _read_checkpoint(ckpt_path)
        frontier_keys = ["-".join(f["tokens"]) for f in data["frontier"]]
        check("연속 환경오류: 루트 노드가 frontier에 남아있음(재시도 대상)",
              "" in frontier_keys, f"frontier={frontier_keys}")
        check("연속 환경오류: 루트 노드가 failed(영구 no-retry)에는 없음",
              "" not in data["failed"], f"failed={data['failed']}")
        check("연속 환경오류: 루트 노드가 visited에도 없음",
              "" not in data["visited"], f"visited={data['visited']}")
    finally:
        os.path.exists(ckpt_path) and os.unlink(ckpt_path)

    # ── 시나리오 C: 저장 실패(로컬 백엔드 문제) → 노드를 frontier로 되돌린 뒤 재시도.
    #    (참고: save_node가 "항상" 실패하면 현재 코드는 processed 카운터를 되돌리기만
    #     하고 무한정 같은 노드를 재시도하므로 --limit으로 멈추지 않는다 — 실제 버그
    #     가능성. 테스트에서는 첫 시도만 실패시키고 그 시점의 체크포인트 스냅샷을
    #     캡처해 "유실되지 않았음"을 확인한 뒤, 재시도가 성공해 루프가 정상 종료되게
    #     한다.)
    try:
        ckpt_path = _fresh_checkpoint_path()
        ct.connect_cdp = lambda cdp_url: _fake_cdp_handles()
        ct.extract_node = lambda page, node_key, nav_timeout: ct.ExtractResult(
            True, hands={"AA": {"raise": 1.0}, "72o": {"fold": 1.0}}, raise_size=2.5, used=None
        )

        snapshots = []
        orig_ckpt_save = ct.Checkpoint.save

        def recording_save(self, frontier):
            orig_ckpt_save(self, frontier)
            snapshots.append({
                "visited": set(self.visited),
                "failed": list(self.failed),
                "frontier_keys": ["-".join(n.path_tokens) for n in frontier._items],
            })

        ct.Checkpoint.save = recording_save

        calls = {"n": 0}

        def flaky_save_node(server, node_key, meta, hands, raise_size):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("가짜 저장 실패(로컬 백엔드 문제 시뮬레이션)")
            return {"ok": True, "situation": meta["situation_label"], "action_seq": node_key}

        ct.save_node = flaky_save_node

        args = _make_args(ckpt_path, limit=1)
        rc = ct.run(args)
        check("저장 실패 1회 후 재시도 성공 → run() 정상 종료(rc=0)", rc == 0, f"rc={rc}")
        check("save_node가 정확히 2번 호출됨(1차 실패 + 재시도 성공)",
              calls["n"] == 2, f"calls={calls['n']}")

        check("체크포인트 스냅샷이 최소 1개 이상 기록됨", len(snapshots) >= 1)
        first = snapshots[0]
        check("저장 실패 직후 스냅샷: 루트 노드가 frontier에 있음",
              "" in first["frontier_keys"], f"={first}")
        check("저장 실패 직후 스냅샷: 루트 노드가 visited에는 없음(유실 아님)",
              "" not in first["visited"], f"={first}")
        check("저장 실패 직후 스냅샷: 루트 노드가 failed에도 없음",
              "" not in first["failed"], f"={first}")
    finally:
        ct.Checkpoint.save = orig_ckpt_save
        os.path.exists(ckpt_path) and os.unlink(ckpt_path)
        ct.connect_cdp = orig_connect_cdp
        ct.extract_node = orig_extract_node
        ct.save_node = orig_save_node


ALL_TESTS = [
    ("T-1 compute_children 실측 사이즈 verbatim + action_to_token ValueError",
     test_compute_children_uses_measured_size),
    ("T-2 branch_actions epsilon 컷 + 정렬", test_branch_actions_epsilon),
    ("T-3 _replay 베팅 종료 판정", test_replay_terminal_nodes),
    ("T-4 derive_node_meta 라벨 유도", test_derive_node_meta_labels),
    ("T-5 is_env_failure 환경오류/데이터이상 분리", test_env_failure_classification),
    ("T-6 _limit_hit/_parse_usage 카운터 우선", test_limit_hit_counter_authority),
    ("T-7 run() 한도/환경오류/저장실패 시 노드 유실 없음",
     test_run_requeues_node_on_limit_and_env_failure),
]


if __name__ == "__main__":
    print("\n" + "═" * 60)
    print("  프리플랍 GTO 트리 워커 — 원칙 테스트 (test_gto_tree.py)")
    print("═" * 60)

    if _SKIP_BROWSER_DRIVER:
        print(f"\n  [알림] collect_gto_tree import 실패 — 관련 항목 스킵: {_SKIP_REASON}")

    for name, fn in ALL_TESTS:
        print(f"\n[{name}]")
        try:
            fn()
        except Exception as e:
            FAIL += 1
            print(f"  💥 {name} 실행 중 예외: {e}")

    print("\n" + "═" * 60)
    print(f"  결과: {PASS} 통과 / {FAIL} 실패 (총 {PASS + FAIL})")
    print("═" * 60)

    sys.exit(1 if FAIL else 0)
