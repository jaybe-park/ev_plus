#!/usr/bin/env python3
"""
프리플랍 GTO 트리 워커(scripts/gto_tree_worker.py, scripts/collect_gto_tree.py) 원칙 테스트.
브라우저/네트워크 없이 현재 동작을 핀(pin)한다. 배경: gto-findings.md G7~G13
(사람 결정이 필요 없는, 현재 코드 동작 그대로 검증 가능한 항목만).

실행: python3 tests/test_gto_tree.py
"""

import contextlib
import io
import json
import os
import sys
import tempfile
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

# run()이 db.connection.get_connection()으로 실 DB를 읽으므로(load_collected_from_db)
# 그라인드 데이터와 격리한다.
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
    # collect_gto_tree는 모듈 로드 시 playwright를 import하지 않지만(connect_cdp 내부
    # 지연 import) 환경에 따라 실패할 수 있어 방어적으로 가드.
    _SKIP_BROWSER_DRIVER, _SKIP_REASON, ct = True, str(e), None


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


# [T-1] G7 — compute_children: 실측 사이즈 verbatim, 사이즈 없으면 레이즈 자식 없음,
# action_to_token("raise")는 사이즈 없이 호출하면 ValueError
def test_compute_children_uses_measured_size():
    hands = {"AA": {"raise": 1.0}, "72o": {"fold": 1.0}}
    keys = [k for k, _, _ in ct.compute_children("", hands, {"raise": 13.5}, 1.0)]
    check("측정 사이즈 13.5가 자식 키에 verbatim 포함(R13.5)", "R13.5" in keys, f"={keys}")
    check("fold 자식(F)도 포함", "F" in keys, f"={keys}")

    keys2 = [k for k, _, _ in ct.compute_children("", hands, {"raise": None}, 1.0)]
    check("사이즈 None이면 레이즈 자식 생성 안 함",
          "R13.5" not in keys2 and not any(k.startswith("R") for k in keys2), f"={keys2}")
    check("사이즈 없어도 fold 자식은 그대로 있음", "F" in keys2, f"={keys2}")

    try:
        tw.action_to_token("raise")
        check("action_to_token('raise') 사이즈 없이 호출 시 ValueError", False, "예외 발생 안 함")
    except ValueError:
        check("action_to_token('raise') 사이즈 없이 호출 시 ValueError", True)


# [T-2] G8 — branch_actions: epsilon(0.0005) 컷 + 내림차순 정렬
def test_branch_actions_epsilon():
    actions = [a for a, _ in tw.branch_actions({"fold": 0.0004, "call": 0.0006, "raise": 0.5})]
    check("0.0004(≤ε)은 제외", "fold" not in actions, f"={actions}")
    check("0.0006(>ε)은 포함", "call" in actions, f"={actions}")
    check("빈도 내림차순 정렬(raise 먼저, call 나중)", actions == ["raise", "call"], f"={actions}")


# [T-3] G9 — _replay: 베팅 종료 판정(결정 노드 아님) + 다음 행동 좌석
def test_replay_terminal_nodes():
    for tokens, label in [
        (["F"] * 5, "전원(UTG~SB) 폴드 → BB만 남아 결정 노드 아님(None)"),
        (["R2.5", "F", "F", "F", "F", "F"],
         "R2.5-F-F-F-F-F(레이저 제외 전원 폴드)는 결정 노드 아님(None)"),
    ]:
        _, next_actor = ct._replay(tokens)
        check(label, next_actor is None, f"={next_actor}")

    _, actor = ct._replay(["R2.5", "C"])
    check("R2.5-C 다음 행동자는 CO", ct.POSITIONS[actor] == "CO",
          f"={ct.POSITIONS[actor] if actor is not None else None}")


