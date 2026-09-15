#!/usr/bin/env python3
"""
다시, 한 걸음(one-step) — 서비스 전용 도구 제한 검사 (모델 호출 없음)

프로젝트 루트에서 실행 (Hermes 환경은 .venv가 아니라 venv):
    ~/.hermes/hermes-agent/venv/bin/python deploy/check_service_tools.py

- HERMES_HOME을 서비스 전용 프로필(deploy/ServiceProfile)로 지정
- MCP 서버(one-step-policy)를 연결
- get_tool_definitions()로 모델에 전달될 도구 목록을 확인
- 정책 조회 도구(gov24_search, on_youth_search)만 남는지 본다

주의:
- 이 스크립트는 실제 hermes chat을 실행하지 않으며, 모델 API도 호출하지 않는다.
- MCP 연결이 성공해야 도구 목록을 볼 수 있다. MCP 서버(process)이 안 뜨면 결과가 비어 있을 수 있다.
- 이 검사만으로는 "실제 서비스 배포에 충분하다"를 보장하지 않는다. 특히 -t 인자 처리,
  브리지(tool_search/tool_describe/tool_call) 포함 여부, 실제 대화 맥락에서의 제한은
  따로 확인해야 한다.
"""

import os
import sys
import time
import logging

# 서비스 전용 프로필 경로 사용 (개발용 one-step과 별개)
os.environ["HERMES_HOME"] = (
    "/Users/JWoon/GitHub/solar-end-to-end/deploy/ServiceProfile"
)

sys.path.insert(0, "/Users/JWoon/.hermes/hermes-agent")

from hermes_cli.mcp_startup import start_background_mcp_discovery, _any_mcp_connected

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

print("=== 서비스 전용 프로필로 MCP 연결 시작 ===")
start_background_mcp_discovery(
    logger=logging.getLogger("check"),
    thread_name="check-mcp",
)

# MCP 연결이 완료될 때까지 짧게 대기 (정책 API 키 유효성 검사가 아니라
# MCP 서버 프로세스가 떠서 도구 등록을 마치는지만 본다)
for _ in range(40):
    if _any_mcp_connected():
        break
    time.sleep(0.5)

from model_tools import get_tool_definitions

print("=== MCP 연결 완료 (또는 타임아웃) ===")
print()

# ---------------------------------------------------------------------------
# 1) 기본 도구 조립 (skip_tool_search_assembly=False)
#    실제 서비스에서 주로 쓰는 경로와 같다. 브리지(tool_search 등)가 포함될 수 있다.
# ---------------------------------------------------------------------------
print("=== 1) 기본 도구 조립 (skip_tool_search_assembly=False) ===")
for toolsets in (["one-step-policy"], ["mcp-one-step-policy"]):
    defs = get_tool_definitions(enabled_toolsets=toolsets, quiet_mode=True)
    names = [d["function"]["name"] for d in defs]
    print(f"  enabled_toolsets={toolsets}")
    print(f"    도구 {len(names)}개: {names}")
print()

# ---------------------------------------------------------------------------
# 2) 브리지 제외 (skip_tool_search_assembly=True)
#    브리지(tool_search/tool_describe/tool_call)를 빼고 MCP 도구만 남는지 본다.
#    이 결과만으로 실제 서비스 검증이 끝났다고 보지 않는다. 실제 서비스 호출 경로와
#    다를 수 있고, -t 인자 처리 결과의 대체도 아니다.
# ---------------------------------------------------------------------------
print("=== 2) 브리지 제외 (skip_tool_search_assembly=True) ===")
for toolsets in (["one-step-policy"], ["mcp-one-step-policy"]):
    defs = get_tool_definitions(
        enabled_toolsets=toolsets,
        quiet_mode=True,
        skip_tool_search_assembly=True,
    )
    names = [d["function"]["name"] for d in defs]
    print(f"  enabled_toolsets={toolsets}")
    print(f"    도구 {len(names)}개: {names}")
print()

# ---------------------------------------------------------------------------
# 참고: 도구셋 유효성, 도구명 표기 방식 확인
# ---------------------------------------------------------------------------
print("=== 참고: validate_toolset / get_toolset ===")
from toolsets import get_toolset, validate_toolset

for name in (
    "one-step-policy",
    "mcp-one-step-policy",
    "mcp__one_step_policy__on_youth_search",
):
    print(f"  validate_toolset({name!r}) = {validate_toolset(name)}")
    ts_def = get_toolset(name, include_registry=True)
    print(f"    get_toolset = {ts_def}")
print()

print("=== 미확인 사항(주석) ===")
print("  - hermes chat -t <도구셋> 실제 실행 시 정책 2개만 남는지 미확인")
print("  - MCP 도구명(mcp__one_step_policy__*)을 -t에 직접 넣었을 때 인식 여부 미확인")
print("  - 실제 대화 맥락에서 user 입력이 도구 제한을 우회할 수 있는지 미확인")
print("  - Vercel rewrite 프록시(120초)와 현재 timeout=180의 충돌 해소 방안 미결정")
