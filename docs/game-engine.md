# 게임 엔진

`core/` 폴더. UI에 완전히 독립적이며, CLI·웹 모두 이 코드를 그대로 사용한다.

---

## 모듈별 역할

### card.py
- `Suit`: SPADES / HEARTS / DIAMONDS / CLUBS
- `Rank`: TWO(2) ~ ACE(14), `.rank_value` / `.symbol` 속성
- `Card`: `rank + suit`, `str(card)` → `"A♠"` 형식

### deck.py
- 52장 덱, 초기화 시 자동 셔플
- `deal(n)` → `List[Card]`, 뽑은 카드는 덱에서 제거

### player.py
- `Player`: name, chips, hole_cards, is_folded, is_all_in
- `place_bet(amount)`: 실제 베팅, 올인 자동 처리, 실제 베팅액 반환
- `reset_for_hand()` / `reset_for_street()`: 핸드/스트리트 시작 시 초기화

### evaluator.py
- `HandEvaluator.evaluate(cards)`: 5~7장 중 최강 5장 평가, `HandResult` 반환
- `HandResult`: `hand_rank` + `tiebreakers` 튜플로 크기 비교 (`>`, `<`, `==`)
- 타이브레이커 비교 순서:
  - Flush: 5장 랭크 전부 비교
  - Straight: high card 1개
  - Full House: (트리플 랭크, 페어 랭크)
  - 원 페어: (페어 랭크, 키커1, 키커2, 키커3)

### game.py
- `TexasHoldem`: 게임 엔진 본체
- `start_hand()`: 리셋 → 블라인드 포스팅 → 홀카드 딜
- `deal_community(street)`: 플랍(3장) / 턴(1장) / 리버(1장) 딜
- `run_street(street)`: 베팅 라운드 진행 (`_action_callback` 호출 방식)
- `apply_action(player, action, amount)`: 개별 액션 적용. "action" 이벤트에
  `position`/`street`/`to_amount`(해당 라운드 도달 총 베팅액, fold/check는 None) 포함
- `preflop_action_seq()`: 프리플랍 자발적 액션(블라인드 제외) 구조화 시퀀스
  `[{position, action, amount_bb}]` 반환. GTO advisor가 콜/순서/참여인원 판별에 사용
- `showdown()`: 핸드 평가 → 팟 분배 → 딜러 버튼 이동
- `get_positions()`: `{name: "BTN"}` 형태의 포지션 맵 반환
- `_get_game_state()`: 현재 상태 dict 반환 (봇 입력용). `preflop_seq` 포함

---

## 게임 진행 순서

```
start_hand()
  ├─ _reset_hand()        덱 리셋, 커뮤니티·팟·현재 베팅 초기화
  ├─ _post_blinds()       SB/BB 블라인드 포스팅
  └─ _deal_hole_cards()   각 플레이어에게 2장씩

[프리플랍] run_street(PREFLOP)
[플랍]     deal_community(FLOP)   → run_street(FLOP)
[턴]       deal_community(TURN)   → run_street(TURN)
[리버]     deal_community(RIVER)  → run_street(RIVER)

showdown()
  ├─ 1명 남으면 → 팟 전액 지급
  └─ 여러 명 → HandEvaluator로 핸드 비교 → 균등 분배 (split pot)
```

---

## 베팅 라운드 규칙

- **프리플랍 행동 순서**: UTG → MP → CO → BTN → SB → BB
  - SB는 블라인드 포스팅으로 `acted` 처리, BB는 옵션 보유
- **포스트플랍 행동 순서**: SB → BB → UTG → ...
- **레이즈 후**: 이전에 액션했던 플레이어들도 다시 기회를 얻음
- **최소 레이즈**: 직전 레이즈 크기 이상 (`min_raise` 자동 보정)
- **헤즈업(2인)**: BTN/SB가 SB 포스팅 + 프리플랍 선행동
- **사이드팟**: `_calculate_side_pots()`가 올인 스택 기준으로 팟을 계층별로 분리,
  각 계층에서 eligible 플레이어끼리만 분배. 단독 eligible 계층(초과 베팅 반환)은
  승자가 아니므로 winners 집계에서 제외

---

## 알려진 미구현

| 항목 | 현황 |
|---|---|
| 포스트플랍 GTO | 미구현 — 봇은 equity 휴리스틱 전략 사용 |
| 런잇트와이스 | 미구현 |
| 사이드팟별 승자 표시(UI) | 미구현 — 팟은 합산 지급되며 팟별 분해 표시는 TODO |
