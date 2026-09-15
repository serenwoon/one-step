#!/usr/bin/env python3
"""
bridge_server.py 실행 모드 검증 (모델/Hermes 호출 없음)
- 서비스 모드(ONE_STEP_SERVICE_MODE=1)에서 ONE_STEP_HERMES_HOME 누락 시 시작 실패 확인
- 서비스 모드에서 실제 hermes 호출 argv에 -t mcp-one-step-policy가 포함되는지 확인
- 로컬 모드에서는 -t가 전달되지 않고 기존 fallback이 유지되는지 확인
- HERMES_CMD를 임시 가짜 실행 파일로 지정하고 POST /ask로 전달 argv를 검사
- 실제 Hermes, 모델, 정책 API는 호출하지 않음
- 테스트용 서버는 테스트 종료 후 정리
"""
import os
import sys
import json
import socket
import shutil
import subprocess
import tempfile
import time
import urllib.request
import urllib.error

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BRIDGE_SCRIPT = os.path.join(PROJECT_ROOT, "bridge_server.py")
SERVICE_PROFILE = os.path.join(PROJECT_ROOT, "deploy", "ServiceProfile")


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _write_fake_hermes(marker_file):
    """받은 argv와 env를 marker_file에 JSON으로 남기고, 짧은 고정 답변을 stdout에 출력한 뒤 0을 반환하는 가짜 hermes."""
    script = (
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import os\n"
        "import sys\n"
        "\n"
        f"marker = {marker_file!r}\n"
        "payload = {\n"
        '    "argv": sys.argv,\n'
        '    "env_HERMES_HOME": os.environ.get("HERMES_HOME"),\n'
        "}\n"
        "try:\n"
        '    with open(marker, "w", encoding="utf-8") as f:\n'
        "        json.dump(payload, f, ensure_ascii=False, indent=2)\n"
        "except Exception as e:\n"
        '    with open(marker, "w", encoding="utf-8") as f:\n'
        '        json.dump({"error": str(e)}, f, ensure_ascii=False)\n'
        'sys.stdout.write(json.dumps({"reply": "테스트용 가짜 hermes 답변"}) + "\\n")\n'
        "sys.exit(0)\n"
    )
    return script


def _wait_health(base_url, timeout_sec=15):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base_url + "/health", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionRefusedError):
            pass
        time.sleep(0.5)
    return False


