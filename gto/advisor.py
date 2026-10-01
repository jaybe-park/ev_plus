"""
GTO 어드바이저
현재 게임 상황 → GTO 추천 액션 + 빈도 반환
사람 힌트 표시 및 봇 전략에 활용
"""

from typing import Optional
from .loader import (
    hand_to_notation, get_open_range, get_vs_open_range, get_vs_3bet_range,
    get_action_frequencies, sample_action,
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
    간단 라벨 enum 행은 큐에 넣지 않는다(ADR 0035 — 정확한 노드 키가 수집 단위).
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
    """구조화 프리플랍 시퀀스에서 자발적 레이즈(`raise`) 횟수. `allin`은 세지 않는다."""
    return sum(1 for a in preflop_seq if a.get("action") == "raise")


def _raisers(preflop_seq: list) -> list:
    """레이즈(`raise`)한 포지션 목록(행동 순서, 중복 제거)."""
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
    """구조화 시퀀스 → GTO Wizard `preflop_actions` 문자열(라이브 실측 사이즈).

    F=fold, X=check, C=call, R{bb}=raise/allin to-amount(bb).
    예: [UTG raise 2.5, HJ raise 8, CO fold] → "R2.5-R8-F".
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
    """구조화 라이브 시퀀스 → 수집 트리의 노드 키(데이터 기반 스냅, ADR 0010·0037).

    라이브 시퀀스를 앞에서부터 훑으며 키를 점증 생성한다. 각 자발적 레이즈에 대해:
      1) 지금까지 만든 프리픽스에서 **수집된 자식 노드들**을 loader로 조회
         (get_children_by_prefix — 수집 데이터에서 읽는다).
      2) 그중 레이즈 형제 사이즈로 스냅. 형제가 하나면 그것, 둘 이상이면 bb 절대거리 최소.
         저장된 토큰 문자열을 그대로 이어붙여 loader 키와 정확히 일치시킨다.
      3) 그 프리픽스에 수집된 레이즈 형제가 없으면 None(상위가 큐 등록 + 휴리스틱 폴백).
      4) 라이브 액션이 **올인**이면 (2)의 대상을 "올인 형제"로 좁힌다: 이 프리픽스 노드
         자신에 저장된 raise_size(수집 당시 "레이즈" 액션의 실측 사이즈)와 정확히 일치하는
         형제는 레이즈 토큰이므로 제외하고, 남은 형제만 대상으로 스냅한다. 남는 형제가
         없으면 None.
    fold/check/call은 사이즈가 없으므로 그대로 이어붙인다. 블라인드는 preflop_seq에
    자발 액션으로 들어오지 않으므로 자동 제외(GTO Wizard 포맷과 동일).

    예(수집분에 "R2.5-R8-F-F-F-F"만 있을 때):
      [UTG raise 2.3, HJ raise 7.5, CO~BB fold] → "R2.5-R8-F-F-F-F". 미수집 브랜치면 None.

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
                return None

            if act == "allin":
                parent = get_range_by_seq(prefix)
                known_raise_bb = parent.get("raise_size") if parent else None
                if known_raise_bb is not None:
                    raise_children = [
                        (c, s) for c, s in raise_children
                        if abs(s - known_raise_bb) > 1e-9
                    ]
                if not raise_children:
                    return None

            live = a.get("amount_bb")
            if live is None:
                # 사이즈 미상 라이브 레이즈: 형제가 하나일 때만 매칭
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


def _is_short_handed(positions: Optional[dict]) -> bool:
    """3~5인 테이블 — 포지션 구성이 6-max 트리와 달라 GTO 데이터에 대응시키지 않는다(ADR 0005)."""
    return 3 <= len(positions or {}) <= 5


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
           대표한다(loader). 데이터 모델 밖 가드(ADR 0006, 올인·림프·3~5인)는 이 경로에 있다.
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
        - 3~5인 테이블이면 None — 트리에 대응시키지 않는다(ADR 0005).
        - 그 외(6인, 또는 positions를 모르는 호출)는 빈 프리픽스.
        """
        labels = set((positions or {}).values())
        if (
            my_position == "BTN/SB"
            or "BTN/SB" in labels
            or any(a.get("position") == "BTN/SB" for a in preflop_seq)
        ):
            return list(HEADSUP_PREFIX)
        if _is_short_handed(positions):
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
            return None, live_key

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
        노드뿐이다(loader). 데이터 모델 밖이면 None:
        - 3~5인 테이블(ADR 0005)
        - 시퀀스에 올인이 있음(올인을 레이즈 라벨로 읽지 않는다, ADR 0037)
        - RFI는 시퀀스에 콜·레이즈가 없을 때만(림프 팟은 RFI가 아니다, ADR 0046), BB는 RFI 불가
        - vs_open에서 오프너가 히어로보다 뒤 좌석 / vs_3bet에서 히어로 ≠ 오프너(ADR 0006)
        미수집 큐 기록은 하지 않는다(get_recommendation이 정확한 노드 키로 기록).
        """
        if len(hole_cards) < 2:
            return None
        if game_state.get("street", "프리플랍") != "프리플랍":
            return None
        if _is_short_handed(positions):
            return None

        # 헤즈업 딜러 라벨 "BTN/SB"는 조회 시점에서만 6-max "SB"로 본다(ADR 0005).
        my_position = _gto_position(my_position)
        hand = hand_to_notation(hole_cards[0], hole_cards[1])
        current_bet = game_state.get("current_bet", 0)
        preflop_seq = game_state.get("preflop_seq") or []
        actions = [a.get("action") for a in preflop_seq]
        if "allin" in actions:
            return None

        raise_count = _count_raises(preflop_seq)
        raisers = [_gto_position(p) for p in _raisers(preflop_seq)]
        is_rfi = current_bet <= big_blind and not any(a in ("call", "raise") for a in actions)

        if is_rfi:
            if my_position == "BB":
                return None
            range_data = get_open_range(my_position)
            if range_data is None:
                return None
            freqs = get_action_frequencies(range_data, hand)
            if freqs is None:
                return None
            return {
                "hand": hand,
                "frequencies": freqs,
                "situation": range_data.get("situation", f"{my_position} RFI"),
                "raise_size": range_data.get("raise_size") or None,
                "raise_count": 0,
                "node_key": range_data.get("node_key"),
            }

        if raise_count == 1:
            opener_pos = raisers[0]
            # 오프너가 히어로보다 뒤 좌석(림프 후 아이솔레이트 등)은 모델 밖
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

        if raise_count == 2 and len(raisers) >= 2:
            opener_pos, three_bettor_pos = raisers[0], raisers[1]
            # 오프너가 3벳에 대응하는 레인지만 있다 — 히어로가 오프너가 아니면 모델 밖
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

        # 레이즈 없는 림프 팟, 4벳 이상: 라벨 데이터 없음
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
        반환: {"action": "fold"|"call"|"raise"|"allin", "raise_count": N, "raise_size": bb|None} 또는 None
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
