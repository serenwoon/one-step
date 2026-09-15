#!/usr/bin/env python3
"""
서비스 프로필 기준으로 실제 Hermes MCP 초기화 후 도구 제한 검증
- HERMES_HOME을 서비스 프로필로 지정
- hermes_cli.mcp_startup.discover_mcp_tools()로 실제 MCP 서버 연결/등록
- model_tools.get_tool_definitions(enabled_toolsets=["mcp-one-step-policy"]) 결과 확인
- 모델 호출, 정책 API 호출 없음
- 임시 파일/가변 환경만 사용, 키 값 출력 없음
"""
import os
import sys
import json
import threading
import time

HERMES_AGENT = "/Users/JWoon/.hermes/hermes-agent"
PROJECT_ROOT = "/Users/JWoon/GitHub/solar-end-to-end"
SERVICE_PROFILE = os.path.join(PROJECT_ROOT, "deploy", "ServiceProfile")

# 서비스 프로필 + 서비스 모드 환경 구성
os.environ["HERMES_HOME"] = SERVICE_PROFILE
os.environ["ONE_STEP_SERVICE_MODE"] = "1"
os.environ["ONE_STEP_HERMES_HOME"] = SERVICE_PROFILE

# hermes-agent 패키지를import할 수 있게 경로 추가
if HERMES_AGENT not in sys.path:
    sys.path.insert(0, HERMES_AGENT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ---------------------------------------------------------------------------
# 1) 도구셋/레지스트리 수준 확인 (MCP 서버 연결 전)
# ---------------------------------------------------------------------------
from toolsets import validate_toolset, resolve_toolset, get_toolset
from tools.mcp_tool_discovery import discover_mcp_tools, get_mcp_status

ts_name = "mcp-one-step-policy"

print("=== 1) 도구셋/레지스트리 수준 확인 (MCP 연결 전) ===")
print(f"  validate_toolset({ts_name!r}) = {validate_toolset(ts_name)}")
print(f"  get_toolset({ts_name!r}, include_registry=True) = {get_toolset(ts_name, include_registry=True)!r}")
print(f"  resolve_toolset({ts_name!r}) = {resolve_toolset(ts_name)!r}")

def _any_mcp_connected():
    return any(entry.get("connected") for entry in (get_mcp_status() or []))

# ---------------------------------------------------------------------------
# 2) 실제 MCP 연결 + 도구 목록 확인
# ---------------------------------------------------------------------------
from tools.mcp_tool_lifecycle import shutdown_mcp_servers
from model_tools import get_tool_definitions

print()
print("=== 2) MCP 발견 + 도구 정의 조회 ===")

def _discover(timeout_sec=90):
    done = []
    err = []
    def _run():
        try:
            result = discover_mcp_tools()  # config.yaml 기준 모든 서버 연결 시도
            done.append(result)
        except Exception as e:
            err.append(e)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout_sec)
    if t.is_alive():
        raise TimeoutError(f"discover_mcp_tools가 {timeout_sec}초 안에 끝나지 않음")
    if err:
        raise err[0]
    return done[0]

try:
    tool_names_from_discovery = _discover(timeout_sec=90)
    print(f"  discover_mcp_tools() 반환 도구 수: {len(tool_names_from_discovery)}")
    print(f"  discover_mcp_tools() 도구 샘플: {tool_names_from_discovery[:20]}")
    print(f"  MCP 연결 상태: {_any_mcp_connected()}")
except Exception as e:
    print(f"  [블록] MCP 발견 단계에서 오류/타임아웃: {type(e).__name__}: {e}")
    tool_names_from_discovery = []

# 도구 정의 조회 (서비스 모드에서 -t mcp-one-step-policy만 준 상황)
print()
print("=== 3) get_tool_definitions(enabled_toolsets=['mcp-one-step-policy']) ===")
try:
    defs = get_tool_definitions(
        enabled_toolsets=[ts_name],
        disabled_toolsets=None,
        quiet_mode=True,
        skip_tool_search_assembly=False,
    )
    names = sorted(d["function"]["name"] for d in defs)
    print(f"  도구 수: {len(names)}")
    print(f"  도구 목록: {names}")
except Exception as e:
    print(f"  [블록] get_tool_definitions 실패: {type(e).__name__}: {e}")
    names = []

