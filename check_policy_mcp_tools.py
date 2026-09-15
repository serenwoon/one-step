#!/usr/bin/env python3
import asyncio
import os
import sys
from mcp.client.stdio import stdio_client, StdioServerParameters

os.chdir(os.path.dirname(os.path.abspath(__file__)))

async def main():
    command = sys.executable
    args = ["policy_mcp_server.py"]
    async with stdio_client(StdioServerParameters(command=command, args=args)) as (read, write):
        from mcp.client.session import ClientSession
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            names = [tool.name for tool in result.tools]
            if set(names) != {"gov24_search", "on_youth_search"}:
                raise RuntimeError(f"예상과 다른 도구 목록: {names}")
            print("도구 목록:", names)

if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=30))
