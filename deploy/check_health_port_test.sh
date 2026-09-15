#!/bin/sh
set -eu

# 어느 작업 폴더에서 실행해도 같은 검증을 사용한다.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$SCRIPT_DIR/check_health_port_test.py"
