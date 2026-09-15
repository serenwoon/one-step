#!/usr/bin/env python3
import asyncio
import json
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
            result = await session.call_tool("on_youth_search", {"keyword": "월세", "page_size": 3})

            print("isError:", result.is_error)
            print("도구 결과 콘텐츠 수:", len(result.content))
            if result.content and result.content[0].type == "text":
                text = result.content[0].text
                print("반환 JSON:")
                print(text)
                try:
                    data = json.loads(text)
                except Exception as e:
                    print("JSON 파싱 실패:", e)
                    return

                print()
                print("요약:")
                print("  status:", data.get("status"))
                print("  httpStatus:", data.get("httpStatus"))
                print("  apiResultCode:", data.get("apiResultCode"))
                print("  totalCount:", data.get("totalCount"))
                print("  fetchedCount:", data.get("fetchedCount"))
                print("  policyName(첫 건):", (data.get("results") or [{}])[0].get("policyName"))
                print("  results 수:", len(data.get("results") or []))
            else:
                print("텍스트 결과가 아닙니다:")
                print(result.content)

if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=60))
