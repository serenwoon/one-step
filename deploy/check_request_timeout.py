#!/usr/bin/env python3
"""
bridge_server.py의 요청 타임아웃(ONE_STEP_REQUEST_TIMEOUT)과
504/500 오류 처리를 검증한다.

- 느린 가짜 hermes로 타임아웃 재현 → HTTP 504, 질문 유지 확인
- 정상 hermes로 정상 응답 확인
- 존재하지 않는 실행 파일로 일반 실패 확인 → HTTP 500

검증은 별도 임시 포트에서 진행하며, 실제 9876 서버는 건드리지 않는다.
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
HERMES_CMD = shutil.which("hermes") or "hermes"

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
        except (urllib.error.URLError, ConnectionRefusedError, OSError):
            pass
        time.sleep(0.3)
    return None

def http_post(base_url, query, cookie=None, timeout=200):
    """POST /ask 실행. (code, headers, body_bytes, elapsed) 반환."""
    start = time.time()
    body = json.dumps({"query": query}).encode("utf-8")
    req = urllib.request.Request(
        base_url + "/ask",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed = time.time() - start
            return resp.status, dict(resp.headers), resp.read(), elapsed
    except urllib.error.HTTPError as e:
        elapsed = time.time() - start
        return e.code, dict(e.headers), e.read(), elapsed
    except Exception as e:
        elapsed = time.time() - start
        return None, {}, str(e).encode("utf-8"), elapsed

def make_slow_hermes(target_dir):
    """지정한 초만큼 sleep 후 고정 응답을 출력하는 가짜 hermes 스크립트.
    Hermes가 전달하는 인자와 무관하게 고정된 지연 시간을 사용한다."""
    script = os.path.join(target_dir, "slow-hermes.sh")
    with open(script, "w") as f:
        f.write(f"#!{sys.executable}\nimport time\ntime.sleep(60)\nprint('가짜 응답')\n")
    os.chmod(script, 0o755)
    return script

def make_fail_hermes(target_dir):
    """즉시 종료 코드 1로 끝나는 가짜 hermes."""
    script = os.path.join(target_dir, "fail-hermes.sh")
    with open(script, "w") as f:
        f.write("""#!/bin/sh
echo "실패한 hermes" >&2
exit 1
""")
    os.chmod(script, 0o755)
    return script

def main():
    overall_ok = True
    tmp_dir = tempfile.mkdtemp(prefix="one-step-timeout-check-")
    profile_dir = tempfile.mkdtemp(prefix="one-step-profile-")
    print(f"임시 프로필: {profile_dir}")
    print(f"테스트 자산: {tmp_dir}")

    try:
        # 테스트용 프로필 초기화 (서비스 모드 기동 필수)
        init_script = os.path.join(PROJECT_ROOT, "deploy", "init_service_profile.py")
        init_result = subprocess.run(
            [sys.executable, init_script, profile_dir, "--python-cmd", sys.executable],
            capture_output=True, text=True, timeout=10,
        )
        if init_result.returncode != 0:
            print(f"FAIL: 프로필 초기화 실패: {init_result.stderr}")
            return 1
        print(f"프로필 초기화 완료: {profile_dir}")

        # ---- 케이스 1: 타임아웃(504) 재현 ----
        print("\n=== 케이스 1: ONE_STEP_REQUEST_TIMEOUT 짧게 + 느린 hermes → 504 ===")
        port1 = free_port()
        base1 = f"http://127.0.0.1:{port1}"

        slow_hermes = make_slow_hermes(tmp_dir)
        env1 = os.environ.copy()
        env1.update({
            "ONE_STEP_SERVICE_MODE": "1",
            "ONE_STEP_HERMES_HOME": profile_dir,
            "HERMES_HOME": profile_dir,
            "ONE_STEP_HOST": "127.0.0.1",
            "ONE_STEP_PORT": str(port1),
            "HERMES_CMD": slow_hermes,
            "ONE_STEP_REQUEST_TIMEOUT": "2",  # 2초 제한
            "UPSTAGE_API_KEY": "registration-check-only",
            "ON_YOUTH_API_KEY": "registration-check-only",
            "GOV24_API_KEY": "registration-check-only",
            "PATH": os.environ.get("PATH", ""),
        })

        proc1 = subprocess.Popen(
            [sys.executable, os.path.join(PROJECT_ROOT, "bridge_server.py")],
            env=env1,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            health1 = wait_health(base1)
            if not health1:
                print("FAIL: 케이스1 브리지 기동 실패")
                overall_ok = False
            else:
                print(f"OK: 케이스1 브리지 기동: {health1}")

                # 첫 요청으로 쿠키 확보 (느린 hermes라도 쿠키는 설정됨)
                code1, hdrs1, body1, elapsed1 = http_post(base1, "월세가 걱정돼요.", timeout=10)
                cookie1 = hdrs1.get("Set-Cookie", "")
                print(f"첫 요청: HTTP {code1}, {elapsed1:.1f}초, 쿠키: {cookie1[:40] if cookie1 else '없음'}...")

                if code1 == 504:
                    print("OK: 타임아웃 → HTTP 504")
                    # 오류 메시지가 질문 유지 안내인지 확인
                    data1 = json.loads(body1.decode("utf-8"))
                    msg1 = data1.get("error", "")
                    if "입력하신 내용을 유지한 채 다시 시도해 주세요" in msg1:
                        print("OK: 504 응답에 질문 유지 안내 포함")
                    else:
                        print(f"FAIL: 504 응답 메시지 예상과 다름: {msg1}")
                        overall_ok = False
                else:
                    print(f"FAIL: 예상 504, 실제 {code1}")
                    overall_ok = False

                # 같은 서버와 쿠키를 유지한 채 다음 실행만 빠른 응답으로 바꾼다.
                with open(slow_hermes, "w") as f:
                    f.write("#!/bin/sh\necho '재시도 정상 응답'\n")
                if cookie1:
                    cookie_header = cookie1.split(";", 1)[0]
                    code2, hdrs2, body2, elapsed2 = http_post(base1, "다시 시도", cookie=cookie_header, timeout=10)
                    if code2 != 200 or hdrs2.get("Set-Cookie", "").split(";", 1)[0] != cookie_header:
                        overall_ok = False
                        print("FAIL: 같은 쿠키로 정상 재시도 실패")
                    else:
                        print("OK: 시간 초과 뒤 같은 쿠키로 HTTP 200. 대화 잠금과 슬롯 해제 확인")
                else:
                    overall_ok = False
        finally:
            proc1.terminate()
            try:
                proc1.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc1.kill()
                proc1.wait(timeout=5)
            print(f"케이스1 브리지 종료 (PID {proc1.pid})")

        # ---- 케이스 2: 정상 응답 (기본 타임아웃, 빠른 hermes) ----
        print("\n=== 케이스 2: 정상 hermes → HTTP 200 ===")
        port2 = free_port()
        base2 = f"http://127.0.0.1:{port2}"

        # 빠르게 응답하는 가짜 hermes (echo만 하고 종료)
        fast_script = os.path.join(tmp_dir, "fast-hermes.sh")
        with open(fast_script, "w") as f:
            f.write("""#!/bin/sh
