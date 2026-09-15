#!/usr/bin/env python3
"""
다시, 한 걸음(one-step) — 정책 MCP 서버
정부24 공공서비스 혜택 정보와 온통청년 청년정책 조회를 MCP 도구로 제공한다.
키는 서버 안에서 .env로 읽고, 도구 결과에는 정책 데이터만 반환한다.
"""
import asyncio
import json
import os
import sys
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, ListToolsResult, CallToolResult, TextContent, CallToolRequestParams
from mcp.server.context import ServerRequestContext

# 같은 폴더의 policy_fetch를 사용한다.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import policy_fetch

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

def _env():
    return policy_fetch.load_env(ENV_PATH)

async def on_list_tools(context: ServerRequestContext, params):
    tools = [
        Tool(
            name="gov24_search",
            description="정부24 공공서비스 혜택 정보에서 한 건을 조회한다.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="on_youth_search",
            description=(
                "온통청년 청년정책에서 정책명으로 검색해 여러 페이지를 조회하고, "
                "region_codes 기준으로 지역 분류(matched/unmatched/region_unknown)를 함께 반환한다. "
                "region_codes를 지정하면 해당 지역(법정시군구코드 5자리)만 필터링한다. "
                "신청 자격 판정은 하지 않는다."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "정책명 검색어"},
                    "page_size": {"type": "integer", "description": "페이지당 건수(기본 10, 최대 100)"},
                    "max_pages": {"type": "integer", "description": "최대 조회할 페이지 수(기본 3, 최대 10)"},
                    "region_codes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "법정시군구코드 5자리 목록 (예: [\"11440\"] - 서울 마포구). 미지정 시 전국 대상.",
                    },
                },
                "required": ["keyword"],
            },
        ),
    ]
    return ListToolsResult(tools=tools)

async def on_call_tool(context: ServerRequestContext, params: CallToolRequestParams):
    name = params.name
    if name == "gov24_search":
        keys = policy_fetch.load_api_keys()
        key = keys.get("GOV24_API_KEY", "").strip()
        if not key:
            return CallToolResult(content=[TextContent(type="text", text="GOV24_API_KEY가 비어 있습니다")], is_error=True)
        code, body = policy_fetch.gov24_fetch(key)
        result = policy_fetch.gov24_result(code, body)
        text = str(result)
        return CallToolResult(content=[TextContent(type="text", text=text)], is_error=result.get("status") == "error")
    if name == "on_youth_search":
        keys = policy_fetch.load_api_keys()
        key = keys.get("ON_YOUTH_API_KEY", "").strip()
        if not key:
            return CallToolResult(content=[TextContent(type="text", text="ON_YOUTH_API_KEY가 비어 있습니다")], is_error=True)
        try:
            arguments = params.arguments or {}
            keyword = arguments.get("keyword")
            if not isinstance(keyword, str) or not keyword.strip():
                raise TypeError("keyword가 비어 있습니다")
            page_size = arguments.get("page_size")
            if page_size is None:
                page_size = 10
            elif type(page_size) is not int or not 1 <= page_size <= 100:
                raise TypeError("page_size는 1부터 100까지의 정수여야 합니다")
            max_pages = arguments.get("max_pages")
            if max_pages is None:
                max_pages = 3
            elif type(max_pages) is not int or not 1 <= max_pages <= 10:
                raise TypeError("max_pages는 1부터 10까지의 정수여야 합니다")
            region_codes = arguments.get("region_codes")
            if region_codes is not None:
                if not isinstance(region_codes, list):
                    raise TypeError("region_codes는 문자열 배열이어야 합니다")
                for rc in region_codes:
                    if not isinstance(rc, str) or not rc.strip() or len(rc.strip()) != 5:
                        raise TypeError("region_codes의 각 값은 5자리 법정시군구코드 문자열이어야 합니다")
                region_codes = [rc.strip() for rc in region_codes]
            return_classified = arguments.get("return_classified", True)
            if return_classified is False:
                result = policy_fetch.on_youth_search_multi(
                    key, keyword.strip(),
                    region_codes=region_codes,
                    max_pages=max_pages,
                    page_size=page_size,
                )
            else:
                result = policy_fetch.on_youth_search_classified(
                    key, keyword.strip(),
                    region_codes=region_codes,
                    max_pages=max_pages,
                    page_size=page_size,
                )
        except TypeError as e:
            return CallToolResult(content=[TextContent(type="text", text=str(e))], is_error=True)
        except Exception as e:
            return CallToolResult(content=[TextContent(type="text", text="정책 조회 중 오류가 발생했습니다")], is_error=True)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        return CallToolResult(content=[TextContent(type="text", text=text)], is_error=result.get("status") == "error")
    return CallToolResult(content=[TextContent(type="text", text=f"알 수 없는 도구: {name}")], is_error=True)

server = Server(
    "one-step-policy",
    on_list_tools=on_list_tools,
    on_call_tool=on_call_tool,
)

async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
