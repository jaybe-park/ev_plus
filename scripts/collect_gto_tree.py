#!/usr/bin/env python3
"""
프리플랍 트리 수집 드라이버 — 디버그 크롬(CDP)에 붙어 GTO Wizard 노드를 추출·저장한다.

규칙: docs/spec/gto-preflop.md "수집" 절(ADR 0009~0012). 순수 로직은 gto_tree_worker.py.
노드 1개: url_from_node_key로 이동 → 169셀 레이어 파싱 + 실측 사이즈 → badSum 검증 →
POST /gto/preflop/save → 콤보 가중 빈도 > ε 액션만 자식으로 frontier에 push(도달확률 순).
체크포인트(visited/frontier/failed)는 저장마다 기록, 없거나 비면 DB 트리에서 다시 시드한다.
사용: --dry-run(첫 노드 추출만) · --limit N · --reseed-checkpoint [--dry-run](브라우저 없이
DB에서 frontier 재시드, 기존 파일은 .json.bak) · 운영 방법은 spec "운영 방법".
"""
import argparse
import json
import random
import shutil
import sys
import time
from collections import deque
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import gto_tree_worker as tw  # 순수 로직 재사용 (집계/분기/토큰/큐)
from gto.url_generator import url_from_node_key
from gto.loader import freq_sum_ok, read_preflop_nodes, collected_by_seq
from gto.node_key import POSITIONS, split_key, _replay, derive_node_meta  # noqa: E402,F401

DEFAULT_CHECKPOINT = ROOT / "gto_tree_checkpoint.json"
DEFAULT_SERVER = "https://localhost:8765"
DEFAULT_CDP = "http://localhost:9222"

# 100bb 트리에서 올인 to-amount = 시작 스택(정의상 결정론적). 화면에서 올인 사이즈를
# 읽지 못했을 때와, DB에 올인 사이즈가 없는 시드 경로에서 쓴다.
ALLIN_FALLBACK_BB = 100.0

# 일일 한도: 상단 "X/100" 카운터가 유일한 권위 신호다. 안내 문구는 평상시에도 떠 있어
# 카운터를 못 읽을 때만 폴백으로 쓴다. 스팟 이동 1회 = 1 소모.
DAILY_LIMIT = 100
SAFETY_MARGIN = 5  # 남은 스팟이 이 값 이하가 되면 새 수집을 멈춘다.
LIMIT_WARN_PHRASE = "Free accounts can browse 100 preflop spots per day"

# 환경 오류(크래시·타임아웃·네트워크)는 데이터 이상이 아니라 재시도 대상 — failed에 넣지 않고
# frontier로 되돌린다(ADR 0012).
ENV_FAILURE_MARKERS = ("navigate 실패", "렌더 대기 타임아웃", "추출 JS 실패")
CONSEC_ENV_RECOVERY_THRESHOLD = 2   # 연속 환경오류 이 횟수부터 탭 재생성 시도
CONSEC_ENV_ABORT_THRESHOLD = 6      # 재생성해도 계속 실패하면 이 횟수에서 안전 중단
PAGE_RECYCLE_EVERY = 25             # 크래시 없어도 이만큼 처리할 때마다 예방적 탭 재생성


def is_env_failure(reason: str) -> bool:
    """실패 사유가 '재시도하면 되는 환경 오류'인지 판정(진짜 데이터 이상과 구분)."""
    return any(marker in (reason or "") for marker in ENV_FAILURE_MARKERS)


def recreate_page(ctx, old_page):
    """크래시/누적 메모리 대비 탭을 새로 만든다. 같은 컨텍스트라 로그인 세션(쿠키)은 유지."""
    try:
        old_page.close()
    except Exception:
        pass
    new_page = ctx.new_page()
    return new_page


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
def load_collected_from_db(conn=None) -> dict:
    """DB의 수집 노드 → {action_seq: {hands, raise_size}} (gto.loader.read_preflop_nodes).

    conn을 주지 않으면 앱 연결(get_connection)을 열고 닫는다. 읽기 전용 연결도 된다.
    """
    own = conn is None
    if own:
        from db.connection import get_connection
        conn = get_connection()
    try:
        return collected_by_seq(read_preflop_nodes(conn))
    finally:
        if own:
            conn.close()


