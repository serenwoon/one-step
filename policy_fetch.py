#!/usr/bin/env python3
"""
다시, 한 걸음(one-step) — 정책 API 조회용 연결 코드
프로젝트 .env를 읽어서 실제 정책 데이터를 조회한다.
키 값과 키가 붙은 요청 주소는 출력하지 않는다.
"""
import os
import sys
import json
import re
import time
import urllib.request
import urllib.parse
import urllib.error

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

# 온통청년 공식 지역 코드 목록. 광역 검색을 하위 시·군·구까지 확장한다.
with open(os.path.join(os.path.dirname(__file__), 'region_codes.json'), encoding='utf-8') as f:
    REGION_DATA = json.load(f)


def expand_region_codes(codes):
    """광역 선택은 하위 지역 전체. 기초 지역 선택은 상위 광역까지 조회한다."""
    expanded = set()
    for code in codes or []:
        expanded.add(code)
        expanded.add(code[:2] + '000')
        expanded.update(REGION_DATA['provinces'].get(code, []))
        expanded.update(REGION_DATA.get('cities', {}).get(code, []))
        for city, children in REGION_DATA.get('cities', {}).items():
            if code in children or any(child in expanded for child in children):
                expanded.add(city)
        # 일반구가 있는 시를 선택한 경우 해당 시의 구도 포함한다.
        name = REGION_DATA['names'].get(code, '')
        if name.endswith('시') and code not in REGION_DATA['provinces']:
            expanded.update(k for k, v in REGION_DATA['names'].items() if v.startswith(name + ' '))
    return sorted(expanded)


def policy_region_scope(item):
    """거주 대상 코드로 전국·광역·기초 범위를 표시한다. 주관기관으로 추측하지 않는다."""
    codes = set(_parse_region_codes(item.get('regionCodes')) or [])
    provinces = REGION_DATA['provinces']
    districts = {code for values in provinces.values() for code in values}
    if districts <= codes or set(provinces) <= codes:
        return {'level': '전국 공통', 'label': '전국 공통'}
    if not codes:
        return {'level': '지역 확인 필요', 'label': '대상 지역 확인 필요'}
    names = REGION_DATA['names']
    labels = []
    remaining = set(codes)
    for province, children in provinces.items():
        if province in codes or (children and set(children) <= codes):
            labels.append(names[province] + ' 전체')
            remaining.difference_update(children)
            remaining.discard(province)
    labels.extend(names.get(code, code + ' (지역명 확인 필요)') for code in sorted(remaining))
    return {'level': '광역' if not remaining else '시·군·구',
            'label': ' · '.join(labels), 'codes': sorted(codes)}


PURPOSES = {
    '주거': ('월세', '주거', '전세', '보증금', '임대', '주택'),
    '취업': ('취업', '구직', '일자리', '면접', '직업', '다시 일'),
    '교육': ('교육', '훈련', '자격증', '학비', '장학', '등록금'),
    '창업': ('창업', '사업 시작', '스타트업'),
    '생활': ('생활비', '생계', '식비', '긴급 지원'),
    '마음건강': ('마음', '심리', '우울', '불안'),
}


ON_URL = "https://www.youthcenter.go.kr/go/ythip/getPlcy"
GOV24_BASE_URL = "https://api.odcloud.kr/api"


def load_env(path):
    env = {}
    if not os.path.exists(path):
        return env
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip()
                # 키 값에 둘러진 따옴표가 있으면 제거한다.
                if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
                    v = v[1:-1]
                env[k] = v
    return env


def load_api_keys():
    """정책 API 키를 환경변수 우선으로 읽고, 없으면 같은 폴더의 .env를 보조로 읽는다.

    서버에서는 .env 파일이 없어도 환경변수만으로 설정이 가능해야 한다.
    실제 키 값은 여기서 출력하거나 다른 파일에 복사하지 않는다.
    """
    env_on = os.environ.get("ON_YOUTH_API_KEY", "").strip()
    env_gov = os.environ.get("GOV24_API_KEY", "").strip()

    # 환경변수 값에 둘러진 따옴표가 있으면 제거한다.
    if len(env_on) >= 2 and env_on[0] == env_on[-1] and env_on[0] in ('"', "'"):
        env_on = env_on[1:-1]
    if len(env_gov) >= 2 and env_gov[0] == env_gov[-1] and env_gov[0] in ('"', "'"):
        env_gov = env_gov[1:-1]

    out = {}
    if env_on:
        out["ON_YOUTH_API_KEY"] = env_on
    if env_gov:
        out["GOV24_API_KEY"] = env_gov

    if not out.get("ON_YOUTH_API_KEY") or not out.get("GOV24_API_KEY"):
        file_env = load_env(ENV_PATH)
        f_on = file_env.get("ON_YOUTH_API_KEY", "").strip()
        f_gov = file_env.get("GOV24_API_KEY", "").strip()
        if not out.get("ON_YOUTH_API_KEY") and f_on:
            out["ON_YOUTH_API_KEY"] = f_on
        if not out.get("GOV24_API_KEY") and f_gov:
            out["GOV24_API_KEY"] = f_gov

    return out


