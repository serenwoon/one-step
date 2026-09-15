#!/usr/bin/env python3
"""
다시, 한 걸음(one-step) — 새 서비스 프로필 브리지 기동 + 정책 MCP 도구 등록 확인

동작:
- deploy/init_service_profile.py로 새 빈 프로필 디렉터리를 만든다.
- 그 프로필로 서비스 모드 브리지를 임시 포트에 띄운다(모델/정책 API 호출 없음).
- GET /health로 브리지 기동을 확인한다.
- hermes MCP 연결(discover_mcp_tools) 후 정책 도구 2개가 등록되는지 확인한다.
- 종료 시 브리지와 MCP 서버를 정리한다.

이 스크립트는 실제 hermes chat을 실행하지 않으며, 모델/정책 API도 호출하지 않는다.
MCP 도구 등록 여부까지만 확인한다.

주의:
- 새 프로필 경로는 기본값으로 시스템 임시 디렉터리를 사용한다.
- 기존 프로필(deploy/ServiceProfile/)은 건드리지 않는다.
- 실제 도구 이름(one-step-policy / mcp__one_step_policy__*)은 코드에 맞춰 확인한다.
"""

import argparse
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
BRIDGE = os.path.join(PROJECT_ROOT, "bridge_server.py")
INIT = os.path.join(PROJECT_ROOT, "deploy", "init_service_profile.py")

def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _wait_health(base_url, timeout_sec=20):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base_url + "/health", timeout=2) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, ConnectionRefusedError):
            pass
        time.sleep(0.5)
    return None


def _run_init(target_dir, python_cmd):
    cmd = [sys.executable, INIT, target_dir, "--python-cmd", python_cmd]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"FAIL: 프로필 초기화 실패\n  {proc.stdout}\n  {proc.stderr}")
        return None
    return target_dir


def _start_bridge(profile_dir, port, python_cmd, hermes_cmd, keys_env):
    env = os.environ.copy()
    env["ONE_STEP_SERVICE_MODE"] = "1"
    env["ONE_STEP_HERMES_HOME"] = profile_dir
    env["ONE_STEP_HOST"] = "127.0.0.1"
    env["ONE_STEP_PORT"] = str(port)
    env["HERMES_CMD"] = hermes_cmd
    env["HERMES_HOME"] = profile_dir
    env.update(keys_env)
    proc = subprocess.Popen(
        [python_cmd, BRIDGE],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return proc


def _discover_policy_tools(profile_dir, python_cmd, keys_env, timeout_sec=90):
    """새 프로필을 별도 Python 프로세스에 전달해 MCP 연결을 확인한다."""
    env = os.environ.copy()
    env.update(keys_env)
    env["ONE_STEP_HERMES_HOME"] = profile_dir
    env["HERMES_HOME"] = profile_dir
    env["ONE_STEP_SERVICE_MODE"] = "1"
    checker = os.path.join(PROJECT_ROOT, "deploy", "check_policy_tools_connected.py")
    result = subprocess.run(
        [python_cmd, checker], env=env, cwd=PROJECT_ROOT,
        capture_output=True, text=True, timeout=timeout_sec,
    )
    # 라이브러리 안내 출력이 있어도 마지막 JSON 결과를 읽는다.
    for line in reversed(result.stdout.splitlines()):
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict) and "policy_ok" in data:
            if result.returncode != 0:
                data["policy_ok"] = False
            return data
    raise RuntimeError(f"MCP 검증 결과 없음 (종료 코드: {result.returncode})\n{result.stderr[-2000:]}")


def main():
    parser = argparse.ArgumentParser(
        description="새 서비스 프로필로 브리지 기동 + 정책 MCP 도구 등록 확인"
    )
    parser.add_argument(
        "--profile-dir",
        default=None,
        help="아직 존재하지 않는 새 프로필 경로 (기본값: 시스템 임시 디렉터리)",
    )
    parser.add_argument(
        "--python-cmd",
        default=None,
        help="브리지 및 MCP 서버에 사용할 Python 명령 (기본값: sys.executable)",
    )
    parser.add_argument(
        "--keep-profile",
        action="store_true",
        help="검증 후에도 만든 프로필 디렉터리를 지우지 않는다",
    )
    parser.add_argument("--hermes-cmd", default=os.environ.get("HERMES_CMD") or "hermes",
                        help="Hermes CLI 실행 파일")
    args = parser.parse_args()

    python_cmd = shutil.which(args.python_cmd or sys.executable)
    hermes_cmd = shutil.which(args.hermes_cmd)
    if not python_cmd or not hermes_cmd:
        print("FAIL: Python 또는 Hermes 실행 파일을 찾지 못함")
        return 1

    # 기존 경로는 빈 폴더라도 사용하지 않는다. 이 실행이 만든 경로만 정리한다.
    if args.profile_dir:
        profile_dir = os.path.abspath(os.path.expanduser(args.profile_dir))
        try:
            os.makedirs(profile_dir, exist_ok=False)
        except FileExistsError:
            print(f"FAIL: 이미 있는 경로는 사용하지 않습니다: {profile_dir}")
            return 1
    else:
        profile_dir = tempfile.mkdtemp(prefix="one-step-verify-")

    proc = None
    try:
        if not _run_init(profile_dir, python_cmd):
            return 1

        # 기동과 도구 목록만 검사한다. 실제 키나 개발용 auth.json은 필요 없다.
        keys_env = {
            name: "registration-check-only"
            for name in ("UPSTAGE_API_KEY", "ON_YOUTH_API_KEY", "GOV24_API_KEY")
        }
        port = _free_port()
        base_url = f"http://127.0.0.1:{port}"
        proc = _start_bridge(profile_dir, port, python_cmd, hermes_cmd, keys_env)
        health = _wait_health(base_url)
        if not health:
            print("FAIL: 브리지 기동 실패 (health 타임아웃)")
            return 1
        print(f"브리지 health 확인: {health}")

        result = _discover_policy_tools(profile_dir, python_cmd, keys_env)
        print(f"MCP 연결 상태: {result['connected']}")
        print(f"정책 도구: {result['policy_tools']}")
        if not result["policy_ok"]:
            print(f"FAIL: 정책 MCP 도구 등록 미확인: {result.get('discover_error')}")
            return 1
        print("OK: 새 프로필 브리지 기동 + 정책 MCP 도구 2개 등록 확인")
        return 0
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as e:
        print(f"FAIL: {e}")
        return 1
    finally:
        # 초기화나 MCP 연결이 실패해도 이 실행에서 만든 자원만 정리한다.
        try:
            if proc is not None:
                proc.terminate()
                try:
                    proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.communicate(timeout=5)
        finally:
            if not args.keep_profile:
                shutil.rmtree(profile_dir)
                print(f"임시 프로필 제거: {profile_dir}")
            else:
                print(f"프로필 보존: {profile_dir}")


if __name__ == "__main__":
    sys.exit(main())
