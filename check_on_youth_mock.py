#!/usr/bin/env python3
import asyncio
import json
import os
import sys
from unittest.mock import patch

os.chdir(os.path.dirname(os.path.abspath(__file__)))

MOCK_RESULT = {
    "status": "ok",
    "httpStatus": 200,
    "apiResultCode": "200",
    "source": "온통청년",
    "sourceUrl": "https://www.youthcenter.go.kr/go/ythip/getPlcy",
    "keyword": "월세",
    "searchParameter": "plcyNm",
    "regionFilterApplied": False,
    "pageNum": 1,
    "pageSize": 3,
    "fetchedCount": 3,
    "totalCount": 57,
    "allMatchingResultsFetched": False,
    "results": [
        {
            "policyName": "월세 지원 정책 예시 1",
            "policyNo": "P001",
            "regionCodes": None,
            "regionName": None,
            "supportContent": "월세 일부를 지원합니다.",
            "applyUrl": "https://example.com/apply1",
            "orgName": "예시 기관",
            "source": "온통청년",
            "sourceUrl": "https://www.youthcenter.go.kr/go/ythip/getPlcy",
        },
        {
            "policyName": "월세 지원 정책 예시 2",
            "policyNo": "P002",
            "regionCodes": None,
            "regionName": None,
            "supportContent": "청년 월세 부담을 덜어줍니다.",
            "applyUrl": "https://example.com/apply2",
            "orgName": "예시 기관",
            "source": "온통청년",
            "sourceUrl": "https://www.youthcenter.go.kr/go/ythip/getPlcy",
        },
    ],
    "note": "정책명으로 검색한 한 페이지입니다. 전체 정책 조회나 신청 자격 판정이 아닙니다.",
}

async def main():
    # 실제 HTTP 요청을 막고, policy_fetch.on_youth_search가 항상 MOCK_RESULT를 반환하게 만든다.
    with patch("policy_fetch.on_youth_search", return_value=MOCK_RESULT):
        from mcp.client.stdio import stdio_client, StdioServerParameters
        from mcp.client.session import ClientSession

        command = sys.executable
        args = ["policy_mcp_server.py"]
        async with stdio_client(StdioServerParameters(command=command, args=args)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # 도구 호출: keyword="월세", page_size=2
                result = await session.call_tool("on_youth_search", {"keyword": "월세", "page_size": 2})
                assert result.is_error is False, f"오류로 끝남: {result}"
                assert len(result.content) == 1
                content = result.content[0]
                assert content.type == "text"
                text = content.text
                parsed = json.loads(text)
                assert parsed["status"] == "ok"
                assert parsed["keyword"] == "월세"
                assert parsed["pageSize"] == 2
                assert len(parsed["results"]) == 2
                print("호출 결과 JSON:")
                print(text)
                print()
                print("점검 통과: 키워드/페이지 크기와 mock 결과가 그대로 JSON으로 반환됨")

if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=30))
