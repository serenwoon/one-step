#!/usr/bin/env python3
"""
bridge_server.py의 ONE_STEP_HOST 반영 확인 (모델 호출 없음)
- ONE_STEP_HOST 미지정 시 127.0.0.1
- ONE_STEP_HOST 지정 시 해당 host로 서버 생성
- --fail은 서버를 띄우지 않고 실패 결과의 종료 코드만 확인
- 실제 hermes 호출은 하지 않음
- 테스트용 서버는 종료 시 정리
"""
import os
import sys
import socket
import selectors
import subprocess
import time
import urllib.request
import urllib.error

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE_SCRIPT = os.path.join(PROJECT_ROOT, "bridge_server.py")


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _wait_health(host, port, timeout_sec=15):
    url = f"http://{host}:{port}/health"
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionRefusedError):
            pass
        time.sleep(0.5)
    return False


def _stop_bridge(proc):
    """검사용 서버를 종료하고 출력 파이프도 닫는다."""
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    finally:
        proc.stdout.close()
        proc.stderr.close()


def _start_bridge(env, timeout_sec=15):
    proc = subprocess.Popen(
        [sys.executable, BRIDGE_SCRIPT],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + timeout_sec
        output = b""
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                if not selector.select(timeout=max(0, remaining)):
                    break
                chunk = os.read(proc.stdout.fileno(), 4096)
                if not chunk:
                    raise RuntimeError("bridge가 시작 직후 종료됨")
                output += chunk
                if b"\n" in output:
                    return proc, output.split(b"\n", 1)[0].decode("utf-8")
        raise RuntimeError("bridge 시작 대기 중 timeout")
    except Exception:
        _stop_bridge(proc)
        raise


def test_default_host():
    """ONE_STEP_HOST 미지정 → 127.0.0.1"""
    port = _free_port()
    env = os.environ.copy()
    env.pop("ONE_STEP_HOST", None)
    env.pop("ONE_STEP_HERMES_HOME", None)
    env.pop("ONE_STEP_SERVICE_MODE", None)
    env.pop("ONE_STEP_PORT", None)
    env["ONE_STEP_PORT"] = str(port)
    env["HERMES_CMD"] = "/usr/bin/true"

    proc, first_line = _start_bridge(env)
    try:
        if "127.0.0.1" not in first_line:
            print(f"[FAIL] 기본 호스트 불일치: {first_line!r}")
            return False
        if not _wait_health("127.0.0.1", port):
            print("[FAIL] 기본 호스트 health 연결 실패")
            return False
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as resp:
            data = resp.read().decode("utf-8")
        print(f"OK: 기본 호스트=127.0.0.1 — health 응답: {data[:120]}")
        return True
    finally:
        _stop_bridge(proc)


def test_custom_host():
    """ONE_STEP_HOST=0.0.0.0 지정 → 해당 host로 서버 생성"""
    port = _free_port()
    env = os.environ.copy()
    env.pop("ONE_STEP_HOST", None)
    env.pop("ONE_STEP_HERMES_HOME", None)
    env.pop("ONE_STEP_SERVICE_MODE", None)
    env["ONE_STEP_HOST"] = "0.0.0.0"
    env["ONE_STEP_PORT"] = str(port)
    env["HERMES_CMD"] = "/usr/bin/true"

    proc, first_line = _start_bridge(env)
    try:
        if "0.0.0.0" not in first_line:
            print(f"[FAIL] 지정 호스트 반영 실패: {first_line!r}")
            return False
        if not _wait_health("127.0.0.1", port):
            print("[FAIL] 지정 호스트 health 연결 실패")
            return False
        print(f"OK: 지정 호스트=0.0.0.0 — health 응답 확인")
        return True
    finally:
        _stop_bridge(proc)


def main(force_failure=False):
    results = []
    if force_failure:
        # 실패 결과를 같은 집계 경로로 보내고, 검사 파일을 다시 실행하지 않는다.
        results.append(("의도한 실패", False))
    else:
        results.append(("기본 호스트 (127.0.0.1)", test_default_host()))
        results.append(("지정 호스트 (0.0.0.0)", test_custom_host()))

    print()
    for name, ok in results:
        print(f"  {name}: {'OK' if ok else 'FAIL'}")

    if all(ok for _, ok in results):
        print("\nOK: ONE_STEP_HOST 반영 확인 완료")
        return 0
    print("\nFAILED: 일부 케이스 실패")
    return 1


if __name__ == "__main__":
    sys.exit(main(force_failure="--fail" in sys.argv))
