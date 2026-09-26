# 0025. 포트 고정(8765/5766) + 백엔드 HTTPS 필수

- 상태: 유효
- 날짜: 2026-06-19(포트·HTTPS 도입), 2026-07-19(프론트 포트 5765→5766) · 결정자: jaybe-park

## 맥락
GTO Wizard 브라우저 확장 저장 스크립트(`extractAndSave`)가 GTO Wizard 페이지(HTTPS)에서
로컬 백엔드로 직접 fetch한다. 백엔드가 HTTP면 Mixed Content로 브라우저가 요청을 막는다.
또한 개발용 디버그 크롬(`--remote-debugging-port=9222`, GTO 자동 수집용)이 다른 프로젝트의
프론트 개발 포트(5765)와 충돌해 프론트를 5766으로 옮겨야 했다.

## 결정
백엔드는 항상 HTTPS로 띄운다(`dev.sh`/`prod.sh`가 자체 서명 인증서를 생성·사용, 포트 8765
고정). 프론트 개발 서버는 포트 5766 고정(`web/vite.config.ts`의 `server.port` +
`strictPort: true` — 충돌 시 다른 포트로 넘어가지 않고 에러). 프로덕션은 FastAPI가
`web/dist`를 같은 8765 포트로 직접 서빙하므로 프론트 포트는 개발 모드에만 쓰인다.

## 버린 대안
- 백엔드 HTTP 유지 — GTO Wizard 수동/자동 저장 경로가 Mixed Content로 막힌다.
- 프론트 포트 5765 유지 — 디버그 크롬 원격 포트와 매번 충돌.

## 결과
- 영향받는 spec: `docs/spec/game.md`
- 강제 장치: 없음(`dev.sh`, `prod.sh`, `web/vite.config.ts:7`에 하드코딩된 값이 실제
  동작을 보장 — 코드 확인 완료, 자동 검사는 없음)
