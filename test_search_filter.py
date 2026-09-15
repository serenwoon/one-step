#!/usr/bin/env python3
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import solar_service as svc
import policy_fetch as pf
import datetime as dt

KST = dt.timezone(dt.timedelta(hours=9))
TODAY = dt.date(2026, 9, 13)  # 재현 기준일


def make_policy(policy_no, name, region_codes, min_age, max_age, age_lmt_yn,
                add_qlfc_cnd_cn, ptcp_prp_trgt_cn, aply_ymd,
                biz_prd_end_ymd=None):
    return {
        "policyNo": policy_no,
        "policyName": name,
        "regionCodes": region_codes,
        "sprtTrgtMinAge": str(min_age) if min_age is not None else None,
        "sprtTrgtMaxAge": str(max_age) if max_age is not None else None,
        "sprtTrgtAgeLmtYn": age_lmt_yn,
        "addAplyQlfcCndCn": add_qlfc_cnd_cn,
        "ptcpPrpTrgtCn": ptcp_prp_trgt_cn,
        "aplyYmd": aply_ymd,
        "bizPrdEndYmd": biz_prd_end_ymd,
        "supportContent": "지원 내용",
        "applyUrl": "https://example.test/policy",
        "orgName": "담당 기관",
        "classification": "matched",
        "classificationReason": "지역 일치",
    }


def classify_result(items, keyword, region_codes):
    """search()가 기대하는 on_youth_search_classified 응답 골격을 만든다."""
    deduped = pf._dedup_by_policy_no(items)
    matched = []
    unmatched = []
    region_unknown = []
    filter_only_matched = []
    original_nos = {str(i.get("policyNo")).strip() for i in items if i.get("policyNo")}
    for item in deduped:
        cls, _ = pf._classify_single_item(item, region_codes)
        item["classification"] = cls
        no = item.get("policyNo")
        if cls == "matched":
            if no and str(no).strip() not in original_nos:
                filter_only_matched.append(item)
            else:
                matched.append(item)
        elif cls == "unmatched":
            unmatched.append(item)
        else:
            region_unknown.append(item)

    return {
        "status": "ok",
        "httpStatus": 200,
        "keyword": keyword,
        "regionFilterApplied": bool(region_codes),
        "regionCodes": region_codes,
        "fetchedCount": len(deduped),
        "totalCount": len(deduped),
        "pagesFetched": 1,
        "allMatchingResultsFetched": True,
        "matchedCount": len(matched),
        "unmatchedCount": len(unmatched),
        "regionUnknownCount": len(region_unknown),
        "filterOnlyMatchedCount": len(filter_only_matched),
        "pageErrors": [],
        "classifications": {
            "matched": matched,
            "filter_only_matched": filter_only_matched,
            "unmatched": unmatched,
            "region_unknown": region_unknown,
        },
        "allResults": deduped,
    }


def policy_start_str(item):
    period = item["_applyPeriod"]
    return period.get("aplyStart") or ""


