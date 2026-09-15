#!/usr/bin/env python3
import asyncio
import json
import os
import sys
from unittest.mock import MagicMock

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 실제 HTTP 요청 없이, policy_fetch.on_youth_search가 dict를 반환하는지 확인
import policy_fetch

MOCK_RESULT = policy_fetch.on_youth_search(
    "DUMMY_KEY_FOR_UNIT_CHECK",
    "월세",
    page_size=2,
)

assert isinstance(MOCK_RESULT, dict), "on_youth_search가 dict를 반환하지 않음"
assert MOCK_RESULT.get("status") == "ok", f"예상과 다른 상태: {MOCK_RESULT.get('status')}"
assert MOCK_RESULT.get("keyword") == "월세"
assert MOCK_RESULT.get("pageSize") == 2
assert isinstance(MOCK_RESULT.get("results"), list)
assert len(MOCK_RESULT["results"]) == 2

# JSON 직렬화 확인
serialized = json.dumps(MOCK_RESULT, ensure_ascii=False, indent=2)
parsed = json.loads(serialized)
assert parsed == MOCK_RESULT, "직렬화/파싱 결과가 원본 dict와 다름"

print("on_youth_search 반환 타입:", type(MOCK_RESULT).__name__)
print("키워드:", MOCK_RESULT["keyword"])
print("pageSize:", MOCK_RESULT["pageSize"])
print("results 수:", len(MOCK_RESULT["results"]))
print("결과 JSON 직렬화 정상:", bool(serialized))
print()
print("결과 JSON(일부):")
print(json.dumps({k: v for k, v in MOCK_RESULT.items() if k in ("status", "keyword", "pageSize", "fetchedCount", "totalCount", "results")}, ensure_ascii=False, indent=2))
print()
print("점검 통과: 실제 HTTP로 받은 dict를 MCP 서버가 그대로 JSON 반환할 수 있음")
