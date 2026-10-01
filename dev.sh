#!/bin/bash
# 개발 모드 실행
# - 백엔드: uvicorn HTTPS --reload (GTO Wizard 연동용)
# - 프론트: Vite dev server (HMR)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/scripts/server_env.sh"

echo "♠ Texas Hold'em — 개발 모드"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  백엔드  https://localhost:8765  (HTTPS, reload 활성화)"
echo "  프론트  http://localhost:5766   (HMR 활성화)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

find_python
ensure_ssl "$SCRIPT_DIR"

cd "$SCRIPT_DIR"
# 서버 코드 디렉터리만 감시한다 — tests/·scripts/·docs 수정으로 재시작되면 메모리의 게임이 사라진다
$PYTHON -m uvicorn server.main:app \
  --host 0.0.0.0 --port 8765 \
  --ssl-keyfile "$SSL_KEY" --ssl-certfile "$SSL_CERT" \
  --reload --reload-dir server --reload-dir core --reload-dir ai --reload-dir gto --reload-dir db &
BACKEND_PID=$!

cd "$SCRIPT_DIR/web"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "  ⚠️  첫 실행 시 https://localhost:8765 에서 인증서 수동 허용 필요"
echo "  브라우저: http://localhost:5766"
echo "  종료: Ctrl+C"
echo ""

trap "echo ''; echo '서버 종료 중...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