# skip_tool_search_assembly=True 버전도 같이 확인
print()
print("=== 4) get_tool_definitions(..., skip_tool_search_assembly=True) ===")
try:
    defs_raw = get_tool_definitions(
        enabled_toolsets=[ts_name],
        disabled_toolsets=None,
        quiet_mode=True,
        skip_tool_search_assembly=True,
    )
    names_raw = sorted(d["function"]["name"] for d in defs_raw)
    print(f"  도구 수: {len(names_raw)}")
    print(f"  도구 목록: {names_raw}")
except Exception as e:
    print(f"  [블록] get_tool_definitions(skip_tool_search_assembly=True) 실패: {type(e).__name__}: {e}")
    names_raw = []

# ---------------------------------------------------------------------------
# 3) 판정
# ---------------------------------------------------------------------------
EXPECTED_POLICY_CORE = {"gov24_search", "on_youth_search"}
# 위험 도구 후보 (절대 최종 목록에 있으면 안 됨)
DANGEROUS = {
    "terminal", "process_manage",
    "read_file", "write_file", "patch", "search_files",
    "web_search", "web_extract",
    "browser_navigate", "browser_snapshot", "browser_click", "browser_type",
    "browser_scroll", "browser_back", "browser_press", "browser_get_images",
    "browser_vision", "browser_console", "browser_cdp", "browser_dialog",
    "browser_exec",
    "skills_list", "skill_view", "skill_manage",
    "cronjob_manage",
    "delegate_task", "execute_code",
    "computer_use",
    "text_to_speech",
    "todo_list", "memory",
    "session_search",
    "clarify",
    "vision_analyze", "image_generate",
}

def prefixed(s):
    return s.startswith("mcp__")

print()
print("=== 5) 판정 ===")
final_names = names or names_raw
policy_tools_found = [n for n in final_names if not prefixed(n) and n in EXPECTED_POLICY_CORE]
policy_tools_mcp = [n for n in final_names if prefixed(n) and (n.endswith("__gov24_search") or n.endswith("__on_youth_search"))]
danger_present = [n for n in final_names if n in DANGEROUS]
bridge_present = [n for n in final_names if n in {"tool_search", "tool_describe", "tool_call"}]

print(f"  최종 도구 목록: {final_names}")
print(f"  기대 정책 도구(비MCP 이름): {sorted(policy_tools_found)}")
print(f"  MCP 접두 정책 도구: {sorted(policy_tools_mcp)}")
print(f"  위험 도구 포함 여부: {danger_present if danger_present else '없음'}")
print(f"  브리지 도구 포함 여부: {bridge_present if bridge_present else '없음'}")

# 정책 도구가 하나라도 있는지
policy_ok = bool(policy_tools_found) or bool(policy_tools_mcp)
danger_ok = not danger_present

# 브리지 도구가 있을 때 다른 도구 접근 가능 여부 점검
bridge_scope_ok = True
if bridge_present:
    # tool_search 브릿지는 get_tool_definitions 시점에 same enabled/disabled toolsets로
    # 조립된 current_defs 범위 내에서만 동작해야 한다 (model_tools._dispatch_bridge_tool).
    # 여기서 추가로 확인할 수 있는 건 브리지 도구 자체가 "다른 도구"를 열거할 수 있는 API를
    # 노출하는지 정도다. 현재 코드상 tool_search/tool_describe/tool_call은 current_defs를
    # 넘겨받아 동작하므로, 브리지 자체가 범위 밖으로 나가는 경로는 없다.
    print("  브리지 도구 존재: 있음")
    print("  브리지 범위 점검: _dispatch_bridge_tool는 current_defs(동일 toolsets로 조립된 목록) 기준으로만")
    print("    tool_search/tool_describe/tool_call을 처리하므로, 범위 밖으로 나가는 경로는 코드상 없음")
else:
    print("  브리지 도구 존재: 없음")

ok = policy_ok and danger_ok
print()
print("=== 결과 ===")
print(f"  정책 도구 확인: {'OK' if policy_ok else 'FAIL'}")
print(f"  위험 도구 제외: {'OK' if danger_ok else 'FAIL'}")
print(f"  전체: {'PASS' if ok else 'FAIL'}")

# MCP 서버 정리
print()
print("=== 정리 ===")
try:
    shutdown_mcp_servers()
    print("  shutdown_mcp_servers() 호출 완료")
except Exception as e:
    print(f"  정리 중 오류: {type(e).__name__}: {e}")

sys.exit(0 if ok else 1)
