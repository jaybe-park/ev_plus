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

from server.schemas import StartGameRequest, ActionRequest, GameStateResponse
from server.session import WebGameSession

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
    session.submit_action(req.action, req.amount)
    return session.get_state()


@app.post("/game/{session_id}/next-hand", response_model=GameStateResponse)
def next_hand(session_id: str):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    session.next_hand()
    return session.get_state()


# ──────────────────────────────────────────
# GTO 데이터 관리 API
# ──────────────────────────────────────────

class GtoPreflopSaveRequest(BaseModel):
    position: str                          # BTN, CO, MP, UTG, SB, BB
    vs_position: Optional[str] = None     # None=RFI, "BTN"=vs_open
    range_type: str                        # open | vs_open | vs_3bet
    raise_size: Optional[str] = None      # "2.5bb", "3x"
    situation_label: str                   # "BTN RFI"
    hands: Dict[str, Dict[str, float]]    # {"AA": {"raise": 1.0}, ...}


@app.post("/gto/preflop/save")
def save_gto_preflop(req: GtoPreflopSaveRequest):
    """GTO Wizard에서 추출한 프리플랍 레인지를 DB에 저장 (덮어쓰기)."""
    from db.connection import get_connection
    conn = get_connection()
    cur = conn.cursor()

    # SQLite에서 NULL=NULL이 성립하지 않아 ON CONFLICT가 작동 안 함
    # → IS NULL 비교로 직접 존재 여부 확인 후 update or insert
    if req.vs_position is None:
        row = cur.execute(
            "SELECT id FROM gto_preflop_situations WHERE position=? AND range_type=? AND vs_position IS NULL",
            (req.position, req.range_type)
        ).fetchone()
    else:
        row = cur.execute(
            "SELECT id FROM gto_preflop_situations WHERE position=? AND range_type=? AND vs_position=?",
            (req.position, req.range_type, req.vs_position)
        ).fetchone()

    if row:
        sit_id = row["id"]
        cur.execute(
            "UPDATE gto_preflop_situations SET raise_size=?, situation_label=? WHERE id=?",
            (req.raise_size, req.situation_label, sit_id)
        )
    else:
        cur.execute(
            "INSERT INTO gto_preflop_situations (position, vs_position, range_type, raise_size, situation_label) VALUES (?,?,?,?,?)",
            (req.position, req.vs_position, req.range_type, req.raise_size, req.situation_label)
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

    # 캐시 무효화
    import gto.loader as loader
    loader._cache.clear()
    loader._loaded = False

    return {"ok": True, "situation": req.situation_label, "hands": len(req.hands)}


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
    uvicorn.run("server.main:app", host="0.0.0.0", port=8000, reload=True)