def load_missing_queue_from_db() -> list:
    """gto_missing_spots_preflop의 미완료(collected=0) 시퀀스 큐 항목(range_type='seq')
    노드 키 목록을 반환한다. 노드 키는 vs_position 칸에 저장돼 있다(advisor._save_missing_seq).
    """
    from db.connection import get_connection
    conn = get_connection()
    rows = conn.execute(
        "SELECT vs_position FROM gto_missing_spots_preflop "
        "WHERE range_type='seq' AND collected=0"
    ).fetchall()
    conn.close()
    return [r["vs_position"] for r in rows]


# 큐(트리 밖 스팟)에서 프론티어로 추가하는 노드의 우선순위 — 정상 트리 프론티어(reach ≥
# epsilon=0.0005)보다 항상 낮게 둔다. ADR 0011 "트리 밖 스팟 큐는 보조 2순위".
QUEUE_FRONTIER_REACH = 1e-9


def next_action_freq(node: dict, token: str) -> float:
    """수집된 노드에서 다음 토큰 액션의 콤보 가중 빈도(0~1).

    F=fold, C/X=call. 레이즈 토큰은 노드의 실측 raise_size와 같으면 raise, 올인 사이즈
    (ALLIN_FALLBACK_BB)면 allin, raise_size를 모르면 raise+allin, 그 밖의 사이즈는 0
    (이 노드의 화면에 없는 사이즈 — 트리 밖).
    """
    agg = tw.aggregate_frequencies(node.get("hands") or {})
    if token == "F":
        return agg.get("fold", 0.0)
    if token in ("C", "X"):
        return agg.get("call", 0.0)
    try:
        size = float(token[1:])
    except ValueError:
        return 0.0
    raise_size = node.get("raise_size")
    freq = 0.0
    if raise_size is None:
        return agg.get("raise", 0.0) + agg.get("allin", 0.0)
    if abs(size - raise_size) < 1e-9:
        freq += agg.get("raise", 0.0)
    if abs(size - ALLIN_FALLBACK_BB) < 1e-9:
        freq += agg.get("allin", 0.0)
    return freq


def queue_frontier_additions(missing_keys: list, collected: dict,
                             epsilon: float = tw.EPSILON) -> list:
    """미수집 큐 키들 → 프론티어에 추가할 (tokens, reach) 목록 (ADR 0011 "큐=2순위").

    건너뛰는 키: 이미 수집됨 / 결정 노드 아님 / **트리 밖**(경로의 수집된 조상 노드에서 다음
    액션 빈도가 epsilon 이하 — 예: UTG RFI에서 림프 `C`, 화면에 없는 사이즈 `R2.9`).
    그 밖엔 **가장 얕은 미수집 조상**(자기 자신 포함)만 하나 추가한다 — 조상이 먼저 수집돼야
    자식이 정상 확장(compute_children)으로 이어지고, 다음 실행에서 한 단계 더 깊은 조상
    또는 키 자신으로 넘어간다. reach는 QUEUE_FRONTIER_REACH로 고정(보조 2순위).
    """
    out = []
    seen = set()
    for key in missing_keys:
        if key in collected:
            continue
        if derive_node_meta(key) is None:
            continue
        tokens = split_key(key)
        target_tokens = None
        off_tree = False
        for i in range(len(tokens) + 1):
            prefix_key = "-".join(tokens[:i])
            node = collected.get(prefix_key)
            if node is None:
                if target_tokens is None:
                    target_tokens = tokens[:i]
                continue
            if i < len(tokens) and next_action_freq(node, tokens[i]) <= epsilon:
                off_tree = True
                break
        if off_tree or target_tokens is None:
            continue
        target_key = "-".join(target_tokens)
        if target_key in seen:
            continue
        seen.add(target_key)
        out.append((target_tokens, QUEUE_FRONTIER_REACH))
    return out


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