# [T-4] G10 — derive_node_meta: 노드 키 → 라벨/3종 키 결정론적 유도
# (RFI, vs_open, squeeze/vs_3bet, vs_4bet. 림프 케이스는 결정 보류로 스킵)
def test_derive_node_meta_labels():
    for key, expected, label in [
        ("", {"hero_position": "UTG", "vs_position": None, "range_type": "open",
              "situation_label": "UTG RFI"}, "RFI(빈 키) → UTG RFI"),
        ("R2.5", {"hero_position": "HJ", "vs_position": "UTG", "range_type": "vs_open",
                  "situation_label": "HJ vs UTG open"}, "vs_open(R2.5) → HJ vs UTG open"),
        ("R2.5-C-R8", {"hero_position": "BTN", "vs_position": "UTG/CO", "range_type": "vs_3bet",
                       "situation_label": "BTN vs CO 3bet"},
         "squeeze/vs_3bet(R2.5-C-R8, HJ 콜드콜 후 CO 3벳) → BTN vs CO 3bet"),
        ("R2.5-R8-R20", {"hero_position": "BTN", "vs_position": "UTG/HJ/CO",
                         "range_type": "vs_4bet", "situation_label": "BTN vs CO 4bet"},
         "vs_4bet(R2.5-R8-R20) → BTN vs CO 4bet"),
    ]:
        actual = ct.derive_node_meta(key)
        check(label, actual == expected, f"={actual}")


# [T-5] G11 — is_env_failure: 환경 오류(재시도 대상) vs 데이터 이상(사람 확인 필요) 구분
def test_env_failure_classification():
    for msg, expected, label in [
        ("navigate 실패: 타임아웃", True, "'navigate 실패: ...' → 환경 오류"),
        ("렌더 대기 타임아웃", True, "'렌더 대기 타임아웃' → 환경 오류"),
        ("badSum 검증 실패(3핸드)", False, "'badSum 검증 실패(3핸드)' → 데이터 이상(환경 오류 아님)"),
        ("파싱된 핸드 0개", False, "'파싱된 핸드 0개' → 데이터 이상(환경 오류 아님)"),
    ]:
        check(label, ct.is_env_failure(msg) is expected)


# [T-6] G13 — _limit_hit / _parse_usage: 한도 판단은 카운터 우선
def test_limit_hit_counter_authority():
    # gto-findings.md 제안값 used=99는 DAILY_LIMIT=100 기준 `used >= DAILY_LIMIT`이
    # 조건이라 미도달(False)이다. 카운터가 한도값(100) 자체에 도달한 경우로 검증한다.
    for args, expected, label in [
        ((100, True, True), True, "used=100(카운터=한도) → 한도 도달"),
        ((50, True, False), False, "used=50(카운터 신뢰, 경고 문구 무시) → 한도 아님"),
        ((None, True, False), True, "used=None + 경고문구 + 렌더 실패 → 폴백으로 한도 도달 간주"),
    ]:
        check(label, ct._limit_hit(*args) is expected)
    check("_parse_usage('... 42/100 ...') == 42", ct._parse_usage("blah 42/100 blah") == 42)


# [T-7] G12 — run(): 한도 도달 / 환경 오류 / 저장 실패 시 꺼낸 노드를 잃지 않는다
# (frontier에 되돌리고 visited·failed에는 넣지 않음)
def _make_args(checkpoint_path, limit=1):
    ap = ct.build_parser()
    return ap.parse_args(["--limit", str(limit), "--checkpoint", checkpoint_path,
                           "--min-delay", "0", "--max-delay", "0"])


def _fresh_checkpoint_path():
    f = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f.close()
    os.unlink(f.name)  # run()이 "체크포인트 없음" 경로(DB에서 시드)를 타도록 파일 자체를 없앤다
    return f.name


def _fake_cdp_handles():
    """connect_cdp가 반환하는 (p, browser, ctx, page) 4종을 흉내낸다. run()이 호출하는
    메서드(close/stop/new_page 등)만 있으면 되므로 전부 MagicMock."""
    page = MagicMock()
    page.inner_text.side_effect = Exception("no body in fake page")  # read_usage → None 유도
    ctx = MagicMock()
    ctx.new_page.return_value = MagicMock()
    return MagicMock(), MagicMock(), ctx, page


def _run_quiet(args):
    with contextlib.redirect_stdout(io.StringIO()):
        return ct.run(args)


def _run_with_fake_env(extract_result, limit=1):
    """connect_cdp/extract_node를 스텁으로 바꿔 run()을 조용히 실행하고
    (rc, checkpoint dict)를 반환한다."""
    ckpt_path = _fresh_checkpoint_path()
    try:
        ct.connect_cdp = lambda cdp_url: _fake_cdp_handles()
        ct.extract_node = lambda page, node_key, nav_timeout: extract_result
        rc = _run_quiet(_make_args(ckpt_path, limit=limit))
        with open(ckpt_path) as f:
            return rc, json.load(f)
    finally:
        os.path.exists(ckpt_path) and os.unlink(ckpt_path)


