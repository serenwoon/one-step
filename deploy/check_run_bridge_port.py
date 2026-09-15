#!/usr/bin/env python3
"""run_bridge.sh의 포트 우선순위와 프로필 초기화/보존을 검증한다.

- PORT만 지정한 경우, ONE_STEP_PORT를 직접 지정한 경우를 각각 실행
- /health가 어느 포트에 응답하는지 확인
- 첫 서버 종료 + 포트 닫힘 확인 후 같은 프로필로 재실행해서 config.yaml 보존 확인
- 실제 모델·정책 API는 호출하지 않는다.
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
HERMES_CMD = shutil.which("hermes") or "hermes"

# verify_new_service_profile.py의 keys_env를 참고: 키 값 없이 이름만 전달
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


def read_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def run_bridge(profile_dir, port, one_step_port=None, extra_env=None):
    env = os.environ.copy()
    env.pop("PORT", None)
    env.pop("ONE_STEP_PORT", None)
    env["ONE_STEP_SERVICE_MODE"] = "1"
    env["ONE_STEP_HERMES_HOME"] = profile_dir
    env["ONE_STEP_HOST"] = "127.0.0.1"
    env["HERMES_CMD"] = HERMES_CMD
    env["PORT"] = str(port)
    if one_step_port is not None:
        env["ONE_STEP_PORT"] = str(one_step_port)
    if KEYS_ENV:
        env.update(KEYS_ENV)
    if extra_env:
        env.update(extra_env)
    return subprocess.Popen(
        [SHELL, RUN_BRIDGE],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def is_port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except OSError:
            return False


def wait_port_closed(port, timeout_sec=15):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if not is_port_open(port):
            return True
        time.sleep(0.3)
    return False


def wait_bridge_ready(proc, profile_dir, port, timeout_sec=20):
    """bridge가 떠서 /health에 응답하거나 프로세스가 죽을 때까지 기다린다.

    proc.poll()로 시작 실패(즉시 종료)를 감지하면 stdout/stderr를 출력한다.
    """
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        # 프로세스가 이미 끝났으면 시작 실패로 간주
        if proc.poll() is not None:
            stdout = proc.stdout.read() if proc.stdout else ""
            stderr = proc.stderr.read() if proc.stderr else ""
            print(f"  브릿지 시작 실패 (종료 코드 {proc.returncode}):")
            if stdout:
                print(f"    stdout: {stdout[:500]}")
            if stderr:
                print(f"    stderr: {stderr[:500]}")
            return None
        health = wait_health(f"http://127.0.0.1:{port}", timeout_sec=1)
        if health is not None:
            return health
        time.sleep(0.3)
    # 타임아웃: 프로세스 상태 확인
    if proc.poll() is not None:
        stdout = proc.stdout.read() if proc.stdout else ""
        stderr = proc.stderr.read() if proc.stderr else ""
        print(f"  브릿지 타임아웃 후 종료 (코드 {proc.returncode}):")
        if stdout:
            print(f"    stdout: {stdout[:500]}")
        if stderr:
            print(f"    stderr: {stderr[:500]}")
    else:
        print(f"  브릿지 타임아웃: /health 응답 없음 (포트 {port})")
    return None


def kill_proc(proc):
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def main():
    overall_ok = True
    procs = []

    try:
        # --- 케이스 1: PORT만 지정 ---
        print("\n=== 케이스 1: PORT만 지정 ===")
        p1 = free_port()
        profile1 = tempfile.mkdtemp(prefix="one-step-port-only-")
        print(f"임시 프로필: {profile1}")
        print(f"PORT={p1}, ONE_STEP_PORT=(미지정)")

        proc1 = run_bridge(profile1, port=p1, one_step_port=None)
        procs.append(proc1)

        health1 = wait_bridge_ready(proc1, profile1, p1)
        if health1 and health1.get("ok"):
            print(f"OK: /health 응답 포트={p1} -> {health1}")
        else:
            print(f"FAIL: PORT={p1}에서 /health 응답 없음")
            overall_ok = False

        # --- 케이스 2: ONE_STEP_PORT 직접 지정 (PORT도 있지만 우선순위 확인) ---
        print("\n=== 케이스 2: ONE_STEP_PORT 직접 지정 ===")
        p2 = free_port()
        explicit_port = free_port()  # p2+1 대신 별도 빈 포트
        profile2 = tempfile.mkdtemp(prefix="one-step-explicit-")
        print(f"임시 프로필: {profile2}")
        print(f"PORT={p2}, ONE_STEP_PORT={explicit_port}")

        proc2 = run_bridge(profile2, port=p2, one_step_port=explicit_port)
        procs.append(proc2)

        health2 = wait_bridge_ready(proc2, profile2, explicit_port)
        if health2 and health2.get("ok"):
            print(f"OK: /health 응답 포트={explicit_port} (ONE_STEP_PORT 우선) -> {health2}")
        else:
            print(f"FAIL: ONE_STEP_PORT={explicit_port}에서 /health 응답 없음")
            overall_ok = False

        # 첫 번째 서버들을 모두 종료하고 포트가 닫히는지 확인
        print("\n=== 첫 서버 종료 + 포트 닫힘 확인 ===")
        for proc in procs:
            kill_proc(proc)
        procs.clear()

        for label, port in [("케이스1", p1), ("케이스2", explicit_port)]:
            if wait_port_closed(port):
                print(f"OK: {label} 포트 {port} 닫힘")
            else:
                print(f"FAIL: {label} 포트 {port}가 닫히지 않음")
                overall_ok = False

        # --- 재실행: 프로필 보존 확인 ---
        print("\n=== 재실행: 프로필 보존 확인 ===")
        # 케이스 1 재실행 (PORT만)
        first_text1 = read_file(os.path.join(profile1, "config.yaml"))
        proc_r1 = run_bridge(profile1, port=p1, one_step_port=None)
        procs.append(proc_r1)
        health_r1 = wait_bridge_ready(proc_r1, profile1, p1)
        if health_r1 and health_r1.get("ok"):
            print(f"OK: 케이스1 재실행 /health 응답 -> {health_r1}")
        else:
            print(f"FAIL: 케이스1 재실행 /health 응답 없음")
            overall_ok = False
        second_text1 = read_file(os.path.join(profile1, "config.yaml"))
        if first_text1 == second_text1:
            print(f"OK: 케이스1 config.yaml 보존됨")
        else:
            print(f"FAIL: 케이스1 config.yaml 변경됨")
            overall_ok = False

        # 케이스 2 재실행 (ONE_STEP_PORT 직접 지정)
        first_text2 = read_file(os.path.join(profile2, "config.yaml"))
        proc_r2 = run_bridge(profile2, port=p2, one_step_port=explicit_port)
        procs.append(proc_r2)
        health_r2 = wait_bridge_ready(proc_r2, profile2, explicit_port)
        if health_r2 and health_r2.get("ok"):
            print(f"OK: 케이스2 재실행 /health 응답 -> {health_r2}")
        else:
            print(f"FAIL: 케이스2 재실행 /health 응답 없음")
            overall_ok = False
        second_text2 = read_file(os.path.join(profile2, "config.yaml"))
        if first_text2 == second_text2:
            print(f"OK: 케이스2 config.yaml 보존됨")
        else:
            print(f"FAIL: 케이스2 config.yaml 변경됨")
            overall_ok = False

        # 재실행 서버 먼저 종료
        print("\n=== 재실행 서버 종료 ===")
        for proc in procs:
            kill_proc(proc)
        procs.clear()

        # 최종 포트 닫힘 확인 (재실행 서버 모두 종료한 후)
        print("\n=== 최종 포트 닫힘 확인 ===")
        for label, port in [("케이스1 재실행", p1), ("케이스2 재실행", explicit_port)]:
            if wait_port_closed(port):
                print(f"OK: {label} 포트 {port} 닫힘")
            else:
                print(f"FAIL: {label} 포트 {port}가 닫히지 않음")
                overall_ok = False

    finally:
        print("\n=== 남는 프로세스 정리 ===")
        for proc in procs:
            kill_proc(proc)
        procs.clear()
        # 마지막 포트 닫힘 재확인
        for label, port in [("케이스1 최종", p1), ("케이스2 최종", explicit_port)]:
            if is_port_open(port):
                print(f"FAIL: {label} 포트 {port} 아직 열려 있음")
                overall_ok = False
            else:
                print(f"OK: {label} 포트 {port} 닫힘")

    print("\n=== 결과 ===")
    if overall_ok:
        print("통과")
        return 0
    else:
        print("실패")
        return 1


if __name__ == "__main__":
    sys.exit(main())
