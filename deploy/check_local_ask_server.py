"""로컬 목업과 API 라우팅을 실제 HTTP 요청으로 검증한다."""
import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from http.server import ThreadingHTTPServer
from local_ask_server import Router
from solar_service import ServiceError


class LocalServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Router)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def request(self, path, data=None):
        request = urllib.request.Request(
            self.url + path, data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            response = urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.read()

    def test_preview_and_health(self):
        status, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn('id="situation"', body.decode())
        for path in ("/health", "/api/health"):
            status, body = self.request(path)
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(body)["ok"])

    def test_invalid_input_returns_json(self):
        for data in (b"{}", b"not-json"):
            status, body = self.request("/ask", data)
            self.assertEqual(status, 400)
            self.assertIn("error", json.loads(body))

    def test_missing_model_key(self):
        with patch.dict(os.environ, {"UPSTAGE_API_KEY": ""}):
            status, body = self.request("/ask", b'{"query":"hello"}')
        self.assertEqual(status, 503)
        self.assertIn("error", json.loads(body))

    def test_reply_and_follow_up(self):
        # 외부 모델 호출만 대체한다. 실제 HTTP 핸들러의 요청 전달을 확인한다.
        with patch("api.ask.answer", return_value={"reply": "테스트 답변", "conversation": "state"}) as answer:
            status, body = self.request("/ask", b'{"query":"hello"}')
            self.assertEqual(status, 200)
            state = json.loads(body)["conversation"]
            status, _ = self.request("/api/ask", json.dumps({"query": "next", "conversation": state}).encode())
            self.assertEqual(status, 200)
            self.assertEqual(answer.call_args.args[0]["conversation"], "state")

    def test_timeout_and_retry(self):
        with patch("api.ask.answer", side_effect=ServiceError(504, "시간 초과")):
            status, body = self.request("/ask", b'{"query":"hello"}')
            self.assertEqual(status, 504)
            self.assertIn("error", json.loads(body))
        with patch("api.ask.answer", return_value={"reply": "재시도 성공"}):
            self.assertEqual(self.request("/ask", b'{"query":"hello"}')[0], 200)

    def test_private_files_are_not_served(self):
        for path in ("/.env", "/solar_service.py", "/../.env", "/unknown"):
            self.assertEqual(self.request(path)[0], 404)


if __name__ == "__main__":
    unittest.main()
