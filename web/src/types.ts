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
  gto_hint: string | null;
  action_log: string[];
  call_amount: number;
  min_raise_to: number;
  events: GameEvent[];
  gto_key: GtoKey | null;
}

// ── 애니메이션 이벤트 ──────────────────────────────

export type GameEvent =
  | { type: "blind";          player: string; position: string; amount: number; street: string; log?: string; chips_after?: number }
  | { type: "deal_card";      player: string; position: string; round: number;  street: string; log?: string }
  | { type: "action";         player: string; position: string; action: string; amount: number; street: string; log?: string; chips_after?: number }
  | { type: "street_start";   street: string;                                                   log?: string }
  | { type: "community_card"; card: string;   street: string;                                   log?: string }
  | { type: "showdown";       hands: Record<string, string[]>;                                  log?: string }
  | { type: "winner";         winners: string[]; pot: number; winner_chips?: Record<string, number>; log?: string };

export interface ActionBadge {
  player: string;
  text: string;
  variant: "blind" | "fold" | "check" | "call" | "raise" | "allin";
}

// ── GTO 레인지 ──────────────────────────────────────

export interface GtoKey {
  position: string;       // BTN, CO, MP, UTG, SB, BB
  vs_position: string | null; // null=RFI, "BTN"=vs_open, "UTG/HJ"=vs_3bet
  range_type: string;     // open | vs_open | vs_3bet
}

export interface GtoRange {
  found: boolean;
  situation?: string;         // "BTN RFI"
  raise_size?: string;        // "2.5bb"
  summary?: Record<string, number>; // {fold:0.48, raise:0.52}
  hands?: Record<string, Record<string, number>>; // {AA:{raise:1.0}, K7o:{raise:0.21,fold:0.79}}
  position?: string;
  vs_position?: string | null;
  range_type?: string;
}

export interface SetupConfig {
  player_name: string;
  chips: number;
  num_bots: number;
  difficulty: "easy" | "medium" | "hard";
  big_blind: number;
}
