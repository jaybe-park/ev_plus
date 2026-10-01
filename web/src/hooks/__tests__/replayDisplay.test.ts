// 재생 중 표시 상태 = "이전 상태 + 소비한 이벤트". 픽스처는 실제 WebGameSession 응답
// (tests/make_replay_fixture.py로 생성 — 4인, 사람 UTG 폴드 후 봇 3명이 리버 쇼다운까지 / 다음 핸드 시작).
import { describe, it, expect } from "vitest";
import fixture from "./fixtures/replay_session.json";
import type { GameState, GameEvent } from "../../types";
import {
  initialDisplay, applyEvent, applyEvents, projectState, eventTiming, HUMAN_ACTION_MS,
  panelState, shownState,
  type DisplayState,
} from "../eventQueueLogic";

const fold = fixture.fold_to_showdown as unknown as { prev: GameState; next: GameState };
const newHand = fixture.new_hand as unknown as { prev: GameState; next: GameState };

/** 이벤트를 하나씩 소비하며 매 시점의 화면 상태(projectState)를 모은다. */
function frames(prev: GameState, next: GameState, isNewHand: boolean) {
  let d: DisplayState = initialDisplay(prev, null, next, isNewHand);
  const out: { event: GameEvent; shown: GameState }[] = [];
  for (const e of next.events) {
    d = applyEvent(d, e);
    out.push({ event: e, shown: projectState(next, d) });
  }
  return { start: projectState(next, initialDisplay(prev, null, next, isNewHand)), out, final: d };
}

describe("재생 표시 상태 — 폴드 후 봇들이 진행", () => {
  const { start, out, final } = frames(fold.prev, fold.next, false);

  it("재생 시작 화면은 요청 직전 상태다(최종 팟·스트리트·보드가 먼저 보이지 않는다)", () => {
    expect(start.pot).toBe(fold.prev.pot);
    expect(start.street).toBe("프리플랍");
    expect(start.community_cards).toEqual([]);
    expect(fold.next.street).toBe("리버");       // 서버 최종 상태는 이미 리버
    expect(fold.next.community_cards.length).toBe(5);
    for (const p of start.players) {
      const before = fold.prev.players.find((q) => q.name === p.name)!;
      expect([p.chips, p.current_bet, p.is_folded]).toEqual([before.chips, before.current_bet, before.is_folded]);
    }
  });

  it("팟은 액션 이벤트와 같은 시점에 바뀐다(pot_after)", () => {
    for (const { event, shown } of out) {
      if (event.type === "action" || event.type === "blind") expect(shown.pot).toBe(event.pot_after);
    }
  });

  it("스트리트 라벨·보드 카드는 street_start/community_card 이벤트에서만 바뀐다", () => {
    let street = "프리플랍";
    let cards = 0;
    for (const { event, shown } of out) {
      if (event.type === "street_start") street = event.street;
      if (event.type === "community_card") cards += 1;
      expect(shown.street).toBe(street);
      expect(shown.community_cards.length).toBe(cards);
    }
  });

  it("봇 베팅액은 그 봇의 액션 이벤트 전에는 보이지 않는다", () => {
    // 플랍 Beta 레이즈 직전 프레임에서 Beta의 베팅은 0(스트리트 시작 리셋)
    const i = out.findIndex(({ event }) => event.type === "action" && event.action === "raise");
    const beta = (event: GameEvent) => (event as { player: string }).player;
    const who = beta(out[i].event);
    expect(out[i - 1].shown.players.find((p) => p.name === who)!.current_bet).toBe(0);
    expect(out[i].shown.players.find((p) => p.name === who)!.current_bet)
      .toBe((out[i].event as { bet_after: number }).bet_after);
  });

  it("폴드 표시는 그 폴드 이벤트부터", () => {
    expect(start.players.find((p) => p.is_human)!.is_folded).toBe(false);
    expect(out[0].shown.players.find((p) => p.is_human)!.is_folded).toBe(true);
  });

  it("모든 이벤트를 소비하면 서버 최종 상태와 같다", () => {
    const shown = projectState(fold.next, final);
    expect(shown.pot).toBe(fold.next.pot);
    expect(shown.street).toBe(fold.next.street);
    expect(shown.community_cards).toEqual(fold.next.community_cards);
    expect(shown.action_log).toEqual(fold.next.action_log);
    expect(shown.players.map((p) => [p.name, p.chips, p.current_bet, p.is_folded]))
      .toEqual(fold.next.players.map((p) => [p.name, p.chips, p.current_bet, p.is_folded]));
    expect(final.showdownRevealed).toBe(true);
  });

  it("스킵(남은 이벤트 한 번에 소비)도 같은 최종 상태", () => {
    const d0 = initialDisplay(fold.prev, null, fold.next, false);
    const half = applyEvents(d0, fold.next.events.slice(0, 7));
    expect(applyEvents(half, fold.next.events.slice(7))).toEqual(final);
  });
});

describe("재생 표시 상태 — 새 핸드 시작", () => {
  const { start, final } = frames(newHand.prev, newHand.next, true);

  it("딜링 전: 팟 0, 카드 0장, 칩 = 직전 핸드 종료 칩", () => {
    expect(start.pot).toBe(0);
    const d = initialDisplay(newHand.prev, null, newHand.next, true);
    for (const p of newHand.next.players) {
      expect(d.seats[p.name].dealt).toBe(0);
      expect(d.seats[p.name].chips).toBe(newHand.prev.players.find((q) => q.name === p.name)!.chips);
    }
  });

  it("블라인드·딜링을 모두 소비하면 서버 상태와 같다", () => {
    const shown = projectState(newHand.next, final);
    expect(shown.pot).toBe(newHand.next.pot);
    expect(shown.players.map((p) => [p.chips, p.current_bet]))
      .toEqual(newHand.next.players.map((p) => [p.chips, p.current_bet]));
    for (const p of newHand.next.players) expect(final.seats[p.name].dealt).toBe(2);
  });
});

