#!/bin/bash
# 프로덕션 모드 실행
# - 프론트를 빌드한 뒤 FastAPI 단일 서버로 정적 파일까지 서빙
# - 포트 8000 하나만 사용

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "♠ Texas Hold'em — 프로덕션 모드"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

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
echo "  http://localhost:8000"
echo "  종료: Ctrl+C"
echo ""

PYTHON=$(command -v python3 || command -v python)
if [ -z "$PYTHON" ]; then
  echo "  오류: python3 또는 python을 찾을 수 없습니다."
  exit 1
fi

cd "$SCRIPT_DIR"
$PYTHON -m uvicorn server.main:app --host 0.0.0.0 --port 8000
