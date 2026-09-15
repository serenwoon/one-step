#!/usr/bin/env python3
"""포트 선택과 실제 상태 확인. 종료 신호 처리까지 격리해서 검증한다."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

SCRIPT_DIR = Path(__file__).resolve().parent
CHECK = SCRIPT_DIR / "check_health_port.py"
SERVER = SCRIPT_DIR / "check_health_port_test_server.py"


def environment(values):
    env = os.environ.copy()
    env.pop("ONE_STEP_PORT", None)
    env.pop("PORT", None)
    env.update(values)
    return env


def run_check(env):
    return subprocess.run([sys.executable, str(CHECK)], env=env,
                          capture_output=True, text=True, timeout=8)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    # 기본 포트 선택은 바인딩하지 않고 확인해서 기존 로컬 앱을 방해하지 않는다.
    for values, expected in [({}, 9001), ({"PORT": "9123"}, 9123),
                             ({"ONE_STEP_PORT": "9200", "PORT": "9201"}, 9200),
                             ({"ONE_STEP_PORT": "", "PORT": "9123"}, 9123)]:
        result = subprocess.run(
            [sys.executable, "-c", "from check_health_port import resolve_port; print(resolve_port())"],
            cwd=SCRIPT_DIR, env=environment(values), capture_output=True, text=True, timeout=5)
        assert result.returncode == 0 and result.stdout.strip() == str(expected), result.stderr
    print("OK: 기본값과 포트 우선순위")

    for mode in ("PORT", "ONE_STEP_PORT", "both"):
        port = free_port()
        values = {"PORT": str(port)} if mode == "PORT" else {"ONE_STEP_PORT": str(port)}
        if mode == "both":
            values["PORT"] = "1"
        env = environment(values)
        proc = subprocess.Popen([sys.executable, str(SERVER)], env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 6
            while True:
                assert proc.poll() is None, "임시 서버 시작 실패"
                if run_check(env).returncode == 0:
                    break
                assert time.monotonic() < deadline, "서버 준비 시간 초과"
                time.sleep(0.05)
            proc.terminate()
            # 종료 신호 교착이 재발하면 여기서 실패한다.
            proc.wait(timeout=3)
            assert proc.returncode == 0, "서버 정상 종료 실패"
            assert run_check(env).returncode == 1, "종료된 서버를 정상으로 판정함"
            print(f"OK: {mode} 실제 HTTP 성공. SIGTERM 종료. 종료 후 실패")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=3)

    for raw in ("abc", "0", "65536", " "):
        result = run_check(environment({"ONE_STEP_PORT": raw, "PORT": "9001"}))
        assert result.returncode == 1, "잘못된 포트를 다른 포트로 대체함"
    print("OK: 잘못된 포트 실패 처리")
    print("통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