def lost_visited_keys(visited, failed, collected: dict) -> set:
    """visited 중 결정 노드인데 DB·failed에 없는 키(덮어써져 사라진 노드)."""
    failed = set(failed)
    return {k for k in visited
            if k not in collected and k not in failed and derive_node_meta(k) is not None}


def reseed_checkpoint(ckpt: "Checkpoint", collected: dict, epsilon: float = tw.EPSILON) -> dict:
    """체크포인트 frontier를 DB 트리에서 다시 만든다(브라우저·네트워크 없음).

    - visited: 기존 visited 보존 + DB 수집 키 추가. 단 "visited인데 DB·failed에 없는" 결정
      노드는 빼서 다시 수집되게 한다. failed는 그대로.
    - frontier: DB 시드(seed_frontier_from_db) ∪ 기존 frontier, visited 제외, 같은 키는 큰 reach.
    ckpt를 제자리에서 바꾸고 변경 요약 dict를 돌려준다(저장은 호출자).
    """
    seed, _ = seed_frontier_from_db(collected, epsilon)
    lost = lost_visited_keys(ckpt.visited, ckpt.failed, collected)
    visited = (set(ckpt.visited) - lost) | set(collected)
    merged: dict = {}
    for tokens, reach in list(ckpt.frontier_items) + list(seed):
        key = "-".join(tokens)
        if key in visited:
            continue
        if key not in merged or reach > merged[key][1]:
            merged[key] = (list(tokens), reach)
    old_keys = {"-".join(t) for t, _ in ckpt.frontier_items}
    summary = {
        "visited_before": len(ckpt.visited), "visited_after": len(visited),
        "frontier_before": len(ckpt.frontier_items), "frontier_after": len(merged),
        "added": sorted(k for k in merged if k not in old_keys),
        "dropped": sorted(k for k in old_keys if k not in merged),
        "lost_requeued": sorted(lost),
        "failed": list(ckpt.failed),
    }
    ckpt.visited = visited
    ckpt.frontier_items = sorted(merged.values(), key=lambda tr: -tr[1])
    return summary


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
        self._write(items)

    def save_items(self):
        """frontier_items 그대로 기록(재시드용)."""
        self._write([{"tokens": t, "reach": r} for t, r in self.frontier_items])

    def _write(self, items: list):
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
    return sum(1 for freqs in hands.values() if not freq_sum_ok(freqs))


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

    # 레인지 테이블 셀 렌더 대기 — 색칠된 셀 수가 600ms 이상 변하지 않으면 완료.
    # 깊은 노드는 레인지가 원래 좁아(예 88/169) 절대 개수 임계값으로는 판정할 수 없다.
    rendered = True
    try:
        page.wait_for_selector('[data-tst^="range_table_cell_0_"]', timeout=nav_timeout)
        # 매 노드마다 안정성 추적 상태 리셋(이전 노드의 폴링 상태가 새 노드로 새는 것 방지)
        page.evaluate("() => { window.__gtowColoredCount = -1; window.__gtowStableSince = 0; }")
        page.wait_for_function(
            """() => {
                const cs = document.querySelectorAll('[data-tst^="range_table_cell_0_"]');
                let n = 0;
                cs.forEach(c => { if (getComputedStyle(c).backgroundImage !== 'none') n++; });
                if (n === 0) return false;  // 아직 아무것도 안 칠해짐 — 확실히 로딩 중
                const now = Date.now();
                if (window.__gtowColoredCount !== n) {
                    window.__gtowColoredCount = n;
                    window.__gtowStableSince = now;
                    return false;  // 개수가 방금 바뀜 — 아직 로딩/변화 중
                }
                // 개수가 마지막 폴링 이후 그대로 → 600ms 이상 안 바뀌면 렌더 완료로 간주
                return (now - window.__gtowStableSince) >= 600;
            }""",
            timeout=nav_timeout,
            polling=200,
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
    # 노드당 논-올인 레이즈는 1개 → 첫(유일한) 레이즈 사이즈를 쓴다.
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
        "action_seq": node_key,  # ADR 0009: 실측 사이즈 키 verbatim
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
    """(playwright, browser, ctx, page) 반환. 실패 시 안내 출력 후 (None,None,None,None)."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print(f"[오류] playwright 미설치: {e}\n  → pip install playwright && python3 -m playwright install chromium")
        return None, None, None, None

    p = sync_playwright().start()
    try:
        browser = p.chromium.connect_over_cdp(cdp_url)
    except Exception as e:
        print(f"[연결 실패] CDP {cdp_url} 에 붙지 못했습니다: {e}\n")
        print(CHROME_HELP)
        p.stop()
        return None, None, None, None

    # 로그인된 컨텍스트/페이지 확보: gtowizard 탭 우선, 없으면 새 페이지
    contexts = browser.contexts
    if not contexts:
        print("[연결 실패] 크롬 컨텍스트가 없습니다. 크롬 창을 하나 열어두세요.\n")
        print(CHROME_HELP)
        browser.close(); p.stop()
        return None, None, None, None
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
    return p, browser, ctx, page


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

    # 미수집 큐(range_type='seq')를 프론티어에 2순위로 반영(ADR 0011). 체크포인트를 이어가도
    # 매 실행 다시 본다(새 큐 항목, 조상이 수집돼 한 단계 깊어진 항목).
    missing_keys = load_missing_queue_from_db()
    if missing_keys:
        existing_frontier_keys = {n.node_key for n in frontier._items}
        added = 0
        for tokens, reach in queue_frontier_additions(missing_keys, collected, epsilon):
            key = "-".join(tokens)
            if key in ckpt.visited or key in existing_frontier_keys:
                continue
            frontier.push(tw.TreeNode(tokens, reach))
            existing_frontier_keys.add(key)
            added += 1
        if added:
            print(f"[큐] 미수집 큐({len(missing_keys)}건)에서 프론티어에 {added}개 추가"
                  "(ADR 0011 2순위 — 조상 미수집이면 조상부터)")

    # 연결
    p, browser, ctx, page = connect_cdp(args.cdp_url)
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
    consec_env_fail = 0  # 연속 환경오류(크래시/타임아웃 등) 카운터 — 성공하면 리셋
    consec_save_fail = 0  # 연속 저장(POST) 실패 카운터 — 성공하면 리셋
    since_recycle = 0    # 마지막 탭 재생성 이후 처리한 노드 수 — 예방적 재생성용
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

            if processed > 0:
                delay = random.uniform(args.min_delay, args.max_delay)
                print(f"        (다음 요청 전 {delay:.1f}초 대기 — 기계적 패턴 회피)")
                time.sleep(delay)

            processed += 1
            print(f"\n[{processed}/{args.limit}] node={key!r} reach={node.reach_prob:.5f} "
                  f"→ {meta['situation_label']}")
            print(f"        url={url_from_node_key(key)}")

            res = extract_node(page, key, args.nav_timeout)

            if res.limit_hit:
                print("        !! 일일 한도/제한 신호 감지 — 안전하게 중단하고 재개 가능 상태로 저장")
                processed -= 1  # 이 노드는 처리 못 함
                # 꺼낸 노드를 되돌린 뒤 중단해야 체크포인트에서 유실되지 않는다.
                frontier.push(node)
                break

            if not res.ok:
                if is_env_failure(res.reason):
                    # 환경 오류 — failed(영구 no-retry)에 넣지 않고 큐에 되돌려 재시도한다.
                    consec_env_fail += 1
                    processed -= 1  # 실제로 처리 못 함 — limit 카운트에서 제외
                    print(f"        [환경오류 {consec_env_fail}/{CONSEC_ENV_ABORT_THRESHOLD}] "
                          f"{res.reason} — 재시도 대상으로 큐에 되돌림(영구 실패 아님)")
                    frontier.push(node)

                    if consec_env_fail == CONSEC_ENV_RECOVERY_THRESHOLD:
                        print(f"        [자동 복구] 연속 환경오류 {consec_env_fail}회 — "
                              f"탭을 새로 만들어 이어갑니다(로그인 세션은 유지됨).")
                        try:
                            page = recreate_page(ctx, page)
                        except Exception as e:
                            print(f"        [복구 실패] 탭 재생성 중 오류: {e}")
                        since_recycle = 0

                    if consec_env_fail >= CONSEC_ENV_ABORT_THRESHOLD:
                        print(f"        [안전 중단] 탭을 재생성했는데도 환경오류가 "
                              f"{consec_env_fail}회 연속 — 더 진행해도 의미 없어 중단합니다. "
                              f"체크포인트 보존(재실행하면 이어감, 크롬 상태를 확인해보세요).")
                        ckpt.save(frontier)
                        break

                    ckpt.save(frontier)
                    continue

                # 진짜 데이터 이상(badSum, 파싱된 핸드 0개 등) — 사람 확인 필요, 영구 no-retry
                print(f"        [스킵] {res.reason} (저장 안 함, 재시도 대상 기록)")
                if key not in ckpt.failed:
                    ckpt.failed.append(key)
                ckpt.visited.add(key)  # 이번 실행에서 무한 재시도 방지(failed에 남아 추후 점검)
                ckpt.save(frontier)
                continue

            consec_env_fail = 0  # 성공 처리 진입 — 연속 환경오류 카운터 리셋

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

            # 저장 (로컬 백엔드 문제는 데이터 이상이 아니라 환경 오류 — 큐에 되돌려 재시도)
            try:
                out = save_node(args.server, key, meta, res.hands, res.raise_size)
            except Exception as e:
                processed -= 1
                consec_save_fail += 1
                print(f"        [저장 실패 {consec_save_fail}/{CONSEC_ENV_ABORT_THRESHOLD}] {e} "
                      f"(서버 실행 중인지 확인) — 재시도 대상으로 큐에 되돌림")
                frontier.push(node)
                # 저장이 연속 실패하면(백엔드가 꺼짐 등) 같은 노드를 무한 재시도해 일일 한도를
                # 소진하지 않도록 환경오류와 같은 기준으로 안전 중단한다(노드는 frontier에 보존).
                if consec_save_fail >= CONSEC_ENV_ABORT_THRESHOLD:
                    print(f"        [안전 중단] 저장이 {consec_save_fail}회 연속 실패 — "
                          f"서버 확인(백엔드가 켜져 있는지 https://localhost:8765). "
                          f"체크포인트 보존(재실행하면 이어감).")
                    ckpt.save(frontier)
                    break
                ckpt.save(frontier)
                continue
            consec_save_fail = 0  # 저장 성공 — 연속 저장실패 카운터 리셋
            saved += 1
            since_recycle += 1
            ckpt.visited.add(key)
            if key in ckpt.failed:
                ckpt.failed.remove(key)
            print(f"        [저장] {out.get('situation')} action_seq={out.get('action_seq')!r}")

            if since_recycle >= PAGE_RECYCLE_EVERY:
                print(f"        [예방적 탭 재생성] {PAGE_RECYCLE_EVERY}개 처리 — "
                      f"누적 메모리 방지를 위해 탭을 새로 만듭니다.")
                try:
                    page = recreate_page(ctx, page)
                except Exception as e:
                    print(f"        [재생성 실패] {e} (계속 진행, 다음 크래시 시 재시도)")
                since_recycle = 0

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
        description="프리플랍 GTO 트리 수집 (Playwright/CDP 드라이버)")
    ap.add_argument("--limit", type=int, default=90,
                    help="이번 실행 최대 신규 노드 수(기본 90, 무료 100/일 안전마진)")
    ap.add_argument("--dry-run", action="store_true",
                    help="추출/검증만, 저장 안 함(첫 노드 상세 출력). --reseed-checkpoint와 함께면 "
                         "바뀔 내용만 출력")
    ap.add_argument("--reseed-checkpoint", action="store_true",
                    help="브라우저 없이 DB(읽기 전용, EV_PLUS_DB → poker.db)에서 체크포인트 "
                         "frontier를 다시 만든다. 기존 파일은 <checkpoint>.bak으로 복사")
    ap.add_argument("--cdp-url", default=DEFAULT_CDP, help="크롬 CDP 엔드포인트")
    ap.add_argument("--server", default=DEFAULT_SERVER, help="로컬 FastAPI 베이스 URL")
    ap.add_argument("--checkpoint", default=str(DEFAULT_CHECKPOINT), help="진행상황 JSON 경로")
    ap.add_argument("--epsilon", type=float, default=tw.EPSILON, help="분기 빈도 컷")
    ap.add_argument("--nav-timeout", type=int, default=30000, help="navigate/셀 대기 ms")
    ap.add_argument("--safety-margin", type=int, default=SAFETY_MARGIN,
                    help=f"남은 스팟이 이 값 이하면 새 수집 중단(기본 {SAFETY_MARGIN}, 무료 100/일 보호)")
    ap.add_argument("--min-delay", type=float, default=2.0,
                    help="노드 처리 사이 최소 지연(초). 기계적으로 빠른 요청 패턴을 피하기 위한 배려/안전장치")
    ap.add_argument("--max-delay", type=float, default=5.0,
                    help="노드 처리 사이 최대 지연(초) — 실제 지연은 [min,max] 균등분포 랜덤")
    return ap


def run_reseed(args) -> int:
    """--reseed-checkpoint: DB를 읽기 전용으로 열어 체크포인트를 재시드한다(네트워크 없음)."""
    from db.connection import get_readonly_connection
    conn = get_readonly_connection()
    try:
        collected = load_collected_from_db(conn)
    finally:
        conn.close()
    path = Path(args.checkpoint)
    ckpt = Checkpoint(path)
    existed = ckpt.load()
    if existed and ckpt.failed:
        print(f"[경고] failed {sorted(ckpt.failed)}는 그대로 보존됩니다(재시드 대상 아님) — 재수집하려면 따로 비우세요.")
    summary = reseed_checkpoint(ckpt, collected, args.epsilon)
    print(f"[재시드] DB 수집 노드 {len(collected)}개, 체크포인트 {'있음' if existed else '없음'}({path})")
    print(f"  failed: {summary['failed'] or '[]'}")
    print(f"  visited {summary['visited_before']} → {summary['visited_after']}, "
          f"frontier {summary['frontier_before']} → {summary['frontier_after']}")
    print(f"  frontier 추가 {len(summary['added'])}: {summary['added']}")
    print(f"  frontier 제외(이미 visited) {len(summary['dropped'])}: {summary['dropped']}")
    print(f"  visited에서 빼 재수집 {len(summary['lost_requeued'])}: {summary['lost_requeued']}")
    if args.dry_run:
        print("[dry-run] 체크포인트를 쓰지 않았습니다.")
        return 0
    if existed:
        backup = path.with_name(path.name + ".bak")
        if backup.exists():  # 원본 백업은 한 번만 — 재실행이 첫 백업을 덮어쓰지 않게 한다
            backup = path.with_name(path.name + f".bak-{int(time.time())}")
        shutil.copy2(path, backup)
        print(f"  백업: {backup}")
    ckpt.save_items()
    print(f"  저장: {path}")
    return 0


def main():
    args = build_parser().parse_args()
    if args.reseed_checkpoint:
        sys.exit(run_reseed(args))
    try:
        sys.exit(run(args))
    except KeyboardInterrupt:
        print("\n[중단] Ctrl+C — 체크포인트는 마지막 저장 지점까지 보존됨. 재실행하면 이어서 진행.")
        sys.exit(130)


if __name__ == "__main__":
    main()
