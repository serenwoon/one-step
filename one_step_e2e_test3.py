#!/usr/bin/env python3
"""서비스 모드 브리지 기동 → 정책 질문 → 답변/정책 도구 호출까지 확인.
환경변수에는 민감 키를 남기지 않고,프로세스 내부에서만 주입해 쓴다.
"""
import os
import sys
import json
import time
import subprocess
import urllib.request
import urllib.error

PROJECT_ROOT = "/Users/JWoon/GitHub/solar-end-to-end"
BRIDGE = os.path.join(PROJECT_ROOT, "bridge_server.py")
PROFILE = os.path.join(PROJECT_ROOT, "deploy", "ServiceProfile")

def load_upstage_token():
    auth_path = os.path.join("/Users/JWoon/.hermes/profiles/one-step", "auth.json")
    with open(auth_path) as f:
        auth = json.load(f)
    for entry in auth.get("credential_pool", {}).get("upstage", []):
        if entry.get("label") == "MABC_FINAL" and entry.get("access_token"):
            return entry["access_token"]
    for entry in auth.get("credential_pool", {}).get("upstage", []):
        if entry.get("access_token"):
            return entry["access_token"]
    return ""

sys.path.insert(0, PROJECT_ROOT)
import policy_fetch
keys = policy_fetch.load_api_keys()
on_key = keys.get("ON_YOUTH_API_KEY", "").strip()
gov_key = keys.get("GOV24_API_KEY", "").strip()
up_key = load_upstage_token()

print("키 준비 완료 (길이만):", "UPSTAGE", len(up_key), "ON_YOUTH", len(on_key), "GOV24", len(gov_key))
if not up_key or not on_key or not gov_key:
    print("키 누락")
    sys.exit(1)

HERMES_CMD = os.environ.get("HERMES_CMD") or "hermes"

env = os.environ.copy()
env["ONE_STEP_SERVICE_MODE"] = "1"
env["ONE_STEP_HERMES_HOME"] = PROFILE
env["ONE_STEP_HOST"] = "127.0.0.1"
env["ONE_STEP_PORT"] = "9092"
env["HERMES_CMD"] = HERMES_CMD
env["HERMES_HOME"] = PROFILE
env["UPSTAGE_API_KEY"] = up_key
env["ON_YOUTH_API_KEY"] = on_key
env["GOV24_API_KEY"] = gov_key

proc = subprocess.Popen(
    [sys.executable, BRIDGE],
    env=env,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)

def health_url():
    return "http://127.0.0.1:9092/health"

def ask_url():
    return "http://127.0.0.1:9092/ask"

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
    reply = data.get("reply", "")
    print("응답 앞 400자:")
    print(reply[:400])
    print()
    print("응답에 정책 도구 호출/조회 결과 반영 여부:")
    print("  - Unknown toolsets 경고 포함 여부:", "Unknown toolsets" in reply)
    print("  - 온통청년 출처 언급 여부:", "온통청년" in reply or "youthcenter" in reply.lower())
    print("  - 정부24 출처 언급 여부:", "정부24" in reply or "odcloud" in reply.lower())
    print("  - 정책명 언급 예시(first 200):", reply[400:600] if len(reply) > 400 else "")
    print()
    print("전체 응답 길이:", len(reply))
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
