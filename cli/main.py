"""
Texas Hold'em CLI 인터페이스
웹앱 전환 시: GameController._get_human_action()을 HTTP endpoint로 교체하면 됩니다.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.game import TexasHoldem, Action, Street
from core.player import Player
from ai.bot import PokerBot, BotDifficulty
from cli.config import BOT_ACTION_DELAY_NORMAL, BOT_ACTION_DELAY_FOLDED
from gto.advisor import GTOAdvisor

_gto_advisor = GTOAdvisor()


# ──────────────────────────────────────────────────────────────
# 화면 출력 헬퍼
# ──────────────────────────────────────────────────────────────

def clear():
    os.system("cls" if os.name == "nt" else "clear")


def print_banner():
    print("=" * 56)
    print("        ♠ ♥  Texas Hold'em Poker  ♦ ♣        ")
    print("=" * 56)


def print_separator(char="-", width=56):
    print(char * width)


def print_community_cards(cards):
    if not cards:
        print("  커뮤니티 카드: (없음)")
    else:
        print(f"  커뮤니티 카드: {' '.join(str(c) for c in cards)}")


def print_players(players, show_all=False, positions=None):
    print_separator()
    if positions is None:
        positions = {}
    for p in players:
        status = ""
        if p.is_folded:
            status = "  [폴드]"
        elif p.is_all_in:
            status = "  [올인]"

        cards = ""
        if show_all and not p.is_human:
            cards = f"  {' '.join(str(c) for c in p.hole_cards)}"
        elif p.is_human:
            cards = f"  {' '.join(str(c) for c in p.hole_cards)}"
        else:
            cards = "  🂠 🂠"

        pos_label = positions.get(p.name, "")
        pos_str = f"[{pos_label:<6}]" if pos_label else "        "
        print(f"  {pos_str} {p.name:<12} 칩: {p.chips:>5}{status}{cards}")
    print_separator()


def print_street_header(game: TexasHoldem, street: Street):
    """스트리트 시작 시 한 번만 출력하는 헤더"""
    print()
    print_separator("═")
    print(f"  📍 {street.value}   💰 팟: {game.pot}")
    print_separator("═")
    print_community_cards(game.community_cards)
    print()
    positions = game.get_positions()
    print_players(game.players, positions=positions)
    print()


def print_action_line(entry: str):
    """액션 한 줄 출력"""
    print(f"  {entry}")


def print_current_status(game: TexasHoldem, street: Street):
    """[s] 커맨드로 요청 시 현재 테이블 상태 출력"""
    print()
    print_separator("─")
    print(f"  📊 현재 상태  |  스트리트: {street.value}  |  팟: {game.pot}")
    print_separator("─")
    print_community_cards(game.community_cards)
    print()
    positions = game.get_positions()
    print_players(game.players, positions=positions)
    print()


# ──────────────────────────────────────────────────────────────
# 게임 컨트롤러
# ──────────────────────────────────────────────────────────────

class GameController:
    def __init__(self):
        self.game: TexasHoldem = None
        self.bots: dict = {}
        self.human_player: Player = None
        self.action_log: list = []       # 현재 핸드 액션 기록
        self.current_street: Street = None
        self.human_folded: bool = False    # 현재 핸드에서 사람이 폴드했는지

    def setup(self):
        clear()
        print_banner()
        print()

        name = input("  플레이어 이름을 입력하세요: ").strip() or "Player"
        try:
            chips = int(input("  시작 칩 수 (기본 1000): ").strip() or "1000")
        except ValueError:
            chips = 1000

        try:
            num_bots = int(input("  AI 봇 수 (1~5, 기본 5): ").strip() or "5")
            num_bots = max(1, min(5, num_bots))
        except ValueError:
            num_bots = 5

        print("\n  난이도: [1] 쉬움  [2] 보통  [3] 어려움")
        diff_input = input("  선택 (기본 2): ").strip() or "2"
        diff_map = {"1": BotDifficulty.EASY, "2": BotDifficulty.MEDIUM, "3": BotDifficulty.HARD}
        difficulty = diff_map.get(diff_input, BotDifficulty.MEDIUM)

        self.human_player = Player(name, chips, is_human=True)
        players = [self.human_player]

        bot_names = ["🤖 Alpha", "🤖 Beta", "🤖 Gamma", "🤖 Delta", "🤖 Epsilon"]
        for i in range(num_bots):
            bot_player = Player(bot_names[i], chips, is_human=False)
            bot = PokerBot(bot_player, difficulty)
            self.bots[bot_player.name] = bot
            players.append(bot_player)

        try:
            sb = int(input(f"\n  스몰 블라인드 (기본 10): ").strip() or "10")
            bb = sb * 2
        except ValueError:
            sb, bb = 10, 20

        self.game = TexasHoldem(players, small_blind=sb, big_blind=bb)
        self.game._action_callback = self._get_action

        diff_names = {BotDifficulty.EASY: "쉬움", BotDifficulty.MEDIUM: "보통", BotDifficulty.HARD: "어려움"}
        print(f"\n  ✅ 설정 완료! 봇 {num_bots}명 ({diff_names[difficulty]} 난이도)")
        input("  Enter를 눌러 시작하세요...")

    def _get_action(self, player: Player, game_state: dict):
        """액션 요청 → 웹앱 전환 시 이 메서드를 HTTP endpoint로 교체"""
        pos = game_state["positions"].get(player.name, "")
        pos_str = f"[{pos}]" if pos else ""

        if not player.is_human:
            bot = self.bots.get(player.name)
            if bot:
                action, amount = bot.decide_action(game_state)
                msg = self._format_action(player.name, pos_str, action, amount, game_state)
                self.action_log.append(msg)
                print_action_line(msg)   # 봇 액션: 한 줄만 출력
                delay = BOT_ACTION_DELAY_FOLDED if self.human_folded else BOT_ACTION_DELAY_NORMAL
                time.sleep(delay)
                return action, amount
            return Action.CHECK, 0

        # 사람 차례: 입력창만 출력
        return self._get_human_action(player, game_state, pos_str)

    def _get_street_enum(self, street_name: str) -> Street:
        return {s.value: s for s in Street}.get(street_name, Street.PREFLOP)

    def _format_action(self, name: str, pos: str, action: Action, amount: int, state: dict) -> str:
        """액션 문자열 생성"""
        current_bet = state["current_bet"]
        if action == Action.FOLD:
            return f"{pos} {name}: 폴드"
        elif action == Action.CHECK:
            return f"{pos} {name}: 체크"
        elif action == Action.CALL:
            player_bet = next((p.current_bet for p in self.game.players if p.name == name), 0)
            call_amt = current_bet - player_bet
            return f"{pos} {name}: 콜 ({call_amt})"
        elif action == Action.RAISE:
            player_bet = next((p.current_bet for p in self.game.players if p.name == name), 0)
            raise_by = amount - player_bet
            return f"{pos} {name}: 레이즈 → {amount} (+{raise_by})"
        elif action == Action.ALL_IN:
            return f"{pos} {name}: 올인!"
        return f"{pos} {name}: {action.value}" 

    def _get_human_action(self, player: Player, game_state: dict, pos_str: str = ""):
        """사람 플레이어의 액션 입력"""
        call_amount = game_state["current_bet"] - player.current_bet
        pot = self.game.pot
        street = self._get_street_enum(game_state["street"])
        min_raise_to = game_state["current_bet"] + game_state["min_raise"]  # 최소 레이즈 총액
        big_blind = self.game.big_blind

        options = []
        if call_amount == 0:
            options.append(("c", "체크", Action.CHECK, 0))
        else:
            options.append(("f", "폴드", Action.FOLD, 0))
            options.append(("c", f"콜", Action.CALL, call_amount))
        if player.chips > call_amount:
            options.append(("r", f"레이즈", Action.RAISE, min_raise_to))
        options.append(("a", f"올인", Action.ALL_IN, 0))
        options.append(("s", "상태 보기", None, 0))

        print(f"\n  ── {pos_str} {player.name}의 차례 ──")
        print(f"  내 카드: {' '.join(str(c) for c in player.hole_cards)}")
        # GTO 힌트
        positions = game_state.get("positions", {})
        my_pos = positions.get(player.name, "")
        gto_rec = _gto_advisor.get_recommendation(player.hole_cards, my_pos, positions, game_state, big_blind)
        gto_hint = _gto_advisor.format_hint(gto_rec)
        if gto_hint:
            print(f"  {gto_hint}")
        print(f"  칩: {player.chips}  |  팟: {pot}  |  콜: {call_amount}")
        print()
        if call_amount > 0:
            print(f"  [f] 폴드")
            print(f"  [c] 콜          {call_amount} 베팅 (내 칩: {player.chips} → {player.chips - call_amount})")
        else:
            print(f"  [c] 체크")
        if player.chips > call_amount:
            raise_cost = min_raise_to - player.current_bet  # 내가 실제 내야 할 금액
            print(f"  [r] 레이즈       총액 {min_raise_to} 이상 지정 (추가 {raise_cost} 이상, 내 칩: {player.chips} → {player.chips - raise_cost})")
        print(f"  [a] 올인         {player.chips} 전부 베팅")
        print(f"  [s] 상태 보기")
        opt_str = ""  # 재출력용 (s 커맨드 후)

        while True:
            choice = input("  선택: ").strip().lower()
            if choice == "s":
                print_current_status(self.game, street)
                print(f"  ── {pos_str} {player.name}의 차례 | 칩: {player.chips}  팟: {self.game.pot}  콜: {call_amount} ──")
                print(f"  내 카드: {' '.join(str(c) for c in player.hole_cards)}")
                print("  선택: f/c/r/a/s")
                continue
            matched = [o for o in options if o[0] == choice and o[2] is not None]
            if matched:
                _, label, action, default_amount = matched[0]
                if action == Action.RAISE:
                    try:
                        amount_input = input(f"  레이즈 총액 입력 (최소 {min_raise_to}): ").strip()
                        amount = int(amount_input) if amount_input else min_raise_to
                        amount = max(amount, min_raise_to)
                    except ValueError:
                        amount = min_raise_to
                    msg = self._format_action(player.name, pos_str, action, amount, game_state)
                    self.action_log.append(msg)
                    print_action_line(msg)
                    return action, amount
                if action == Action.FOLD:
                    self.human_folded = True
                msg = self._format_action(player.name, pos_str, action, default_amount, game_state)
                self.action_log.append(msg)
                print_action_line(msg)
                return action, default_amount
            print("  잘못된 입력입니다. (f/c/r/a/s)")

    def play_hand(self):
        """한 핸드 진행"""
        g = self.game
        self.action_log = []
        self.human_folded = False

        # 파산 플레이어 제거 후 dealer_index 범위 보정
        g.players = [p for p in g.players if p.chips > 0]
        if len(g.players) < 2:
            return False
        g.dealer_index = g.dealer_index % len(g.players)

        g.start_hand()

        # 블라인드 로그 기록
        positions = g.get_positions()
        for name, pos in positions.items():
            if pos in ("SB", "BTN/SB"):
                self.action_log.append(f"[{pos}] {name}: 스몰 블라인드 ({g.small_blind})")
            elif pos == "BB":
                self.action_log.append(f"[{pos}] {name}: 빅 블라인드 ({g.big_blind})")

        streets = [Street.PREFLOP, Street.FLOP, Street.TURN, Street.RIVER]
        for street in streets:
            if g._count_active() <= 1:
                break
            if street != Street.PREFLOP:
                self.action_log.append(f"── {street.value} ──")
            # 커뮤니티 카드를 먼저 딜한 뒤 헤더 출력
            g.deal_community(street)
            print_street_header(g, street)
            g.run_street(street)

        # 쇼다운
        winners = g.showdown()
        self._show_result(winners)
        return True

    def _show_result(self, winners):
        """결과 출력"""
        print()
        print_separator("═")
        print("  🃏 쇼다운 결과")
        print_separator("═")
        print_community_cards(self.game.community_cards)
        print()

        # 쇼다운 핸드 공개
        contenders = [p for p in self.game.players if not p.is_folded]
        if len(contenders) > 1:
            print("  ── 핸드 공개 ──")
            from core.evaluator import HandEvaluator
            for p in contenders:
                all_cards = p.hole_cards + self.game.community_cards
                result = HandEvaluator.evaluate(all_cards)
                cards_str = " ".join(str(c) for c in p.hole_cards)
                print(f"  {p.name}: {cards_str}  →  {result}")
            print()

        print("  🏆 승자: " + ", ".join(w.name for w in winners))
        print()
        positions = self.game.get_positions()
        print_players(self.game.players, show_all=True, positions=positions)

    def run(self):
        """메인 게임 루프"""
        self.setup()
        hand_count = 0

        while True:
            hand_count += 1
            clear()
            print_banner()
            print(f"\n  [핸드 #{hand_count}]")
            print()

            # 인간 플레이어 파산 체크
            if self.human_player.chips <= 0:
                print("  💸 칩이 모두 소진되었습니다. 게임 오버!")
                break

            active_count = sum(1 for p in self.game.players if p.chips > 0)
            if active_count < 2:
                print("  🎉 모든 상대를 이겼습니다! 게임 클리어!")
                break

            result = self.play_hand()
            if not result:
                break

            # 게임 계속 여부
            choice = input("\n  계속 하시겠습니까? [Enter: 계속 / q: 종료]: ").strip().lower()
            if choice == "q":
                print(f"\n  최종 칩: {self.human_player.chips}")
                print("  게임을 종료합니다. 감사합니다!")
                break


# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    controller = GameController()
    controller.run()
