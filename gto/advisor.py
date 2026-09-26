"""
GTO 어드바이저
현재 게임 상황 → GTO 추천 액션 + 빈도 반환
사람 힌트 표시 및 봇 전략에 활용
"""

from typing import Optional
from .loader import (
    hand_to_notation, get_open_range, get_vs_open_range, get_vs_3bet_range,
    get_action_frequencies, sample_action, find_opener_position,
    get_range_by_seq, get_children_by_prefix,
)
from .url_generator import POS_INDEX
from .node_key import HEADSUP_PREFIX, derive_node_meta
from core.card import Card


def _save_missing_seq(node_key_live: str, hero_position: str) -> None:
    """미수집 프리플랍 노드를 큐에 기록(중복 무시).

    node_key_live = 히어로 결정 직전까지의 노드 키(스냅에 성공한 토큰은 수집된 형제
    사이즈, 실패하면 라이브 실측 사이즈). 수집 워커가 이 키로 GTO Wizard에 정확히
    이동(url_from_node_key)해 수집한다. gto_missing_spots_preflop 테이블을 재사용하되
    range_type='seq'로 구분하고, 노드 키를 vs_position에 저장해
    UNIQUE(street, position, vs_position, range_type)로 자연 dedupe.
    (간단 라벨 enum 행 큐 기록은 ADR 0035 이후 하지 않는다 — 정확한 노드 키가 수집 단위.)
    """
    try:
        from db.connection import get_connection
        from .url_generator import url_from_node_key
        url = url_from_node_key(node_key_live)
        conn = get_connection()
        conn.execute(
            """
            INSERT OR IGNORE INTO gto_missing_spots_preflop
                (street, position, vs_position, range_type, situation_label, gto_wizard_url)
            VALUES ('preflop', ?, ?, 'seq', ?, ?)
            """,
            (hero_position, node_key_live, f"seq {node_key_live}", url),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # DB 없거나 오류 시 조용히 무시


def _count_raises(preflop_seq: list) -> int:
    """구조화 프리플랍 시퀀스에서 자발적 레이즈 횟수.

    (구) _count_preflop_raises(한글 action_log 파싱)의 대체. 기존 한글 파서가
    "레이즈" 문자열만 셌고 "올인"은 세지 않았던 것과 동일하게, 여기서도
    action == "raise"만 카운트한다(allin 제외) — 기존 라우팅 동작 보존.
    """
    return sum(1 for a in preflop_seq if a.get("action") == "raise")


def _raisers(preflop_seq: list) -> list:
    """레이즈한 포지션 목록(행동 순서, 중복 제거).

    (구) _find_raisers_in_log의 대체. 기존과 동일하게 "raise" 액션만 대상으로
    하고, 같은 포지션의 중복은 제거한다.
    """
    out = []
    for a in preflop_seq:
        if a.get("action") == "raise":
            pos = a.get("position")
            if pos and pos not in out:
                out.append(pos)
    return out


def _fmt_bb(x) -> str:
    """bb 사이즈를 캐노니컬 문자열로 (2.5→"2.5", 8.0→"8", 17.5→"17.5")."""
    if x is None:
        return ""
    return f"{x:.1f}".rstrip("0").rstrip(".")


def canonical_preflop_actions(preflop_seq: list) -> str:
    """구조화 시퀀스 → GTO Wizard `preflop_actions` 캐노니컬 문자열.

    F=fold, X=check, C=call, R{bb}=raise/allin to-amount(bb).
    예: [UTG raise 2.5, HJ raise 8, CO fold] → "R2.5-R8-F".
    ②(시퀀스 키 스키마)에서 노드 키 생성에 재사용하기 위한 헬퍼(이번 필수 아님).
    """
    parts = []
    for a in preflop_seq:
        act = a.get("action")
        if act == "fold":
            parts.append("F")
        elif act == "check":
            parts.append("X")
        elif act == "call":
            parts.append("C")
        elif act in ("raise", "allin"):
            parts.append(f"R{_fmt_bb(a.get('amount_bb'))}")
    return "-".join(parts)


def _parse_raise_bb(token: str) -> Optional[float]:
    """레이즈 토큰 'R8'/'R2.5'/'R13.5' → 8.0/2.5/13.5. 레이즈 토큰이 아니면 None."""
    if not token or token[0] != "R":
        return None
    try:
        return float(token[1:])
    except ValueError:
        return None


def canonical_node_key(preflop_seq: list, prefix_tokens: Optional[list] = None) -> Optional[str]:
    """구조화 라이브 시퀀스 → 캐노니컬 노드 키(②' 데이터 기반 트리-인지 스냅).

    (②의 깊이-캐노니컬 하드코딩 스냅을 대체) 라이브 시퀀스를 앞에서부터 훑으며 키를
    **점증 생성**한다. 각 자발적 레이즈에 대해:
      1) 지금까지 만든 프리픽스에서 **수집된 자식 노드들**을 loader로 조회
         (get_children_by_prefix — 하드코딩 사이즈 테이블이 아니라 수집 데이터에서 읽음).
      2) 그중 레이즈-형제 사이즈로 스냅. GTO Wizard 트리는 노드당 레이즈 사이즈가 1개라
         보통 형제가 유일 → 그 토큰 사용. 2개 이상이면 **bb 절대거리 최소**로 선택.
         (스토어된 토큰 문자열을 그대로 이어붙여 loader 키와 정확히 일치시킴.)
      3) 해당 프리픽스/브랜치에 **수집된 레이즈-형제가 없으면**(미수집 브랜치) 숫자로
         억지 매칭하지 않고 **None 반환** → 상위(_recommend_by_seq)가 큐 등록 + equity
         휴리스틱 폴백을 타게 한다(추측 금지 대원칙).
      4) 라이브 액션이 **올인**이면(2)의 대상을 "올인 형제"로 좁힌다: 이 프리픽스
         노드 자신에 저장된 raise_size(수집 당시 "레이즈" 액션의 실측 사이즈)와
         정확히 일치하는 형제는 "레이즈" 토큰임이 확정되므로 후보에서 제외하고,
         남은 형제(있다면)만 대상으로 (2)의 스냅을 적용한다. 남는 형제가 없으면
         (올인 데이터가 수집되지 않음) None(억지 매칭 금지 — 숏스택 올인이 일반
         레이즈 노드로 새지 않게 함, T-014).
    fold/check/call은 사이즈가 없으므로 그대로 이어붙인다. 블라인드는 preflop_seq에
    자발 액션으로 들어오지 않으므로 자동 제외(GTO Wizard 포맷과 동일).

    예(수집분에 "R2.5-R8-F-F-F-F"만 있을 때):
      [UTG raise 2.3, HJ raise 7.5, CO~BB fold] → "R2.5-R8-F-F-F-F"
      (2.3→형제 R2.5, 7.5→형제 R8로 스냅). 미수집 브랜치면 None.

    prefix_tokens: 라이브 시퀀스 앞에 붙일 토큰. 헤즈업은 HEADSUP_PREFIX(F-F-F-F)를 넘겨
    6-max SB vs BB 트리로 옮긴다(ADR 0005).
    """
    toks = list(prefix_tokens or [])
    for a in preflop_seq:
        act = a.get("action")
        if act == "fold":
            toks.append("F")
        elif act == "check":
            toks.append("X")
        elif act == "call":
            toks.append("C")
        elif act in ("raise", "allin"):
            prefix = "-".join(toks)
            raise_children = [
                (c, _parse_raise_bb(c)) for c in get_children_by_prefix(prefix)
            ]
            raise_children = [(c, s) for c, s in raise_children if s is not None]
            if not raise_children:
                return None  # 미수집 브랜치 — 억지 매칭 금지, 상위가 큐/폴백 처리

            if act == "allin":
                # T-014 (ADR 0010 확장): 라이브 올인을 "레이즈" 형제와 뭉뚱그려
                # bb 최소거리로 스냅하지 않는다 — 숏스택 올인이 우연히 일반 레이즈
                # 사이즈에 가까우면 비올인 노드로 잘못 스냅될 수 있다(원래 버그).
                # 이 프리픽스 노드 자신에 저장된 raise_size(수집 당시 "레이즈" 액션에
                # 쓰인 실측 사이즈)를 알면, 그 값과 정확히 일치하는 형제는 "레이즈"
                # 토큰임이 데이터로 확정되므로 후보에서 제외한다(추측이 아니라
                # 저장된 값과의 일치 확인). 남는 형제만 "올인 형제" 후보로 본다.
                parent = get_range_by_seq(prefix)
                known_raise_bb = parent.get("raise_size") if parent else None
                if known_raise_bb is not None:
                    raise_children = [
                        (c, s) for c, s in raise_children
                        if abs(s - known_raise_bb) > 1e-9
                    ]
                if not raise_children:
                    return None  # 올인 형제 데이터 없음 — 억지 매칭 금지, 큐/폴백

            live = a.get("amount_bb")
            if live is None:
                # 사이즈 미상 라이브 레이즈: 형제 유일이면 그걸로, 다의면 매칭 불가
                if len(raise_children) == 1:
                    toks.append(raise_children[0][0])
                else:
                    return None
            else:
                toks.append(min(raise_children, key=lambda cs: abs(cs[1] - live))[0])
    return "-".join(toks)


def _gto_position(position: str) -> str:
    """헤즈업 딜러 라벨 "BTN/SB"는 GTO 조회에서만 6-max "SB"로 본다(ADR 0005)."""
    return "SB" if position == "BTN/SB" else position


class GTOAdvisor:

    def get_recommendation(
        self,
        hole_cards: list,
        my_position: str,
        positions: dict,
        game_state: dict,
        big_blind: int = 20,
    ) -> Optional[dict]:
        """현재 상황에 맞는 GTO 추천 반환 (조회 순서: ADR 0035).

        1. 액션 순서 키로 **정확한 노드**를 찾는다(사이즈는 수집된 형제로 스냅, ADR 0010).
           결과 `approx=False`.
        2. 없을 때만 **간단 라벨**(포지션·상대·상황 종류)로 찾는다. 라벨은 콜러 없는 노드만
           대표한다(loader). 데이터 모델 밖 가드(ADR 0006)는 이 경로에 그대로 있다.
           결과 `approx=True` → 힌트 문자열·플레이 평가에 "(근사)" 표시.
        3. 둘 다 없으면 None(힌트 없음, 봇 휴리스틱)이고, 정확한 노드 키를 미수집 큐에 넣는다.
        """
        rec, queue_key = self._seq_lookup(
            hole_cards, my_position, positions, game_state
        )
        if rec is not None:
            rec["approx"] = False
            return rec
        rec = self._recommend_by_enum(
            hole_cards, my_position, positions, game_state, big_blind
        )
        if rec is not None:
            rec["approx"] = True
            return rec
        if queue_key is not None:
            _save_missing_seq(queue_key, _gto_position(my_position))
        return None

    @staticmethod
    def _seq_prefix(my_position: str, positions: Optional[dict], preflop_seq: list):
        """라이브 시퀀스를 6-max 트리 노드 키로 옮길 때 앞에 붙일 토큰.

        - 헤즈업(딜러 라벨 "BTN/SB")이면 F-F-F-F — 6-max SB vs BB 트리(ADR 0005).
        - 3~5인 테이블이면 None — 포지션 구성이 달라 트리에 대응시키지 않는다(ADR 0005).
          (간단 라벨 경로는 기존대로 동작하고 결과는 근사로 표시된다.)
        - 그 외(6인, 또는 positions를 모르는 호출)는 빈 프리픽스.
        """
        labels = set((positions or {}).values())
        if (
            my_position == "BTN/SB"
            or "BTN/SB" in labels
            or any(a.get("position") == "BTN/SB" for a in preflop_seq)
        ):
            return list(HEADSUP_PREFIX)
        if 3 <= len(positions or {}) <= 5:
            return None
        return []

    def _seq_lookup(
        self,
        hole_cards: list,
        my_position: str,
        positions: Optional[dict],
        game_state: dict,
    ):
        """정확한 노드 조회. 반환 (추천 dict 또는 None, 미수집 큐에 넣을 노드 키 또는 None).

        큐 키는 "이 상황의 정확한 노드가 DB에 없다"가 확실할 때만 준다:
        - 스냅 실패(미수집 브랜치) → 라이브 실측 키
        - 스냅은 됐지만 그 노드가 미수집 → 스냅된 키(수집된 형제 사이즈라 GTO Wizard에 그대로 있음)
        노드 키가 가리키는 히어로가 실제 히어로와 다르면(시퀀스 오염, 지원 밖 테이블) 조회도
        큐 기록도 하지 않는다 — 다른 사람의 노드를 내주지 않기 위함.
        """
        if len(hole_cards) < 2:
            return None, None
        if game_state.get("street", "프리플랍") != "프리플랍":
            return None, None
        preflop_seq = game_state.get("preflop_seq") or []
        prefix = self._seq_prefix(my_position, positions, preflop_seq)
        if prefix is None:
            return None, None

        node_key = canonical_node_key(preflop_seq, prefix)
        live = canonical_preflop_actions(preflop_seq)
        live_key = "-".join(prefix + (live.split("-") if live else []))
        meta = derive_node_meta(node_key if node_key is not None else live_key)
        if meta is None or meta["hero_position"] != _gto_position(my_position):
            return None, None
        if node_key is None:
            return None, live_key  # 미수집 브랜치 — 억지 매칭 금지

        data = get_range_by_seq(node_key)
        if data is None:
            return None, node_key
        hand = hand_to_notation(hole_cards[0], hole_cards[1])
        freqs = get_action_frequencies(data, hand)
        if freqs is None:
            return None, None  # 노드는 있고 그 핸드만 없음/손상(ADR 0002) — 수집 대상 아님
        return {
            "hand": hand,
            "frequencies": freqs,
            "situation": data.get("situation", ""),
            "raise_size": data.get("raise_size") or None,
            "raise_count": _count_raises(preflop_seq),
            "node_key": node_key,
        }, None

    def _recommend_by_seq(
        self,
        hole_cards: list,
        my_position: str,
        game_state: dict,
        big_blind: int = 20,
        positions: Optional[dict] = None,
    ) -> Optional[dict]:
        """정확한 노드 조회만(라벨 예비·큐 기록 없음). 조회 순서 전체는 get_recommendation."""
        rec, _ = self._seq_lookup(hole_cards, my_position, positions, game_state)
        return rec

    def _recommend_by_enum(
        self,
        hole_cards: list,
        my_position: str,
        positions: dict,
        game_state: dict,
        big_blind: int = 20,
    ) -> Optional[dict]:
        """간단 라벨 조회(ADR 0035 2순위 — 호출부가 결과를 근사로 표시한다).

        RFI / vs_open / vs_3bet 세 가지 상황 지원. 라벨이 가리키는 노드는 콜러 없는
        노드뿐이다(loader). 데이터 모델 밖 가드(ADR 0006)에 걸리면 None.
        미수집 큐 기록은 하지 않는다(get_recommendation이 정확한 노드 키로 기록).
        """
        if len(hole_cards) < 2:
            return None

        # 헤즈업(2인) 매핑: core/game.py의 딜러 라벨 "BTN/SB"는 UI/핸드
        # 히스토리 표시용 원본이므로 여기서 건드리지 않는다. GTO 조회 시점
        # 에서만 6-max "SB"로 국소 치환해 기존 SB RFI/vs_open/vs_3bet 데이터를
        # 재사용한다(헤즈업 트리는 SB(딜러) vs BB 단둘로 6-max SB 스팟과
        # 게임 트리가 구조적으로 동일하다고 판단, ADR 0005).
        if my_position == "BTN/SB":
            my_position = "SB"

        hand = hand_to_notation(hole_cards[0], hole_cards[1])
        current_bet = game_state.get("current_bet", 0)
        street = game_state.get("street", "프리플랍")
        # 구조화 프리플랍 시퀀스 (core/game.py._get_game_state가 제공).
        # 없으면(구식 game_state) 빈 시퀀스로 폴백 — RFI 등 시퀀스 불필요 경로는 정상 동작.
        preflop_seq = game_state.get("preflop_seq") or []

        if street != "프리플랍":
            return None

        # ── 베팅 라운드 판별 ────────────────────────────
        raise_count = _count_raises(preflop_seq)
        is_rfi = current_bet <= big_blind

        # RFI
        # BB는 강제 베팅 상태라 "오픈(RFI)"이 원천적으로 불가능하다.
        # 림프된 팟(current_bet == big_blind)에서 BB가 레이즈하는 상황은
        # 우리 데이터 모델이 지원하지 않으므로 조회/기록 없이 폴백시킨다.
        if is_rfi and my_position != "BB":
            range_data = get_open_range(my_position)
            if range_data is None:
                return None
            freqs = get_action_frequencies(range_data, hand)
            if freqs is None:
                # 핸드 데이터 손상(로드 시 스킵됨) 또는 미수집 — 특정 액션에
                # 몰아주지 않고 상위(봇)가 휴리스틱 폴백을 타도록 None 반환.
                return None
            return {
                "hand": hand,
                "frequencies": freqs,
                "situation": range_data.get("situation", f"{my_position} RFI"),
                # 실측 bb 값만 사용 — 없으면 None (추측/플레이스홀더 금지, 상위에서 폴백 처리)
                "raise_size": range_data.get("raise_size") or None,
                "raise_count": 0,
                "node_key": range_data.get("node_key"),
            }

        # vs_open (레이즈 1번)
        if raise_count <= 1:
            # 오프너 = 시퀀스상 첫 레이저. 레이즈가 없는데 current_bet가 BB를
            # 넘는 경우(예: 올인만 발생 — 위 _count_raises는 allin을 세지 않음)는
            # 기존과 동일하게 current_bet 기반 find_opener_position으로 폴백한다.
            raisers = _raisers(preflop_seq)
            opener_pos = raisers[0] if raisers else find_opener_position(
                positions, game_state, big_blind
            )
            if opener_pos is None:
                return None
            if opener_pos == "BTN/SB":
                opener_pos = "SB"
            # 우리 데이터 모델은 "오프너가 나보다 먼저 행동하는" open/vs_open
            # 구조만 지원한다. (예: 림프 후 아이솔레이트 레이즈처럼) 오프너가
            # 포지션 순서상 my_position보다 뒤인 경우는 데이터 모델 밖의
            # 상황이므로 조회/기록 없이 None 반환. 헤즈업 포지션(BTN/SB 등
            # POS_INDEX에 없는 값)은 비교 불가하므로 기존 로직을 유지한다.
            if my_position in POS_INDEX and opener_pos in POS_INDEX:
                if POS_INDEX[opener_pos] > POS_INDEX[my_position]:
                    return None
            range_data = get_vs_open_range(my_position, opener_pos)
            if range_data is None:
                return None
            freqs = get_action_frequencies(range_data, hand)
            if freqs is None:
                return None
            return {
                "hand": hand,
                "frequencies": freqs,
                "situation": range_data.get("situation", f"{my_position} vs {opener_pos}"),
                "raise_size": range_data.get("raise_size") or None,
                "raise_count": 1,
                "node_key": range_data.get("node_key"),
            }

        # vs_3bet (레이즈 2번)
        if raise_count == 2:
            raisers = _raisers(preflop_seq)
            if len(raisers) >= 2:
                opener_pos, three_bettor_pos = raisers[0], raisers[1]
                if opener_pos == "BTN/SB":
                    opener_pos = "SB"
                if three_bettor_pos == "BTN/SB":
                    three_bettor_pos = "SB"
                # 우리 데이터 모델은 "원래 오프너가 3벳에 대응하는" 레인지만
                # 수집한다. my_position이 오프너가 아니면(림프 후 대응 등)
                # 데이터 모델 밖의 상황이므로 조회/기록 없이 None 반환.
                if my_position != opener_pos:
                    return None
                range_data = get_vs_3bet_range(my_position, opener_pos, three_bettor_pos)
                if range_data is None:
                    return None
                freqs = get_action_frequencies(range_data, hand)
                if freqs is None:
                    return None
                return {
                    "hand": hand,
                    "frequencies": freqs,
                    "situation": range_data.get("situation", f"{my_position} vs 3bet"),
                    "raise_size": range_data.get("raise_size") or None,
                    "raise_count": 2,
                    "node_key": range_data.get("node_key"),
                }

        # 4벳+ 이상: GTO 데이터 없음 → None 반환 (봇이 별도 처리)
        return None

    def format_hint(self, recommendation: Optional[dict]) -> Optional[str]:
        """사람용 힌트 문자열 생성"""
        if recommendation is None:
            return None

        freqs = recommendation["frequencies"]
        hand = recommendation["hand"]
        situation = recommendation["situation"]

        action_map = {"fold": "폴드", "call": "콜", "raise": "레이즈", "allin": "올인"}
        parts = []
        for action, freq in freqs.items():
            if freq > 0.01:
                label = action_map.get(action, action)
                parts.append(f"{label} {freq*100:.0f}%")

        if not parts:
            return None

        approx = " (근사)" if recommendation.get("approx") else ""
        return f"📊 GTO [{hand}] {situation}{approx}: {' / '.join(parts)}"

    def get_bot_action(
        self,
        hole_cards: list,
        my_position: str,
        positions: dict,
        game_state: dict,
        big_blind: int = 20,
        gto_compliance: float = 1.0,
    ) -> Optional[dict]:
        """
        봇용 GTO 액션 샘플링.
        반환: {"action": "fold"|"call"|"raise", "raise_count": N} 또는 None
        """
        import random
        if random.random() > gto_compliance:
            return None

        rec = self.get_recommendation(hole_cards, my_position, positions, game_state, big_blind)
        if rec is None:
            return None

        action = sample_action(rec["frequencies"])
        return {
            "action": action,
            "raise_count": rec.get("raise_count", 0),
            "raise_size": rec.get("raise_size"),  # 실측 bb (REAL) 또는 None
        }
