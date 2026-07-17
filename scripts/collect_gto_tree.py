#!/usr/bin/env python3
"""
④ 데이터 기반 프리플랍 트리 워커 — Playwright(CDP) 자동화 드라이버.

설계 근거: docs/gto-preflop-tree.md "데이터 기반 트리 수집 방식" + "확정 결정 D1~D3".
순수 로직(집계/분기/우선순위 큐/토큰화)은 scripts/gto_tree_worker.py를 **그대로 재사용**하고,
이 파일은 그 로직에 브라우저(navigate/추출)와 저장(POST)을 붙인 얇은 드라이버다.

핵심 원칙(전부 준수):
  D1  저장 노드 키(action_seq)의 레이즈 토큰은 **화면 실측 사이즈** verbatim.
      깊이-캐노니컬/추측 테이블 사용 금지.
  ε   분기는 gto_tree_worker.branch_actions(ε=0.05%) — 레인지 콤보가중 합산 빈도가
      ε를 넘는 액션만 자식으로 확장. "버튼 존재"로 판단하지 않는다.
  검증 badSum(핸드별 fold+call+raise+allin 합)이 [0.9,1.1] 밖이면 저장하지 않고 스킵.
  우선순위 gto_tree_worker.FrontierQueue — 도달확률(경로 빈도 누적) 내림차순 best-first.

수집 흐름(노드 1개):
  url_from_node_key(node_key) 로 GTO Wizard로 navigate
    → 169핸드 CSS 레이어 파싱(colorToAction/parseCell, 이번 세션 라이브 수집서 검증한 파서)
    → badSum 검증 → 화면에서 raise/allin 실측 사이즈 읽기
    → POST /gto/preflop/save (action_seq=실측 키, raise_size=실측)
    → 저장된 hands로 aggregate_frequencies+branch_actions → 자식 노드를 도달확률 가중으로 push.

CDP 연결:
  사용자가 아래처럼 크롬을 디버그 포트로 미리 띄우고 GTO Wizard에 로그인해 둬야 한다.
    /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\
        --remote-debugging-port=9222 --user-data-dir="$HOME/chrome-gto-debug"
  그 뒤 이 스크립트가 playwright.chromium.connect_over_cdp("http://localhost:9222")로 접속한다.
  (connect_over_cdp는 사용자의 기존 크롬에 붙는 것이라 playwright의 번들 크로미움을
   반드시 내려받을 필요는 없다. 다만 `python3 -m playwright install chromium`을 해두면
   드라이버 바이너리가 준비돼 import/실행이 안정적이다 — 이 저장소에선 설치 완료 확인함.)

중단-재개:
  노드 하나를 저장할 때마다 체크포인트 JSON(--checkpoint)에 visited/frontier/failed를 남긴다.
  스크립트가 죽어도 재실행하면 체크포인트+DB(action_seq)에서 이어서 진행한다.
  체크포인트가 없거나 비면 DB의 이미 수집된 트리에서 프론티어를 재구성(seed)한다.

사용법:
  python3 scripts/collect_gto_tree.py                 # 기본 --limit 90 실전 수집
  python3 scripts/collect_gto_tree.py --dry-run       # 추출/검증만, 저장 안 함
  python3 scripts/collect_gto_tree.py --limit 5       # 이번 실행 신규 노드 5개까지
  python3 scripts/collect_gto_tree.py --cdp-url http://localhost:9333

CLI:
  --limit N     이번 실행에서 처리할 최대 신규 노드 수(기본 90 — 무료 100/일 안전마진).
  --dry-run     추출+검증만 하고 저장/큐 확장 없이 첫 노드 결과를 상세 출력(파서 눈검증).
  --cdp-url     크롬 디버그 CDP 엔드포인트(기본 http://localhost:9222).
  --server      로컬 FastAPI 베이스 URL(기본 https://localhost:8765, 자체서명 → 검증 스킵).
  --checkpoint  진행상황 JSON 경로(기본 <repo>/gto_tree_checkpoint.json).
  --epsilon     분기 빈도 컷(기본 gto_tree_worker.EPSILON=0.0005).
  --nav-timeout navigate/셀 대기 타임아웃 ms(기본 30000).
  --safety-margin 남은 스팟이 이 값 이하면 새 수집 중단(기본 5, 무료 100/일 보호).

실측 사이즈 스크레이프(2026-07-17 라이브 확정):
  히어로가 지금 취할 수 있는 액션(사이즈 포함)은 페이지 하단 "Actions" 패널의
  [data-tst="study_action_btns"] 컨테이너 안 [data-tst^="action_"] 버튼에만 있다.
  버튼 data-tst가 액션+사이즈를 인코딩(action_R8_1=Raise 8, action_RAI_0=Allin,
  action_C_2=Call, action_F_3=Fold)하고 화면 표시 텍스트와 verbatim 일치한다.
  헤더 카드(hspotcrd_action_text: 다른 포지션이 이미 취한 과거 액션)와 접두어가
  달라 절대 겹치지 않는다 → 이전 "body 전체 정규식" 오탐(헤더의 완료 액션을 잘못
  집던 버그) 해소.

일일 한도 신호(2026-07-17 라이브 확정):
  상단 "X/100" 사용량 카운터가 유일한 권위 신호. "Free accounts can browse 100
  preflop spots per day." 문구는 평상시에도 항상 떠 있어(호버 툴팁) 단독 판단 불가 →
  카운터를 파싱해 남은 여유(100-X)를 계산, 안전마진 이하면 새 navigate 없이 안전 종료.
"""
import argparse
import json
import sys
from collections import deque
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import gto_tree_worker as tw  # 순수 로직 재사용 (집계/분기/토큰/큐)
from gto.url_generator import url_from_node_key

