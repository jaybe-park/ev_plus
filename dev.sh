#!/bin/bash
# 개발 모드 실행
# - 백엔드: uvicorn --reload (코드 변경 시 자동 재시작)
# - 프론트: Vite dev server (HMR)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "♠ Texas Hold'em — 개발 모드"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  백엔드  http://localhost:8000  (reload 활성화)"
echo "  프론트  http://localhost:5173  (HMR 활성화)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

PYTHON=$(command -v python3 || command -v python)
if [ -z "$PYTHON" ]; then
  echo "  오류: python3 또는 python을 찾을 수 없습니다."
  exit 1
fi

cd "$SCRIPT_DIR"
$PYTHON -m server.main &
BACKEND_PID=$!

cd "$SCRIPT_DIR/web"
npm run dev &
FRONTEND_PID=$!

echo "  브라우저: http://localhost:5173"
echo "  종료: Ctrl+C"
echo ""

trap "echo ''; echo '서버 종료 중...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
