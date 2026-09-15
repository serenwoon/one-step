#!/usr/bin/env python3
import asyncio
import json
import os
import sys
from unittest.mock import MagicMock, patch

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 정책 서버 모듈의 on_call_tool을 직접 호출해본다.
# policy_fetch.on_youth_search는 같은 프로세스 안에서 mock으로 고정한다.
import policy_mcp_server
from mcp.types import CallToolRequestParams

SUCCESS_DICT = {
    "status": "ok",
    "httpStatus": 200,
    "apiResultCode": 200,
    "source": "온통청년",
    "sourceUrl": "https://www.youthcenter.go.kr/go/ythip/getPlcy",
    "keyword": "월세",
    "searchParameter": "plcyNm",
    "regionFilterApplied": False,
    "pageNum": 1,
    "pageSize": 2,
    "fetchedCount": 2,
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

ERROR_DICT = {
    "status": "error",
    "httpStatus": 200,
    "apiResultCode": "999",
    "source": "온통청년",
    "sourceUrl": "https://www.youthcenter.go.kr/go/ythip/getPlcy",
    "keyword": "없는정책",
    "searchParameter": "plcyNm",
    "regionFilterApplied": False,
    "pageNum": 1,
    "pageSize": 3,
    "fetchedCount": 0,
    "totalCount": 0,
    "allMatchingResultsFetched": True,
    "results": [],
    "note": "정책명으로 검색한 한 페이지입니다. 전체 정책 조회나 신청 자격 판정이 아닙니다.",
    "reason": "정책 API 결과 코드가 성공이 아니거나 누락됐습니다",
}

async def run():
    ctx = MagicMock()

    print("=" * 70)
    print("케이스 1: policy_fetch.on_youth_search가 성공 dict를 반환할 때")
    print("=" * 70)
    with patch("policy_mcp_server.policy_fetch.on_youth_search", return_value=SUCCESS_DICT):
        params = CallToolRequestParams(
            name="on_youth_search",
            arguments={"keyword": "월세", "page_size": 2},
        )
        result = await policy_mcp_server.on_call_tool(ctx, params)

        assert result.is_error is False, f"예상과 달리 is_error=True: {result.is_error}"
        assert len(result.content) == 1
        content = result.content[0]
        assert content.type == "text", f"예상과 다른 content type: {content.type}"
        text = content.text
        parsed = json.loads(text)

        print("반환 텍스트(JSON):")
        print(text)
        print()
        print("파싱 결과 요약:")
        print("  status:", parsed.get("status"))
        print("  keyword:", parsed.get("keyword"))
        print("  pageSize:", parsed.get("pageSize"))
        print("  fetchedCount:", parsed.get("fetchedCount"))
        print("  results 수:", len(parsed.get("results", [])))
        print("  is_error:", result.is_error)
        print()
        assert parsed["status"] == "ok"
        assert parsed["keyword"] == "월세"
        assert parsed["pageSize"] == 2
        assert len(parsed["results"]) == 2
        print("점검 통과: 성공 케이스는 JSON 텍스트 + is_error=False")

    print()
    print("=" * 70)
    print("케이스 2: policy_fetch.on_youth_search가 오류 dict를 반환할 때")
    print("=" * 70)
    with patch("policy_mcp_server.policy_fetch.on_youth_search", return_value=ERROR_DICT):
        params = CallToolRequestParams(
            name="on_youth_search",
            arguments={"keyword": "없는정책"},
        )
        result = await policy_mcp_server.on_call_tool(ctx, params)

        assert result.is_error is True, f"예상과 달리 is_error=False: {result.is_error}"
        assert len(result.content) == 1
        content = result.content[0]
        assert content.type == "text"
        text = content.text
        parsed = json.loads(text)

        print("반환 텍스트(JSON):")
        print(text)
        print()
        print("파싱 결과 요약:")
        print("  status:", parsed.get("status"))
        print("  keyword:", parsed.get("keyword"))
        print("  fetchedCount:", parsed.get("fetchedCount"))
        print("  results 수:", len(parsed.get("results", [])))
        print("  reason:", parsed.get("reason"))
        print("  is_error:", result.is_error)
        print()
        assert parsed["status"] == "error"
        assert parsed["keyword"] == "없는정책"
        assert len(parsed["results"]) == 0
        print("점검 통과: 오류 케이스에서도 JSON 텍스트 + is_error=True")

    print()
    print("=" * 70)
    print("케이스 3: policy_fetch.on_youth_search가 예외를 던질 때")
    print("=" * 70)
    with patch("policy_mcp_server.policy_fetch.on_youth_search", side_effect=Exception("모의 네트워크 오류")):
        params = CallToolRequestParams(
            name="on_youth_search",
            arguments={"keyword": "월세"},
        )
        result = await policy_mcp_server.on_call_tool(ctx, params)

        assert result.is_error is True, f"예상과 달리 is_error=False: {result.is_error}"
        assert len(result.content) == 1
        content = result.content[0]
        assert content.type == "text"
        text = content.text

        print("반환 텍스트:")
        print(text)
        print()
        print("is_error:", result.is_error)
        assert text == "정책 조회 중 오류가 발생했습니다"
        print("점검 통과: 예외 발생 시 is_error=True + 고정 오류 메시지")

    print()
    print("모든 케이스 통과")

if __name__ == "__main__":
    asyncio.run(run())