def test_run_requeues_node_on_limit_and_env_failure():
    if _SKIP_BROWSER_DRIVER:
        print(f"  [스킵] collect_gto_tree import 실패(playwright 등 환경 문제): {_SKIP_REASON}")
        return

    orig_connect_cdp, orig_extract_node, orig_save_node = ct.connect_cdp, ct.extract_node, ct.save_node
    try:
        # 시나리오 A(한도 도달)/B(연속 환경오류: limit은 도달 전 환경오류 중단이 먼저 걸림)
        for extract_result, limit, label in [
            (ct.ExtractResult(False, reason="일일 한도 도달(사용량 99/100)", limit_hit=True, used=99),
             1, "한도 도달"),
            (ct.ExtractResult(False, reason="navigate 실패: 네트워크 오류"), 90, "연속 환경오류"),
        ]:
            rc, data = _run_with_fake_env(extract_result, limit=limit)
            frontier_keys = ["-".join(f["tokens"]) for f in data["frontier"]]
            check(f"{label} 시 run()이 정상 종료(rc=0)", rc == 0, f"rc={rc}")
            check(f"{label}: 루트 노드(RFI, key='')가 frontier에 남아있음(재시도 대상)",
                  "" in frontier_keys, f"frontier={frontier_keys}")
            check(f"{label}: 루트 노드가 visited에는 없음(유실 아님)",
                  "" not in data["visited"], f"visited={data['visited']}")
            check(f"{label}: 루트 노드가 failed(영구 no-retry)에도 없음",
                  "" not in data["failed"], f"failed={data['failed']}")
    finally:
        ct.connect_cdp, ct.extract_node = orig_connect_cdp, orig_extract_node

    # 시나리오 C(저장 실패, 로컬 백엔드 문제, 일시적): 노드를 frontier로 되돌린 뒤 재시도한다.
    # 첫 시도만 실패시키고 그 시점 체크포인트 스냅샷으로 "유실되지 않았음"을 확인한 뒤
    # 재시도가 성공하게 한다.
    ckpt_path = _fresh_checkpoint_path()
    orig_ckpt_save = ct.Checkpoint.save
    try:
        ct.connect_cdp = lambda cdp_url: _fake_cdp_handles()
        ct.extract_node = lambda page, node_key, nav_timeout: ct.ExtractResult(
            True, hands={"AA": {"raise": 1.0}, "72o": {"fold": 1.0}}, raise_size=2.5, used=None)

        snapshots = []

        def recording_save(self, frontier):
            orig_ckpt_save(self, frontier)
            snapshots.append({"visited": set(self.visited), "failed": list(self.failed),
                               "frontier_keys": ["-".join(n.path_tokens) for n in frontier._items]})

        ct.Checkpoint.save = recording_save

        calls = {"n": 0}

        def flaky_save_node(server, node_key, meta, hands, raise_size):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("가짜 저장 실패(로컬 백엔드 문제 시뮬레이션)")
            return {"ok": True, "situation": meta["situation_label"], "action_seq": node_key}

        ct.save_node = flaky_save_node

        rc = _run_quiet(_make_args(ckpt_path, limit=1))
        check("저장 실패 1회 후 재시도 성공 → run() 정상 종료(rc=0)", rc == 0, f"rc={rc}")
        check("save_node가 정확히 2번 호출됨(1차 실패 + 재시도 성공)", calls["n"] == 2, f"calls={calls['n']}")
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
        ct.connect_cdp, ct.extract_node, ct.save_node = orig_connect_cdp, orig_extract_node, orig_save_node


