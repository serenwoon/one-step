#!/usr/bin/env python3
"""서비스 모드 브리지 기동 → 정책 질문 → 답변/정책 조회까지 한 번에 확인.
환경변수는 이미 노출된 것만 사용하고, 키 값은 출력하지 않는다.
"""
import os
import sys
import json
import time
import urllib.request
import urllib.error

PROJECT_ROOT = "/Users/JWoon/GitHub/solar-end-to-end"
BRIDGE = os.path.join(PROJECT_ROOT, "bridge_server.py")
PROFILE = os.path.join(PROJECT_ROOT, "deploy", "ServiceProfile")
HERMES_CMD = os.environ.get("HERMES_CMD") or "hermes"

# 서비스 모드 환경 구성 (기존 노출 키만 사용)
env = os.environ.copy()
env["ONE_STEP_SERVICE_MODE"] = "1"
env["ONE_STEP_HERMES_HOME"] = PROFILE
env["ONE_STEP_HOST"] = "127.0.0.1"
env["ONE_STEP_PORT"] = "9099"
env["HERMES_CMD"] = HERMES_CMD
env["HERMES_HOME"] = PROFILE

# 실제 키가 환경변수에 있으면 그대로 쓰고, 없으면 빈 문자열로 둔다.
for k in ("UPSTAGE_API_KEY", "ON_YOUTH_API_KEY", "GOV24_API_KEY"):
    env.setdefault(k, env.get(k, ""))

# 필수 키가 하나도 없으면 미리 알린다.
missing = [k for k in ("UPSTAGE_API_KEY", "ON_YOUTH_API_KEY", "GOV24_API_KEY") if not env.get(k)]
print("사용할 환경:")
print(f"  HERMES_CMD: {HERMES_CMD}")
print(f"  HERMES_HOME: {PROFILE}")
print(f"  서비스 프로필 config.yaml 존재: {os.path.exists(os.path.join(PROFILE, 'config.yaml'))}")
print(f"  정책/모델 키 누락: {missing if missing else '없음'}")
print()

import subprocess

proc = subprocess.Popen(
    [sys.executable, BRIDGE],
    env=env,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)

def health_url():
    return "http://127.0.0.1:9099/health"

def ask_url():
    return "http://127.0.0.1:9099/ask"

def wait_health(timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(health_url(), timeout=2) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except Exception:
            pass
        time.sleep(0.5)
    return None

try:
    health = wait_health()
    if not health:
        proc.terminate()
        out, err = proc.communicate(timeout=5)
        print("브리지 시작 실패 (health 타임아웃)")
        print("STDOUT:", out)
        print("STDERR:", err[:2000])
        sys.exit(1)

    print("브리지 health 확인:", health)
    print()

    # 정책 질문
    query = "청년 취업 지원 정책을 찾아주세요. 지금 신청할 수 있는 사업도 함께 알려주세요."
    body = json.dumps({"query": query}).encode("utf-8")
    req = urllib.request.Request(
        ask_url(),
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            status = resp.status
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        status = e.code
        data = json.loads(e.read().decode("utf-8"))

    print(f"POST /ask 상태: {status}")
    print("응답:")
    print(json.dumps(data, ensure_ascii=False, indent=2))
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