describe("힌트 패널은 재생이 끝날 때까지 이전 값", () => {
  // 사람이 플랍에서 콜 → 턴·리버가 깔리는 응답: 새 에퀴티는 아직 안 보인 카드를 반영한 값
  const before = { ...fold.prev, equity: { vs_range: 0.4 } } as unknown as GameState;
  const after = { ...fold.next, equity: { vs_range: 0.9 }, gto: null } as unknown as GameState;

  it("재생 중: 에퀴티·GTO·액션 바는 재생 직전 상태", () => {
    expect(panelState(true, before, after)).toBe(before);
  });
  it("재생 끝: 새 상태", () => {
    expect(panelState(false, before, after)).toBe(after);
  });
  it("테이블은 재생 중 표시 상태, 끝나면 서버 최종 상태", () => {
    const d = initialDisplay(fold.prev, null, fold.next, false);
    expect(shownState(true, d, fold.next).street).toBe("프리플랍");
    expect(shownState(false, d, fold.next)).toBe(fold.next);
  });
});

describe("이벤트 타이밍 — 사람 액션은 즉시, 봇만 연출", () => {
  const human = fold.next.players.find((p) => p.is_human)!.name;
  const humanFold = fold.next.events[0];
  const botCall = fold.next.events[1];

  it("사람 자신의 액션은 '생각 중' 없이 0ms에 반영", () => {
    expect(eventTiming(humanFold, human, 1500, 0.4)).toEqual({ thinking: false, applyAt: 0, next: HUMAN_ACTION_MS });
  });

  it("봇 액션은 생각 중 → 배지(40%) → 다음", () => {
    expect(eventTiming(botCall, human, 1500, 0.4)).toEqual({ thinking: true, applyAt: 600, next: 1500 });
  });

  it("기계적 이벤트는 시작하자마자 반영, 딜링은 지연 끝에 반영", () => {
    const street = fold.next.events.find((e) => e.type === "street_start")!;
    expect(eventTiming(street, human, 600, 0.4)).toEqual({ thinking: false, applyAt: 0, next: 600 });
    const deal = newHand.next.events.find((e) => e.type === "deal_card")!;
    expect(eventTiming(deal, human, 220, 0.4)).toEqual({ thinking: false, applyAt: 220, next: 220 });
  });
});

describe("헤더 핸드 번호는 재생이 끝난 뒤에 바뀐다", () => {
  it("새 핸드 재생 중엔 직전 핸드 번호, 끝나면 새 번호", () => {
    expect(newHand.next.hand_number).toBeGreaterThan(newHand.prev.hand_number);
    expect(panelState(true, newHand.prev, newHand.next).hand_number).toBe(newHand.prev.hand_number);
    expect(panelState(false, newHand.prev, newHand.next).hand_number).toBe(newHand.next.hand_number);
  });
});

describe("재생 중 로그는 끝 기준으로 자른다 — 서버는 action_log[-30:]만 보낸다", () => {
  // 30줄 넘는 핸드: 직전 응답이 이미 30줄(전체 0..29)이고 이번 응답이 새 줄 3개(30..32)를 더함
  // → 서버는 끝 30줄(3..32)을 보낸다. 앞 기준으로 자르면(slice(0, 이전 30줄)) 새 줄이 먼저 보인다.
  const full = Array.from({ length: 33 }, (_, i) => `줄 ${i}`);
  const ev = (i: number): GameEvent => ({
    type: "action", player: "🤖 A", position: "BTN", action: "check", amount: 0, street: "플랍", log: full[i],
  });
  const prev = { ...fold.next, hand_over: false, action_log: full.slice(0, 30), events: [] } as unknown as GameState;
  const next = { ...prev, action_log: full.slice(-30), events: [ev(30), ev(31), ev(32)] } as unknown as GameState;

  it("재생 시작: 직전에 보이던 끝 줄까지, 새 줄은 아직 없음", () => {
    const d = initialDisplay(prev, null, next, false);
    const log = projectState(next, d).action_log;
    expect(log[log.length - 1]).toBe("줄 29");
    expect(log).not.toContain("줄 30");
  });

  it("이벤트를 하나씩 소비할 때마다 그 이벤트의 로그 줄이 끝에 붙는다", () => {
    let d = initialDisplay(prev, null, next, false);
    for (const e of next.events) {
      d = applyEvent(d, e);
      const log = projectState(next, d).action_log;
      expect(log[log.length - 1]).toBe(e.log);
    }
    expect(projectState(next, d).action_log).toEqual(next.action_log);
  });

  it("30줄 미만(픽스처)에서도 매 시점 마지막 줄 = 마지막으로 소비한 로그 이벤트", () => {
    let d = initialDisplay(fold.prev, null, fold.next, false);
    let last = fold.prev.action_log[fold.prev.action_log.length - 1];
    for (const e of fold.next.events) {
      d = applyEvent(d, e);
      if (e.log) last = e.log;
      const log = projectState(fold.next, d).action_log;
      expect(log[log.length - 1]).toBe(last);
    }
  });
});