# [T-8] T-012 — save_node가 계속 실패하면(백엔드가 꺼진 등) 한도를 다 쓸 때까지
# 같은 노드를 무한 재시도하지 않고, 환경오류와 같은 기준(CONSEC_ENV_ABORT_THRESHOLD)
# 안에 "서버 확인" 메시지와 함께 안전 중단한다. 노드는 frontier에 보존된다(유실 아님).
def test_run_aborts_on_persistent_save_failure():
    if _SKIP_BROWSER_DRIVER:
        print(f"  [스킵] collect_gto_tree import 실패(playwright 등 환경 문제): {_SKIP_REASON}")
        return

    orig_connect_cdp, orig_extract_node, orig_save_node = ct.connect_cdp, ct.extract_node, ct.save_node
    ckpt_path = _fresh_checkpoint_path()
    try:
        ct.connect_cdp = lambda cdp_url: _fake_cdp_handles()
        ct.extract_node = lambda page, node_key, nav_timeout: ct.ExtractResult(
            True, hands={"AA": {"raise": 1.0}, "72o": {"fold": 1.0}}, raise_size=2.5, used=None)

        calls = {"n": 0}

        def always_fail_save_node(server, node_key, meta, hands, raise_size):
            calls["n"] += 1
            raise RuntimeError("가짜 저장 실패(백엔드가 계속 꺼져 있는 상황 시뮬레이션)")

        ct.save_node = always_fail_save_node

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            # limit을 크게 잡아도(한도를 다 쓰기 전에) 안전 중단해야 한다.
            rc = ct.run(_make_args(ckpt_path, limit=90))
        output = buf.getvalue()

        with open(ckpt_path) as f:
            data = json.load(f)
        frontier_keys = ["-".join(f["tokens"]) for f in data["frontier"]]

        check("run()이 정상 종료(rc=0)", rc == 0, f"rc={rc}")
        check(f"저장이 CONSEC_ENV_ABORT_THRESHOLD({ct.CONSEC_ENV_ABORT_THRESHOLD})회 안에 중단"
              f"(save_node 호출 수가 한도를 다 쓰지 않음)",
              calls["n"] == ct.CONSEC_ENV_ABORT_THRESHOLD,
              f"calls={calls['n']} (limit=90이면 무한 재시도 시 훨씬 커야 함)")
        check("중단 메시지에 '서버 확인'이 포함됨", "서버 확인" in output, f"output 일부={output[-500:]}")
        check("루트 노드가 frontier에 보존됨(유실 아님)", "" in frontier_keys, f"frontier={frontier_keys}")
        check("루트 노드가 visited에는 없음(성공 처리 아님)", "" not in data["visited"],
              f"visited={data['visited']}")
        check("루트 노드가 failed(영구 no-retry)에도 없음(재시도 가능해야 함)",
              "" not in data["failed"], f"failed={data['failed']}")
    finally:
        os.path.exists(ckpt_path) and os.unlink(ckpt_path)
        ct.connect_cdp, ct.extract_node, ct.save_node = orig_connect_cdp, orig_extract_node, orig_save_node


def _seed_nodes(db_path: str, nodes: dict):
    """임시 DB에 {action_seq: (raise_size, hands)} 노드를 저장 API 규칙대로 시딩."""
    from db.connection import get_connection
    from gto.node_key import derive_node_meta
    conn = get_connection(db_path)
    for seq, (raise_size, hands) in nodes.items():
        meta = derive_node_meta(seq)
        sid = conn.execute(
            "INSERT INTO gto_preflop_situations (position, vs_position, range_type, raise_size, "
            "situation_label, action_seq, hero_position) VALUES (?,?,?,?,?,?,?)",
            (meta["hero_position"], meta["vs_position"], meta["range_type"], raise_size,
             meta["situation_label"], seq, meta["hero_position"]),
        ).lastrowid
        for hand, fr in hands.items():
            conn.execute(
                "INSERT INTO gto_preflop_hands (situation_id, hand, freq_fold, freq_call, "
                "freq_raise, freq_allin) VALUES (?,?,?,?,?,?)",
                (sid, hand, fr.get("fold", 0), fr.get("call", 0), fr.get("raise", 0), fr.get("allin", 0)))
    conn.commit()
    conn.close()