def require(key, env=None):
    if env is None:
        env = load_api_keys()
    v = env.get(key, "").strip()
    if not v:
        sys.exit(f"환경변수 {key}가 비어 있습니다")
    return v


def require_api_key(key):
    env = load_api_keys()
    v = env.get(key, "").strip()
    if not v:
        sys.exit(f"환경변수 {key}가 비어 있습니다")
    return v

def fetch(url, params, headers=None, timeout=60):
    qs = urllib.parse.urlencode(params, safe="")
    full = url + "?" + qs
    req = urllib.request.Request(
        full,
        headers={"User-Agent": "one-step-policy-fetch/0.1", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return e.code, body
    except Exception as e:
        return None, str(e)

def on_youth_fetch(api_key):
    params = {
        "apiKeyNm": api_key,
        "rtnType": "json",
        "pageNum": "1",
        "pageSize": "1",
        "pageType": "1",
    }
    return fetch(ON_URL, params)

def on_youth_search(api_key, keyword, page_size=3, page_num=1, region_codes=None, deadline=None):
    """
    온통청년 정책명에서 검색어로 한 페이지 조회한다.
    region_codes: 법정시군구코드 5자리 목록 (예: ["11440"] - 서울 마포구).
                  지정 시 해당 지역 코드만 조회한다. 미지정 시 전국 대상.
    지역 제한과 신청 자격 판정은 하지 않는다.
    공식 문서: https://www.youthcenter.go.kr/cmnFooter/openapiIntro/oaiDoc
    """
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("온통청년 API 키가 비어 있습니다")
    if not isinstance(keyword, str) or not keyword.strip():
        raise ValueError("검색어를 입력해 주세요")
    if type(page_size) is not int or not 1 <= page_size <= 100:
        raise ValueError("page_size는 1부터 100까지의 정수여야 합니다")
    if type(page_num) is not int or page_num < 1:
        raise ValueError("page_num은 1 이상의 정수여야 합니다")
    if region_codes is not None:
        if not isinstance(region_codes, (list, tuple)):
            raise ValueError("region_codes는 코드 목록이어야 합니다")
        for rc in region_codes:
            if not isinstance(rc, str) or not rc.strip() or len(rc.strip()) != 5:
                raise ValueError("region_codes는 5자리 법정시군구코드 문자열 목록이어야 합니다")
    keyword = keyword.strip()
    params = {
        "apiKeyNm": api_key.strip(),
        "rtnType": "json",
        "pageNum": str(page_num),
        "pageSize": str(page_size),
        "pageType": "1",
        "plcyNm": keyword,
    }
    if region_codes:
        params["zipCd"] = ",".join(expand_region_codes([rc.strip() for rc in region_codes]))
    if deadline is not None and deadline <= time.monotonic():
        return {'status': 'error', 'keyword': keyword, 'reason': '정책 조회 시간이 초과됐습니다.'}
    options = {'timeout': min(8, max(0.1, deadline - time.monotonic()))} if deadline is not None else {}
    code, body = fetch(ON_URL, params, **options)
    return on_youth_search_result(code, body, keyword, page_size, page_num, region_codes)


def on_youth_search_result(code, body, keyword, page_size=3, page_num=1, region_codes=None):
    """
    검색 결과에서 상태와 건수와 정책 정보를 정리한다.
    키가 포함될 수 있는 오류 원문과 요청 주소는 반환하지 않는다.
    region_codes가 지정됐으면 해당 지역 코드만 결과에 포함했는지 표시한다.
    """
    result = {
        "status": "error", "httpStatus": code, "apiResultCode": None,
        "source": "온통청년", "sourceUrl": ON_URL,
        "keyword": keyword, "searchParameter": "plcyNm",
        "regionFilterApplied": bool(region_codes),
        "regionCodes": [rc.strip() for rc in region_codes] if region_codes else None,
        "pageNum": page_num, "pageSize": page_size,
        "fetchedCount": 0, "totalCount": None,
        "allMatchingResultsFetched": None,
        "results": [],
        "note": "정책명으로 검색한 한 페이지입니다. 전체 정책 조회나 신청 자격 판정이 아닙니다.",
    }

    def fail(reason):
        result["reason"] = reason
        return result

    if code is None:
        return fail("정책 API에 연결하지 못했습니다")
    if not isinstance(code, int) or not 200 <= code < 300:
        return fail("정책 API가 HTTP 오류를 반환했습니다")
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return fail("정책 API 응답이 JSON 형식이 아닙니다")
    if not isinstance(data, dict):
        return fail("정책 API 응답 구조가 올바르지 않습니다")
    api_code = data.get("resultCode")
    # API 오류 메시지 원문 대신 결과 코드만 확인한다.
    if isinstance(api_code, (str, int)) and not isinstance(api_code, bool):
        if str(api_code).isdigit() and len(str(api_code)) <= 6:
            result["apiResultCode"] = api_code
    if str(api_code) != "200":
        return fail("정책 API 결과 코드가 성공이 아니거나 누락됐습니다")
    payload = data.get("result")
    if not isinstance(payload, dict):
        return fail("정책 API 결과가 누락됐습니다")
    items = payload.get("youthPolicyList")
    if not isinstance(items, list) or any(not isinstance(x, dict) for x in items):
        return fail("정책 목록 형식이 올바르지 않습니다")
    pagination = payload.get("pagging")
    if isinstance(pagination, dict):
        total = pagination.get("totCount")
        if type(total) is int and total >= 0:
            result["totalCount"] = total
        elif isinstance(total, str) and total.isdecimal():
            result["totalCount"] = int(total)
    result["status"] = "ok"
    result["fetchedCount"] = len(items)
    if result["totalCount"] is not None:
        result["allMatchingResultsFetched"] = (
            page_num == 1 and len(items) == result["totalCount"]
        )
    for item in items:
        result["results"].append({
            "policyName": item.get("plcyNm"),
            "policyNo": item.get("plcyNo"),
            "regionCodes": item.get("zipCd") or None,
            "regionName": None,  # 지역 코드에 해당하는 이름은 확인 전이다.
            "supportContent": item.get("plcySprtCn"),
            "applyUrl": item.get("aplyUrlAddr"),
            "orgName": item.get("sprvsnInstCdNm"),
            "source": "온통청년",
            "sourceUrl": ON_URL,
            # 조건 원문 보존: 코드 뜻은 확인 전까지 해석하지 않는다.
            "sprtTrgtMinAge": item.get("sprtTrgtMinAge"),
            "sprtTrgtMaxAge": item.get("sprtTrgtMaxAge"),
            "sprtTrgtAgeLmtYn": item.get("sprtTrgtAgeLmtYn"),
            "bizPrdBgngYmd": item.get("bizPrdBgngYmd"),
            "bizPrdEndYmd": item.get("bizPrdEndYmd"),
            "aplyPrdSeCd": item.get("aplyPrdSeCd"),
            "bizPrdSeCd": item.get("bizPrdSeCd"),
            "aplyYmd": item.get("aplyYmd"),
            "plcyAplyMthdCn": item.get("plcyAplyMthdCn"),
            "addAplyQlfcCndCn": item.get("addAplyQlfcCndCn"),
            "ptcpPrpTrgtCn": item.get("ptcpPrpTrgtCn"),
        })
    return result

def gov24_result(code, body):
    if code is None:
        return {"status": "error", "reason": "요청 수행 중 예외 발생"}
    try:
        data = json.loads(body)
    except Exception:
        return {"status": "error", "reason": "응답 형식 오류 (JSON 파싱 불가)"}
    if not isinstance(data, dict):
        return {"status": "error", "reason": "응답 형식 오류 (최상위 형식 불일치)"}
    data_list = data.get("data")
    if not isinstance(data_list, list) or not data_list:
        return {"status": "error", "reason": "서비스 목록 없음"}
    first = data_list[0]
    return {
        "status": "ok",
        "serviceName": first.get("서비스명"),
        "serviceId": first.get("서비스ID"),
        "supportType": first.get("지원유형"),
        "target": first.get("지원대상"),
        "applyMethod": first.get("신청방법"),
        "orgName": first.get("소관기관명"),
    }

def on_result(body, code):
    if code is None:
        return {"status": "error", "reason": "요청 수행 중 예외 발생"}
    try:
        data = json.loads(body)
    except Exception:
        return {"status": "error", "reason": "응답 형식 오류 (JSON 파싱 불가)"}
    if not isinstance(data, dict):
        return {"status": "error", "reason": "응답 형식 오류 (최상위 형식 불일치)"}
    if "result" not in data or not isinstance(data["result"], dict):
        return {"status": "error", "reason": "응답 구조 이상 (result 없음)"}
    res = data["result"]
    ylist = res.get("youthPolicyList")
    if not isinstance(ylist, list) or not ylist:
        return {"status": "error", "reason": "정책 목록 없음"}
    first = ylist[0]
    return {
        "status": "ok",
        "policyName": first.get("plcyNm"),
        "policyNo": first.get("plcyNo"),
        "supportContent": first.get("plcySprtCn"),
        "applyUrl": first.get("aplyUrlAddr"),
        "orgName": first.get("sprvsnInstCdNm"),
    }

def summarize_on(body, code):
    print("HTTP 상태:", code)
    if code is None:
        print("실패 원인: 요청 수행 중 예외 발생")
        return
    try:
        data = json.loads(body)
    except Exception:
        print("실패 원인: 응답 형식 오류 (JSON 파싱 불가)")
        return
    if not isinstance(data, dict):
        print("실패 원인: 응답 형식 오류 (최상위 형식 불일치)")
        return
    if "result" not in data or not isinstance(data["result"], dict):
        print("실패 원인: 응답 구조 이상 (result 없음)")
        return
    res = data["result"]
    ylist = res.get("youthPolicyList")
    if not isinstance(ylist, list) or not ylist:
        print("실패 원인: 정책 목록 없음")
        return
    first = ylist[0]
    print("정책 이름:", first.get("plcyNm"))
    print("정책번호:", first.get("plcyNo"))

def summarize_gov24(body, code):
    print("HTTP 상태:", code)
    if code is None:
        print("실패 원인: 요청 수행 중 예외 발생")
        return
    try:
        data = json.loads(body)
    except Exception:
        print("실패 원인: 응답 형식 오류 (JSON 파싱 불가)")
        return
    if not isinstance(data, dict):
        print("실패 원인: 응답 형식 오류 (최상위 형식 불일치)")
        return
    data_list = data.get("data")
    if not isinstance(data_list, list) or not data_list:
        print("실패 원인: 서비스 목록 없음")
        return
    first = data_list[0]
    print("서비스 이름:", first.get("서비스명"))

def gov24_fetch(service_key):
    use_key = service_key
    if "%" in use_key:
        use_key = urllib.parse.unquote(use_key)
    params = {
        "serviceKey": use_key,
        "page": "1",
        "perPage": "1",
        "returnType": "JSON",
    }
    return fetch(
        GOV24_BASE_URL + "/gov24/v3/serviceList",
        params,
    )


def _items_match_region(item, region_codes):
    """item의 regionCodes가 region_codes 중 하나와 일치하는지 확인."""
    item_regions = item.get("regionCodes")
    if not item_regions:
        return None  # 지역 정보 없음 → 판단 보류
    if isinstance(item_regions, str):
        item_regions = [item_regions]
    if not isinstance(item_regions, list):
        return None
    target_set = {str(rc).strip() for rc in region_codes}
    item_set = {str(ir).strip() for ir in item_regions if ir}
    return bool(target_set & item_set)


def _classify_by_region(results, region_codes):
    """
    검색 결과를 지역 기준으로 분류한다.
    - matched: region_codes 중 하나와 일치하는 결과
    - unmatched: 지역이 명시됐고 region_codes와 일치하지 않는 결과
    - unknown: 지역 정보가 없는 결과
    """
    matched = []
    unmatched = []
    unknown = []
    for item in results:
        match = _items_match_region(item, region_codes)
        if match is True:
            matched.append(item)
        elif match is False:
            unmatched.append(item)
        else:
            unknown.append(item)
    return matched, unmatched, unknown


def on_youth_search_multi(api_key, keyword, region_codes=None, max_pages=3, page_size=10,
                          preferred=None, extra_pages=0, extension_deadline=None, deadline=None):
    """
    온통청년에서 검색어로 여러 페이지를 조회해 결과를 합친다.
    region_codes가 지정되면 해당 지역 코드만 필터링한다.
    max_pages: 최대 조회할 페이지 수 (기본 3).
    page_size: 페이지당 건수 (기본 10, 최대 100).
    """
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("온통청년 API 키가 비어 있습니다")
    if not isinstance(keyword, str) or not keyword.strip():
        raise ValueError("검색어를 입력해 주세요")
    if type(max_pages) is not int or max_pages < 1:
        raise ValueError("max_pages는 1 이상의 정수여야 합니다")
    if type(page_size) is not int or not 1 <= page_size <= 100:
        raise ValueError("page_size는 1부터 100까지의 정수여야 합니다")

    if type(extra_pages) is not int or not 0 <= extra_pages <= 3:
        raise ValueError("추가 조회는 0부터 3페이지까지 가능합니다")

    all_results = []
    total_count = None
    all_fetched = False
    pages_fetched = 0
    page_errors = []

    # 기본 조회 뒤에도 원하는 후보가 없으면 다음 페이지부터 이어서 찾는다.
    for page_num in range(1, max_pages + extra_pages + 1):
        if deadline is not None and time.monotonic() >= deadline:
            page_errors.append({'page': page_num, 'reason': '정책 조회 시간이 초과됐습니다.'})
            break
        if page_num > max_pages:
            if preferred is None or any(preferred(item) for item in all_results):
                break
            if extension_deadline is not None and time.monotonic() >= extension_deadline:
                break
        single = on_youth_search(
            api_key, keyword,
            page_size=page_size, page_num=page_num, region_codes=region_codes,
            **({'deadline': deadline} if deadline is not None else {}),
        )
        if single.get("status") != "ok":
            if page_num == 1:
                return single
            page_errors.append({"page": page_num, "reason": single.get("reason", "정책 조회 실패")})
            break
        pages_fetched += 1
        all_results.extend(single.get("results", []))
        if total_count is None:
            total_count = single.get("totalCount")
        if single.get("allMatchingResultsFetched"):
            all_fetched = True
            break
        if total_count is not None and len(all_results) >= total_count:
            all_fetched = True
            break
        if not single.get("results"):
            all_fetched = total_count is None or len(all_results) >= total_count
            break

    merged = {
        "status": "ok",
        "httpStatus": 200,
        "apiResultCode": None,
        "source": "온통청년",
        "sourceUrl": ON_URL,
        "keyword": keyword,
        "searchParameter": "plcyNm",
        "regionFilterApplied": bool(region_codes),
        "regionCodes": [rc.strip() for rc in region_codes] if region_codes else None,
        "pageNum": pages_fetched,
        "pageSize": page_size,
        "fetchedCount": len(all_results),
        "totalCount": total_count,
        "allMatchingResultsFetched": all_fetched,
        "results": all_results,
        "pagesFetched": pages_fetched,
        "pageErrors": page_errors,
        "note": f"정책명 '{keyword}'로 최대 {max_pages}페이지 조회한 결과입니다. 전체 정책 조회나 신청 자격 판정이 아닙니다.",
    }
    return merged


def summarize_on_filtered(results, region_codes=None):
    """
    조회 결과를 지역 기준으로 요약한다.
    region_codes가 있으면 matched/unmatched/unknown으로 구분한다.
    """
    print(f"총 조회 건수: {results.get('fetchedCount')}")
    print(f"전체 결과 수(API): {results.get('totalCount')}")
    print(f"지역 필터 적용: {results.get('regionFilterApplied')}")
    if region_codes:
        print(f"대상 지역 코드: {region_codes}")

    matched, unmatched, unknown = _classify_by_region(results.get("results", []), region_codes)

    print(f"\n- 지역 일치(matched): {len(matched)}건")
    for item in matched:
        print(f"  \u00b7 {item.get('policyName')} ({item.get('orgName')})")

    print(f"\n- 지역 불일치(unmatched): {len(unmatched)}건")
    for item in unmatched[:5]:
        print(f"  \u00b7 {item.get('policyName')} ({item.get('orgName')})")
    if len(unmatched) > 5:
        print(f"  ... 외 {len(unmatched) - 5}건")

    print(f"\n- 지역 정보 없음(unknown): {len(unknown)}건")
    for item in unknown[:3]:
        print(f"  \u00b7 {item.get('policyName')} ({item.get('orgName')})")
    if len(unknown) > 3:
        print(f"  ... 외 {len(unknown) - 3}건")


def _region_codes_to_prefix_set(region_codes):
    """region_codes에서 각 코드의 광역 접두어(앞 2자리+000)를 추출."""
    prefix_set = set()
    for rc in region_codes:
        rc = str(rc).strip()
        if len(rc) == 5 and rc[:2].isdigit():
            prefix_set.add(rc[:2] + "000")
    return prefix_set


def _parse_region_codes(value):
    """쉼표 구분 문자열과 배열을 정규화한다. 해석 불가 값은 판단을 보류한다."""
    if value is None or value == "":
        return None
    parts = value.split(",") if isinstance(value, str) else value
    if not isinstance(parts, list):
        return None
    codes = []
    for part in parts:
        if not isinstance(part, str):
            return None
        code = part.strip()
        if len(code) != 5 or not code.isascii() or not code.isdigit():
            return None
        if code not in codes:
            codes.append(code)
    return codes or None


def _classify_single_item(item, region_codes):
    """
    단일 정책의 지역 분류 결과와 이유를 반환.
    반환: (classification, reason)
    - ("matched", 이유)
    - ("unmatched", 이유)
    - ("region_unknown", 이유)
    """
    item_regions = _parse_region_codes(item.get("regionCodes"))
    targets = _parse_region_codes(region_codes)
    if not item_regions or not targets:
        return "region_unknown", "지역 코드가 없거나 형식을 확인할 수 없어 판단을 보류합니다."
    item_set = set(item_regions)
    target_set = set(targets)

    if policy_region_scope(item)['level'] == '전국 공통':
        return "matched", "공식 지역 코드 목록 전체를 포함하는 전국 공통 정책입니다."

    # 광역을 선택하면 그 지역의 시·군·구 제한 정책도 탐색 후보에 포함한다.
    broad = {code for code in targets if code in REGION_DATA['provinces'] or code in REGION_DATA.get('cities', {})}
    broad_codes = set(expand_region_codes(sorted(broad)))
    if item_set & broad_codes:
        return "matched", "선택한 광역 지역 안의 정책입니다. 시·군·구별 거주 조건은 별도 확인해야 합니다."

    # 일반구 거주자는 상위 시 전체 정책도 함께 받는다.
    if item_set & set(expand_region_codes(targets)):
        return "matched", "선택 지역 또는 상위 시·도 전체 정책입니다."

    # 직접 일치
    if item_set & target_set:
        matched_codes = list(item_set & target_set)
        return "matched", f"정책에 명시된 지역 코드 {matched_codes}가 대상 지역 코드 {sorted(target_set)}에 포함됩니다."

    # 광역 코드 포함 관계 확인
    prefixes = _region_codes_to_prefix_set(region_codes)
    if item_set & prefixes:
        matched_prefixes = list(item_set & prefixes)
        return "matched", f"정책에 명시된 지역 코드 {sorted(item_set)}가 대상 지역의 광역 코드 {sorted(matched_prefixes)}에 포함됩니다. (예: 서울특별시 전체 정책)"

    # 다른 지역
    return "unmatched", f"정책에 명시된 지역 코드 {sorted(item_set)}가 대상 지역 코드 {sorted(target_set)}와 일치하지 않습니다. (다른 지역 정책)"


def normalize_profile(value):
    if not isinstance(value, dict):
        return {}

    result = {}

    if 'age' in value:
        age = value['age']
        if isinstance(age, str) and age.strip().isdigit():
            age = int(age.strip())
        result['age'] = age if type(age) is int and 0 <= age <= 120 else None

    if 'employment' in value:
        emp = value['employment']
        result['employment'] = emp if emp in ('employed', 'unemployed') else None
        if emp == 'student':
            result['student'] = True
    if 'student' in value:
        result['student'] = value['student'] if type(value['student']) is bool else None

    if 'purpose' in value:
        purpose = value['purpose']
        result['purpose'] = purpose if isinstance(purpose, str) and purpose in PURPOSES else None

    if 'region_codes' in value:
        codes = value['region_codes']
        if isinstance(codes, list) and len(codes) <= 5:
            valid = all(isinstance(code, str) and re.fullmatch(r'[0-9]{5}', code) for code in codes)
            if valid:
                result['region_codes'] = codes
    return result


def policy_qualification_check(item, user_info):
    """확인 가능한 조건만 비교한다. ok도 최종 자격 확정은 아니다."""
    user = normalize_profile(user_info)
    failed = []
    unknown = []
    matched = []
    target = re.search(r'(?:지원|신청|공모)\s*대상\s*[:：]?\s*(.*?)(?=\n\s*\n|□|$)',
                       str(item.get('supportContent') or ''), re.S)
    if target:
        value = target[1].strip()
        if (re.search(r'(?:전문대학|대학교|지방자치단체|공공기관|운영기관|사업단)\s*(?:등)?\s*$', value)
                and not re.search(r'학생|청년|개인|주민|근로자|구직자', value)):
            failed.append('신청 대상이 대학·기관인 사업으로 개인 대상 추천에서 제외해요.')
    age = user.get('age')
    text = '\n'.join(str(item.get(k) or '') for k in ('addAplyQlfcCndCn', 'ptcpPrpTrgtCn'))
    exception_pattern = r'예외|다만|(?:^|[.\n])\s*단\b|연령\s*연장|나이\s*연장'
    exception = bool(re.search(exception_pattern, text))

    bounds = []
    for key in ('sprtTrgtMinAge', 'sprtTrgtMaxAge'):
        raw = str(item.get(key) if item.get(key) is not None else '').strip()
        bounds.append(int(raw) if raw.isdigit() and 0 <= int(raw) <= 120 else None)
    low, high = bounds
    flag = str(item.get('sprtTrgtAgeLmtYn') or '').strip().upper()
    if flag != 'N' and bounds != [0, 0] and (flag == 'Y' or any(v is not None for v in bounds)):
        if all(v is None for v in bounds) or (low is not None and high is not None and low > high):
            unknown.append('정책 연령 조건 원문 확인이 필요해요.')
        elif age is None:
            unknown.append('만 나이를 확인해야 해요.')
        elif (low is not None and age < low) or (high is not None and age > high):
            if exception:
                unknown.append('연령 범위와 다르지만 예외 적용 여부를 공고에서 확인해야 해요.')
            else:
                low_label = low if low is not None else '하한 없음'
                high_label = high if high is not None else '상한 없음'
                failed.append(f'만 {age}세는 정책 연령 범위({low_label}~{high_label})와 맞지 않아요.')
        else:
            matched.append(f'만 {age}세는 안내된 연령 범위에 들어요.')

    group_pattern = (
        r'미취업(?:자|\s*청년|\s*상태)?|취업\s*준비생|구직자|실업자|'
        r'취업\s*상태가\s*아닌\s*사람|취업\s*상태인\s*사람|(?<!미)취업자|'
        r'재직자|재직\s*중인\s*사람|근로자|직장인|대학\(원\)생|대학원생|'
        r'대학생|재학생|고등학생|중학생|초등학생|학생|'
        r'취업\s*\(?재직\)?\s*이\s*확인된\s*자|재직이\s*확인된\s*자|취업이\s*확인된\s*자|'
        r'참여\s*학생|졸업자|수료자|이수자'
    )
    rules = {'employment': [], 'student': []}
    for clause in re.split(r'[.。;\n,]|(?:이며|이고|지만)\s*', text):
        clause = clause.strip()
        if not clause:
            continue
        groups = list(re.finditer(group_pattern, clause))
        if not groups:
            if not re.search(r'없음|없습니다|무관|관계없|제한\s*없|별도.*명시하지|우대|가점', clause):
                unknown.append('추가 신청 조건은 공식 공고에서 확인해야 해요.')
            continue
        # 복합 조건과 예외는 확인 필요로 남긴다.
        complex_pattern = r'또는|혹은|예외|단,|다만|제외하지|제외\s*아|대상(?:이|은)?\s*아|않|아니면'
        if re.search(complex_pattern, clause) or len(groups) > 1:
            if not re.search(r'무관|관계없|모두\s*(?:가능|대상)', clause):
                unknown.append('복합 대상·예외 조건은 공고 확인이 필요해요.')
            continue
        group = groups[0]
        word = group.group()
        suffix = clause[group.end():].strip()
        if re.search(r'참여\s*학생|졸업자|수료자|이수자', word):
            axis = 'history'
            value = True
        elif re.search(r'학생|재학생|대학.*생', word):
            axis = 'student'
            value = True
        else:
            axis = 'employment'
            value = 'unemployed' if re.search(r'미취업|준비|구직|실업|아닌', word) else 'employed'
        # 우대는 필수 자격이 아니다.
        if re.search(r'무관|관계없|우대|가점|우선', suffix):
            continue
        if axis == 'history':
            unknown.append('과거 참여·학력 조건 확인이 필요해요.')
            continue
        if axis == 'student' and (
            re.match(r'이\s*취업한\s*(?:기업|회사|사업장)', suffix) or
            re.search(r'(?:기업|회사).*대표자.*학생.*부모', clause)
        ):
            unknown.append('기업·업종·특수 관계 조건은 공고 확인이 필요해요.')
            continue
        exclude = bool(re.match(r'(?:을|를|은|는)?\s*(?:제외|불가|아닌|이\s*아닌)', suffix))
        base_required = bool(re.search(
            r'대상|한함|한정|이어야|에게만|지원|지급|신청\s*가능|위한|^만(?:\s|$)',
            suffix,
        ))
        if re.search(r'지급\s*할\s*수\s*없|지급\s*하지\s*않|수\s*없|불가', suffix) and re.search(r'지급', suffix):
            base_required = False
        word_required = bool(re.search(r'확인된\s*자|확인된\s*사람', word))
        required = base_required or word_required
        if not exclude and not required:
            unknown.append(f'{word} 관련 조건의 정확한 대상 여부를 확인해야 해요.')
            continue
        rules[axis].append((value, exclude))

    for axis, conditions in rules.items():
        requirements = {value for value, excluded in conditions if not excluded}
        exclusions = {value for value, excluded in conditions if excluded}
        label = '취업 상태' if axis == 'employment' else '재학 여부'
        if len(requirements) > 1 or requirements & exclusions:
            unknown.append(f'{label} 조건이 서로 달라 원문 확인이 필요해요.')
        elif conditions:
            actual = user.get(axis)
            if actual is None:
                unknown.append(f'{label}를 확인해야 해요.')
            elif any((actual == value) if excluded else (actual != value) for value, excluded in conditions):
                if exception:
                    unknown.append(f'{label} 조건의 예외 적용 여부를 확인해야 해요.')
                else:
                    failed.append(f'알려준 {label}가 정책의 필수·제외 조건과 맞지 않아요.')
            else:
                matched.append(f'알려준 {label}가 확인 가능한 조건과 맞아요.')

    if failed:
        status = 'ineligible'
    elif unknown:
        status = 'needs_check'
    else:
        status = 'ok'
    return {
        'status': status,
        'ineligibleReasons': list(dict.fromkeys(failed)),
        'needsCheckReasons': list(dict.fromkeys(unknown)),
        'matchedReasons': list(dict.fromkeys(matched)),
    }


def _dedup_by_policy_no(results):
    """정책번호가 있는 중복만 제거한다. 번호 없는 후보와 원래 순서는 유지한다."""
    seen = set()
    output = []
    for item in results:
        no = item.get("policyNo")
        if isinstance(no, (str, int)) and not isinstance(no, bool):
            no = str(no).strip()
        else:
            no = ""
        if no:
            if no in seen:
                continue
            seen.add(no)
        output.append(dict(item))
    return output


def on_youth_search_classified(api_key, keyword, region_codes=None, max_pages=3, page_size=10,
                               preferred=None, extra_pages=0, deadline=None):
    """
    온통청년에서 keyword로 전국 조회 + region_codes 필터링 조회를 수행하고,
    결과를 지역 기준으로 분류하여 반환한다.

    - region_codes가 없으면: 전국 조회만 수행, 모든 결과는 region_unknown 처리 (지역 정보 있는 것만 지역별 분류)
    - region_codes가 있으면:
        1) 무필터(전국) 조회 → region_codes 기준으로 분류 (matched/unmatched/region_unknown)
        2) 필터 조회 → 필터에서 추가된 matched 항목을 filter_only_matched로 표시
    """
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("온통청년 API 키가 비어 있습니다")
    if not isinstance(keyword, str) or not keyword.strip():
        raise ValueError("검색어를 입력해 주세요")
    if type(max_pages) is not int or max_pages < 1:
        raise ValueError("max_pages는 1 이상의 정수여야 합니다")
    if type(page_size) is not int or not 1 <= page_size <= 100:
        raise ValueError("page_size는 1부터 100까지의 정수여야 합니다")

    # 추가 조회는 두 경로가 같은 시간 한도를 사용한다.
    extension_deadline = time.monotonic() + 25
    extension = ({"preferred": preferred, "extra_pages": extra_pages,
                  "extension_deadline": extension_deadline} if preferred else {})

    if deadline is not None:
        extension['deadline'] = deadline

    # 1) 무필터(전국) 조회
    nationwide = on_youth_search_multi(
        api_key, keyword,
        region_codes=None,
        max_pages=max_pages,
        page_size=page_size,
        **extension,
    )

    if nationwide.get("status") != "ok":
        return nationwide

    # 2) region_codes가 있으면 필터링 조회도 수행
    filtered = None
    filter_error = None
    if region_codes:
        filtered = on_youth_search_multi(
            api_key, keyword,
            region_codes=region_codes,
            max_pages=max_pages,
            page_size=page_size,
            **extension,
        )
        if filtered.get("status") != "ok":
            filter_error = filtered.get("reason", "필터링 조회에서 오류가 발생했습니다.")

    # 조회 결과를 먼저 합쳐 중복 제거한 뒤 한 번만 분류한다.
    all_items = nationwide.get("results", [])
    additional = filtered.get("results", []) if filtered and filtered.get("status") == "ok" else []
    deduped = _dedup_by_policy_no(all_items + additional)
    original_nos = {str(item.get("policyNo")).strip() for item in all_items if item.get("policyNo")}
    matched = []
    unmatched = []
    region_unknown = []
    filter_only_matched = []
    for item in deduped:
        classification, reason = _classify_single_item(item, region_codes)
        item["classification"] = classification
        item["classificationReason"] = reason
        no = item.get("policyNo")
        if classification == "matched":
            if no and str(no).strip() not in original_nos:
                filter_only_matched.append(item)
            else:
                matched.append(item)
        elif classification == "unmatched":
            unmatched.append(item)
        else:
            region_unknown.append(item)

    # 실제 실패한 페이지의 정보만 표시한다. 빈 페이지는 오류가 아니다.
    page_errors = [{**error, "query": "nationwide"} for error in nationwide.get("pageErrors", [])]
    pages_fetched = nationwide.get("pagesFetched", 0)
    if filtered:
        page_errors.extend({**error, "query": "filtered"} for error in filtered.get("pageErrors", []))
    if filter_error:
        page_errors.append({"page": 1, "query": "filtered", "reason": filter_error})

    return {
        "status": "ok",
        "httpStatus": 200,
        "apiResultCode": None,
        "source": "온통청년",
        "sourceUrl": ON_URL,
        "keyword": keyword,
        "searchParameter": "plcyNm",
        "regionFilterApplied": bool(region_codes),
        "regionCodes": [rc.strip() for rc in region_codes] if region_codes else None,
        "totalCount": nationwide.get("totalCount"),
        "fetchedCount": len(deduped),
        "pagesFetched": pages_fetched,
        "allMatchingResultsFetched": bool(nationwide.get("allMatchingResultsFetched")) and (
            not region_codes or bool(filtered and filtered.get("allMatchingResultsFetched"))),
        "filteredPagesFetched": filtered.get("pagesFetched", 0) if filtered else 0,
        "classifications": {
            "matched": matched,
            "unmatched": unmatched,
            "region_unknown": region_unknown,
            "filter_only_matched": filter_only_matched,
        },
        "matchedCount": len(matched),
        "unmatchedCount": len(unmatched),
        "regionUnknownCount": len(region_unknown),
        "filterOnlyMatchedCount": len(filter_only_matched),
        "pageErrors": page_errors,
        "allResults": deduped,
        "note": (
            f"정책명 '{keyword}'로 최대 {max_pages}페이지 조회한 결과입니다. "
            + (f"대상 지역 코드 {region_codes} 기준으로 분류했습니다. " if region_codes else "지역 필터 없이 전국 조회했습니다. ")
            + "분류는 정책 응답에 포함된 지역 코드(zipCd) 기준이며, 신청 자격 판정이 아닙니다. "
            + "지역 코드가 없는 정책은 'region_unknown'으로 보류했습니다."
        ),
    }


def main():
    keys = load_api_keys()
    on_key = require("ON_YOUTH_API_KEY", keys)
    gov_key = require("GOV24_API_KEY", keys)

    print("=== 온통청년 청년정책 API 요청 ===")
    code, body = fetch(
        ON_URL,
        {
            "apiKeyNm": on_key,
            "rtnType": "json",
            "pageNum": "1",
            "pageSize": "1",
            "pageType": "1",
        },
    )
    summarize_on(body, code)

    print()
    print("=== 정부24 공공서비스 혜택 정보 API 요청 ===")
    code, body = gov24_fetch(gov_key)
    summarize_gov24(body, code)

if __name__ == "__main__":
    main()
