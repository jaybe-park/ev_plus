"""
프리플랍 노드 키(action_seq) 순수 규칙 — 저장·조회·수집·감사가 함께 쓰는 단일 소스.

노드 키 = 히어로 결정 직전까지의 자발적 액션 토큰(F/X/C/R{bb})을 '-'로 이은 문자열
(GTO Wizard `preflop_actions` 포맷, 좌석 순서 UTG→HJ→CO→BTN→SB→BB, ADR 0008).

- `_replay`: 순수 포커 규칙으로 토큰을 재생해 토큰별 행동 좌석과 다음 행동 좌석을 구한다.
- `derive_node_meta`: 노드 키 → 3종 키(hero/vs_position/range_type) + 라벨. 저장 API는
  클라이언트가 보낸 3종 키를 이 값과 대조하고(ADR 0038), 감사 스크립트는 저장된 행이
  이 값과 같은지 검사한다.
- `has_caller`: 노드 키에 콜(`C`) 토큰이 있는지 — 간단 라벨 조회는 콜러 없는 노드만 쓴다
  (ADR 0035, 0038).

(원래 scripts/collect_gto_tree.py에 있던 함수를 서버·로더도 쓰도록 옮겼다. 수집 스크립트는
이 모듈을 그대로 재노출한다.)
"""

from collections import deque
from typing import Optional

POSITIONS = ["UTG", "HJ", "CO", "BTN", "SB", "BB"]

# 헤즈업 = 6-max SB vs BB 트리(ADR 0005): 앞 4좌석(UTG~BTN) 폴드를 노드 키 앞에 붙인다.
HEADSUP_PREFIX = ["F", "F", "F", "F"]


def split_key(node_key: Optional[str]) -> list:
    return node_key.split("-") if node_key else []


def _replay(tokens: list):
    """토큰 리스트 재생 → (좌석_per_토큰: list, 다음_행동_좌석: Optional[int]).

    좌석 순서 UTG(0)…BB(5). 블라인드는 committed로만 반영(자발 액션 아님).
    레이즈가 나오면 그 뒤 활성 좌석들이 다시 행동 대상이 된다(라운드 재개).
    """
    folded = set()
    committed = [0.0] * 6
    committed[4] = 0.5   # SB
    committed[5] = 1.0   # BB
    current_bet = 1.0
    queue = deque(range(6))  # 프리플랍 첫 순회: UTG→BB
    actor_per_token = []

    for tok in tokens:
        while queue and queue[0] in folded:
            queue.popleft()
        if not queue:
            actor_per_token.append(None)
            continue
        actor = queue.popleft()
        actor_per_token.append(actor)

        if tok == "F":
            folded.add(actor)
        elif tok in ("C", "X"):
            committed[actor] = max(committed[actor], current_bet)
        elif tok.startswith("R"):
            try:
                size = float(tok[1:])
            except ValueError:
                size = current_bet
            committed[actor] = size
            current_bet = size
            # 레이즈 후: 폴드 안 한 나머지 좌석이 레이저 다음 순번부터 다시 행동
            active = [s for s in range(6) if s not in folded and s != actor]
            active.sort(key=lambda s: (s - actor) % 6)
            queue = deque(active)
        # 알 수 없는 토큰은 무시(방어)

    while queue and queue[0] in folded:
        queue.popleft()
    next_actor = queue[0] if queue else None
    # 활성(폴드 안 한) 플레이어가 1명 이하면 핸드 종료(예: 모두 BB에게 폴드 →
    # BB가 블라인드로 무혈 승리, 결정 노드 아님). 순수 포커 규칙(가정 아님).
    active = [s for s in range(6) if s not in folded]
    if len(active) <= 1:
        return actor_per_token, None
    return actor_per_token, next_actor


def derive_node_meta(node_key: str) -> Optional[dict]:
    """노드 키 → 저장용 메타(hero_position/vs_position/range_type/situation_label).

    베팅 순서로 히어로(다음 행동 좌석)와 레이저 포지션들을 유도한다.
    결정 노드가 아니면(베팅 종료) None. 라벨 규칙:
      open      → "{H} RFI"                       (vs_position=None)
      vs_open   → "{H} vs {opener} open"          (vs_position="opener")
      vs_3bet   → "{H} vs {3bettor} 3bet"         (vs_position="opener/3bettor")
      vs_Nbet   → "{H} vs {last} Nbet"            (vs_position="opener/…/last")
    """
    tokens = split_key(node_key)
    actor_per_token, hero_seat = _replay(tokens)
    if hero_seat is None:
        return None
    hero = POSITIONS[hero_seat]

    raisers = [
        POSITIONS[actor_per_token[i]]
        for i, t in enumerate(tokens)
        if t.startswith("R") and actor_per_token[i] is not None
    ]
    n = len(raisers)

    if n == 0:
        return {"hero_position": hero, "vs_position": None, "range_type": "open",
                "situation_label": f"{hero} RFI"}
    if n == 1:
        return {"hero_position": hero, "vs_position": raisers[0], "range_type": "vs_open",
                "situation_label": f"{hero} vs {raisers[0]} open"}
    bet_num = n + 1  # 2레이즈=3bet, 3레이즈=4bet …
    range_type = "vs_3bet" if n == 2 else f"vs_{bet_num}bet"
    return {
        "hero_position": hero,
        "vs_position": "/".join(raisers),
        "range_type": range_type,
        "situation_label": f"{hero} vs {raisers[-1]} {bet_num}bet",
    }


def has_caller(node_key: Optional[str]) -> bool:
    """노드 키에 콜(림프 포함) 토큰이 하나라도 있으면 True."""
    return "C" in split_key(node_key)
