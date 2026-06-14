import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from typing import Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from server.schemas import StartGameRequest, ActionRequest, GameStateResponse
from server.session import WebGameSession

app = FastAPI(title="Texas Hold'em Poker")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
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
        small_blind=req.small_blind,
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


# 프로덕션: React 빌드 파일 서빙
web_dist = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "dist")
if os.path.isdir(web_dist):
    app.mount("/", StaticFiles(directory=web_dist, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.main:app", host="0.0.0.0", port=8000, reload=True)
