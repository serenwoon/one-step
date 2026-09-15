#!/usr/bin/env python3
"""고교 취업연계 장려금 — 미취업자에게 나오는 문제 재현 (RED)."""
import sys
sys.path.insert(0, '.')
import policy_fetch as pf

BASE = {"sprtTrgtMinAge": "17", "sprtTrgtMaxAge": "21", "sprtTrgtAgeLmtYn": "N"}

def check(label, cond_cn, ptcp_cn, info, expect_status):
    item = {**BASE, "addAplyQlfcCndCn": cond_cn, "ptcpPrpTrgtCn": ptcp_cn}
    r = pf.policy_qualification_check(item, info)
    ok = r["status"] == expect_status
    flag = "OK " if ok else "XX "
    print(f"{flag}{label}")
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
    print("=" * 92)
    print("고교 취업연계 장려금 — 미취업자에게 나오는 문제 (RED)")
    print("=" * 92)

    COND = '''아래 3가지 요건을 모두 충족한 자
(1) 기본요건 : 대한민국 국적자로 고교 취업연계 장려금을 신청한 자
(2) 학력요건 : 직업계고 3학년 및 일반고 3학년 中 직업교육 위탁과정 6개월(180일) 이상 참여 학생 (미졸업시 전액 반환)
(3) 재직요건 : 중소·중견 기업에 취업(재직)이 확인된 자로 근무시간이 주 15시간 이상인 자(고용보험 가입이력 정보로만 심사)
※ 1차 지급 시 3개월 재직 이력, 2차 지급 시 추가 9개월 간 재직이력 확인'''
    PTCP = '''학생이 취업한 기업이 아래에 해당할 경우 장려금을 지급할 수 없습니다.
기업 규모: 중소기업 및 중견기업이 아닌 대기업, 공공기관, 국가 및 지방자치단체, 공기업
제외 업종: 부적격 업종(유흥, 사행성 업종, 무점포 소매업, 다단계 판매 등)
특수 관계: 기업의 대표자가 학생의 부모인 경우'''

    # 핵심 문제: 미취업 비재학자에게 이 정책이 나오면 안 됨 → ineligible
    results.append(check(
        "미취업 비재학 + 고교 취업연계 장려금 (원래 문제)",
        COND, PTCP,
        {"age": 27, "employment": "unemployed", "student": False},
        "ineligible",
    ))

    # 재직자 비학생: 재직요건 충족, 학생요건 미충족 → needs_check (학생 조건 확인 필요)
    results.append(check(
        "재직자 비학생 + 고교 취업연계 장려금",
        COND, PTCP,
        {"age": 27, "employment": "employed", "student": False},
        "needs_check",
    ))

    # 재직자 학생: 재직요건이 확인된 자 → 고용 충족, 학생요건 확인됨.
    # 다만 국적 요건·기업 규모·제외업종 등 미확인 조건이 남아 needs_check로 유지.
    results.append(check(
        "재직자 학생 + 고교 취업연계 장려금",
        COND, PTCP,
        {"age": 19, "employment": "employed", "student": True},
        "needs_check",
    ))

    # 취업(재직) 확인만 있는 단순 케이스 — 미취업자는 ineligible
    results.append(check(
        "취업(재직)이 확인된 자 + 미취업",
        "중소·중견 기업에 취업(재직)이 확인된 자로 근무시간이 주 15시간 이상인 자",
        None,
        {"age": 27, "employment": "unemployed", "student": False},
        "ineligible",
    ))

    # 취업(재직) 확인만 있는 단순 케이스 — 재직자는 ok
    results.append(check(
        "취업(재직)이 확인된 자 + 재직자",
        "중소·중견 기업에 취업(재직)이 확인된 자로 근무시간이 주 15시간 이상인 자",
        None,
        {"age": 27, "employment": "employed", "student": False},
        "ok",
    ))

    print("=" * 92)
    passed = sum(results)
    total = len(results)
    print(f"통과: {passed} / {total}")
    print("=" * 92)
    return 0 if all(results) else 1

if __name__ == "__main__":
    sys.exit(main())