def _start_bridge_and_get_stderr(env, timeout_sec=15):
    """시작 실패를 기다리고 (proc, stderr_text)를 반환한다. 대기 시간도 제한한다."""
    proc = subprocess.Popen(
        [sys.executable, BRIDGE_SCRIPT],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _, stderr_text = proc.communicate(timeout=timeout_sec)
        return proc, stderr_text
    except subprocess.TimeoutExpired:
        # 출력이 없는 채로 살아 있어도 검사 프로세스가 계속 남지 않게 한다.
        proc.kill()
        proc.communicate()
        raise RuntimeError("bridge 시작 대기 중 timeout") from None


def _post_ask(base_url, port, fake_bin, marker_file):
    ask_body = json.dumps({"query": "테스트용 짧은 입력"}).encode("utf-8")
    req = urllib.request.Request(
        base_url + "/ask",
        data=ask_body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        status = e.code
        body = e.read().decode("utf-8")

    if status != 200:
        return {"fail": f"POST /ask HTTP {status}", "body": body}

    try:
        data = json.loads(body)
    except Exception:
        return {"fail": "POST /ask 응답 JSON 아님", "body": body}

    reply = data.get("reply")
    if not isinstance(reply, str) or not reply.strip():
        return {"fail": "POST /ask reply 비어 있음", "body": body}

    if not os.path.exists(marker_file):
        return {"fail": "가짜 hermes가 환경 정보를 남기지 않음"}

    with open(marker_file, encoding="utf-8") as f:
        received = json.load(f)

    argv = received.get("argv")
    env_home = received.get("env_HERMES_HOME")
    return {"argv": argv, "env_home": env_home, "reply": reply}


def test_service_mode_missing_home():
    """ONE_STEP_SERVICE_MODE=1일 때 ONE_STEP_HERMES_HOME이 없으면 시작 즉시 종료."""
    port = _free_port()
    env = os.environ.copy()
    env.pop("ONE_STEP_HERMES_HOME", None)
    env["ONE_STEP_SERVICE_MODE"] = "1"
    env["ONE_STEP_PORT"] = str(port)
    env["HERMES_CMD"] = "/usr/bin/true"

    proc, stderr_text = _start_bridge_and_get_stderr(env)
    proc.wait(timeout=5)

    if proc.returncode != 0:
        combined = stderr_text or ""
        if "ONE_STEP_SERVICE_MODE=1 requires ONE_STEP_HERMES_HOME" in combined:
            print("OK: 서비스 모드 프로필 누락 시 시작 실패")
            return True
        print(f"[FAIL] 서비스 모드 프로필 누락: 예상과 다른 종료/메시지\n  종료코드={proc.returncode}\n  메시지={combined!r}")
        return False

    print("[FAIL] 서비스 모드 프로필 누락: 오류로 끝나지 않음")
    return False


def test_service_mode_argv():
    """서비스 모드에서 실제 hermes 호출 argv에 -t mcp-one-step-policy가 포함되는지 확인."""
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"

    with tempfile.TemporaryDirectory(prefix="one-step-fake-hermes-") as tmpdir:
        fake_bin = os.path.join(tmpdir, "hermes")
        marker_file = os.path.join(tmpdir, "hermes_received.json")

        fake_script = _write_fake_hermes(marker_file)
        with open(fake_bin, "w", encoding="utf-8") as f:
            f.write(fake_script)
        os.chmod(fake_bin, 0o755)

        env = os.environ.copy()
        env.pop("ONE_STEP_HERMES_HOME", None)
        env["ONE_STEP_SERVICE_MODE"] = "1"
        env["ONE_STEP_HERMES_HOME"] = SERVICE_PROFILE
        env["ONE_STEP_PORT"] = str(port)
        env["HERMES_CMD"] = fake_bin

        proc = subprocess.Popen(
            [sys.executable, BRIDGE_SCRIPT],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            if not _wait_health(base_url):
                proc.terminate()
                proc.wait(timeout=5)
                print("[FAIL] 서비스 모드 테스트 서버가 시작되지 않음")
                return False

            result = _post_ask(base_url, port, fake_bin, marker_file)
            if "fail" in result:
                proc.terminate()
                proc.wait(timeout=5)
                print(f"[FAIL] 서비스 모드 POST /ask 실패: {result['fail']}")
                return False

            argv = result["argv"]
            env_home = result["env_home"]

            print("=== 서비스 모드(argv 확인) ===")
            print(f"  받은 HERMES_HOME: {env_home}")
            print(f"  가짜 hermes argv: {argv}")

            if env_home != SERVICE_PROFILE:
                print(f"[FAIL] 서비스 모드 HERMES_HOME 불일치\n  기대값: {SERVICE_PROFILE}\n  실제값: {env_home}")
                return False

            # -t mcp-one-step-policy가 argv에 순서대로 있는지 확인
            expected_tail = ["-t", "mcp-one-step-policy"]
            if argv[-2:] != expected_tail:
                print(f"[FAIL] 서비스 모드 -t 전달 불일치\n  기대 tail: {expected_tail}\n  실제 tail: {argv[-2:] if len(argv) >= 2 else argv}")
                return False

            print("OK: 서비스 모드 — HERMES_HOME 전달 + -t mcp-one-step-policy 포함 확인")
            return True
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            shutil.rmtree(tmpdir, ignore_errors=True)


def test_local_mode_no_t():
    """로컬 모드에서는 -t가 전달되지 않고, 환경변수 미지정 시 개발용 fallback이 유지되는지 확인."""
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"

    with tempfile.TemporaryDirectory(prefix="one-step-fake-hermes-") as tmpdir:
        fake_bin = os.path.join(tmpdir, "hermes")
        marker_file = os.path.join(tmpdir, "hermes_received.json")

        fake_script = _write_fake_hermes(marker_file)
        with open(fake_bin, "w", encoding="utf-8") as f:
            f.write(fake_script)
        os.chmod(fake_bin, 0o755)

        env = os.environ.copy()
        env.pop("ONE_STEP_HERMES_HOME", None)
        env.pop("ONE_STEP_SERVICE_MODE", None)
        env["ONE_STEP_PORT"] = str(port)
        env["HERMES_CMD"] = fake_bin

        proc = subprocess.Popen(
            [sys.executable, BRIDGE_SCRIPT],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            if not _wait_health(base_url):
                proc.terminate()
                proc.wait(timeout=5)
                print("[FAIL] 로컬 모드 테스트 서버가 시작되지 않음")
                return False

            result = _post_ask(base_url, port, fake_bin, marker_file)
            if "fail" in result:
                proc.terminate()
                proc.wait(timeout=5)
                print(f"[FAIL] 로컬 모드 POST /ask 실패: {result['fail']}")
                return False

            argv = result["argv"]
            env_home = result["env_home"]
            expected_home = "/Users/JWoon/.hermes/profiles/one-step"

            print("=== 로컬 모드(argv 확인) ===")
            print(f"  받은 HERMES_HOME: {env_home}")
            print(f"  가짜 hermes argv: {argv}")

            if env_home != expected_home:
                print(f"[FAIL] 로컬 모드 HERMES_HOME 불일치\n  기대값: {expected_home}\n  실제값: {env_home}")
                return False

            if "-t" in argv:
                idx = argv.index("-t")
                print(f"[FAIL] 로컬 모드에서 -t가 전달됨 (기성 로컬 동작 유지 실패)\n  argv: {argv}")
                return False

            print("OK: 로컬 모드 — -t 미포함 + 개발용 fallback 유지 확인")
            return True
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    results = []

    results.append(("서비스 모드 프로필 누락 실패", test_service_mode_missing_home()))
    results.append(("서비스 모드 argv(-t 포함)", test_service_mode_argv()))
    results.append(("로컬 모드 -t 미포함", test_local_mode_no_t()))

    print()
    for name, ok in results:
        print(f"  {name}: {'OK' if ok else 'FAIL'}")

    if all(ok for _, ok in results):
        print("\nOK: 실행 모드 관련 검증 완료 (인자 연결까지만 확인)")
        return 0
    print("\nFAILED: 일부 케이스가 실패함")
    return 1


if __name__ == "__main__":
    sys.exit(main())
