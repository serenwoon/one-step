#!/usr/bin/env python3
"""
check_health_port.py 검증용 임시 서버.

상태 확인에 필요한 /health 응답을 제공한다.
실행:
    python3 deploy/check_health_port_test_server.py
기본 포트 9001. ONE_STEP_PORT / PORT 환경변수로 포트를 바꿀 수 있다.
"""
from __future__ import annotations

import os
import sys
import json
import signal
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            data = json.dumps({"ok": True, "hermes_cmd": "hermes"}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        # 테스트 출력은 병합돼서 헷갈리므로(stdout 섞어 씀) stderr로 돌린다.
        print(f"[test-server] {self.address_string()} - {format % args}", file=sys.stderr)


def main() -> int:
    if os.environ.get("ONE_STEP_PORT"):
        port = int(os.environ["ONE_STEP_PORT"])
    elif os.environ.get("PORT"):
        port = int(os.environ["PORT"])
    else:
        port = 9001

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"[test-server] listening on 127.0.0.1:{port}", file=sys.stderr)

    def shutdown(signum, frame):
        print(f"[test-server] shutting down (signal={signum})", file=sys.stderr)
        # serve_forever와 다른 스레드에서 종료해야 교착되지 않는다.
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
