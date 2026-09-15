#!/usr/bin/env python3
"""목업과 Vercel API 핸들러를 같은 주소에서 실행하는 로컬 확인 서버."""
import os
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from api.ask import handler as AskHandler
from api.health import handler as HealthHandler
from api.check_draft import handler as CheckDraftHandler
from api.check_health import handler as CheckHealthHandler

PREVIEW_DIR = Path(__file__).resolve().parent / "preview"


class Router(AskHandler):
    # /ask의 응답 메서드도 상속해 실제 API와 동일한 오류 응답을 사용한다.
    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ("/health", "/api/health"):
            HealthHandler.do_GET(self)
        elif path in ("/check_health", "/api/check_health"):
            CheckHealthHandler.do_GET(self)
        elif path in ("/", "/index.html"):
            self.send_preview()
        else:
            self.respond(404, {"error": "페이지를 찾을 수 없어요."})

    def send_preview(self):
        # 저장소 전체를 정적 파일로 열지 않고 목업 파일만 제공한다.
        body = (PREVIEW_DIR / "index.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = urlsplit(self.path).path
        if path in ("/ask", "/api/ask"):
            super().do_POST()
        elif path in ("/check_draft", "/api/check_draft"):
            CheckDraftHandler.do_POST(self)
        else:
            self.respond(404, {"error": "요청 주소를 확인해 주세요."})


if __name__ == "__main__":
    port = int(os.environ.get("LOCAL_ASK_PORT", "9002"))
    with ThreadingHTTPServer(("127.0.0.1", port), Router) as server:
        print(f"local ask server: http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