POSITIONS = ["UTG", "HJ", "CO", "BTN", "SB", "BB"]

DEFAULT_CHECKPOINT = ROOT / "gto_tree_checkpoint.json"
DEFAULT_SERVER = "https://localhost:8765"
DEFAULT_CDP = "http://localhost:9222"

# 100bb 가정에서 올인 to-amount = 시작 스택(정의상 결정론적, 추측 아님).
# 화면에서 올인 사이즈를 읽지 못했을 때만 이 값으로 폴백한다.
ALLIN_FALLBACK_BB = 100.0

# ── 일일 한도 신호 (2026-07-17 라이브 실측으로 확정, 추측 키워드 폐기) ──────────
# GTO Wizard 무료 계정은 페이지 상단에 "X/100" 사용량 카운터를 항상 노출하고,
# 그 옆에 "Free accounts can browse 100 preflop spots per day." 고정 문구를
# (호버 툴팁으로) 항상 표시한다. 문구는 한도 도달 여부와 무관하게 늘 떠 있으므로
# **문구 존재만으로 한도로 판단하면 안 된다** — 카운터가 유일한 권위 신호다.
#   - 스팟을 새로 볼 때마다 카운터가 +1 된다(실측: 18→19→20). 즉 navigate=1스팟 소모.
#   - 남은 여유 = DAILY_LIMIT - used. 안전마진(SAFETY_MARGIN) 이하로 떨어지면
#     새 노드 navigate를 멈추고 안전 종료(체크포인트 보존 → 재실행 시 이어감).
DAILY_LIMIT = 100
SAFETY_MARGIN = 5  # 남은 스팟이 이 값 이하가 되면 새 수집을 멈춘다(무료 100/일 보호).
# 카운터를 읽지 못할 때(파싱 실패)만 폴백으로 쓰는 한도 확정 문구(부분 매칭).
LIMIT_WARN_PHRASE = "Free accounts can browse 100 preflop spots per day"


