#!/usr/bin/env python3
"""복수 지역. 번호 없는 후보. 중복 분류와 페이지 오류를 API 호출 없이 검증한다."""
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import policy_fetch as p


def main():
    assert p._classify_single_item({'regionCodes': '11440,28237'}, ['11440'])[0] == 'matched'
    for raw in ('11440|28237', ['28237', None], 'unknown'):
        assert p._classify_single_item({'regionCodes': raw}, ['11440'])[0] == 'region_unknown'
    assert p._classify_single_item({'regionCodes': '28237'}, ['11440'])[0] == 'unmatched'
    assert p._classify_single_item({'regionCodes': '11000'}, ['11440'])[0] == 'matched'
    items = [{'policyNo':'P1','regionCodes':'11440,28237'},
             {'policyNo':'P1','regionCodes':'11440'},
             {'policyName':'번호 없음','regionCodes':None}]
    page = {'status':'ok','results':items,'pagesFetched':1,'totalCount':3,
            'allMatchingResultsFetched':True,'pageErrors':[]}
    with patch.object(p, 'on_youth_search_multi', return_value=page):
        r = p.on_youth_search_classified('test','월세',['11440'])
    assert r['fetchedCount'] == 3  # 두 조회의 번호 없는 후보는 임의로 합치지 않는다.
    assert r['matchedCount'] == 1
    assert r['regionUnknownCount'] == 2
    assert sum(len(v) for v in r['classifications'].values()) == r['fetchedCount']
    assert 'classification' not in items[0]
    with patch.object(p,'on_youth_search',side_effect=[
        {'status':'ok','results':items[:1],'totalCount':2},
        {'status':'error','reason':'일시 오류'}]):
        r = p.on_youth_search_multi('test','월세',page_size=1)
    assert r['pageErrors'][0]['page'] == 2 and not r['allMatchingResultsFetched']
    with patch.object(p,'on_youth_search',side_effect=[
        {'status':'ok','results':items[:1],'totalCount':2},
        {'status':'ok','results':[{'policyNo':'P2'}],'totalCount':2}]):
        r = p.on_youth_search_multi('test','월세',page_size=1)
    assert r['allMatchingResultsFetched'] and r['pagesFetched'] == 2
    print('PASS: 복수 지역. 미확인 형식 보류. 번호 없는 후보 보존. 중복 후 분류 건수. 페이지 오류와 완료 판정')

if __name__ == '__main__':
    main()
