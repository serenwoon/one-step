#!/bin/sh
set -eu

# one-step 서비스 브리지 실행 스크립트 (컨테이너/호스팅용)
# 필요한 값은 환경변수로 주입한다. 키는 이미지에 넣지 않는다.
#
# 포트 우선순위: ONE_STEP_PORT(직접 지정) > 호스팅 PORT > 기본값 9001
# 설치 경로가 달라도 스크립트 자신의 위치를 기준으로 경로를 계산한다.

: "${ONE_STEP_SERVICE_MODE:=1}"
: "${ONE_STEP_HERMES_HOME:=/opt/one-step/.hermes/profiles/one-step-service}"
: "${ONE_STEP_HOST:=0.0.0.0}"
: "${HERMES_CMD:=hermes}"

# 포트: ONE_STEP_PORT가 있으면 우선, 없으면 호스팅 PORT, 둘 다 없으면 9001
if [ -n "${ONE_STEP_PORT:-}" ]; then
  PORT_USED="$ONE_STEP_PORT"
elif [ -n "${PORT:-}" ]; then
  PORT_USED="$PORT"
  export ONE_STEP_PORT="$PORT_USED"
else
  PORT_USED="9001"
  export ONE_STEP_PORT="$PORT_USED"
fi

# 스크립트 자신의 위치를 기준으로 설치 루트를 잡는다.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
INIT_SCRIPT="$SCRIPT_DIR/init_service_profile.py"

# 서비스 프로필 디렉터리가 없으면 템플릿으로 초기화 (init_service_profile.py 사용)
if [ ! -f "$ONE_STEP_HERMES_HOME/config.yaml" ]; then
  mkdir -p "$ONE_STEP_HERMES_HOME"
  python3 "$INIT_SCRIPT" "$ONE_STEP_HERMES_HOME"
fi

export ONE_STEP_SERVICE_MODE
export ONE_STEP_HERMES_HOME
export ONE_STEP_HOST
export ONE_STEP_PORT
export HERMES_HOME="$ONE_STEP_HERMES_HOME"
export HERMES_CMD

echo "one-step bridge starting"
echo "  HERMES_HOME=$HERMES_HOME"
echo "  ONE_STEP_HOST=$ONE_STEP_HOST"
echo "  ONE_STEP_PORT=$ONE_STEP_PORT (PORT_USED=$PORT_USED)"
echo "  ONE_STEP_SERVICE_MODE=$ONE_STEP_SERVICE_MODE"
echo "  HERMES_CMD=$HERMES_CMD"
echo "  PROJECT_ROOT=$PROJECT_ROOT"

exec python3 "$PROJECT_ROOT/bridge_server.py"
