#!/usr/bin/env python3
"""
수정 전 재현: 나이·취업 상태가 명백히 안 맞는 정책이
지역 일치 + 신청 기간 '신청 중'만으로 추천 후보로 올라오는 사례를 확인한다.

API 호출 없이 mock 항목으로 solar_service.py의 조립 로직 일부를 재연한다.
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import datetime as dt
import policy_fetch as p
import solar_service as s

KST = dt.timezone(dt.timedelta(hours=9))

# ------------------------------------------------------------------
# 사용자 프로필 (입력 정보)
# ------------------------------------------------------------------
# 이 시나리오에서는 "나이 35세, 취업 상태: 재직 중(직장인)"만 주어졌다고 가정.
# 소득·가구·학력 등은 제공되지 않음 → 정보 부족은 '확인 필요'로 남겨야 한다.
USER = {
    "age": 35,                 # 만 나이 기준이라고 가정
    "employment": "employed",  # 재직 중 (취업 상태)
    # region_code는 시나리오마다 제공 (아래 시나리오에서 지정)
}

# ------------------------------------------------------------------
# 재현할 정책 mock
# 키워드 검색 결과에 섞여 들어오는 형태로 만든다.
# (실제 응답 필드 일부를 그대로 사용)
# ------------------------------------------------------------------
def make_policy(**overrides):
    base = {
        "policyNo": "MOCK-000",
        "policyName": "placeholder",
        "supportContent": "청년 지원 내용",
        "applyUrl": "https://example.test/policy",
        "orgName": "담당 기관",
        "regionCodes": None,
        "sprtTrgtMinAge": None,
        "sprtTrgtMaxAge": None,
        "sprtTrgtAgeLmtYn": None,
        "aplyYmd": "2026-09-01 ~ 2026-09-30",   # 오늘(9/13) 기준 신청 중
        "bizPrdEndYmd": None,
        "addAplyQlfcCndCn": None,
        "ptcpPrpTrgtCn": None,
        "classification": None,
        "classificationReason": None,
    }
    base.update(overrides)
    return base


SCENARIOS = []

# 시나리오 A: 나이는 맞지만 취업 상태가 명백히 다름
# - 정책 대상: "만 15~39세 미취업 청년" (취업 상태 조건 명시)
# - 사용자: 35세, 재직 중 → 취업 상태에서 불일치
SCENARIOS.append({
    "name": "A: 나이는 범위 안이지만 취업 상태 '미취업' 조건과 불일치",
    "user": dict(USER),
    "region_codes": ["11440"],  # 서울 마포구 (지역 일치 가정)
    "policies": [
        make_policy(
            policyNo="A-1",
            policyName="미취업 청년 취업연계 수당 (서울 마포구)",
            regionCodes="11440",
            sprtTrgtMinAge="15",
            sprtTrgtMaxAge="39",
            sprtTrgtAgeLmtYn="Y",
            addAplyQlfcCndCn="미취업 상태인 청년 대상. 재직자 제외.",
            ptcpPrpTrgtCn="취업 상태 아닌 사람",
            aplyYmd="2026.09.01 ~ 2026.09.30",
        ),
    ],
    "expected_issue": "현재 파이프라인은 지역 일치 + 신청 중 → 추천 후보로 올림 (취업 상태 불일치 무시)",
})

# 시나리오 B: 나이 상한을 넘음
# - 정책 대상: "만 19~34세 청년"
# - 사용자: 35세 → 나이 상한 초과 (명백한 불일치)
SCENARIOS.append({
    "name": "B: 나이 상한(34세)을 초과한 사용자에게 추천",
    "user": dict(USER),
    "region_codes": ["11440"],
    "policies": [
        make_policy(
            policyNo="B-1",
            policyName="청년 월세 지원 (만 19~34세)",
            regionCodes="11440",
            sprtTrgtMinAge="19",
            sprtTrgtMaxAge="34",
            sprtTrgtAgeLmtYn="Y",
            addAplyQlfcCndCn="만 19세 이상 34세 이하",
            aplyYmd="2026.09.01 ~ 2026.09.30",
        ),
    ],
    "expected_issue": "나이 상한 초과를 걸러내지 못함",
})

# 시나리오 C: 나이 하한 미달
SCENARIOS.append({
    "name": "C: 나이 하한(19세) 미달 사용자에게 추천",
    "user": dict(USER, age=17),
    "region_codes": ["11440"],
    "policies": [
        make_policy(
            policyNo="C-1",
            policyName="청년 자산형성 지원 (만 19~34세)",
            regionCodes="11440",
            sprtTrgtMinAge="19",
            sprtTrgtMaxAge="34",
            sprtTrgtAgeLmtYn="Y",
            addAplyQlfcCndCn="만 19세 이상 34세 이하",
            aplyYmd="2026.09.01 ~ 2026.09.30",
        ),
    ],
    "expected_issue": "나이 하한 미달을 걸러내지 못함",
})

# 시나리오 D: 나이 정보 없음 + 취업 상태 조건 불명확 (정보 부족으로 남겨야 함)
# - 정책 대상: 나이 제한 명시 안 됨, "취업 준비생 우대" 정도만 서술
# - 사용자: 나이·취업 상태 모두 미제공 → 자격 판정 불가 → 확인 필요
SCENARIOS.append({
    "name": "D: 사용자 나이·취업 정보 없음 → 자격 판정 불가 (확인 필요)",
    "user": {"age": None, "employment": None},
    "region_codes": ["11440"],
    "policies": [
        make_policy(
            policyNo="D-1",
            policyName="취업 준비생 우대 멘토링 (나이 제한 미명시)",
            regionCodes="11440",
            sprtTrgtMinAge=None,
            sprtTrgtMaxAge=None,
            sprtTrgtAgeLmtYn="N",
            addAplyQlfcCndCn="취업 준비생 우대 ( 명문화된 나이·취업 조건 없음 )",
            aplyYmd="2026.09.01 ~ 2026.09.30",
        ),
    ],
    "expected_issue": "현재 파이프라인은 연령 검증 없이 그냥 후보로 올림 / 정보 부족 구분 없음",
})

# 시나리오 E: 연령은 적합하지만 취업 상태 조건 확인이 필요함 (명시적 불일치 아님)
# - 정책 대상: "만 15~39세", 취업 상태는 원문상 별도 조건 없음
# - 사용자: 28세, 재직 중 → 나이 적합, 취업 상태는 문서에 명시 안 됨 → 확인 필요
SCENARIOS.append({
    "name": "E: 나이는 적합, 취업 상태 조건은 원문에 명시 안 됨 → 확인 필요",
    "user": dict(USER, age=28),
    "region_codes": ["11440"],
    "policies": [
        make_policy(
            policyNo="E-1",
            policyName="청년 생애 첫걸음 지원 (만 15~39세, 취업 상태 조건 미명시)",
            regionCodes="11440",
            sprtTrgtMinAge="15",
            sprtTrgtMaxAge="39",
            sprtTrgtAgeLmtYn="Y",
            addAplyQlfcCndCn="별도로 취업 상태를 명시하지 않음",
            aplyYmd="2026.09.01 ~ 2026.09.30",
        ),
    ],
    "expected_issue": "취업 상태가 문서에 없어 불일치라 할 수 없으나, 현재 파이프라인은 그걸 구분하지 않음",
})


def today_str():
    return dt.datetime.now(KST).strftime('%Y%m%d')


def build_enriched(policies, region_codes, now=None):
    """solar_service.search()의 enriched 조립을 모킹 없이 따라간다."""
    now = now or dt.datetime.now(KST)
    enriched = []
    for item in policies:
        base = {
            k: str(item[k])[:1800]
            for k in (
                "policyNo", "policyName", "supportContent", "applyUrl",
                "orgName", "classification", "sprtTrgtMinAge", "sprtTrgtMaxAge",
                "sprtTrgtAgeLmtYn", "aplyYmd", "bizPrdEndYmd",
                "addAplyQlfcCndCn", "ptcpPrpTrgtCn",
            )
            if item.get(k) is not None
        }
        base["_regionScope"] = p.policy_region_scope(item)
        base["_applyPeriod"] = s._normalize_apply_period(item, now)
        # 아래 줄은 수정 전 파이프라인(자격 검증 없음)을 흉내 낸다.
        base["_qual_min_age"] = item.get("sprtTrgtMinAge")
        base["_qual_max_age"] = item.get("sprtTrgtMaxAge")
        base["_qual_age_lmt_yn"] = item.get("sprtTrgtAgeLmtYn")
        base["_qual_add_qlfc_cnd"] = item.get("addAplyQlfcCndCn")
        base["_qual_ptcp_prp"] = item.get("ptcpPrpTrgtCn")
        enriched.append(base)
    return enriched


def print_scenario(sc):
    print("\n" + "=" * 90)
    print("시나리오:", sc["name"])
    print("사용자:", sc["user"])
    print("대상 지역 코드:", sc["region_codes"])
    print("-" * 90)
    for pol in sc["policies"]:
        print("  정책:", pol["policyName"])
        print("    regionCodes:", pol.get("regionCodes"))
        print("    sprtTrgtMinAge:", pol.get("sprtTrgtMinAge"),
              "/ sprtTrgtMaxAge:", pol.get("sprtTrgtMaxAge"),
              "/ ageLmtYn:", pol.get("sprtTrgtAgeLmtYn"))
        print("    addAplyQlfcCndCn:", pol.get("addAplyQlfcCndCn"))
        print("    ptcpPrpTrgtCn:", pol.get("ptcpPrpTrgtCn"))
        print("    aplyYmd(원문):", pol.get("aplyYmd"))
    print("현재 파이프라인 관점의 문제:", sc["expected_issue"])


def main():
    print("작성일 기준 한국 날짜:", today_str())
    print("사용 정책 파이프라인: solar_service._normalize_apply_period + policy_fetch 지역 분류")
    print("※ 실제 API 호출 없이 mock 항목으로 재구성한 로컬 재현이다.")

    for sc in SCENARIOS:
        print_scenario(sc)
        enriched = build_enriched(sc["policies"], sc["region_codes"])
        open_now = [e for e in enriched if e["_applyPeriod"]["status"] == "신청 중"]
        print("  → 신청 기간 상태 '신청 중'인 정책 수:", len(open_now))
        for e in open_now:
            print("    -", e.get("policyName"),
                  "| 적용기간:", e["_applyPeriod"]["raw"],
                  "| 상태:", e["_applyPeriod"]["status"])
        print("  문제 재현 요약:", sc["expected_issue"])

    print("\n" + "=" * 90)
    print("재현 결론(예시):")
    print(" - 정책과 사용자 나이·취업 상태 대조 로직이 없으면")
    print("   지역 일치 + 신청 중이기만 하면 명백히 자격이 맞지 않는 정책도 추천 후보에 포함됨")
    print(" - 나이·취업 정보가 없는 경우는 '불일치'가 아니라 '확인 필요'로 구분해야 하나")
    print("   현재 파이프라인에는 그런 구분이 없음")
    print("=" * 90)


if __name__ == "__main__":
    main()
