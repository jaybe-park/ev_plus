import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import threading
import time
import uuid
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from server.schemas import StartGameRequest, ActionRequest, GameStateResponse, SessionReviewResponse
from server.session import WebGameSession
from core.game import IllegalActionError

app = FastAPI(title="Texas Hold'em Poker")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"(http://(localhost|127\.0\.0\.1)(:\d+)?|https://.*\.gtowizard\.com)",
    allow_methods=["*"],
    allow_headers=["*"],
)

sessions: Dict[str, WebGameSession] = {}

# 세션 정리: 세션은 메모리에만 있으므로 오래 안 쓴 세션·개수 초과분을 지운다.
# 지워진 세션에 대한 요청은 404 → 프론트가 "세션 만료 — 새 게임" 안내를 띄운다.
SESSION_TTL_SEC = 24 * 3600      # 마지막 요청 후 24시간 지나면 만료
MAX_SESSIONS = 20                # 넘으면 가장 오래 안 쓴 세션부터 정리
_sessions_lock = threading.Lock()
_last_seen: Dict[str, float] = {}


def _now() -> float:
    return time.monotonic()


def _prune_sessions(now: Optional[float] = None, keep: Optional[str] = None) -> List[str]:
    """만료(TTL)·개수 초과 세션을 지우고 지운 ID 목록을 돌려준다. keep은 지우지 않는다.
    _last_seen에 없는 세션(직접 등록된 것)은 지금 본 것으로 친다."""
    now = _now() if now is None else now
    with _sessions_lock:
        for sid in sessions:
            _last_seen.setdefault(sid, now)
        for sid in [s for s in _last_seen if s not in sessions]:
            _last_seen.pop(sid, None)
        doomed = [sid for sid, t in _last_seen.items()
                  if sid != keep and now - t > SESSION_TTL_SEC]
        alive = sorted((t, sid) for sid, t in _last_seen.items()
                       if sid not in doomed and sid != keep)
        overflow = len(alive) + (1 if keep in sessions else 0) - MAX_SESSIONS
        if overflow > 0:
            doomed += [sid for _, sid in alive[:overflow]]
        for sid in doomed:
            sessions.pop(sid, None)
            _last_seen.pop(sid, None)
    return doomed


def _register_session(session_id: str, session: WebGameSession) -> None:
    with _sessions_lock:
        sessions[session_id] = session
        _last_seen[session_id] = _now()
    _prune_sessions(keep=session_id)


def _get_session(session_id: str) -> WebGameSession:
    _prune_sessions()
    with _sessions_lock:
        session = sessions.get(session_id)
        if session:
            _last_seen[session_id] = _now()
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    return session


# 게임 엔드포인트는 동기 def라 FastAPI 스레드풀에서 동시에 돈다. 같은 세션에 대한 요청은
# session.lock으로 직렬화하고, 이벤트는 그 요청이 만든 것만 응답에 싣는다.

@app.post("/game/start", response_model=GameStateResponse)
def start_game(req: StartGameRequest):
    session_id = str(uuid.uuid4())
    session = WebGameSession(
        session_id=session_id,
        human_name=req.player_name,
        chips=req.chips,
        num_bots=req.num_bots,
        difficulty=req.difficulty,
        small_blind=req.big_blind // 2,  # BB 입력(짝수 검증됨) → SB = BB / 2
    )
    # 첫 상태 계산까지 성공한 세션만 등록한다 — 도중에 실패하면 목록에 남지 않는다
    state = session.get_state(session.start_events)
    _register_session(session_id, session)
    return state


@app.get("/game/{session_id}/state", response_model=GameStateResponse)
def get_state(session_id: str):
    """현재 상태 조회. 봇 차례에 멈춘 세션(요청 중간 오류의 흔적)이면 사람 차례까지
    진행해 복구하고 그 이벤트를 싣는다. 정상 세션이면 상태를 바꾸지 않는다(events=[])."""
    session = _get_session(session_id)
    with session.lock:
        return session.get_state(session.recover())


@app.post("/game/{session_id}/action", response_model=GameStateResponse)
def submit_action(session_id: str, req: ActionRequest):
    session = _get_session(session_id)
    with session.lock:
        try:
            events = session.submit_action(req.action, req.amount)
        except IllegalActionError as e:
            # 불법 액션은 상태를 바꾸지 않고 거절한다(기록·방송·평가 없음)
            raise HTTPException(status_code=400, detail=str(e))
        return session.get_state(events)


@app.post("/game/{session_id}/next-hand", response_model=GameStateResponse)
def next_hand(session_id: str):
    session = _get_session(session_id)
    with session.lock:
        return session.get_state(session.next_hand())


