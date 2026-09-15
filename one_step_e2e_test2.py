#!/usr/bin/env python3
"""서비스 모드 브리지 기동 → 정책 질문 → 답변/정책 조회까지 한 번에 확인.
모델 키는 hermes 프로필 auth.json에서 가져온다.
"""
import os
import sys
import json
import time
import urllib.request
import urllib.error
import subprocess

PROJECT_ROOT = "/Users/JWoon/GitHub/solar-end-to-end"
BRIDGE = os.path.join(PROJECT_ROOT, "bridge_server.py")
PROFILE = os.path.join(PROJECT_ROOT, "deploy", "ServiceProfile")

# 모델 키: hermes 프로필 auth.json에서 가져온다
AUTH_PATH = os.path.join("/Users/JWoon/.hermes/profiles/one-step", "auth.json")
with open(AUTH_PATH) as f:
    auth = json.load(f)
upstage_tokens = auth.get("credential_pool", {}).get("upstage", [])
token = None
for entry in upstage_tokens:
    if entry.get("label") == "MABC_FINAL" and entry.get("access_token"):
        token = entry["access_token"]
        break
if not token:
    for entry in upstage_tokens:
        if entry.get("access_token"):
            token = entry["access_token"]
            break
if not token:
    print("모델 키를 auth.json에서 찾지 못함")
    sys.exit(1)
print("모델 키 준비 완료 (길이:", len(token), ")")

# 정책 키: 프로젝트 .env에서 환경변수 우선으로 읽는다
sys.path.insert(0, PROJECT_ROOT)
import policy_fetch
keys = policy_fetch.load_api_keys()
on_key = keys.get("ON_YOUTH_API_KEY", "").strip()
gov_key = keys.get("GOV24_API_KEY", "").strip()
if not on_key or not gov_key:
    print("정책 키 누락")
    sys.exit(1)
print("정책 키 준비 완료 (on:", len(on_key), "gov:", len(gov_key), ")")

HERMES_CMD = os.environ.get("HERMES_CMD") or "hermes"

env = os.environ.copy()
env["ONE_STEP_SERVICE_MODE"] = "1"
env["ONE_STEP_HERMES_HOME"] = PROFILE
env["ONE_STEP_HOST"] = "127.0.0.1"
env["ONE_STEP_PORT"] = "9097"
env["HERMES_CMD"] = HERMES_CMD
env["HERMES_HOME"] = PROFILE
env["UPSTAGE_API_KEY"] = token
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
    return "http://127.0.0.1:9097/health"

def ask_url():
    return "http://127.0.0.1:9097/ask"

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
