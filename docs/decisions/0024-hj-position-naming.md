# 0024. 포지션 네이밍은 GTO Wizard 기준(HJ, MP 아님)

- 상태: 유효
- 날짜: 2026-06-14 · 결정자: jaybe-park

## 맥락
6인 테이블 4번째 좌석(딜러 기준 UTG 다음, CO 이전)의 이름을 "MP"(Middle Position)로
쓰고 있었다. GTO Wizard 등 실제로 참고하는 프리플랍 솔버 자료는 이 좌석을 "HJ"
(Hijack)로 부른다. 이름이 다르면 GTO 데이터·해설을 그대로 대조하기 어렵다.

## 결정
좌석 수별 포지션 라벨 배열(`core/game.py::get_positions`)에서 6인 기준 4번째 좌석을
`HJ`로 쓴다. 좌석 수별 라벨: 2인 `["BTN/SB","BB"]`, 3인 `["BTN","SB","BB"]`, 4인
`["BTN","SB","BB","UTG"]`, 5인 `["BTN","SB","BB","UTG","CO"]`, 6인
`["BTN","SB","BB","UTG","HJ","CO"]`, 7인 `["BTN","SB","BB","UTG","UTG+1","HJ","CO"]`.

## 버린 대안
- "MP" 유지 — GTO Wizard 데이터·문서와 용어가 어긋나 대조가 번거롭다.

## 결과
- 영향받는 spec: `docs/spec/game.md`
- 강제 장치: 없음(라벨 배열 자체를 검사하는 전용 테스트는 없다. 좌석 순서를 쓰는
  간접 테스트: `tests/test_poker_full.py::test_2_5_preflop_betting_order_3players`)
- 참고: 이 결정 이후에도 `docs/api.md`, `docs/game-engine.md`, `docs/db-schema.md`에는
  "MP"가 남아 있었다(이관 시 spec 새로 쓰기로 해소).
