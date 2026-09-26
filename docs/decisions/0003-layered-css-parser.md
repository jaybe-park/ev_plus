# 0003. 레이어 기반 CSS 파서로 GTO Wizard 빈도 추출

- 상태: 유효
- 날짜: 2026-07-12 · 결정자: jaybe-park

## 맥락
기존 파서는 "단일 gradient + % 색상 스탑" 구조를 가정했다. 실제 화면 구조는 겹친 linear-gradient 레이어와 누적된 `background-size`였다. call이 없는 스팟에서는 우연히 맞았지만, SB RFI처럼 call이 섞인 스팟에서는 169핸드 전부 파싱에 실패했다(badSum 실패 169건).

## 결정
레이어를 앞에서 뒤 순서로 allin/raise/call/fold 색상에 매칭하고, `background-size` 누적폭의 차분으로 각 액션의 빈도를 구한다. `background: none`인 셀은 오픈 레인지 밖 핸드이므로 정당하게 제외한다(누락이 아니라 "해당 없음"). 자동 워커(`scripts/collect_gto_tree.py`)도 같은 파서를 재사용한다.

## 버린 대안
- 단일 gradient 파서 — call/allin 혼합 스팟에서 틀렸다.
- XHR로 솔루션 JSON 가로채기(초기 설계 1순위) — 구현되지 않았고 CSS 경로가 채택됐다.
- 브라우저 밖에서 API 직접 호출 — 약관 리스크로 금지(0012).

## 결과
- 영향받는 spec: `docs/spec/gto-preflop.md`
- 강제 장치: 없음. 파서가 브라우저에 주입하는 JS 문자열(`EXTRACT_JS`)이라 단위 테스트가 없다.
