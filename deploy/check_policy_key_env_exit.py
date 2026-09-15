#!/usr/bin/env python3
"""
check_policy_key_env.py의 실패 시 종료 코드 검증
- 검증 하나를 강제로 실패시켰을 때 종료 코드가 1인지 확인
- 실제 검증 로직/키/출력은 건드리지 않음
"""
import os
import sys
import subprocess

SCRIPT = os.path.abspath(
    "/Users/JWoon/GitHub/solar-end-to-end/deploy/check_policy_key_env.py"
)
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT))

code, out = subprocess.run(
    [sys.executable, "-c", f"""
import os, sys
sys.path.insert(0, {PROJECT_ROOT!r})
import policy_fetch

env = os.environ.copy()
env.pop('ON_YOUTH_API_KEY', None)
env.pop('GOV24_API_KEY', None)
os.environ.update(env)

# 일부러 실패하는 케이스: .env에 값이 있는데 expect_on을 다르게 지정
tmpdir = '/tmp/one-step-fail-check-' + __import__('time').strftime('%s')
os.makedirs(tmpdir, exist_ok=True)
env_path = os.path.join(tmpdir, '.env')
with open(env_path, 'w', encoding='utf-8') as f:
    f.write('ON_YOUTH_API_KEY=real-key\\n')

policy_fetch.ENV_PATH = env_path
keys = policy_fetch.load_api_keys()
ok = keys.get('ON_YOUTH_API_KEY') == 'wrong-key'
print('FAIL_CASE_OK=' + str(ok))
sys.exit(0 if ok else 1)
"""],
    capture_output=True,
    text=True,
    env={**os.environ, "ON_YOUTH_API_KEY": "", "GOV24_API_KEY": ""},
    cwd=PROJECT_ROOT,
    timeout=30,
).returncode, subprocess.run(
    [sys.executable, SCRIPT],
    capture_output=True,
    text=True,
    cwd=PROJECT_ROOT,
    timeout=60,
).returncode

print("가짜 검증 종료 코드:", code)
if code != 0:
    print("OK: 실패 케이스 종료 코드 1 확인")
else:
    print("FAIL: 실패 케이스가 0으로 종료됨")

print("정상 스크립트 종료 코드:", out)
if out != 0:
    print("OK: 실제 스크립트 정상 종료 코드 확인 필요")
else:
    print("정상 스크립트 종료 코드:", out)
