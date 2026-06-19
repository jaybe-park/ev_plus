#!/bin/bash
# 개발 모드 실행
# - 백엔드: uvicorn HTTPS --reload (GTO Wizard 연동용)
# - 프론트: Vite dev server (HMR)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSL_KEY="$SCRIPT_DIR/ssl/key.pem"
SSL_CERT="$SCRIPT_DIR/ssl/cert.pem"

echo "♠ Texas Hold'em — 개발 모드"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  백엔드  https://localhost:8765  (HTTPS, reload 활성화)"
echo "  프론트  http://localhost:5765   (HMR 활성화)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

PYTHON=$(command -v python3 || command -v python)
if [ -z "$PYTHON" ]; then
  echo "  오류: python3 또는 python을 찾을 수 없습니다."
  exit 1
fi

if [ ! -f "$SSL_CERT" ] || [ ! -f "$SSL_KEY" ]; then
  echo "  SSL 인증서가 없습니다. 생성 중..."
  mkdir -p "$SCRIPT_DIR/ssl"
  openssl req -x509 -newkey rsa:2048 \
    -keyout "$SSL_KEY" -out "$SSL_CERT" \
    -days 3650 -nodes -subj "/CN=localhost" 2>/dev/null
  echo "  인증서 생성 완료."
fi

cd "$SCRIPT_DIR"
$PYTHON -m uvicorn server.main:app \
  --host 0.0.0.0 --port 8765 \
  --ssl-keyfile "$SSL_KEY" --ssl-certfile "$SSL_CERT" \
  --reload &
BACKEND_PID=$!

cd "$SCRIPT_DIR/web"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "  ⚠️  첫 실행 시 https://localhost:8765 에서 인증서 수동 허용 필요"
echo "  브라우저: http://localhost:5765"
echo "  종료: Ctrl+C"
echo ""

trap "echo ''; echo '서버 종료 중...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