# ──────────────────────────────────────────────────────────────────────────
# 프리플랍 베팅 순서 시뮬레이터 (순수 포커 규칙 — GTO 가정 아님)
#   노드 키(F/C/X/R{bb} 토큰)를 좌석 순서로 재생해:
#     - 각 토큰을 실행한 좌석
#     - 다음에 행동할 좌석(=히어로, 없으면 None=베팅 종료 → 프리플랍 결정 노드 아님)
#   을 구한다. 저장 라벨(hero/vs_position/range_type) 유도 + 자식 유효성 필터에 쓴다.
# ──────────────────────────────────────────────────────────────────────────
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
    결정 노드가 아니면(베팅 종료) None. 라벨 규칙은 기존 DB 표기와 일치:
      open      → "{H} RFI"                       (vs_position=None)
      vs_open   → "{H} vs {opener} open"          (vs_position="opener")
      vs_3bet   → "{H} vs {3bettor} 3bet"         (vs_position="opener/3bettor")
      vs_Nbet   → "{H} vs {last} Nbet"            (vs_position="opener/…/last")
    """
    tokens = node_key.split("-") if node_key else []
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


# ──────────────────────────────────────────────────────────────────────────
# 자식 노드 계산 (gto_tree_worker 로직 재사용 + 베팅 규칙 유효성 필터)
# ──────────────────────────────────────────────────────────────────────────
def compute_children(node_key: str, hands: dict, size_map: dict, reach_prob: float,
                     epsilon: float = tw.EPSILON) -> list:
    """노드의 hands(추출/저장 데이터)로부터 자식 TreeNode 후보 목록 생성.

    size_map = {"raise": <실측 raise to-amount>, "allin": <실측 allin to-amount>}.
    반환: [(child_key, child_tokens, child_reach), …]. 자식이 프리플랍 결정 노드가
    아니면(베팅 종료) 제외한다. 실측 사이즈 없는 raise/allin은 토큰 생성 불가라 스킵.
    """
    agg = tw.aggregate_frequencies(hands)
    parent_tokens = node_key.split("-") if node_key else []
    out = []
    for action, freq in tw.branch_actions(agg, epsilon):
        try:
            token = tw.action_to_token(action, raise_size=size_map.get(action))
        except ValueError:
            # 실측 사이즈 없는 레이즈/올인 — 추측 금지, 자식 생성 불가 → 스킵
            continue
        child_tokens = parent_tokens + [token]
        _, nxt = _replay(child_tokens)
        if nxt is None:
            continue  # 베팅 종료 → 프리플랍 결정 노드 아님
        out.append(("-".join(child_tokens), child_tokens, reach_prob * freq))
    return out


# ──────────────────────────────────────────────────────────────────────────
# DB 조회 (이미 수집된 노드 재수집 방지 + 프론티어 시드)
# ──────────────────────────────────────────────────────────────────────────
def load_collected_from_db() -> dict:
    """DB의 gto_preflop_situations를 읽어 {action_seq: {hands, raise_size}} 반환.

    action_seq가 NULL인 레거시 행은 노드 키가 없어 제외(트리 좌표 불명).
    """
    from db.connection import get_connection
    conn = get_connection()
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT id, action_seq, raise_size FROM gto_preflop_situations "
        "WHERE action_seq IS NOT NULL"
    ).fetchall()
    collected = {}
    for r in rows:
        hands_rows = cur.execute(
            "SELECT hand, freq_fold, freq_call, freq_raise, freq_allin "
            "FROM gto_preflop_hands WHERE situation_id=?",
            (r["id"],),
        ).fetchall()
        hands = {}
        for h in hands_rows:
            freqs = {}
            if h["freq_fold"] > 0:  freqs["fold"] = h["freq_fold"]
            if h["freq_call"] > 0:  freqs["call"] = h["freq_call"]
            if h["freq_raise"] > 0: freqs["raise"] = h["freq_raise"]
            if h["freq_allin"] > 0: freqs["allin"] = h["freq_allin"]
            hands[h["hand"]] = freqs
        collected[r["action_seq"]] = {"hands": hands, "raise_size": r["raise_size"]}
    conn.close()
    return collected


def seed_frontier_from_db(collected: dict, epsilon: float):
    """이미 수집된 트리를 루트("")부터 BFS로 훑어, 아직 미수집인 자식들을
    도달확률 가중으로 프론티어에 시드한다(수집된 노드는 재방문하지 않음).

    반환: (frontier_items: [(tokens, reach)], visited_keys: set)
    """
    frontier = []
    known = set()
    visited = set(collected.keys())
    if "" not in collected:
        # 루트(UTG RFI)조차 없으면 루트부터 수집해야 함 → 프론티어에 루트만.
        return [([], 1.0)], set()

    bfs = deque([("", 1.0)])
    seen_bfs = set()
    while bfs:
        key, reach = bfs.popleft()
        if key in seen_bfs:
            continue
        seen_bfs.add(key)
        node = collected.get(key)
        if node is None:
            continue
        size_map = {"raise": node["raise_size"], "allin": ALLIN_FALLBACK_BB}
        for child_key, child_tokens, child_reach in compute_children(
            key, node["hands"], size_map, reach, epsilon
        ):
            if child_key in collected:
                bfs.append((child_key, child_reach))  # 이미 수집 → 더 파고듦
            elif child_key not in known:
                known.add(child_key)
                frontier.append((child_tokens, child_reach))
    return frontier, visited


# ──────────────────────────────────────────────────────────────────────────
# 체크포인트
# ──────────────────────────────────────────────────────────────────────────
class Checkpoint:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.visited = set()
        self.failed = []
        self.frontier_items = []  # [(tokens, reach)]

    def load(self) -> bool:
        if not self.path.exists():
            return False
        try:
            data = json.loads(self.path.read_text())
        except Exception:
            return False
        self.visited = set(data.get("visited", []))
        self.failed = list(data.get("failed", []))
        self.frontier_items = [(f["tokens"], f["reach"]) for f in data.get("frontier", [])]
        return True

    def save(self, frontier: "tw.FrontierQueue"):
        items = [{"tokens": n.path_tokens, "reach": n.reach_prob} for n in frontier._items]
        data = {
            "visited": sorted(self.visited),
            "failed": self.failed,
            "frontier": items,
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        tmp.replace(self.path)


# ──────────────────────────────────────────────────────────────────────────
# 브라우저 추출 (CSS 레이어 파서 — 이번 세션 라이브 수집서 검증된 코드 이식)
# ──────────────────────────────────────────────────────────────────────────
EXTRACT_JS = r"""
() => {
  function colorToAction(r,g,b){
    if (r>=110 && r<=140 && g<50 && b<50) return 'allin';
    if (r>200 && g<100 && b<100) return 'raise';
    if (r<100 && g>150 && b<160) return 'call';
    if (r<100 && g>100 && g<160 && b>150) return 'fold';
    return null;
  }
  function parseCell(cell){
    const cs = getComputedStyle(cell);
    const bgImg = cs.backgroundImage;
    if (bgImg === 'none') return null;
    const bgSize = cs.backgroundSize;
    const colorMatches = [...bgImg.matchAll(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/g)];
    const layerColors = [];
    for (let i=0;i<colorMatches.length;i+=2){ layerColors.push(colorMatches[i]); }
    const sizeParts = bgSize.split(',').map(s=>parseFloat(s.trim()));
    const result = {};
    let prevWidth = 0;
    for (let i=0;i<layerColors.length;i++){
      const [,r,g,b] = layerColors[i];
      const action = colorToAction(+r,+g,+b);
      const width = sizeParts[i];
      const freq = width - prevWidth;
      prevWidth = width;
      if (action) result[action] = (result[action]||0) + freq/100;
    }
    return result;
  }
  const cells = document.querySelectorAll('[data-tst^="range_table_cell_0_"]');
  const hands = {};
  let parsed = 0, none = 0;
  cells.forEach(cell => {
    const hand = cell.getAttribute('data-tst').replace('range_table_cell_0_','');
    const res = parseCell(cell);
    if (res === null) { none++; return; }
    hands[hand] = res;
    parsed++;
  });

  // ── 실측 사이즈: 히어로의 Actions 패널 버튼에서만 읽는다 ────────────────────
  // 컨테이너 [data-tst="study_action_btns"] 안의 [data-tst^="action_"] 버튼들이
  // "히어로가 지금 취할 수 있는" 액션이다. 각 버튼 data-tst 코드가 액션+사이즈를
  // 그대로 인코딩한다: action_<CODE>_<idx>, CODE ∈ {RAI(올인), R<size>(레이즈),
  // C(콜), F(폴드)}. 코드의 숫자는 화면 표시 텍스트("Raise 8" 등)와 verbatim 일치.
  // ⚠️ 헤더 카드(hspotcrd_action_text, 다른 포지션이 이미 취한 과거 액션)나
  //    핸드테이블 셀(htc_action_*)과는 접두어가 달라 절대 겹치지 않는다.
  const container = document.querySelector('[data-tst="study_action_btns"]');
  const btns = container
    ? [...container.querySelectorAll('[data-tst^="action_"]')]
    : [];
  const actions = [];       // [{action, size, code, text}]
  const raiseSizes = [];    // 논-올인 레이즈 to-금액(bb)
  const allinSizes = [];    // 올인 to-금액(bb)
  let allinPresent = false;
  for (const b of btns) {
    const tst = b.getAttribute('data-tst') || '';
    const m = tst.match(/^action_(.+)_\d+$/);
    if (!m) continue;
    const code = m[1];
    const text = (b.innerText || '').replace(/\s+/g, ' ').trim();
    if (code === 'RAI') {
      allinPresent = true;
      const am = text.match(/Allin\s+([\d]+(?:\.[\d]+)?)/i);
      const size = am ? parseFloat(am[1]) : null;
      if (size !== null) allinSizes.push(size);
      actions.push({action: 'allin', size, code, text});
    } else if (/^R\d/.test(code)) {              // R + 숫자 = 레이즈 (RAI는 위에서 걸러짐)
      const size = parseFloat(code.slice(1));
      if (!isNaN(size)) raiseSizes.push(size);
      actions.push({action: 'raise', size, code, text});
    } else if (code === 'C') {
      actions.push({action: 'call', size: null, code, text});
    } else if (code === 'F') {
      actions.push({action: 'fold', size: null, code, text});
    } else {
      actions.push({action: 'unknown', size: null, code, text});
    }
  }

  // ── 일일 한도: "X/100" 카운터가 유일한 권위 신호(문구는 늘 떠 있어 판단 불가) ──
  const bodyText = (document.body ? document.body.innerText : '') || '';
  const counterMatch = bodyText.match(/(\d+)\s*\/\s*100\b/);
  const used = counterMatch ? parseInt(counterMatch[1], 10) : null;
  const warnPresent = /Free accounts can browse 100 preflop spots per day/i.test(bodyText);

  return {
    hands, cellCount: cells.length, parsed, none,
    actions, actionsFound: btns.length,
    raiseSizes, allinSizes, allinPresent,
    used, warnPresent,
    bodyTextSample: bodyText.slice(0, 4000),
  };
}
"""


def _badsum_count(hands: dict) -> int:
    bad = 0
    for freqs in hands.values():
        s = sum(freqs.values())
        if not (0.9 <= s <= 1.1):
            bad += 1
    return bad


import re as _re

_COUNTER_RE = _re.compile(r"(\d+)\s*/\s*100\b")


def _parse_usage(text: str) -> Optional[int]:
    """페이지 텍스트에서 'X/100' 사용량 카운터를 파싱 → X(int) 또는 None."""
    m = _COUNTER_RE.search(text or "")
    return int(m.group(1)) if m else None


def read_usage(page) -> Optional[int]:
    """현재 로드된 페이지에서 사용량 카운터(X/100)를 읽는다(navigate 안 함).

    루프 진입 전 '이미 한도 근처인지'를 스팟 소모 없이 확인하는 데 쓴다.
    """
    try:
        return _parse_usage(page.inner_text("body"))
    except Exception:
        return None


def _limit_hit(used: Optional[int], warn_present: bool, rendered: bool) -> bool:
    """한도 도달 여부 확정.

    - 카운터를 읽었으면 그것만 신뢰: used >= DAILY_LIMIT 이면 한도 도달.
    - 카운터를 못 읽었고(파싱 실패) 레인지도 안 떴는데 경고 문구가 있으면 폴백으로 한도 간주.
      (경고 문구는 평상시에도 항상 떠 있어 단독 신호로 쓰면 안 되므로 폴백 한정.)
    """
    if used is not None:
        return used >= DAILY_LIMIT
    return warn_present and not rendered


class ExtractResult:
    def __init__(self, ok, hands=None, raise_size=None, allin_size=None,
                 reason="", raw=None, limit_hit=False, used=None):
        self.ok = ok
        self.hands = hands or {}
        self.raise_size = raise_size
        self.allin_size = allin_size
        self.reason = reason
        self.raw = raw or {}
        self.limit_hit = limit_hit
        self.used = used  # 이 노드 로드 시점의 일일 사용량(X/100의 X), 못 읽으면 None

    @property
    def remaining(self) -> Optional[int]:
        return None if self.used is None else DAILY_LIMIT - self.used


def extract_node(page, node_key: str, nav_timeout: int) -> ExtractResult:
    """한 노드로 navigate → 169핸드 파싱 + 실측 사이즈 읽기 + badSum 검증."""
    url = url_from_node_key(node_key)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=nav_timeout)
    except Exception as e:
        return ExtractResult(False, reason=f"navigate 실패: {e}")

    # 레인지 테이블 셀 렌더 대기(고정 sleep 대신 조건 대기)
    rendered = True
    try:
        page.wait_for_selector('[data-tst^="range_table_cell_0_"]', timeout=nav_timeout)
        # 배경 레이어(빈도 색)까지 채워질 때까지: 색 있는 셀이 충분히 나올 때까지 대기
        page.wait_for_function(
            """() => {
                const cs = document.querySelectorAll('[data-tst^="range_table_cell_0_"]');
                let n = 0;
                cs.forEach(c => { if (getComputedStyle(c).backgroundImage !== 'none') n++; });
                return n >= 150;
            }""",
            timeout=nav_timeout,
        )
        # 히어로 Actions 패널 버튼도 함께 대기(사이즈 실측 소스)
        page.wait_for_selector('[data-tst="study_action_btns"] [data-tst^="action_"]',
                               timeout=nav_timeout)
    except Exception:
        rendered = False
        # 테이블/액션이 안 뜸 → 카운터로 한도인지 확정(문구는 폴백)
        try:
            txt = page.inner_text("body")
        except Exception:
            txt = ""
        used = _parse_usage(txt)
        warn = LIMIT_WARN_PHRASE.lower() in txt.lower()
        if _limit_hit(used, warn, rendered):
            return ExtractResult(False, reason=f"일일 한도 도달(사용량 {used}/{DAILY_LIMIT})",
                                 limit_hit=True, used=used, raw={"bodyTextSample": txt[:4000]})
        return ExtractResult(False, reason="레인지 테이블 렌더 대기 타임아웃",
                             used=used, raw={"bodyTextSample": txt[:4000]})

    try:
        raw = page.evaluate(EXTRACT_JS)
    except Exception as e:
        return ExtractResult(False, reason=f"추출 JS 실패: {e}")

    used = raw.get("used")
    hands = raw.get("hands", {})
    # 렌더는 됐지만 카운터가 한도를 가리키면 안전 중단(경계 케이스)
    if _limit_hit(used, raw.get("warnPresent", False), rendered=True):
        return ExtractResult(False, reason=f"일일 한도 도달(사용량 {used}/{DAILY_LIMIT})",
                             limit_hit=True, used=used, raw=raw)
    if not hands:
        return ExtractResult(False, reason="파싱된 핸드 0개", used=used, raw=raw)

    bad = _badsum_count(hands)
    if bad > 0:
        return ExtractResult(False, reason=f"badSum 검증 실패({bad}핸드)", used=used, raw=raw)

    # 실측 사이즈: 히어로 Actions 패널 버튼에서 읽은 값(헤더/과거 액션과 분리됨).
    # ③ 실측대로 노드당 논-올인 레이즈는 1개 → 첫(유일한) 레이즈 사이즈를 쓴다.
    raise_sizes = raw.get("raiseSizes") or []
    allin_sizes = raw.get("allinSizes") or []
    raise_size = raise_sizes[0] if raise_sizes else None
    allin_size = allin_sizes[0] if allin_sizes else (
        ALLIN_FALLBACK_BB if raw.get("allinPresent") else None
    )
    return ExtractResult(True, hands=hands, raise_size=raise_size,
                         allin_size=allin_size, used=used, raw=raw)


# ──────────────────────────────────────────────────────────────────────────
# 저장 (기존 /gto/preflop/save 재사용)
# ──────────────────────────────────────────────────────────────────────────
def save_node(server: str, node_key: str, meta: dict, hands: dict,
              raise_size: Optional[float]) -> dict:
    import requests
    payload = {
        "position": meta["hero_position"],
        "vs_position": meta["vs_position"],
        "range_type": meta["range_type"],
        "raise_size": raise_size,
        "situation_label": meta["situation_label"],
        "hands": hands,
        "action_seq": node_key,  # D1: 실측 사이즈 키 verbatim
    }
    resp = requests.post(
        f"{server}/gto/preflop/save", json=payload, verify=False, timeout=30
    )
    resp.raise_for_status()
    return resp.json()


# ──────────────────────────────────────────────────────────────────────────
# CDP 연결
# ──────────────────────────────────────────────────────────────────────────
CHROME_HELP = """\
[크롬 디버그 세션이 필요합니다]

