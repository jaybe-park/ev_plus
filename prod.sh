#!/bin/bash
# 프로덕션 모드 실행
# - 프론트를 빌드한 뒤 FastAPI 단일 HTTPS 서버로 서빙
# - 포트 8765 하나만 사용

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/scripts/server_env.sh"

echo "♠ Texas Hold'em — 프로덕션 모드"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

find_python
ensure_ssl "$SCRIPT_DIR"

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
echo "  https://localhost:8765"
echo "  종료: Ctrl+C"
echo ""

cd "$SCRIPT_DIR"
$PYTHON -m uvicorn server.main:app \
  --host 0.0.0.0 --port 8765 \
  --ssl-keyfile "$SSL_KEY" --ssl-certfile "$SSL_CERT"
