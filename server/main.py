import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from typing import Dict

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


@app.post("/game/start", response_model=GameStateResponse)
def start_game(req: StartGameRequest):
    session_id = str(uuid.uuid4())
    session = WebGameSession(
        session_id=session_id,
        human_name=req.player_name,
        chips=req.chips,
        num_bots=req.num_bots,
        difficulty=req.difficulty,
        small_blind=req.big_blind // 2,  # BB 입력 → SB = BB / 2
    )
    sessions[session_id] = session
    return session.get_state()


@app.get("/game/{session_id}/state", response_model=GameStateResponse)
def get_state(session_id: str):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    return session.get_state()


@app.post("/game/{session_id}/action", response_model=GameStateResponse)
def submit_action(session_id: str, req: ActionRequest):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    try:
        session.submit_action(req.action, req.amount)
    except IllegalActionError as e:
        # 불법 액션은 상태를 바꾸지 않고 거절한다(기록·방송·평가 없음)
        raise HTTPException(status_code=400, detail=str(e))
    return session.get_state()


@app.post("/game/{session_id}/next-hand", response_model=GameStateResponse)
def next_hand(session_id: str):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    session.next_hand()
    return session.get_state()


@app.get("/session/{session_id}/review", response_model=SessionReviewResponse)
def get_session_review(session_id: str):
    """세션 전체 누적 플레이 평가 요약."""
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    reviews = session.session_reviews
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
    # 노드 키(필수, ADR 0008/0009/0038): GTO Wizard URL의 preflop_actions 문자열 그대로
    # (실측 사이즈, 예 "F-F-F-R2.5-F"). UTG RFI는 "". 저장 행은 이 값으로만 찾는다.
    action_seq: str
    hands: Dict[str, Dict[str, float]]    # {"AA": {"raise": 1.0}, ...}
    raise_size: Optional[float] = None    # bb 단위 실측 raise-to 값 (예: 2.5, 8.0, 13.5)
    # 아래 3종 키·라벨은 action_seq에서 서버가 유도한다. 보내면 유도값과 대조해 다르면 거부.
    position: Optional[str] = None         # 히어로 포지션
    vs_position: Optional[str] = None      # None=RFI, "BTN"=vs_open, "BTN/BB"=vs_3bet(opener/three_bettor)
    range_type: Optional[str] = None       # open | vs_open | vs_3bet | vs_4bet ...
    situation_label: Optional[str] = None  # "BTN RFI" (없으면 유도 라벨)


# 핸드별 fold+call+raise+allin 합 허용 범위(ADR 0002 — 수집기·로더와 같은 기준)
_SAVE_FREQ_SUM_MIN = 0.9
_SAVE_FREQ_SUM_MAX = 1.1


@app.post("/gto/preflop/save")
def save_gto_preflop(req: GtoPreflopSaveRequest):
    """GTO Wizard에서 추출한 프리플랍 노드 1개를 DB에 저장 (같은 action_seq면 덮어쓰기).

    거부(422): action_seq가 결정 노드가 아님 / 보낸 3종 키가 action_seq 유도값과 다름 /
    핸드 0개 / 어떤 핸드든 빈도합이 [0.9, 1.1] 밖(ADR 0002 — 손상 스팟은 저장하지 않는다).
    """
    from db.connection import get_connection
    from gto.url_generator import node_key_active_count
    from gto.node_key import derive_node_meta

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
        total = sum(freqs.get(a, 0.0) for a in ("fold", "call", "raise", "allin"))
        if not (_SAVE_FREQ_SUM_MIN <= total <= _SAVE_FREQ_SUM_MAX):
            bad.append((hand, round(total, 3)))
    if bad:
        raise HTTPException(
            status_code=422,
            detail=f"빈도합이 [0.9, 1.1] 밖인 핸드 {len(bad)}개 — 저장하지 않습니다: {bad[:10]}",
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

    conn.commit()
    conn.close()

    # 캐시 무효화 (enum + 시퀀스 키 캐시 모두)
    import gto.loader as loader
    loader._cache.clear()
    loader._cache_by_seq.clear()
    loader._loaded = False

    return {
        "ok": True, "situation": label,
        "hands": len(req.hands), "action_seq": action_seq,
    }


@app.get("/gto/preflop/range")
def get_gto_preflop_range(
    position: str,
    vs_position: Optional[str] = None,
    range_type: str = "open",
):
    """프리플랍 레인지 데이터 반환 (전체 169핸드 + 요약 통계)"""
    from gto.loader import _load_all, _cache
    _load_all()

    key = (position, vs_position, range_type)
    data = _cache.get(key)

    if not data:
        return {
            "found": False,
            "position": position,
            "vs_position": vs_position,
            "range_type": range_type,
        }

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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.main:app", host="0.0.0.0", port=8765, reload=True)
