export interface PlayerState {
  name: string;
  chips: number;
  current_bet: number;
  is_folded: boolean;
  is_all_in: boolean;
  is_human: boolean;
  position: string;
  hole_cards: string[] | null;
}

export interface GameState {
  session_id: string;
  hand_number: number;
  street: string;
  pot: number;
  current_bet: number;
  min_raise: number;
  big_blind: number;
  community_cards: string[];
  players: PlayerState[];
  waiting_for_action: boolean;
  hand_over: boolean;
  game_over: boolean;
  winners: string[];
  showdown_hands: Record<string, string>;
  action_log: string[];
  call_amount: number;
  min_raise_to: number;
  can_raise: boolean;       // 사람이 지금 레이즈/올인-레이즈를 할 수 있나(false면 버튼 숨김)
  events: GameEvent[];
  gto: GtoNode | null;
  equity: EquityInfo | null;
  hand_review: HandReviewEntry[] | null;
  pots?: PotShare[] | null; // 핸드 종료 시 팟 계층(없거나 null이면 계층 표시 없이 승자만)
}

// 팟 계층 하나. returned=true는 아무도 받지 않은 초과 베팅을 낸 사람에게 돌려준 몫.
export interface PotShare {
  amount: number;
  eligible: string[];
  winners: string[];
  returned: boolean;
}

// ── 에퀴티 패널 / 플레이 평가 ──────────────────────────

export interface EquityOpponent {
  name: string;
  position: string;
  role: "raiser" | "caller" | "unknown";
  equity: number | null;
}

export interface EquityHistoryEntry {
  street: string;
  vs_range: number;   // 그 스트리트 첫 결정의 vs_range (패널과 같은 기준)
}

export interface EquityInfo {
  vs_random: number;       // 화면 비표시(ADR 0022/0034) — 평가·기록용
  vs_range: number;        // 패널이 보여주는 값(게이지·팟오즈 색·콜 EV·추이 모두 이 기준)
  range_applied: boolean;  // 레인지 정보가 있는 상대가 있나(없으면 vs_range = 랜덤 핸드 기준)
  pot_odds: number;
  call_ev_bb: number | null;
  source: string;          // vs_range를 만든 경로: preflop-table | exact | mc:N
  samples: number;         // 그 계산의 샘플 수
  num_opponents: number;
  opponents: EquityOpponent[];
  history: EquityHistoryEntry[];
}

export interface HandReviewEntry {
  street: string;
  action: string;
  grade: string;
  reason: string;
  ev_loss_bb: number | null;     // 양수 = 손실 크기(bb). 손실 없음·판정 안 함은 null
  pot_odds: number | null;
  equity: number | null;
  gto_freq: number | null;
}

export interface SessionReview {
  total_actions: number;
  grade_counts: Record<string, number>;
  total_ev_loss_bb: number;      // 양수 = 누적 손실 크기(bb)
  gto_match_rate: number | null;
}

// ── 애니메이션 이벤트 ──────────────────────────────

export type GameEvent =
  | { type: "blind";          player: string; position: string; amount: number; street: string; log?: string; chips_after?: number; pot_after?: number; bet_after?: number }
  | { type: "deal_card";      player: string; position: string; round: number;  street: string; log?: string }
  | { type: "action";         player: string; position: string; action: string; amount: number; street: string; log?: string; chips_after?: number; pot_after?: number; bet_after?: number }
  | { type: "street_start";   street: string;                                                   log?: string; pot_after?: number }
  | { type: "community_card"; card: string;   street: string;                                   log?: string }
  | { type: "showdown";       hands: Record<string, string[]>;                                  log?: string }
  | { type: "winner";         winners: string[]; pot: number; winner_chips?: Record<string, number>; log?: string };

export interface ActionBadge {
  player: string;
  text: string;
  variant: "blind" | "fold" | "check" | "call" | "raise" | "allin";
}

// ── GTO 레인지 ──────────────────────────────────────

// 게임 상태의 GTO 패널 정보 — advisor 추천 하나에서 만든다(server/session.py::_get_gto_panel).
// found=false: 이 상황의 GTO 데이터 없음. 레인지는 node_key로 /gto/preflop/range?action_seq= 조회.
export interface GtoNode {
  found: boolean;
  position: string;                 // 히어로 포지션(헤즈업은 BTN/SB)
  node_key?: string | null;         // 추천이 쓴 노드의 action_seq (UTG RFI는 "")
  approx?: boolean;                 // 간단 라벨 예비 결과 → "(근사)" (ADR 0035)
  situation?: string;               // "BTN RFI"
  hand?: string | null;             // "AKs"
  frequencies?: Record<string, number> | null; // 내 패 액션 빈도
}

export interface GtoRange {
  found: boolean;
  situation?: string;         // "BTN RFI"
  raise_size?: number | null; // 실측 bb(REAL) 단위 raise-to, 없으면 null — server/main.py::raise_size
  summary?: Record<string, number>; // {fold:0.48, raise:0.52}
  hands?: Record<string, Record<string, number>>; // {AA:{raise:1.0}, K7o:{raise:0.21,fold:0.79}}
  action_seq?: string;
}

export interface SetupConfig {
  player_name: string;
  chips: number;
  num_bots: number;
  difficulty: "easy" | "medium" | "hard";
  big_blind: number;
}
