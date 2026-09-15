#!/usr/bin/env python3
"""학생 중립 문구 반례 테스트 — 학생 단어가 있다고 비학생을 제외해선 안 된다."""
import sys
sys.path.insert(0, '.')
import policy_fetch as pf

BASE = {"sprtTrgtMinAge": None, "sprtTrgtMaxAge": None, "sprtTrgtAgeLmtYn": "N"}

def check(label, cond_cn, ptcp_cn, info, expect_status):
    item = {**BASE, "addAplyQlfcCndCn": cond_cn, "ptcpPrpTrgtCn": ptcp_cn}
    r = pf.policy_qualification_check(item, info)
    ok = r["status"] == expect_status
    flag = "OK " if ok else "XX "
    print(f"{flag}{label}")
    print(f"    정책 조건: {cond_cn}")
    print(f"    사용자: {info}")
    print(f"    결과: {r['status']}  (예상: {expect_status})")
    if r["ineligibleReasons"]:
        print(f"    부적격: {r['ineligibleReasons']}")
    if r["needsCheckReasons"]:
        print(f"    확인필요: {r['needsCheckReasons']}")
    if r["matchedReasons"]:
        print(f"    일치: {r['matchedReasons']}")
    if not ok:
        print(f"    −→ 실패")
    return ok

def main():
    results = []
    age_policy = {"sprtTrgtMinAge": "15", "sprtTrgtMaxAge": "39", "sprtTrgtAgeLmtYn": "Y"}

    print("=" * 92)
    print("학생 중립 문구 — 비학생 부적격 오류 재현 (RED)")
    print("=" * 92)

    # 핵심 반례: "학생 여부 확인 서류 제출"은 대상/제외가 아닌 중립 문구
    # student=False여도 ineligible이 아니라 needs_check여야 한다.
    results.append(check(
        "학생 여부 확인 서류 제출 + 비학생",
        "학생 여부 확인 서류 제출", None,
        {"age": 27, "employment": "unemployed", "student": False},
        "needs_check",
    ))

    # 대비: "학생 대상"은 비학생을 명확히 부적격 처리해야 함
    results.append(check(
        "학생 대상 + 비학생",
        "학생 대상", None,
        {"age": 27, "employment": "unemployed", "student": False},
        "ineligible",
    ))

    # 대비: "학생 제외"는 비학생이 통과해야 함
    results.append(check(
        "학생 제외 + 비학생",
        "학생 제외", None,
        {"age": 27, "employment": "unemployed", "student": False},
        "ok",
    ))

    # 대비: "학생 제외"라도 학생은 부적격
    results.append(check(
        "학생 제외 + 학생",
        "학생 제외", None,
        {"age": 22, "employment": "unemployed", "student": True},
        "ineligible",
    ))

    # "재학생 여부 확인 서류 등록" — "등록"은 서류 안내일 뿐 대상 조건이 아님
    # student=False여도 ineligible이 아니라 needs_check여야 한다.
    results.append(check(
        "재학생 여부 확인 서류 등록 + 비학생",
        "재학생 여부 확인 서류 등록", None,
        {"age": 27, "employment": "unemployed", "student": False},
        "needs_check",
    ))

    # 복합 조건: "학생 또는 졸업자 대상" + "미졸업시 전액 반환"
    # "또는 졸업자 대상"이므로 학생만 대상이 아님. 미졸업시 반환이 붙어도
    # 졸업자 제외를 추론하지 않아야 함 → 비학생(졸업자)도 needs_check
    results.append(check(
        "학생 또는 졸업자 대상 + 미졸업시 전액 반환 + 비학생(졸업자)",
        "학생 또는 졸업자 대상 (미졸업시 전액 반환)", None,
        {"age": 27, "employment": "unemployed", "student": False},
        "needs_check",
    ))

    # 대비: "학생 또는 졸업자 대상" 단독으로는 원래대로 needs_check
    results.append(check(
        "학생 또는 졸업자 대상 + 비학생(졸업자)",
        "학생 또는 졸업자 대상", None,
        {"age": 27, "employment": "unemployed", "student": False},
        "needs_check",
    ))

    # 미졸업 시 반환만으로 졸업자 제외를 추론하지 않아야 함
    # (별도 제외 문구 없이 "미졸업시 전액 반환"만 있을 때 비학생=졸업자라고 단정하면 안 됨)
    results.append(check(
        "참여 학생 (미졸업시 전액 반환) + 비학생(졸업자)",
        "직업계고 3학년 참여 학생 (미졸업시 전액 반환)", None,
        {"age": 27, "employment": "unemployed", "student": False},
        "needs_check",
    ))

    # PTCP 반례: "학생이 취업한 기업이…지급할 수 없습니다"는 기업 제외 안내일 뿐
    # 학생 대상 조건이 아니다 → 비학생도 ineligible이 아니라 needs_check
    results.append(check(
        "학생 취업 기업 제외 안내 + 비학생",
        "대한민국 국적자 (연령 제한 없음)",
        "학생이 취업한 기업이 아래에 해당할 경우 장려금을 지급할 수 없습니다.\n기업 규모: 대기업, 공공기관, 국가 및 지방자치단체, 공기업",
        {"age": 27, "employment": "unemployed", "student": False},
        "needs_check",
    ))

    print("=" * 92)
    passed = sum(results)
    total = len(results)
    print(f"통과: {passed} / {total}")
    print("=" * 92)
    return 0 if all(results) else 1

if __name__ == "__main__":
    sys.exit(main())
