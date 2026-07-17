"""
④ 데이터 기반 프리플랍 트리 워커 — 핵심 로직 모듈.

설계: docs/gto-preflop-tree.md "데이터 기반 트리 수집 방식" 섹션을 그대로 구현.
- 가정 없이: GTO Wizard가 실제로 보여주는 액션/사이즈/빈도로만 가지를 뻗는다.
- 분기 기준: 레인지 콤보 가중 합산 빈도 > EPSILON(0.05%)인 액션만 자식으로 확장.
- 저장 키: 실측 사이즈 그대로(verbatim). 깊이-캐노니컬 하드코딩 사용 안 함.
- 우선순위: 도달 확률(경로상 액션 빈도 누적) 가중 best-first — 자주 나오는 라인부터.

이 모듈은 브라우저 자동화(Playwright/Chrome MCP)와 독립적인 **순수 로직**만 담는다.
실제 브라우저 조작(navigate/extract)은 별도 드라이버(Chrome MCP 대화형 또는 향후
Playwright 스크립트)가 이 모듈의 함수를 호출해 사용한다.
"""
from typing import Optional

EPSILON = 0.0005  # 0.05% — 레인지 합산 빈도 컷 (③ 실측: 노드당 논-올인 레이즈 1개)

COMBOS = {"pair": 6, "suited": 4, "offsuit": 12}


def combo_weight(hand: str) -> int:
    """'AA'→6(pair), 'AKs'→4(suited), 'AKo'→12(offsuit)."""
    if len(hand) == 2:
        return COMBOS["pair"]
    return COMBOS["suited"] if hand.endswith("s") else COMBOS["offsuit"]


def aggregate_frequencies(hands: dict) -> dict:
    """{hand: {action: freq}} → {action: 콤보가중 합산비율(0~1)}.

    hands는 노드 추출기가 반환한 169(또는 그 이하, 오프너 레인지 밖 핸드는 이미 제외)
    핸드의 액션별 빈도. 합산은 콤보 가중 평균(AA=6, AKs=4, AKo=12 등)이라 핸드 개수가
    아니라 실제 콤보 비율을 반영한다.
    """
    total_w = 0
    agg: dict = {}
    for hand, freqs in hands.items():
        w = combo_weight(hand)
        total_w += w
        for action, freq in freqs.items():
            agg[action] = agg.get(action, 0.0) + freq * w
    if total_w == 0:
        return {}
    return {a: v / total_w for a, v in agg.items()}


def branch_actions(agg_freqs: dict, epsilon: float = EPSILON) -> list:
    """합산 빈도 > epsilon인 액션만, 빈도 내림차순으로 반환 (best-first 우선순위 기준).

    fold/call/raise/allin 어떤 액션이든 이 컷을 넘으면 자식 노드로 확장 대상이다.
    "버튼이 있다"가 아니라 "실제로 콤보 비중이 있다"가 유일한 기준(가정 배제 원칙).
    """
    items = [(a, f) for a, f in agg_freqs.items() if f > epsilon]
    items.sort(key=lambda x: -x[1])
    return items


def action_to_token(action: str, raise_size: Optional[float] = None) -> str:
    """액션명 → 노드 키 토큰. raise/allin은 실측 사이즈(bb)를 verbatim으로 포함."""
    if action == "fold":
        return "F"
    if action == "check":
        return "X"
    if action == "call":
        return "C"
    if action in ("raise", "allin"):
        if raise_size is None:
            raise ValueError(f"{action} 토큰 생성엔 실측 raise_size 필요(추측 금지)")
        s = raise_size
        s_str = str(int(s)) if float(s).is_integer() else str(s)
        return f"R{s_str}"
    raise ValueError(f"알 수 없는 액션: {action}")


class TreeNode:
    """방문 대상 노드. path = 부모까지의 노드 키(토큰 리스트), reach_prob = 이 노드에
    도달할 누적 확률(빈도 가중, 우선순위 큐 정렬용)."""

    def __init__(self, path_tokens: list, reach_prob: float):
        self.path_tokens = path_tokens
        self.reach_prob = reach_prob

    @property
    def node_key(self) -> str:
        return "-".join(self.path_tokens)

    def __repr__(self):
        return f"TreeNode({self.node_key!r}, reach={self.reach_prob:.4f})"


def expand_node(node: TreeNode, agg_freqs: dict) -> list:
    """한 노드의 집계 빈도로부터 자식 TreeNode 목록 생성(빈도 가중 reach_prob 전파).

    raise/allin 토큰은 이 함수 호출 전에 실측 사이즈로 이미 치환된 액션명
    (예: "raise:8.0")을 넘기거나, 별도로 raise_size를 채워 action_to_token에 넘겨야 한다.
    이 함수는 액션→토큰 변환은 호출자가 처리했다고 가정하고 우선순위 전파만 담당한다.
    """
    children = []
    for action_token, freq in branch_actions(agg_freqs):
        children.append(TreeNode(node.path_tokens + [action_token], node.reach_prob * freq))
    children.sort(key=lambda n: -n.reach_prob)
    return children


class FrontierQueue:
    """도달확률 내림차순 best-first 우선순위 큐(간단한 리스트 기반 — 노드 수가
    ③에서 실측된 규모라 힙이 굳이 필요 없음)."""

    def __init__(self):
        self._items: list = []

    def push(self, node: TreeNode):
        self._items.append(node)
        self._items.sort(key=lambda n: -n.reach_prob)

    def push_all(self, nodes: list):
        for n in nodes:
            self.push(n)

    def pop(self) -> Optional[TreeNode]:
        if not self._items:
            return None
        return self._items.pop(0)

    def __len__(self):
        return len(self._items)
