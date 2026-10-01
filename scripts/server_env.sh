#!/bin/bash
# dev.sh·prod.sh 공용 함수. 사용: source "$SCRIPT_DIR/scripts/server_env.sh"

# PYTHON = python3(없으면 python). 둘 다 없으면 종료.
find_python() {
  PYTHON=$(command -v python3 || command -v python)
  if [ -z "$PYTHON" ]; then
    echo "  오류: python3 또는 python을 찾을 수 없습니다."
    exit 1
  fi
}

# 로컬 HTTPS(GTO Wizard Mixed Content 방지)용 자체서명 인증서. 인자 = 저장소 루트.
# SSL_KEY·SSL_CERT를 정하고, 파일이 없으면 <루트>/ssl/에 만든다.
ensure_ssl() {
  SSL_KEY="$1/ssl/key.pem"
  SSL_CERT="$1/ssl/cert.pem"
  if [ ! -f "$SSL_CERT" ] || [ ! -f "$SSL_KEY" ]; then
    echo "  SSL 인증서가 없습니다. 생성 중..."
    mkdir -p "$1/ssl"
    openssl req -x509 -newkey rsa:2048 \
      -keyout "$SSL_KEY" -out "$SSL_CERT" \
      -days 3650 -nodes -subj "/CN=localhost" 2>/dev/null
    echo "  인증서 생성 완료."
  fi
}
