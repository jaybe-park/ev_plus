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
}

export interface SetupConfig {
  player_name: string;
  chips: number;
  num_bots: number;
  difficulty: "easy" | "medium" | "hard";
  small_blind: number;
}
