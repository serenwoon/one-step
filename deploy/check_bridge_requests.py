#!/usr/bin/env python3
"""
브리지 동시 요청과 검사 시간 제한 검증 (외부 API/모델 호출 없음)
- 답변 대기 중에도 상태 확인과 다른 대화는 응답하는지
- 같은 대화의 중복 요청과 전체 실행 한도를 지키는지
- 시작 검사 시간 초과 시 자식 프로세스를 정리하는지
"""
import os
import sys
import json
import threading
import tempfile
import subprocess
import unittest
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

import bridge_server
import check_bridge_profile_env


class QuietHandler(bridge_server.Handler):
    def log_message(self, *args):
        pass


class BridgeRequestTests(unittest.TestCase):
    def setUp(self):
        self.server = bridge_server.ConversationServer(("127.0.0.1", 0), QuietHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, query=None, cookie=None):
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        body = json.dumps({"query": query}).encode() if query is not None else None
        req = urllib.request.Request(self.url + ("/ask" if body else "/health"), data=body, headers=headers)
        try:
            response = urllib.request.urlopen(req, timeout=3)
        except urllib.error.HTTPError as e:
            response = e
        with response:
            return response.status, json.loads(response.read()), response.headers.get("Set-Cookie")

    def test_independent_requests_and_duplicate(self):
        entered = threading.Event()
        release = threading.Event()

        def fake_run(cmd, **kwargs):
            if cmd[cmd.index("-q") + 1].endswith("대기"):
                entered.set()
                if not release.wait(5):
                    raise RuntimeError("검사 대기 시간 초과")
            return SimpleNamespace(returncode=0, stdout="가짜 답변", stderr="")

        with patch.object(bridge_server.subprocess, "run", side_effect=fake_run):
            status, _, cookie = self.request("시작")
            self.assertEqual(status, 200)
            cookie = cookie.split(";", 1)[0]
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(self.request, "대기", cookie)
                try:
                    self.assertTrue(entered.wait(3))
                    self.assertEqual(self.request()[0], 200)
                    self.assertEqual(self.request("다른 대화")[0], 200)
                    self.assertEqual(self.request("중복", cookie)[0], 409)
                finally:
                    release.set()
                self.assertEqual(pending.result(timeout=3)[0], 200)
            self.assertEqual(self.request("후속", cookie)[0], 200)

    def test_capacity_and_release_after_error(self):
        for _ in range(4):
            self.assertTrue(self.server.request_slots.acquire(blocking=False))
        try:
            status, _, cookie = self.request("한도 초과")
            self.assertEqual(status, 503)
        finally:
            for _ in range(4):
                self.server.request_slots.release()
        cookie = cookie.split(";", 1)[0]
        with patch.object(bridge_server.subprocess, "run", side_effect=subprocess.TimeoutExpired("fake", 180)):
            self.assertEqual(self.request("시간 초과", cookie)[0], 504)
        with patch.object(bridge_server.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="가짜 답변", stderr="")):
            self.assertEqual(self.request("재시도", cookie)[0], 200)
        for _ in range(4):
            self.assertTrue(self.server.request_slots.acquire(blocking=False))
        for _ in range(4):
            self.server.request_slots.release()

    def test_start_timeout_cleans_process(self):
        processes = []
        real_popen = subprocess.Popen

        def record_process(*args, **kwargs):
            proc = real_popen(*args, **kwargs)
            processes.append(proc)
            return proc

        with tempfile.TemporaryDirectory() as tmpdir:
            script = os.path.join(tmpdir, "silent.py")
            with open(script, "w", encoding="utf-8") as f:
                f.write("import time\ntime.sleep(30)\n")
            with patch.object(check_bridge_profile_env, "BRIDGE_SCRIPT", script), patch.object(subprocess, "Popen", side_effect=record_process):
                with self.assertRaisesRegex(RuntimeError, "timeout"):
                    check_bridge_profile_env._start_bridge_and_get_stderr(os.environ.copy(), timeout_sec=0.1)
            self.assertIsNotNone(processes[0].poll())


if __name__ == "__main__":
    unittest.main(verbosity=2)
