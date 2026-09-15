#!/usr/bin/env python3
"""
one-step 브리지 헬스체크용 포트 판별 + 상태 확인 스크립트.

시작 스크립트(run_bridge.sh)와 같은 우선순위로 포트를 계산한다.
1) ONE_STEP_PORT 가 있으면 그 값
2) 없으면 호스팅 PORT
3) 둘 다 없으면 9001

HEALTHCHECK는 시작 스크립트와 별도 프로세스이므로 직접
환경변수 우선순위로 포트를 계산한 뒤 http://localhost:<포트>/health 를
확인하고, 성공하면 0, 실패하면 1을 반환한다.

실행 예시:
    ONE_STEP_PORT=9123 python3 deploy/check_health_port.py
    PORT=9090 python3 deploy/check_health_port.py
    python3 deploy/check_health_port.py
"""
from __future__ import annotations

import os
import sys
import urllib.request
import urllib.error


def resolve_port() -> int:
    raw = os.environ.get("ONE_STEP_PORT") or os.environ.get("PORT") or "9001"
    # 잘못 지정한 포트를 다른 포트로 대체하면 엉뚱한 서버를 검사할 수 있다.
    port = int(raw)
    if not 1 <= port <= 65535:
        raise ValueError("포트는 1~65535 범위여야 합니다")
    return port


def check_health(port: int, timeout: float = 5.0) -> bool:
    url = f"http://localhost:{port}/health"
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=timeout) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        print(f"health check: HTTP {e.code} from {url}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"health check: 연결 실패 ({url}: {e})", file=sys.stderr)
        return False


def main() -> int:
    try:
        port = resolve_port()
    except ValueError as e:
        print(f"health check: 포트 설정 오류 ({e})", file=sys.stderr)
        return 1
    print(f"health check: using port={port}", file=sys.stderr)
    if check_health(port):
        print(f"health check: ok (http://localhost:{port}/health)", file=sys.stderr)
        return 0
    print(f"health check: 실패 (http://localhost:{port}/health)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
