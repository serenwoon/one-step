#!/usr/bin/env python3
import asyncio
import os
import sys
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

os.chdir(os.path.dirname(os.path.abspath(__file__)))

async def main():
    command = sys.executable
    args = ["policy_mcp_server.py"]
    async with stdio_client(StdioServerParameters(command=command, args=args)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            names = {tool.name: tool.input_schema for tool in result.tools}
            if set(names) != {"gov24_search", "on_youth_search"}:
                raise RuntimeError(f"예상과 다른 도구 목록: {set(names)}")
            s = names["on_youth_search"]
            print("on_youth_search 입력 스키마:")
            print(s)
            expected = {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "정책명 검색어"},
                    "page_size": {"type": "integer", "description": "한 번에 가져올 정책 수(기본 3, 최대 100)"},
                },
                "required": ["keyword"],
            }
            if s != expected:
                raise RuntimeError("on_youth_search 입력 스키마가 예상과 다릅니다")
            print("스키마 점검을 통과했습니다.")

if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=30))
