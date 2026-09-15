import os, json, time, sys

sys.path.insert(0, ".")
import solar_service as svc
import policy_fetch as pf

PROFILE_UNEMPLOYED = {"age": 28, "employment": "unemployed", "purpose": "주거", "region_codes": ["11440"]}
PROFILE_EMPLOYED = {"age": 28, "employment": "employed", "purpose": "주거", "region_codes": ["11440"]}

KEY = pf.load_api_keys()["ON_YOUTH_API_KEY"]

def summarize_classified(result):
    print("분류 결과 status:", result.get("status"))
    g = result.get("classifications", {})
    print("matched:", len(g.get("matched", [])))
    print("filter_only_matched:", len(g.get("filter_only_matched", [])))
    print("region_unknown:", len(g.get("region_unknown", [])))
    print("unmatched:", len(g.get("unmatched", [])))
    for label, items in g.items():
        print(f"\n[{label}]")
        for it in items[:10]:
            per = svc._normalize_apply_period(it)
            print("-", it.get("policyName"), "| region:", it.get("regionCodes"),
                  "| apply:", per["status"], "|", per["raw"][:40])

print("=" * 92)
print("A) policy_fetch 직접 호출: keyword='월세', region=['11440']")
print("=" * 92)
res = pf.on_youth_search_classified(KEY, "월세", ["11440"], max_pages=2, page_size=20)
summarize_classified(res)
print("fetchedCount:", res.get("fetchedCount"), "totalCount:", res.get("totalCount"))
print("pageErrors:", res.get("pageErrors"))

print("\n지역 코드 '11440'이 실제로 매칭되는지 샘플 확인")
for it in (res.get("classifications", {}).get("matched", []) or [])[:5]:
    print("-", it.get("policyName"), "| regionCodes:", it.get("regionCodes"))
    print("   addAplyQlfcCndCn:", it.get("addAplyQlfcCndCn"))
    print("   ptcpPrpTrgtCn:", it.get("ptcpPrpTrgtCn"))
    print("   sprtTrgtMinAge/MaxAge:", it.get("sprtTrgtMinAge"), it.get("sprtTrgtMaxAge"))

# ------------------------------------------------------------------
# 1) 미취업 / 월세 / 서울 마포구 검색
# ------------------------------------------------------------------
t0 = time.time()
r1 = svc.search({"keyword": "월세", "region_codes": ["11440"], "user_info": PROFILE_UNEMPLOYED})
dt1 = time.time() - t0
print("검색1 상태:", r1["status"], "| 호출 시간(초):", round(dt1, 3))
print("검색1 summary:", json.dumps(r1["summary"], ensure_ascii=False, indent=2)[:800])

print("\n[검색1] candidates:")
for c in r1["candidates"]:
    print("-", c.get("policyName"))
    print("   region:", c.get("_regionScope", {}).get("label"))
    print("   applyPeriod:", c.get("_applyPeriod", {}).get("status"), "|", c.get("_applyPeriod", {}).get("raw"))
    print("   applyUrl:", c.get("applyUrl"))
    print("   _qual:", json.dumps(c.get("_qual", {}), ensure_ascii=False))
    print("   _relevance:", json.dumps(c.get("_relevance", {}), ensure_ascii=False))

# ------------------------------------------------------------------
# 2) 동일 대화 맥락 취업 정정 후 재검색
# ------------------------------------------------------------------
t1 = time.time()
r2 = svc.search({"keyword": "월세", "region_codes": ["11440"], "user_info": PROFILE_EMPLOYED})
dt2 = time.time() - t1
print("\n검색2 상태:", r2["status"], "| 호출 시간(초):", round(dt2, 3))
print("[검색2] candidates:")
for c in r2["candidates"]:
    print("-", c.get("policyName"))
    print("   applyPeriod:", c.get("_applyPeriod", {}).get("status"), "|", c.get("_applyPeriod", {}).get("raw"))
    print("   _qual:", json.dumps(c.get("_qual", {}), ensure_ascii=False))
    print("   _relevance:", json.dumps(c.get("_relevance", {}), ensure_ascii=False))

# ------------------------------------------------------------------
# 3) 실제 API 원문과 첫 후보 비교
# ------------------------------------------------------------------
if r1["candidates"]:
    first = r1["candidates"][0]
    pn = first.get("policyNo")
    print("\n=== 원본 비교: policyNo", pn, "===")
    try:
        raw = pf.on_youth_search(pf.load_api_keys()["ON_YOUTH_API_KEY"], first.get("policyName", ""), page_size=1, region_codes=["11440"])
        print("원본 조회 상태:", raw.get("status"), "| 건수:", raw.get("fetchedCount"))
        if raw.get("status") == "ok" and raw.get("results"):
            orig = raw["results"][0]
            for k in ("policyName", "regionCodes", "sprtTrgtMinAge", "sprtTrgtMaxAge", "sprtTrgtAgeLmtYn",
                      "aplyYmd", "bizPrdEndYmd", "addAplyQlfcCndCn", "ptcpPrpTrgtCn", "applyUrl"):
                print(f"원본 {k}:", orig.get(k))
            print("\n가공본 _applyPeriod.raw:", first.get("_applyPeriod", {}).get("raw"))
            print("가공본 _applyPeriod.status:", first.get("_applyPeriod", {}).get("status"))
            print("가공본 _qual:", json.dumps(first.get("_qual", {}), ensure_ascii=False))
        else:
            print("원본 조회 결과 없음:", raw)
    except Exception as e:
        print("원본 비교 중 오류:", e)
