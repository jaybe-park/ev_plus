#!/bin/bash
# 프로덕션 모드 실행
# - 프론트를 빌드한 뒤 FastAPI 단일 HTTPS 서버로 서빙
# - 포트 8000 하나만 사용

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSL_KEY="$SCRIPT_DIR/ssl/key.pem"
SSL_CERT="$SCRIPT_DIR/ssl/cert.pem"

echo "♠ Texas Hold'em — 프로덕션 모드"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

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

# 1. 프론트 빌드
echo "  [1/2] 프론트엔드 빌드 중..."
cd "$SCRIPT_DIR/web"
npm run build

if [ $? -ne 0 ]; then
  echo "  빌드 실패. 종료합니다."
  exit 1
fi

echo "  [2/2] 서버 시작..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  https://localhost:8000"
echo "  종료: Ctrl+C"
echo ""

cd "$SCRIPT_DIR"
$PYTHON -m uvicorn server.main:app \
  --host 0.0.0.0 --port 8000 \
  --ssl-keyfile "$SSL_KEY" --ssl-certfile "$SSL_CERT"