이 워커는 사용자가 로그인해 둔 GTO Wizard 크롬 세션에 CDP로 붙습니다.
아래처럼 크롬을 디버그 포트로 실행하고 GTO Wizard에 로그인한 뒤 다시 실행하세요:

  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\
      --remote-debugging-port=9222 \\
      --user-data-dir="$HOME/chrome-gto-debug"

그 창에서 https://app.gtowizard.com 에 로그인 → 이 스크립트를 다시 실행하세요.
(포트를 바꿨다면 --cdp-url http://localhost:PORT 로 지정)
"""


def connect_cdp(cdp_url: str):
    """(playwright, browser, page) 반환. 실패 시 안내 출력 후 (None,None,None)."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print(f"[오류] playwright 미설치: {e}\n  → pip install playwright && python3 -m playwright install chromium")
        return None, None, None

    p = sync_playwright().start()
    try:
        browser = p.chromium.connect_over_cdp(cdp_url)
    except Exception as e:
        print(f"[연결 실패] CDP {cdp_url} 에 붙지 못했습니다: {e}\n")
        print(CHROME_HELP)
        p.stop()
        return None, None, None

    # 로그인된 컨텍스트/페이지 확보: gtowizard 탭 우선, 없으면 새 페이지
    contexts = browser.contexts
    if not contexts:
        print("[연결 실패] 크롬 컨텍스트가 없습니다. 크롬 창을 하나 열어두세요.\n")
        print(CHROME_HELP)
        browser.close(); p.stop()
        return None, None, None
    ctx = contexts[0]
    page = None
    for pg in ctx.pages:
        try:
            if "gtowizard.com" in (pg.url or ""):
                page = pg
                break
        except Exception:
            continue
    if page is None:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return p, browser, page


# ──────────────────────────────────────────────────────────────────────────
# 메인 루프
# ──────────────────────────────────────────────────────────────────────────
def run(args) -> int:
    import urllib3
    urllib3.disable_warnings()  # 자체서명 HTTPS 경고 억제

    epsilon = args.epsilon
    collected = load_collected_from_db()
    print(f"[시작] DB 기수집 노드 {len(collected)}개")

    ckpt = Checkpoint(Path(args.checkpoint))
    frontier = tw.FrontierQueue()
    if ckpt.load() and ckpt.frontier_items:
        print(f"[재개] 체크포인트 로드: visited={len(ckpt.visited)} "
              f"frontier={len(ckpt.frontier_items)} failed={len(ckpt.failed)}")
        for tokens, reach in ckpt.frontier_items:
            frontier.push(tw.TreeNode(tokens, reach))
    else:
        seed_frontier, seed_visited = seed_frontier_from_db(collected, epsilon)
        ckpt.visited = set(collected.keys()) | seed_visited
        for tokens, reach in seed_frontier:
            frontier.push(tw.TreeNode(tokens, reach))
        print(f"[시드] DB 트리에서 프론티어 {len(frontier)}개 재구성 "
              f"(visited={len(ckpt.visited)})")

    # DB에 이미 있는 노드는 항상 visited로 취급(중복 재수집 방지)
    ckpt.visited |= set(collected.keys())

    # 연결
    p, browser, page = connect_cdp(args.cdp_url)
    if page is None:
        # 연결 실패는 크래시가 아니라 정상 종료(안내는 connect_cdp가 출력)
        return 0

    margin = args.safety_margin
    # 루프 진입 전, 현재 열려 있는 페이지에서 사용량을 스팟 소모 없이 미리 확인.
    init_used = read_usage(page)
    if init_used is not None:
        print(f"[한도] 현재 사용량 {init_used}/{DAILY_LIMIT} "
              f"(남은 여유 {DAILY_LIMIT - init_used}, 안전마진 {margin})")
        if DAILY_LIMIT - init_used <= margin:
            print("[안전 종료] 남은 여유가 안전마진 이하 — 새 수집을 시작하지 않습니다. "
                  "내일 다시 실행하면 체크포인트에서 이어갑니다.")
            try:
                browser.close(); p.stop()
            except Exception:
                pass
            return 0

    processed = 0
    saved = 0
    try:
        while len(frontier) > 0 and processed < args.limit:
            node = frontier.pop()
            key = node.node_key
            if key in ckpt.visited:
                continue

            meta = derive_node_meta(key)
            if meta is None:
                # 결정 노드가 아님(베팅 종료) — 방문 처리하고 스킵
                ckpt.visited.add(key)
                continue

            processed += 1
            print(f"\n[{processed}/{args.limit}] node={key!r} reach={node.reach_prob:.5f} "
                  f"→ {meta['situation_label']}")
            print(f"        url={url_from_node_key(key)}")

            res = extract_node(page, key, args.nav_timeout)

            if res.limit_hit:
                print("        !! 일일 한도/제한 신호 감지 — 안전하게 중단하고 재개 가능 상태로 저장")
                processed -= 1  # 이 노드는 처리 못 함
                break

            if not res.ok:
                print(f"        [스킵] {res.reason} (저장 안 함, 재시도 대상 기록)")
                if key not in ckpt.failed:
                    ckpt.failed.append(key)
                ckpt.visited.add(key)  # 이번 실행에서 무한 재시도 방지(failed에 남아 추후 점검)
                ckpt.save(frontier)
                continue

            usage_str = (f" [사용량 {res.used}/{DAILY_LIMIT}, 남은 {res.remaining}]"
                         if res.used is not None else "")
            print(f"        추출 OK: {len(res.hands)}핸드, raise_size={res.raise_size} "
                  f"allin_size={res.allin_size}{usage_str}")

            if args.dry_run:
                print("        [dry-run] 저장/확장 생략. 집계 빈도:")
                agg = tw.aggregate_frequencies(res.hands)
                for a, f in tw.branch_actions(agg, epsilon):
                    print(f"          {a}: {f:.4f}")
                print(f"          raiseSizes(raw)={res.raw.get('raiseSizes')} "
                      f"allinSizes(raw)={res.raw.get('allinSizes')}")
                print(f"          Actions 패널(실측): {res.raw.get('actions')}")
                # dry-run은 첫 노드만 자세히 보고 종료
                break

            # 저장
            try:
                out = save_node(args.server, key, meta, res.hands, res.raise_size)
            except Exception as e:
                print(f"        [저장 실패] {e} (서버 실행 중인지 확인). 재시도 대상 기록")
                if key not in ckpt.failed:
                    ckpt.failed.append(key)
                ckpt.save(frontier)
                continue
            saved += 1
            ckpt.visited.add(key)
            if key in ckpt.failed:
                ckpt.failed.remove(key)
            print(f"        [저장] {out.get('situation')} action_seq={out.get('action_seq')!r}")

            # 자식 확장(도달확률 가중 push)
            size_map = {"raise": res.raise_size, "allin": res.allin_size}
            children = compute_children(key, res.hands, size_map, node.reach_prob, epsilon)
            pushed = 0
            for child_key, child_tokens, child_reach in children:
                if child_key in ckpt.visited:
                    continue
                frontier.push(tw.TreeNode(child_tokens, child_reach))
                pushed += 1
            print(f"        자식 {pushed}개 push (frontier={len(frontier)})")

            ckpt.save(frontier)

            # 이번 노드 로드로 사용량이 안전마진 이하로 떨어졌으면 다음 navigate 전에 안전 종료
            if res.remaining is not None and res.remaining <= margin:
                print(f"        [안전 종료] 남은 여유 {res.remaining} ≤ 안전마진 {margin} "
                      f"— 더 이상 새 노드로 이동하지 않습니다(체크포인트 보존, 재실행 시 이어감).")
                break

        # 루프 종료 후 최종 체크포인트
        ckpt.save(frontier)
    finally:
        try:
            browser.close()
        except Exception:
            pass
        try:
            p.stop()
        except Exception:
            pass

    print(f"\n[완료] 처리 {processed}개 / 저장 {saved}개 / "
          f"frontier 잔여 {len(frontier)} / failed {len(ckpt.failed)}")
    if ckpt.failed:
        print(f"  재시도 대상(badSum/저장실패): {ckpt.failed[:20]}"
              + (" …" if len(ckpt.failed) > 20 else ""))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="④ 데이터 기반 프리플랍 트리 워커 (Playwright/CDP 드라이버)")
    ap.add_argument("--limit", type=int, default=90,
                    help="이번 실행 최대 신규 노드 수(기본 90, 무료 100/일 안전마진)")
    ap.add_argument("--dry-run", action="store_true",
                    help="추출/검증만, 저장 안 함(첫 노드 상세 출력)")
    ap.add_argument("--cdp-url", default=DEFAULT_CDP, help="크롬 CDP 엔드포인트")
    ap.add_argument("--server", default=DEFAULT_SERVER, help="로컬 FastAPI 베이스 URL")
    ap.add_argument("--checkpoint", default=str(DEFAULT_CHECKPOINT), help="진행상황 JSON 경로")
    ap.add_argument("--epsilon", type=float, default=tw.EPSILON, help="분기 빈도 컷")
    ap.add_argument("--nav-timeout", type=int, default=30000, help="navigate/셀 대기 ms")
    ap.add_argument("--safety-margin", type=int, default=SAFETY_MARGIN,
                    help=f"남은 스팟이 이 값 이하면 새 수집 중단(기본 {SAFETY_MARGIN}, 무료 100/일 보호)")
    return ap


def main():
    args = build_parser().parse_args()
    try:
        sys.exit(run(args))
    except KeyboardInterrupt:
        print("\n[중단] Ctrl+C — 체크포인트는 마지막 저장 지점까지 보존됨. 재실행하면 이어서 진행.")
        sys.exit(130)


if __name__ == "__main__":
    main()
