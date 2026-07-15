"""
GTO Wizard URL 생성기

URL 패턴:
  https://app.gtowizard.com/solutions?...&preflop_actions=R2.5-R8-F-F-F-F&history_spot=6

- preflop_actions: 해당 결정 직전까지의 액션 시퀀스 (R{size} = 레이즈, F = 폴드)
- history_spot: 해당 결정이 전체 시퀀스의 몇 번째 행동인지 (0-indexed)

포지션 순서 (6-max): UTG(0) → HJ(1) → CO(2) → BTN(3) → SB(4) → BB(5)
"""

POSITIONS = ["UTG", "HJ", "CO", "BTN", "SB", "BB"]
POS_INDEX = {p: i for i, p in enumerate(POSITIONS)}

# GTO Wizard 6-max NL25 기준 표준 오픈 사이즈
OPEN_SIZE = {
    "UTG": 2.5, "HJ": 2.5, "CO": 2.5, "BTN": 2.5,
    "SB": 3.5,  # SB는 헤즈업 오픈이라 더 큼
}

# ⚠️ 경고 (2026-07-10 확정): 아래 THREE_BET_SIZE는 대부분 검증되지 않은 추측치다.
# 실측 확인된 것은 UTG open(2.5) → 3bet 8(HJ/CO/BTN 8.0)뿐이며, 나머지(특히 SB/BB
# 대상 9.0 값들)는 "비슷한 비율" 추정일 뿐 GTO Wizard에서 직접 읽은 값이 아니다.
# 실측 결과 UTG/SB=11.0, UTG/BB=13.5처럼 배수가 일정하지 않음이 확인됐다(포지션마다
# 다름 → 공식으로 추론 불가). 이 테이블 값으로 만든 URL은 잘못된 노드로 이동시킬
# 위험이 있으니, 수집 시 URL 이동 후 반드시 화면에 표시된 실제 사이징을 확인하고
# 그 값을 저장할 것 — 이 테이블 값을 그대로 믿고 저장하지 말 것.
THREE_BET_SIZE = {
    # (opener_pos, three_bettor_pos): size
    ("UTG", "HJ"):  8.0,  # 실측 확인
    ("UTG", "CO"):  8.0,
    ("UTG", "BTN"): 8.0,
    ("UTG", "SB"):  9.0,
    ("UTG", "BB"):  9.0,
    ("HJ",  "CO"):  8.0,
    ("HJ",  "BTN"): 8.0,
    ("HJ",  "SB"):  9.0,
    ("HJ",  "BB"):  9.0,
    ("CO",  "BTN"): 8.0,
    ("CO",  "SB"):  9.0,
    ("CO",  "BB"):  9.0,
    ("BTN", "SB"):  9.0,
    ("BTN", "BB"):  9.0,
    ("SB",  "BB"):  9.0,  # SB opens 3.5, BB 3bets ~9
}

BASE = (
    "https://app.gtowizard.com/solutions"
    "?solution_type=gwiz&gmfs_solution_tab=ai_sols"
    "&gametype=Cash6mGeneral_6mNL25R25&depth=100"
)

# ──────────────────────────────────────────
# ② 시퀀스 키(노드 키) 캐노니컬 사이즈 — 저장/조회 일원화 단일 소스
# ──────────────────────────────────────────
# 노드 키 = 히어로 결정 직전까지의 액션 시퀀스를 "캐노니컬 사이즈"로 스냅한 문자열.
# 실전(사람/봇) 베팅은 연속값이지만 솔브 트리는 노드당 논-올인 레이즈 사이즈가
# 정확히 1개(docs/gto-preflop-tree.md ③ 정찰). 따라서 사이즈가 아니라 **레이즈 깊이
# (자발적 레이즈 순번)**로 스냅한다 — 깊이 자체는 액션 순서로 구조적으로 결정되므로
# "13.5bb 3벳이 4벳(17.5)로 오분류"되는 사이즈-근접 스냅의 함정을 피한다.
#
# 깊이별 to-amount(bb)는 ③ 실측 에스컬레이션(2.5 → 8 → 17.5 → 35 → 올인) 기준.
# 오픈(깊이1)만 포지션 의존(SB 3.5, 나머지 2.5)이 실측돼 반영. 3벳+ 깊이의 실제
# 사이즈는 포지션 의존이지만(HJ 3벳=8/SB=11/BB=13.5) 노드 키는 깊이별 단일 캐노니컬
# 값(3벳=8)으로 **스냅**한다 — 저장 키와 런타임 조회 키가 같은 테이블을 쓰므로
# 항상 매칭된다(구현 결정: docs/gto-preflop-tree.md "② 구현 결정" 참고).
CANONICAL_OPEN_SIZE = {"UTG": 2.5, "HJ": 2.5, "CO": 2.5, "BTN": 2.5, "SB": 3.5}
CANONICAL_RAISE_BY_DEPTH = {1: 2.5, 2: 8.0, 3: 17.5, 4: 35.0}
_CANONICAL_MAX_DEPTH = 4  # 100bb 기준 5벳(35) 이후는 사실상 올인 — 그 이상은 35로 캡


def canonical_raise_size(depth: int, position: str = None) -> float:
    """레이즈 깊이(1=오픈, 2=3벳, 3=4벳, 4=5벳) → 캐노니컬 to-amount(bb).
    깊이1(오픈)은 포지션 의존(SB 3.5). 헤즈업 딜러 라벨 'BTN/SB'는 'SB'로 매핑.
    깊이 > 4는 5벳 사이즈(35)로 캡(100bb 기준 그 이상은 올인 강제)."""
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


