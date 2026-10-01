# web — ev_plus 프론트엔드 (React + Vite + Tailwind)

```bash
npm install          # 처음 한 번
npm run dev          # http://localhost:5766 (백엔드 https://localhost:8765 필요 — 루트 ./start.sh가 둘 다 띄움)
npm run build        # tsc -b + vite build
npm run lint         # eslint
npm run test         # vitest (src/**/__tests__/*.test.ts, 순수 로직만)
```

화면·API 규칙은 루트 `docs/spec/game.md`(웹 게임 흐름)를 본다.