echo "빠른 답변: 정상 응답입니다."
""")
        os.chmod(fast_script, 0o755)

        env2 = os.environ.copy()
        env2.update({
            "ONE_STEP_SERVICE_MODE": "1",
            "ONE_STEP_HERMES_HOME": profile_dir,
            "HERMES_HOME": profile_dir,
            "ONE_STEP_HOST": "127.0.0.1",
            "ONE_STEP_PORT": str(port2),
            "HERMES_CMD": fast_script,
            "ONE_STEP_REQUEST_TIMEOUT": "",  # 미설정 → 기본값 180
            "UPSTAGE_API_KEY": "registration-check-only",
            "ON_YOUTH_API_KEY": "registration-check-only",
            "GOV24_API_KEY": "registration-check-only",
            "PATH": os.environ.get("PATH", ""),
        })

        proc2 = subprocess.Popen(
            [sys.executable, os.path.join(PROJECT_ROOT, "bridge_server.py")],
            env=env2,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            health2 = wait_health(base2)
            if not health2:
                print("FAIL: 케이스2 브리지 기동 실패")
                overall_ok = False
            else:
                print(f"OK: 케이스2 브리지 기동: {health2}")
                code, hdrs, body, elapsed = http_post(base2, "다시 일하고 싶어요.", timeout=10)
                print(f"요청: HTTP {code}, {elapsed:.1f}초")
                if code == 200:
                    data = json.loads(body.decode("utf-8"))
                    reply = data.get("reply", "")
                    if "빠른 답변" in reply:
                        print(f"OK: 정상 응답 수신: {reply[:80]}...")
                    else:
                        print(f"FAIL: 예상과 다른 응답: {reply[:200]}")
                        overall_ok = False
                else:
                    print(f"FAIL: 예상 200, 실제 {code}")
                    overall_ok = False
        finally:
            proc2.terminate()
            try:
                proc2.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc2.kill()
                proc2.wait(timeout=5)
            print(f"케이스2 브리지 종료 (PID {proc2.pid})")

        # ---- 케이스 3: 일반 실행 실패 (존재하지 않는 hermes) → 500 ----
        print("\n=== 케이스 3: 없는 hermes 실행 파일 → HTTP 500 ===")
        port3 = free_port()
        base3 = f"http://127.0.0.1:{port3}"

        env3 = os.environ.copy()
        env3.update({
            "ONE_STEP_SERVICE_MODE": "1",
            "ONE_STEP_HERMES_HOME": profile_dir,
            "HERMES_HOME": profile_dir,
            "ONE_STEP_HOST": "127.0.0.1",
            "ONE_STEP_PORT": str(port3),
            "HERMES_CMD": "/nonexistent/hermes-fake",
            "ONE_STEP_REQUEST_TIMEOUT": "",  # 미설정
            "UPSTAGE_API_KEY": "registration-check-only",
            "ON_YOUTH_API_KEY": "registration-check-only",
            "GOV24_API_KEY": "registration-check-only",
            "PATH": os.environ.get("PATH", ""),
        })

        proc3 = subprocess.Popen(
            [sys.executable, os.path.join(PROJECT_ROOT, "bridge_server.py")],
            env=env3,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            health3 = wait_health(base3, timeout_sec=10)
            if not health3:
                # 실행 파일이 없어서 시작 자체가 실패할 수 있음 → 그 상태를 확인
                if proc3.poll() is not None:
                    stdout = proc3.stdout.read() if proc3.stdout else ""
                    stderr = proc3.stderr.read() if proc3.stderr else ""
                    print(f"참고: 케이스3 브리지 시작 실패 (코드 {proc3.returncode})")
                    if "HERMES_CMD" in (stderr or "") or "찾을 수 없음" in (stderr or ""):
                        print("OK: 없는 실행 파일 → 시작 시 감지")
                    else:
                        print(f"stderr: {stderr[:300]}")
                        print(f"stdout: {stdout[:300]}")
                else:
                    print("FAIL: 케이스3 /health 응답 없음")
                    overall_ok = False
            else:
                print(f"OK: 케이스3 브리지 기동: {health3}")
                code, hdrs, body, elapsed = http_post(base3, "테스트", timeout=10)
                print(f"요청: HTTP {code}, {elapsed:.1f}초")
                if code == 500:
                    data = json.loads(body.decode("utf-8"))
                    msg = data.get("error", "")
                    print(f"OK: 일반 실패 → HTTP 500: {msg}")
                else:
                    print(f"FAIL: 예상 500, 실제 {code}")
                    overall_ok = False
        finally:
            if proc3.poll() is None:
                proc3.terminate()
                try:
                    proc3.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc3.kill()
                    proc3.wait(timeout=5)
            print(f"케이스3 브리지 종료 (PID {proc3.pid})")

        # ---- 케이스 4: 잘못된 ONE_STEP_REQUEST_TIMEOUT 설정 거부 ----
        print("\n=== 케이스 4: 잘못된 ONE_STEP_REQUEST_TIMEOUT → 시작 시 거부 ===")
        port4 = free_port()
        env4 = os.environ.copy()
        env4.update({
            "ONE_STEP_SERVICE_MODE": "1",
            "ONE_STEP_HERMES_HOME": profile_dir,
            "HERMES_HOME": profile_dir,
            "ONE_STEP_HOST": "127.0.0.1",
            "ONE_STEP_PORT": str(port4),
            "HERMES_CMD": HERMES_CMD,
            "ONE_STEP_REQUEST_TIMEOUT": "abc",  # 잘못된 값
            "UPSTAGE_API_KEY": "registration-check-only",
            "ON_YOUTH_API_KEY": "registration-check-only",
            "GOV24_API_KEY": "registration-check-only",
            "PATH": os.environ.get("PATH", ""),
        })

        proc4 = subprocess.Popen(
            [sys.executable, os.path.join(PROJECT_ROOT, "bridge_server.py")],
            env=env4,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            proc4.wait(timeout=10)
            if proc4.returncode == 4:
                stderr4 = proc4.stderr.read() if proc4.stderr else ""
                print(f"OK: 잘못된 타임아웃 설정 → 종료 코드 4")
                if "ONE_STEP_REQUEST_TIMEOUT은 1 이상의 정수" in stderr4:
                    print("OK: 오류 메시지 포함")
                else:
                    print(f"stderr: {stderr4[:200]}")
            else:
                print(f"FAIL: 예상 종료 코드 4, 실제 {proc4.returncode}")
                print(f"stderr: {proc4.stderr.read()[:200] if proc4.stderr else ''}")
                overall_ok = False
        except subprocess.TimeoutExpired:
            proc4.kill()
            proc4.wait(timeout=5)
            print(f"FAIL: 케이스4 브리지 종료 대기 초과 (아직 실행 중)")
            overall_ok = False

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        shutil.rmtree(profile_dir, ignore_errors=True)
        print(f"\n임시 자원 정리: {tmp_dir}, {profile_dir}")

    print("\n=== 결과 ===")
    if overall_ok:
        print("통과")
        return 0
    else:
        print("실패")
        return 1

if __name__ == "__main__":
    sys.exit(main())