# [T-9] T-001 — 덮어써져 사라진 노드(visited인데 DB·failed에 없음)를 frontier로 되돌린다.
# 기본 드라이런은 체크포인트를 바꾸지 않고, --apply만 바꾼다.
def test_requeue_lost_nodes():
    import requeue_lost_gto_nodes as rq
    db_path = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    # 루트(UTG RFI): AA 레이즈 100%, 72o 폴드 100% → 콤보가중 raise=6/18, fold=12/18
    _seed_nodes(db_path, {
        "": (2.5, {"AA": {"raise": 1.0}, "72o": {"fold": 1.0}}),
        "R2.5": (8.0, {"AA": {"raise": 1.0}, "KK": {"fold": 1.0}}),  # HJ: fold 6/12
        "R2.5-C": (11.0, {"AA": {"raise": 1.0}}),   # 덮어쓴 쪽(남아 있음)
    })
    ckpt = {
        "visited": ["", "R2.5-C", "R2.5-F",            # R2.5-F: 덮어써져 사라짐
                    "R2.5-F-F-F-F-F",                   # 결정 노드 아님(모두 폴드)
                    "F-F-F-R2.5-F"],                    # failed에 있음 → 대상 아님
        "failed": ["F-F-F-R2.5-F"],
        "frontier": [{"tokens": ["F"], "reach": 0.5}],
    }
    fd, ckpt_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        with open(ckpt_path, "w") as f:
            json.dump(ckpt, f)
        before = open(ckpt_path).read()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rq.main(["--checkpoint", ckpt_path, "--db", db_path])
        check("드라이런은 체크포인트를 바꾸지 않음", open(ckpt_path).read() == before)
        check("드라이런이 사라진 노드 1개(R2.5-F)를 보고", "'R2.5-F'" in out.getvalue()
              and "1개" in out.getvalue(), out.getvalue()[-400:])

        with contextlib.redirect_stdout(io.StringIO()):
            rq.main(["--checkpoint", ckpt_path, "--db", db_path, "--apply"])
        data = json.load(open(ckpt_path))
        fr = {"-".join(f["tokens"]): f["reach"] for f in data["frontier"]}
        check("--apply: R2.5-F가 visited에서 빠짐", "R2.5-F" not in data["visited"], str(data["visited"]))
        check("--apply: R2.5-F가 frontier에 들어감", "R2.5-F" in fr, str(fr))
        check("--apply: reach = 루트 raise(6/18) × HJ fold(6/12)",
              abs(fr.get("R2.5-F", 0) - (6 / 18) * 0.5) < 1e-9, str(fr.get("R2.5-F")))
        check("--apply: 결정 노드 아님·failed·DB 노드는 visited 유지",
              {"R2.5-F-F-F-F-F", "F-F-F-R2.5-F", "", "R2.5-C"} <= set(data["visited"]),
              str(data["visited"]))
        check("--apply: 기존 frontier 보존", "F" in fr, str(fr))
    finally:
        os.unlink(ckpt_path)


# [T-10] T-001 — audit: 3종 키 = derive_node_meta(action_seq), visited인데 DB·failed에 없음 = 0
def test_audit_key_and_lost_checks():
    import audit_gto_preflop as audit
    db_path = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    _seed_nodes(db_path, {"F-F-F-R2.5-F": (14.0, {"AA": {"raise": 1.0}})})
    from db.connection import get_connection
    conn = get_connection(db_path)
    # 라벨이 action_seq와 다른 행(옛 덮어쓰기 흔적 재현)
    conn.execute("INSERT INTO gto_preflop_situations (position, vs_position, range_type, "
                 "situation_label, action_seq, hero_position) "
                 "VALUES ('BB','BTN','vs_open','BB vs BTN open','R2.5-C-F-F-F','BB')")
    conn.commit()
    rows = conn.execute("SELECT * FROM gto_preflop_situations").fetchall()
    conn.close()
    mism = audit.key_mismatches(rows)
    check("3종 키 불일치 1건(R2.5-C-F-F-F는 BB vs UTG)",
          [m[0] for m in mism] == ["R2.5-C-F-F-F"], str(mism))

    fd, ckpt_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        with open(ckpt_path, "w") as f:
            json.dump({"visited": ["F-F-F-R2.5-F", "F-F-F-R2.5-C", "R2.5-F-F-F-F-F"],
                       "failed": [], "frontier": []}, f)
        lost = audit.lost_visited(ckpt_path, {"F-F-F-R2.5-F", "R2.5-C-F-F-F"})
        check("visited인데 DB·failed에 없음 = [F-F-F-R2.5-C]", lost == ["F-F-F-R2.5-C"], str(lost))
        with contextlib.redirect_stdout(io.StringIO()):
            rc = audit.main(["--db", db_path, "--checkpoint", ckpt_path])
        check("audit이 불일치를 실패(1)로 보고", rc == 1, f"rc={rc}")
        check("체크포인트 없으면 lost 검사는 None(생략)",
              audit.lost_visited(ckpt_path + ".none", set()) is None)
    finally:
        os.unlink(ckpt_path)


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
    ("T-8 run() 저장이 계속 실패하면 N회 안에 안전 중단(T-012)",
     test_run_aborts_on_persistent_save_failure),
    ("T-9 사라진 노드 frontier 복구(드라이런 기본, T-001)", test_requeue_lost_nodes),
    ("T-10 audit 3종 키·visited 누락 검사(T-001)", test_audit_key_and_lost_checks),
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
