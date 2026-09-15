#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import policy_fetch as p

# 사용자 정보 형식:
#   age: int|None
#   employment: "employed"|"unemployed"|None   (취업 상태, 학생과 별개)
#   student: True|False|None           (재학 여부, 취업 상태와 별개)

BASE = {"sprtTrgtMinAge": None, "sprtTrgtMaxAge": None, "sprtTrgtAgeLmtYn": "N"}

def row(label, cond_cn, ptcp_cn, info, expect_status, **values):
    item = {**BASE, "addAplyQlfcCndCn": cond_cn, "ptcpPrpTrgtCn": ptcp_cn, **values}
    r = p.policy_qualification_check(item, info)
    ok = r["status"] == expect_status
    flag = "OK " if ok else "XX "
    print(f"{flag}{label}")
    print(f"    정책: {cond_cn} | {ptcp_cn}")
    print(f"    사용자: {info}")
    print(f"    결과: {r['status']}")
    if r["ineligibleReasons"]:
        print(f"    부적격 사유: {r['ineligibleReasons']}")
    if r["needsCheckReasons"]:
        print(f"    확인 필요 사유: {r['needsCheckReasons']}")
    if not ok:
        print(f"    예상 상태: {expect_status}")
    return ok

def main():
    print("=" * 92)
    print("정책 자격 판정 테스트")
    print("=" * 92)

    results = []

    def check(*args, **values):
        results.append(row(*args, **values))

    age_policy = {"sprtTrgtMinAge": "15", "sprtTrgtMaxAge": "39", "sprtTrgtAgeLmtYn": "Y"}

    # 1) 취업 상태 무관 정책 — 모든 취업 상태가 통과해야 함
    check("취업 무관 + 재직자",
          "취업 상태 무관", None,
          {"age": 35, "employment": "employed", "student": False},
          "ok", **age_policy)
    check("취업 무관 + 미취업자",
          "취업 상태 무관", None,
          {"age": 28, "employment": "unemployed", "student": False},
          "ok", **age_policy)
    check("취업 무관 + 취업 정보 없음",
          "취업 상태 무관", None,
          {"age": 28, "employment": None, "student": None},
          "ok", **age_policy)

    # 연령 필드와 본문 불일치.
    check("연령 필드와 본문 불일치",
          "취업 상태 무관, 만 15~39세", None,
          {"age": 28, "employment": "employed", "student": False},
          "needs_check")

    # 2) 우대는 필수 자격이 아님
    check("재직자 우대 + 재직자",
          "재직자에게 우대 지급", None,
          {"age": 35, "employment": "employed", "student": False},
          "ok")
    check("재직자 우대 + 미취업자",
          "재직자에게 우대 지급", None,
          {"age": 28, "employment": "unemployed", "student": False},
          "ok")  # 우대는 제외 근거가 아님
    check("재직자 우대 + 취업 정보 없음",
          "재직자에게 우대 지급", None,
          {"age": 28, "employment": None, "student": None},
          "ok")  # 우대만으로 부적격 처리하면 안 됨

    # 3) “재직자 대상. 대학생 제외.” — 조항 단위 제외 적용 (같은 대상의 조건에만)
    check("재직자 대상. 대학생 제외 + 재직자(비학생)",
          "재직자 대상. 대학생 제외.", None,
          {"age": 35, "employment": "employed", "student": False},
          "ok")
    check("재직자 대상. 대학생 제외 + 재직자(학생)",
          "재직자 대상. 대학생 제외.", None,
          {"age": 25, "employment": "employed", "student": True},
          "ineligible")  # 학생 제외 적용
    check("재직자 대상. 대학생 제외 + 미취업자",
          "재직자 대상. 대학생 제외.", None,
          {"age": 28, "employment": "unemployed", "student": False},
          "ineligible")  # 재직자 대상인데 미취업자

    # 4) 학생 대상 / 학생 제외 (취업 상태와 별개로 비교)
    check("대학생 대상 + 학생",
          "대학생 대상 장학금", None,
          {"age": 22, "employment": None, "student": True},
          "ok")
    check("대학생 대상 + 비학생(취업자)",
          "대학생 대상 장학금", None,
          {"age": 35, "employment": "employed", "student": False},
          "ineligible")
    check("대학생 대상 + 취업 정보 없음",
          "대학생 대상 장학금", None,
          {"age": 22, "employment": None, "student": None},
          "needs_check")
    check("대학생 제외 + 학생",
          "대학생 제외 대상", None,
          {"age": 22, "employment": "employed", "student": True},
          "ineligible")
    check("대학생 제외 + 비학생(취업자)",
          "대학생 제외 대상", None,
          {"age": 35, "employment": "employed", "student": False},
          "ok")
    check("대학생 제외 + 비학생(미취업자)",
          "대학생 제외 대상", None,
          {"age": 28, "employment": "unemployed", "student": False},
          "ok")
    check("대학생 제외 + 재학 정보 없음",
          "대학생 제외 대상", None,
          {"age": 28, "employment": None, "student": None},
          "needs_check")

    # 5) “취업 상태” 문구 정확 처리
    check("취업 상태인 사람 대상 + 재직자",
          "취업 상태인 사람 대상", None,
          {"age": 30, "employment": "employed", "student": False},
          "ok")
    check("취업 상태인 사람 대상 + 미취업자",
          "취업 상태인 사람 대상", None,
          {"age": 28, "employment": "unemployed", "student": False},
          "ineligible")
    check("취업 상태가 아닌 사람 대상 + 미취업자",
          "취업 상태가 아닌 사람 대상", None,
          {"age": 28, "employment": "unemployed", "student": False},
          "ok")
    check("취업 상태가 아닌 사람 대상 + 재직자",
          "취업 상태가 아닌 사람 대상", None,
          {"age": 30, "employment": "employed", "student": False},
          "ineligible")

    # 6) “미취업 청년 대상. 재직자 제외.” 복합 (강화 표현)
    check("미취업 청년 대상. 재직자 제외 + 미취업자",
          "미취업 청년 대상. 재직자 제외.", None,
          {"age": 28, "employment": "unemployed", "student": False},
          "ok")
    check("미취업 청년 대상. 재직자 제외 + 재직자",
          "미취업 청년 대상. 재직자 제외.", None,
          {"age": 30, "employment": "employed", "student": False},
          "ineligible")

    # 7) 재학·취업 혼합: 학생이 아니면서 취업 상태인 사람은 각자 조건에 따라 판정
    check("대학생 대상 + 재직자 학생",
          "대학생 대상", None,
          {"age": 25, "employment": "employed", "student": True},
          "ok")  # 학생이므로 대학생 대상 충족
    check("재직자 대상 + 재직자 학생",
          "재직자 대상", None,
          {"age": 25, "employment": "employed", "student": True},
          "ok")  # 취업 상태로 충족, 학생 여부는 무관(학생 제외 문구 없음)

    print("=" * 92)
    print("통과:", sum(results), "/", len(results))
    print("=" * 92)
    return 0 if all(results) else 1

if __name__ == "__main__":
    sys.exit(main())
