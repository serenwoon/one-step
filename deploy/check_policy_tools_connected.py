#!/usr/bin/env python3
"""
다시, 한 걸음(one-step) — MCP 연결 후 정책 도구 2개 등록 여부 확인 (헤르메스 에이전트 파이썬 전용)

이 모듈은 헤르메스 에이전트 가상env 파이썬에서만 import/실행한다.
일반 python3로는 tools.mcp_tool_discovery 등을 가져올 수 없다.

동작:
- HERMES_HOME을 서비스 프로필로 지정
- discover_mcp_tools()로 정책 MCP 서버 연결
- get_mcp_status()로 연결 완료 대기
- EXPECTED_POLICY_TOOLS (mcp__one_step_policy__gov24_search,
  mcp__one_step_policy__on_youth_search) 등록 여부를 확인
- 결과를 JSON 한 줄로 출력
- 마지막에 shutdown_mcp_servers()로 정리

모델 호출, 정책 API 호출은 하지 않는다.
"""

import os
import sys
import json

HERMES_AGENT = os.path.expanduser("~/.hermes/hermes-agent")
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))

EXPECTED_POLICY_TOOLS = {
    "mcp__one_step_policy__gov24_search",
    "mcp__one_step_policy__on_youth_search",
}


def _ensure_paths():
    if HERMES_AGENT not in sys.path:
        sys.path.insert(0, HERMES_AGENT)
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)


def main():
    _ensure_paths()

    profile_dir = os.environ.get("ONE_STEP_HERMES_HOME")
    if not profile_dir:
        print(json.dumps({"error": "ONE_STEP_HERMES_HOME 없음"}))
        return 1

    os.environ["HERMES_HOME"] = profile_dir

    from tools.mcp_tool_discovery import discover_mcp_tools, get_mcp_status
    from tools.mcp_tool_lifecycle import shutdown_mcp_servers

    discovered = []
    connected = False
    discover_error = None
    try:
        discovered = discover_mcp_tools(allowed_mcp_names=["one-step-policy"]) or []
        connected = any(
            entry.get("name") == "one-step-policy" and entry.get("connected")
            for entry in (get_mcp_status() or [])
        )
    except Exception as e:
        discover_error = f"{type(e).__name__}: {e}"
    finally:
        # 등록에 실패해도 시작한 MCP 서버를 정리한다.
        try:
            shutdown_mcp_servers()
        except Exception as e:
            discover_error = f"MCP 정리 실패: {type(e).__name__}: {e}"

    policy_tools = set(discovered) & EXPECTED_POLICY_TOOLS

    out = {
        "profile_dir": profile_dir,
        "discover_error": discover_error,
        "discovered": sorted(discovered),
        "connected": connected,
        "policy_tools": sorted(policy_tools),
        "policy_ok": connected and not discover_error and set(discovered) == EXPECTED_POLICY_TOOLS,
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out["policy_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