@app.get("/session/{session_id}/review", response_model=SessionReviewResponse)
def get_session_review(session_id: str):
    """세션 전체 누적 플레이 평가 요약."""
    session = _get_session(session_id)
    with session.lock:
        reviews = list(session.session_reviews)
    total_actions = len(reviews)

    grade_counts: Dict[str, int] = {}
    for r in reviews:
        g = r.get("grade", "⬜")
        grade_counts[g] = grade_counts.get(g, 0) + 1

    total_ev_loss_bb = sum(
        r["ev_loss_bb"] for r in reviews if r.get("ev_loss_bb") is not None
    )

    preflop_reviews = [r for r in reviews if r.get("street") == "프리플랍" and r.get("grade") != "⬜"]
    if preflop_reviews:
        gto_match_rate = sum(1 for r in preflop_reviews if r.get("grade") == "✅") / len(preflop_reviews)
    else:
        gto_match_rate = None

    return {
        "total_actions": total_actions,
        "grade_counts": grade_counts,
        "total_ev_loss_bb": round(total_ev_loss_bb, 4),
        "gto_match_rate": round(gto_match_rate, 4) if gto_match_rate is not None else None,
    }


# ──────────────────────────────────────────
# GTO 데이터 관리 API
# ──────────────────────────────────────────

class GtoPreflopSaveRequest(BaseModel):
    # 노드 키(필수, ADR 0008/0009/0044): GTO Wizard URL의 preflop_actions 문자열 그대로
    # (실측 사이즈, 예 "F-F-F-R2.5-F"). UTG RFI는 "". 저장 행은 이 값으로만 찾는다.
    action_seq: str
    hands: Dict[str, Dict[str, float]]    # {"AA": {"raise": 1.0}, ...}
    raise_size: Optional[float] = None    # bb 단위 실측 raise-to 값 (예: 2.5, 8.0, 13.5)
    # 아래 3종 키·라벨은 action_seq에서 서버가 유도한다. 보내면 유도값과 대조해 다르면 거부.
    position: Optional[str] = None         # 히어로 포지션
    vs_position: Optional[str] = None      # None=RFI, "BTN"=vs_open, "BTN/BB"=vs_3bet(opener/three_bettor)
    range_type: Optional[str] = None       # open | vs_open | vs_3bet | vs_4bet ...
    situation_label: Optional[str] = None  # "BTN RFI" (없으면 유도 라벨)


