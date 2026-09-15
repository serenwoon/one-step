#!/usr/bin/env python3
"""bridge_server.py의 GET /health와 OPTIONS /ask를 실제 HTTP 요청으로 검증한다.

- GET /health: 200 응답 + body JSON 확인
- OPTIONS /ask: 204 응답 + CORS 헤더 확인
- 응답 순서 문제로 BadStatusLine이 발생하지 않는지 확인
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
RUN_BRIDGE = os.path.join(PROJECT_ROOT, "deploy", "run_bridge.sh")
SHELL = "/bin/sh"
HERMES_CMD = os.environ.get("HERMES_CMD") or shutil.which("hermes") or "hermes"
KEYS_ENV = {
    "UPSTAGE_API_KEY": "registration-check-only",
    "ON_YOUTH_API_KEY": "registration-check-only",
    "GOV24_API_KEY": "registration-check-only",
}


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def wait_health(base_url, timeout_sec=20):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base_url + "/health", timeout=2) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, ConnectionRefusedError, OSError, socket.timeout):
            pass
        time.sleep(0.3)
    return None


def http_request(url, method="GET", body=None, headers=None):
    """실제 HTTP 요청을 보내고 (code, headers, body_bytes)를 반환한다."""
    req = urllib.request.Request(url, method=method, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            code = resp.status
            hdrs = dict(resp.headers)
            raw = resp.read()
            return code, hdrs, raw
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()
    except urllib.error.URLError as e:
        return None, {}, str(e).encode("utf-8")
    except Exception as e:
        return None, {}, str(e).encode("utf-8")


def main():
    port = free_port()
    profile_dir = tempfile.mkdtemp(prefix="one-step-http-check-")
    base_url = f"http://127.0.0.1:{port}"

    print(f"임시 프로필: {profile_dir}")
    print(f"포트: {port}")
    print(f"브리지 기동 중...")

    env = os.environ.copy()
    env.pop("PORT", None)
    env.pop("ONE_STEP_PORT", None)
    env.update(KEYS_ENV)
    env.update({
        "ONE_STEP_SERVICE_MODE": "1",
        "ONE_STEP_HERMES_HOME": profile_dir,
        "ONE_STEP_HOST": "127.0.0.1",
        "HERMES_CMD": HERMES_CMD,
        "PORT": str(port),
    })

    proc = subprocess.Popen(
        [SHELL, RUN_BRIDGE],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        # /health 응답 대기
        health = wait_health(base_url)
        if not health:
            print(f"FAIL: GET /health 응답이 없습니다 (포트 {port})")
            return 1
        print(f"OK: GET /health -> {health}")

        # OPTIONS /ask 요청 (preflight)
        code, headers, raw = http_request(base_url + "/ask", method="OPTIONS")
        if code == 204:
            cors_origin = headers.get("Access-Control-Allow-Origin")
            cors_methods = headers.get("Access-Control-Allow-Methods")
            cors_headers_hdr = headers.get("Access-Control-Allow-Headers")
            print(f"OK: OPTIONS /ask -> {code}")
            print(f"  Access-Control-Allow-Origin: {cors_origin}")
            print(f"  Access-Control-Allow-Methods: {cors_methods}")
            print(f"  Access-Control-Allow-Headers: {cors_headers_hdr}")
            if not cors_origin or not cors_methods:
                print("FAIL: CORS 헤더가 불충분합니다")
                return 1
        else:
            print(f"FAIL: OPTIONS /ask -> {code} (예상 204)")
            print(f"  응답 헤더: {headers}")
            print(f"  응답 본문: {raw[:200]}")
            return 1

        # GET /health 다시 확인 (응답 순서 문제로 BadStatusLine 발생 여부)
        code2, headers2, raw2 = http_request(base_url + "/health")
        if code2 == 200:
            try:
                data2 = json.loads(raw2.decode("utf-8"))
                print(f"OK: GET /health 재요청 -> {code2} (body OK, BadStatusLine 미발생)")
            except Exception as e:
                print(f"FAIL: GET /health 응답 파싱 실패: {e}")
                print(f"  원본: {raw2[:200]}")
                return 1
        else:
            print(f"FAIL: GET /health 재요청 -> {code2} (BadStatusLine 가능성)")
            print(f"  응답 본문: {raw2[:200]}")
            return 1

        print("\n=== 결과 ===")
        print("GET /health, OPTIONS /ask 모두 정상")
        return 0
    finally:
        # 정리
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        shutil.rmtree(profile_dir)
        print(f"\n브리지 종료 완료 (PID {proc.pid})")


if __name__ == "__main__":
    sys.exit(main())