def rfi_url(position: str) -> str:
    """
    포지션 오픈(RFI) URL.
    예) UTG RFI → history_spot=0, HJ RFI → preflop_actions=F&history_spot=1
    """
    if position not in POS_INDEX:
        return ""
    idx = POS_INDEX[position]
    actions = ["F"] * idx  # 앞 포지션들 모두 폴드
    return _build_url(actions, len(actions))


def vs_open_url(my_pos: str, opener_pos: str) -> str:
    """
    오픈레인지에 대응하는 URL.
    예) CO vs UTG open → preflop_actions=R2.5-F&history_spot=2
    """
    if my_pos not in POS_INDEX or opener_pos not in POS_INDEX:
        return ""
    opener_idx = POS_INDEX[opener_pos]
    my_idx = POS_INDEX[my_pos]
    open_size = OPEN_SIZE.get(opener_pos, 2.5)

    actions = []
    for i in range(my_idx):
        if i < opener_idx:
            actions.append("F")          # 오프너 이전: 폴드
        elif i == opener_idx:
            actions.append(f"R{_fmt(open_size)}")  # 오프너 레이즈
        else:
            actions.append("F")          # 오프너 이후~내 앞: 폴드

    return _build_url(actions, len(actions))


def vs_3bet_url(my_pos: str, opener_pos: str, three_bettor_pos: str) -> str:
    """
    3벳에 대한 오프너의 결정 URL.
    예) UTG vs HJ 3bet → preflop_actions=R2.5-R8-F-F-F-F&history_spot=6
    """
    if any(p not in POS_INDEX for p in [my_pos, opener_pos, three_bettor_pos]):
        return ""
    opener_idx = POS_INDEX[opener_pos]
    bettor_idx = POS_INDEX[three_bettor_pos]
    open_size = OPEN_SIZE.get(opener_pos, 2.5)
    bet_size = THREE_BET_SIZE.get((opener_pos, three_bettor_pos), 9.0)

    actions = []
    # 0) 오프너 이전 포지션들: 폴드 (오프너가 UTG가 아닐 때 필수 — 이전엔 누락돼
    #    비-UTG 오프너 vs_3bet URL이 잘못된 노드를 가리켰음. 2026-07-15 수정)
    for i in range(opener_idx):
        actions.append("F")
    # 1) 오프너(=my_pos) 첫 레이즈
    actions.append(f"R{_fmt(open_size)}")
    # 2) 오프너~3벳자 사이: 폴드
    for i in range(opener_idx + 1, bettor_idx):
        actions.append("F")
    # 3) 3벳자 레이즈
    actions.append(f"R{_fmt(bet_size)}")
    # 4) 3벳자 이후 끝(BB)까지: 폴드
    for i in range(bettor_idx + 1, 6):
        actions.append("F")
    # 5) 이제 오프너(my_pos)의 두 번째 결정 → history_spot = len(actions)

    return _build_url(actions, len(actions))


def situation_to_node_key(position: str, vs_position, range_type: str):
    """(position, vs_position, range_type) enum → 캐노니컬 노드 키 문자열.

    노드 키 = 히어로(=position)가 결정하기 **직전까지**의 액션 시퀀스를 캐노니컬
    사이즈(canonical_raise_size)로 표기한 문자열. 히어로 자신의 이번 액션은 키에
    포함하지 않는다(GTO Wizard preflop_actions + history_spot 규약과 동일).

    - open(RFI): 앞 포지션 전부 폴드 → "F"*idx (UTG RFI = "")
    - vs_open: 오프너 오픈(깊이1) + 나머지 폴드
    - vs_3bet: 오프너 오픈(깊이1) + 3벳자 3벳(깊이2) + 나머지 폴드.
      vs_position은 'opener/three_bettor' 정규형을 기대(마이그레이션/save가 정규화).

    마이그레이션 백필(db.schema.backfill_v12)과 런타임 스냅(gto.advisor.canonical_node_key)이
    **동일한 캐노니컬 사이즈 테이블**을 공유하도록 하는 결정론적 변환. 6-max POSITIONS
    밖(헤즈업 'BTN/SB' 등)이거나 vs_position 파싱 불가면 None(키 생성 불가).
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
    """캐노니컬 노드 키 → GTO Wizard URL(preflop_actions + history_spot).

    노드 키 토큰이 그대로 preflop_actions가 되고 history_spot = 토큰 수(=히어로의
    결정 시점 인덱스). ④(수집)에서 노드 키로 GTO Wizard 스팟에 직접 이동하는 데 재사용.
    ⚠️ 키의 3벳+ 사이즈는 캐노니컬 스냅값(예: 8)이라 화면 실측값(예: 13.5)과 다를 수
    있다 — 이동 후 실제 표시 사이징 확인 필요(THREE_BET_SIZE 경고와 동일 원칙).
    """
    toks = node_key.split("-") if node_key else []
    return _build_url(toks, len(toks))


def get_url(range_type: str, position: str, vs_position: str = "") -> str:
    """
    range_type과 포지션 정보로 URL 자동 생성.
    vs_position: RFI='' / vs_open='UTG' / vs_3bet='UTG/HJ'
    """
    if range_type == "open":
        return rfi_url(position)
    elif range_type == "vs_open":
        return vs_open_url(position, vs_position)
    elif range_type == "vs_3bet":
        parts = vs_position.split("/")
        if len(parts) == 2:
            return vs_3bet_url(position, parts[0], parts[1])
    return ""