def run_scenarios():
    print("검색 파이프라인 자격 필터 검증 (search() 모킹 호출)")
    print("기준일:", TODAY.isoformat())

    # 시나리오 1: 부적격 1건이 섞였을 때 반환 후보에서 제거되는지
    policies = [
        make_policy("OK-1", "청년 취업 지원 (만 15~39세)",
                    "11440", 15, 39, "Y", None, None,
                    "2026.09.01 ~ 2026.09.30"),
        make_policy("OK-2", "청년 주거 지원 (만 19~34세)",
                    "11440", 19, 34, "Y", None, None,
                    "2026.09.10 ~ 2026.09.30"),
        make_policy("BAD-1", "청년 자산형성 (만 19~34세)",
                    "11440", 19, 34, "Y", None, None,
                    "2026.09.12 ~ 2026.09.30"),  # 35세 → 부적격
        make_policy("OK-3", "청년 창업 지원 (나이 제한 없음)",
                    "11440", None, None, "N", None, None,
                    "2026.09.11 ~ 2026.09.30"),
    ]

    result = classify_result(policies, "청년", ["11440"])
    user_info = {"age": 35, "employment": "employed"}

    with patch.object(pf, "on_youth_search_classified", return_value=result):
        resp = svc.search({
            "keyword": "청년",
            "region_codes": ["11440"],
            "user_info": user_info,
        })

    assert resp.get("status") == "ok", resp.get("status")
    cand_ids = {str(c.get("policyNo")) for c in resp.get("candidates", [])}
    all_ids = {str(c.get("policyNo")) for c in resp.get("allCandidates", [])}

    print("\n[시나리오1] 부적격(BAD-1)이 반환에서 제거됐는지")
    print("  candidates policyNo:", sorted(cand_ids))
    print("  allCandidates policyNo:", sorted(all_ids))
    assert "BAD-1" not in cand_ids, "candidates에 부적격 정책이 남음"
    assert "BAD-1" not in all_ids, "allCandidates에 부적격 정책이 남음"

    # 건수와 목록 일관성
    print("\n[시나리오1] 건수 일관성")
    print("  openCandidateCount:", resp.get("openCandidateCount"))
    print("  displayedCandidateCount:", resp.get("displayedCandidateCount"))
    print("  summary 전체 후보 건수:", resp.get("summary", {}).get("전체 후보 건수"))
    assert resp.get("openCandidateCount") == len(resp.get("candidates", [])), "openCandidateCount 불일치"
    assert resp.get("displayedCandidateCount") == len(resp.get("candidates", [])), "displayedCandidateCount 불일치"
    assert resp.get("summary", {}).get("전체 후보 건수") == len(resp.get("allCandidates", [])), "전체 후보 건수 불일치"

    # 최신순 유지: aplyStart 기준으로 내림차순이어야 함
    starts = [policy_start_str(c) for c in resp.get("candidates", [])]
    parsed = []
    for s in starts:
        if s and len(s) == 8 and s.isdigit():
            parsed.append(dt.date(int(s[:4]), int(s[4:6]), int(s[6:8])))
    print("\n[시나리오1] 후보 신청 시작일(최신순):", [p.isoformat() for p in parsed])
    assert parsed == sorted(parsed, reverse=True), "신청 시작일 최신순이 아님"

    # 시나리오 2: needs_check는 검색 후보에서 제외되는지
    policies2 = [
        make_policy("OK-A", "청년 멘토링 (만 15~39세)",
                    "11440", 15, 39, "Y", None, None,
                    "2026.09.02 ~ 2026.09.25"),
        make_policy("CHK-A", "취업 준비생 지원 (나이·취업 조건 불분명)",
                    "11440", None, None, "N",
                    "재직자 대상", None,
                    "2026.09.05 ~ 2026.09.25"),
    ]
    result2 = classify_result(policies2, "청년", ["11440"])
    with patch.object(pf, "on_youth_search_classified", return_value=result2):
        resp2 = svc.search({
            "keyword": "청년",
            "region_codes": ["11440"],
            "user_info": {"age": 28, "employment": None},
        })

    cand2_ids = {str(c.get("policyNo")) for c in resp2.get("candidates", [])}
    all2_ids = {str(c.get("policyNo")) for c in resp2.get("allCandidates", [])}
    print("\n[시나리오2] needs_check(CHK-A)가 반환 후보에 남는지")
    print("  candidates policyNo:", sorted(cand2_ids))
    print("  allCandidates policyNo:", sorted(all2_ids))
    assert "CHK-A" in cand2_ids, "needs_check가 candidates에서 빠짐"
    assert "CHK-A" in all2_ids, "needs_check가 allCandidates에서 빠짐"

    # CHK-A의 _qual.status가 needs_check인지 확인
    chk_item = next(c for c in resp2.get("allCandidates", []) if str(c.get("policyNo")) == "CHK-A")
    chk_status = chk_item.get("_qual", {}).get("status")
    print("  CHK-A _qual.status:", chk_status)
    assert chk_status == "needs_check", f"CHK-A는 needs_check여야 하나 {chk_status}"

    # 시나리오 3: 그 외는 그대로 통과
    policies3 = [
        make_policy("OK-B", "청년 상담 지원 (만 15~39세)",
                    "11440", 15, 39, "Y", None, None,
                    "2026.09.03 ~ 2026.09.28"),
    ]
    result3 = classify_result(policies3, "청년", ["11440"])
    with patch.object(pf, "on_youth_search_classified", return_value=result3):
        resp3 = svc.search({
            "keyword": "청년",
            "region_codes": ["11440"],
            "user_info": {"age": 28, "employment": "employed"},
        })
    cand3_ids = {str(c.get("policyNo")) for c in resp3.get("candidates", [])}
    print("\n[시나리오3] 적합 정책만 있을 때 그대로 유지되는지")
    print("  candidates policyNo:", sorted(cand3_ids))
    assert cand3_ids == {"OK-B"}, "적합 정책이 빠짐"
    assert resp3.get("openCandidateCount") == 1

    print("\n모든 시나리오 통과")


def main():
    # 날짜와 외부 키에 관계없이 같은 검색 경로를 재현한다.
    normalize = svc._normalize_apply_period
    fixed_now = dt.datetime.combine(TODAY, dt.time(12), KST)
    with patch.object(pf, 'load_api_keys', return_value={'ON_YOUTH_API_KEY': 'local-test'}), \
         patch.object(svc, '_normalize_apply_period', side_effect=lambda item, now: normalize(item, fixed_now)):
        run_scenarios()


if __name__ == "__main__":
    main()
