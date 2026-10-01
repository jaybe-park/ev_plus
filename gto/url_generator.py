"""
GTO Wizard URL·노드 키 유틸

URL 패턴:
  https://app.gtowizard.com/solutions?...&preflop_actions=R2.5-R8-F-F-F-F&history_spot=6

- preflop_actions: 해당 결정 직전까지의 액션 시퀀스 (R{size} = 레이즈, F = 폴드)
- history_spot: 해당 결정이 전체 시퀀스의 몇 번째 행동인지 (0-indexed)

포지션 순서 (6-max): UTG(0) → HJ(1) → CO(2) → BTN(3) → SB(4) → BB(5)
"""

POSITIONS = ["UTG", "HJ", "CO", "BTN", "SB", "BB"]
POS_INDEX = {p: i for i, p in enumerate(POSITIONS)}

BASE = (
    "https://app.gtowizard.com/solutions"
    "?solution_type=gwiz&gmfs_solution_tab=ai_sols"
    "&gametype=Cash6mGeneral_6mNL25R25&depth=100"
)

# 깊이-캐노니컬 사이즈 표 — v12 마이그레이션 백필(db.schema.backfill_v12)의
# situation_to_node_key 전용이다. 런타임 스냅·저장 키는 실측 사이즈만 쓴다(ADR 0009·0010).
CANONICAL_OPEN_SIZE = {"UTG": 2.5, "HJ": 2.5, "CO": 2.5, "BTN": 2.5, "SB": 3.5}
CANONICAL_RAISE_BY_DEPTH = {1: 2.5, 2: 8.0, 3: 17.5, 4: 35.0}
_CANONICAL_MAX_DEPTH = 4  # 100bb 기준 5벳(35) 이후는 사실상 올인 — 그 이상은 35로 캡


def canonical_raise_size(depth: int, position: str = None) -> float:
    """레이즈 깊이(1=오픈, 2=3벳, 3=4벳, 4=5벳) → 깊이-캐노니컬 to-amount(bb). v12 백필 전용.
    깊이1(오픈)은 포지션 의존(SB 3.5). 헤즈업 딜러 라벨 'BTN/SB'는 'SB'로 매핑."""
    if depth <= 1:
        p = "SB" if position == "BTN/SB" else position
        return CANONICAL_OPEN_SIZE.get(p, 2.5)
    return CANONICAL_RAISE_BY_DEPTH.get(
        depth, CANONICAL_RAISE_BY_DEPTH[_CANONICAL_MAX_DEPTH]
    )


def _canon_raise_token(depth: int, position: str = None) -> str:
    return f"R{_fmt(canonical_raise_size(depth, position))}"


def _fmt(v) -> str:
    """2.5 → '2.5', 8.0 → '8', 9.0 → '9' (불필요한 .0 제거)"""
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)


def _build_url(actions: list, history_spot: int) -> str:
    actions_str = "-".join(_fmt(a) for a in actions) if actions else ""
    if actions_str:
        return f"{BASE}&preflop_actions={actions_str}&history_spot={history_spot}"
    return f"{BASE}&history_spot={history_spot}"


def situation_to_node_key(position: str, vs_position, range_type: str):
    """(position, vs_position, range_type) → 깊이-캐노니컬 노드 키. v12 백필 전용.

    3종 키만으로는 조상의 실측 사이즈를 알 수 없어 깊이-캐노니컬 사이즈로 근사한 키를
    만든다(3벳+는 화면 실측과 다를 수 있다). 새 경로는 실측 키(action_seq)를 쓴다.

    - open(RFI): 앞 포지션 전부 폴드 → "F"*idx (UTG RFI = "")
    - vs_open: 오프너 오픈(깊이1) + 나머지 폴드
    - vs_3bet: 오프너 오픈(깊이1) + 3벳자 3벳(깊이2) + 나머지 폴드.
      vs_position은 'opener/three_bettor' 정규형을 기대한다.
    6-max POSITIONS 밖(헤즈업 'BTN/SB' 등)이거나 vs_position 파싱 불가면 None.
    """
    if position not in POS_INDEX:
        return None
    my_idx = POS_INDEX[position]

    if range_type == "open":
        return "-".join(["F"] * my_idx)

    if range_type == "vs_open":
        opener = vs_position
        if opener not in POS_INDEX:
            return None
        opener_idx = POS_INDEX[opener]
        toks = []
        for i in range(my_idx):
            toks.append(_canon_raise_token(1, opener) if i == opener_idx else "F")
        return "-".join(toks)

    if range_type == "vs_3bet":
        parts = (vs_position or "").split("/")
        if len(parts) != 2:
            return None
        opener, three_bettor = parts
        if opener not in POS_INDEX or three_bettor not in POS_INDEX:
            return None
        opener_idx = POS_INDEX[opener]
        bettor_idx = POS_INDEX[three_bettor]
        toks = []
        for i in range(opener_idx):            # 오프너 이전 폴드
            toks.append("F")
        toks.append(_canon_raise_token(1, opener))         # 오프너 오픈(깊이1)
        for i in range(opener_idx + 1, bettor_idx):        # 오프너~3벳자 사이 폴드
            toks.append("F")
        toks.append(_canon_raise_token(2, three_bettor))   # 3벳(깊이2)
        for i in range(bettor_idx + 1, 6):                 # 3벳자 이후 끝까지 폴드
            toks.append("F")
        return "-".join(toks)

    return None


def node_key_active_count(node_key) -> int:
    """노드 키에서 히어로 결정 시점의 미폴드 인원(6 - 폴드 토큰 수)을 파생."""
    if not node_key:
        return 6
    return 6 - sum(1 for t in node_key.split("-") if t == "F")


def url_from_node_key(node_key) -> str:
    """노드 키 → GTO Wizard URL(preflop_actions + history_spot).

    노드 키 토큰이 그대로 preflop_actions가 되고 history_spot = 토큰 수(=히어로의 결정 시점
    인덱스). 실측 사이즈 키를 넘기면 URL이 화면과 정확히 일치한다.
    """
    toks = node_key.split("-") if node_key else []
    return _build_url(toks, len(toks))