@app.post("/gto/preflop/save")
def save_gto_preflop(req: GtoPreflopSaveRequest):
    """GTO Wizard에서 추출한 프리플랍 노드 1개를 DB에 저장 (같은 action_seq면 덮어쓰기).

    거부(422): action_seq가 결정 노드가 아님 / 보낸 3종 키가 action_seq 유도값과 다름 /
    핸드 0개 / 어떤 핸드든 빈도합이 [0.9, 1.1] 밖(ADR 0002 — 손상 스팟은 저장하지 않는다).
    """
    from db.connection import get_connection
    from gto.url_generator import node_key_active_count
    from gto.node_key import derive_node_meta
    from gto.loader import FREQ_SUM_MIN, FREQ_SUM_MAX, freq_sum_ok

    action_seq = req.action_seq.strip()
    meta = derive_node_meta(action_seq)
    if meta is None:
        raise HTTPException(
            status_code=422,
            detail=f"action_seq {action_seq!r}는 프리플랍 결정 노드가 아닙니다(베팅 종료).",
        )

    # 보낸 3종 키 대조. vs_3bet 반쪽 포맷(three_bettor만)은 'opener/three_bettor'로 정규화한
    # 뒤 비교한다(우리 모델은 opener==hero, backfill_v12와 같은 규칙).
    sent_vs = req.vs_position
    if req.range_type == "vs_3bet" and sent_vs and "/" not in sent_vs and req.position:
        sent_vs = f"{req.position}/{sent_vs}"
    mismatches = []
    if req.position is not None and req.position != meta["hero_position"]:
        mismatches.append(f"position {req.position!r}≠{meta['hero_position']!r}")
    if req.range_type is not None and req.range_type != meta["range_type"]:
        mismatches.append(f"range_type {req.range_type!r}≠{meta['range_type']!r}")
    if (req.position is not None or req.range_type is not None) and sent_vs != meta["vs_position"]:
        mismatches.append(f"vs_position {sent_vs!r}≠{meta['vs_position']!r}")
    if mismatches:
        raise HTTPException(
            status_code=422,
            detail=f"action_seq {action_seq!r}와 3종 키가 다릅니다: " + ", ".join(mismatches),
        )

    if not req.hands:
        raise HTTPException(status_code=422, detail="핸드가 0개입니다 — 저장하지 않습니다.")
    bad = []
    for hand, freqs in req.hands.items():
        if not freq_sum_ok(freqs):
            bad.append((hand, round(sum(freqs.values()), 3)))
    if bad:
        raise HTTPException(
            status_code=422,
            detail=f"빈도합이 [{FREQ_SUM_MIN}, {FREQ_SUM_MAX}] 밖인 핸드 {len(bad)}개 "
                   f"— 저장하지 않습니다: {bad[:10]}",
        )

    position = meta["hero_position"]
    vs_position = meta["vs_position"]
    range_type = meta["range_type"]
    label = req.situation_label or meta["situation_label"]
    num_active = node_key_active_count(action_seq)

    conn = get_connection()
    cur = conn.cursor()
    row = cur.execute(
        "SELECT id FROM gto_preflop_situations WHERE action_seq=?", (action_seq,)
    ).fetchone()

    if row:
        sit_id = row["id"]
        cur.execute(
            "UPDATE gto_preflop_situations "
            "SET position=?, vs_position=?, range_type=?, raise_size=?, situation_label=?, "
            "hero_position=?, num_active=? WHERE id=?",
            (position, vs_position, range_type, req.raise_size, label,
             position, num_active, sit_id)
        )
    else:
        cur.execute(
            "INSERT INTO gto_preflop_situations "
            "(position, vs_position, range_type, raise_size, situation_label, action_seq, hero_position, num_active) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (position, vs_position, range_type, req.raise_size,
             label, action_seq, position, num_active)
        )
        sit_id = cur.lastrowid

    # 기존 핸드 삭제 후 재삽입
    cur.execute("DELETE FROM gto_preflop_hands WHERE situation_id=?", (sit_id,))
    for hand, freqs in req.hands.items():
        cur.execute("""
            INSERT INTO gto_preflop_hands
                (situation_id, hand, freq_fold, freq_call, freq_raise, freq_allin)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            sit_id, hand,
            freqs.get("fold", 0.0),
            freqs.get("call", 0.0),
            freqs.get("raise", 0.0),
            freqs.get("allin", 0.0),
        ))

    # 미수집 큐(range_type='seq') 완료 처리(ADR 0011 "큐=2순위"): 같은 action_seq를
    # 가리키던 큐 행이 있으면 collected=1로 갱신 — show_missing_spots.py가 더는 미수집으로
    # 보여주지 않는다. 큐에 없던 노드(직접 수집 등)는 매치되는 행이 없어 조용히 0행 갱신.
    cur.execute(
        "UPDATE gto_missing_spots_preflop SET collected=1, collected_at=datetime('now') "
        "WHERE range_type='seq' AND vs_position=? AND collected=0",
        (action_seq,),
    )

    conn.commit()
    conn.close()

    from gto.loader import invalidate
    invalidate()

    return {
        "ok": True, "situation": label,
        "hands": len(req.hands), "action_seq": action_seq,
    }


@app.get("/gto/preflop/range")
def get_gto_preflop_range(action_seq: str):
    """노드 키(action_seq)로 프리플랍 레인지 반환 (전체 핸드 + 콤보가중 요약).

    GTO 패널은 게임 상태 `gto.node_key`(advisor 추천이 쓴 노드)를 그대로 넘긴다 — 힌트와
    패널이 항상 같은 노드다. UTG RFI는 빈 문자열(`?action_seq=`).
    """
    from gto.loader import get_range_by_seq
    data = get_range_by_seq(action_seq)

    if not data:
        return {"found": False, "action_seq": action_seq}

    hands = data.get("hands", {})

    # 콤보 수 가중 평균 계산
    COMBOS = {"pair": 6, "suited": 4, "offsuit": 12}
    total_combos = 0
    summary: Dict[str, float] = {}

    for hand, freqs in hands.items():
        if len(hand) == 2:
            c = COMBOS["pair"]
        elif hand.endswith("s"):
            c = COMBOS["suited"]
        else:
            c = COMBOS["offsuit"]
        total_combos += c
        for action, freq in freqs.items():
            summary[action] = summary.get(action, 0.0) + freq * c

    if total_combos > 0:
        summary = {k: round(v / total_combos, 4) for k, v in summary.items()}

    return {
        "found": True,
        "action_seq": action_seq,
        "situation": data.get("situation", ""),
        "raise_size": data.get("raise_size", ""),
        "summary": summary,
        "hands": hands,
    }


@app.get("/gto/preflop/situations")
def list_gto_situations():
    """저장된 프리플랍 스팟 목록 반환."""
    from db.connection import get_connection
    conn = get_connection()
    rows = conn.execute("""
        SELECT s.situation_label, s.position, s.vs_position, s.range_type,
               COUNT(h.id) as hand_count
        FROM gto_preflop_situations s
        LEFT JOIN gto_preflop_hands h ON h.situation_id = s.id
        GROUP BY s.id ORDER BY s.range_type, s.position
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# 프로덕션: React 빌드 파일 서빙
web_dist = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "dist")
if os.path.isdir(web_dist):
    app.mount("/", StaticFiles(directory=web_dist, html=True), name="static")

