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

# GTO Wizard 기준 3벳 사이즈 (실측값 기반)
# UTG open(2.5) → 3bet 8 확인됨; 그 외는 비슷한 비율로 추정
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
