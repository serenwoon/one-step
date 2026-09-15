import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import policy_fetch as p


def show(label, item, user_info):
    r = p.policy_qualification_check(item, user_info)
    print(f"\n{label}")
    print("  정책 text:", item.get("addAplyQlfcCndCn"), "|", item.get("ptcpPrpTrgtCn"))
    print("  user_info:", user_info)
    print("  result:", r["status"])
    if r["ineligibleReasons"]:
        print("  ineligible:", r["ineligibleReasons"])
    if r["needsCheckReasons"]:
        print("  needs_check:", r["needsCheckReasons"])


def main():
    base = {
        "sprtTrgtMinAge": None,
        "sprtTrgtMaxAge": None,
        "sprtTrgtAgeLmtYn": "N",
    }

    # CASE 1: 취업 정보 없음 + 재직자 대상 정책 → needs_check 여야 함
    show(
        "CASE 1: 취업 정보 없음 + ‘재직자 대상’",
        {**base, "addAplyQlfcCndCn": "재직자 대상 복지", "ptcpPrpTrgtCn": None},
        {"age": 35, "employment": None},
    )

    # CASE 2: 미취업 청년 + ‘미취업 청년 대상. 재직자 제외.’ → OK 여야 함
    show(
        "CASE 2: 미취업자 + ‘미취업 청년 대상. 재직자 제외.’",
        {**base, "addAplyQlfcCndCn": "미취업 청년 대상. 재직자 제외.", "ptcpPrpTrgtCn": None},
        {"age": 28, "employment": "unemployed"},
    )

    # CASE 3: 재직자 + ‘미취업 청년 대상. 재직자 제외.’ → ineligible
    show(
        "CASE 3: 재직자 + ‘미취업 청년 대상. 재직자 제외.’",
        {**base, "addAplyQlfcCndCn": "미취업 청년 대상. 재직자 제외.", "ptcpPrpTrgtCn": None},
        {"age": 30, "employment": "employed"},
    )

    # CASE 4: 취업 정보 없음 + ‘미취업 청년 대상. 재직자 제외.’ → needs_check
    show(
        "CASE 4: 취업 정보 없음 + ‘미취업 청년 대상. 재직자 제외.’",
        {**base, "addAplyQlfcCndCn": "미취업 청년 대상. 재직자 제외.", "ptcpPrpTrgtCn": None},
        {"age": 28, "employment": None},
    )

    # CASE 5: 학생 + ‘대학생 제외’ → ineligible
    show(
        "CASE 5: 학생 + ‘대학생 제외’",
        {**base, "addAplyQlfcCndCn": "대학생 제외 대상", "ptcpPrpTrgtCn": None},
        {"age": 22, "employment": "student"},
    )

    # CASE 6: 취업 정보 없음 + ‘대학생 대상’ → needs_check
    show(
        "CASE 6: 취업 정보 없음 + ‘대학생 대상’",
        {**base, "addAplyQlfcCndCn": "대학생 대상 장학금", "ptcpPrpTrgtCn": None},
        {"age": 21, "employment": None},
    )

    # CASE 7: ‘취업 상태’라는 문구가 들어간 재직자 요구로 오인하는 사례
    show(
        "CASE 7: ‘취업 상태’ 문구가 들어간 재직자 요구 정책 (오판 재현)",
        {**base, "addAplyQlfcCndCn": "취업 상태인 청년 대상", "ptcpPrpTrgtCn": None},
        {"age": 30, "employment": None},
    )

    # CASE 8: ‘취업 상태가 아닌 사람’(미취업자 대상) → 미취업자는 OK
    show(
        "CASE 8: ‘취업 상태가 아닌 사람 대상’ + 미취업자",
        {**base, "addAplyQlfcCndCn": "취업 상태가 아닌 사람 대상", "ptcpPrpTrgtCn": None},
        {"age": 28, "employment": "unemployed"},
    )

    # CASE 9: ‘취업 상태가 아닌 사람’ + 재직자 → ineligible
    show(
        "CASE 9: ‘취업 상태가 아닌 사람 대상’ + 재직자",
        {**base, "addAplyQlfcCndCn": "취업 상태가 아닌 사람 대상", "ptcpPrpTrgtCn": None},
        {"age": 30, "employment": "employed"},
    )


if __name__ == "__main__":
    main()
