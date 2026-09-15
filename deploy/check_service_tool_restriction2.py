#!/usr/bin/env python3
"""
서비스 프로필 + 실제 MCP 초기화 후 도구 제한 검증 (2단계)
- MCP 초기화 전/후 validate_toolset("mcp-one-step-policy") 구분
- MCP 초기화 후 도구셋 별칭과 정책 도구 등록 상태 확인
- get_tool_definitions 결과 비교 (skip_assembly True/False)
- tool_search/tool_call의 current_defs 범위가 정책 도구 2개로 한정되는지 코드 근거로 확인
- 모델 호출, 정책 API 호출 없음
"""
import os
import sys

HERMES_AGENT = "/Users/JWoon/.hermes/hermes-agent"
PROJECT_ROOT = "/Users/JWoon/GitHub/solar-end-to-end"
SERVICE_PROFILE = os.path.join(PROJECT_ROOT, "deploy", "ServiceProfile")

os.environ["HERMES_HOME"] = SERVICE_PROFILE
os.environ["ONE_STEP_SERVICE_MODE"] = "1"
os.environ["ONE_STEP_HERMES_HOME"] = SERVICE_PROFILE

if HERMES_AGENT not in sys.path:
    sys.path.insert(0, HERMES_AGENT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from toolsets import validate_toolset, resolve_toolset
from tools.mcp_tool_discovery import discover_mcp_tools
from tools.mcp_tool_lifecycle import shutdown_mcp_servers
from tools.tool_search import BRIDGE_TOOL_NAMES, scoped_deferrable_names
from model_tools import get_tool_definitions
from tools.registry import registry

ts_name = "mcp-one-step-policy"
EXPECTED_POLICY_TOOLS = {
    "mcp__one_step_policy__gov24_search",
    "mcp__one_step_policy__on_youth_search",
}


def check_scope(current_names, scoped, final_names):
    """비어 있거나 정책 외 도구가 섞인 허용 목록은 통과시키지 않는다."""
    return {
        "서비스 원본 목록": set(current_names) == EXPECTED_POLICY_TOOLS,
        "중간 도구 실행 범위": set(scoped) == EXPECTED_POLICY_TOOLS,
        # 정책 도구는 중간 도구 뒤에 있을 수 있으므로 최종 표시 이름과 구분한다.
        "최종 표시 목록": (
            bool(final_names)
            and set(final_names) <= EXPECTED_POLICY_TOOLS | set(BRIDGE_TOOL_NAMES)
            and (EXPECTED_POLICY_TOOLS <= set(final_names)
                 or set(BRIDGE_TOOL_NAMES) <= set(final_names))
        ),
    }


def main():
    results = {}
    cleanup_ok = False
    try:
        print("=== MCP 초기화 전 ===")
        print(f"  별칭 유효 여부: {validate_toolset(ts_name)}")
        discovered = discover_mcp_tools()
        print(f"  발견한 도구: {sorted(discovered)}")

        print("=== MCP 초기화 후 ===")
        # 별칭 진단과 실제 선택 결과를 구분한다. 별칭 상태만으로 전체를 판정하지 않는다.
        print(f"  별칭 유효 여부: {validate_toolset(ts_name)}")
        print(f"  별칭 해석 목록: {sorted(resolve_toolset(ts_name))}")
        registered = {
            name for name in registry.get_all_tool_names()
            if name.startswith("mcp__one_step_policy__")
        }
        results["정책 도구 등록"] = registered == EXPECTED_POLICY_TOOLS

        current_defs = get_tool_definitions(
            enabled_toolsets=[ts_name], disabled_toolsets=None,
            quiet_mode=True, skip_tool_search_assembly=True,
        )
        final_defs = get_tool_definitions(
            enabled_toolsets=[ts_name], disabled_toolsets=None,
            quiet_mode=True, skip_tool_search_assembly=False,
        )
        current_names = {d["function"]["name"] for d in current_defs}
        final_names = {d["function"]["name"] for d in final_defs}
        scoped = scoped_deferrable_names(current_defs)
        print(f"  서비스 원본 목록: {sorted(current_names)}")
        print(f"  중간 도구 실행 범위: {sorted(scoped)}")
        print(f"  최종 표시 목록: {sorted(final_names)}")
        results.update(check_scope(current_names, scoped, final_names))
    except Exception as e:
        print(f"FAIL: 검사 실행 ({type(e).__name__})")
        results["검사 실행"] = False
    finally:
        # 초기화나 목록 조회 중 실패해도 MCP 프로세스를 정리한다.
        try:
            shutdown_mcp_servers()
            cleanup_ok = True
        except Exception as e:
            print(f"FAIL: MCP 정리 ({type(e).__name__})")

    results["MCP 정리"] = cleanup_ok
    print("=== 결과 ===")
    for name, ok in results.items():
        print(f"  {name}: {'OK' if ok else 'FAIL'}")
    all_ok = all(results.values())
    print(f"  전체: {'PASS' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
