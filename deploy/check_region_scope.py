"""광역·기초·전국 범위와 API 지역 확장을 검증한다."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import policy_fetch as p


class RegionTest(unittest.TestCase):
    def test_province_expands_and_district_does_not_include_siblings(self):
        seoul = p.expand_region_codes(['11000'])
        self.assertEqual(len(seoul), 26)
        self.assertIn('11440', seoul)
        self.assertNotIn('41000', seoul)
        self.assertEqual(p.expand_region_codes(['11440']), ['11000', '11440'])
        self.assertIn('41110', p.expand_region_codes(['41000']))

    def test_broad_and_specific_residence(self):
        self.assertEqual(p._classify_single_item({'regionCodes':'11440'}, ['11000'])[0], 'matched')
        self.assertEqual(p._classify_single_item({'regionCodes':'11680'}, ['11440'])[0], 'unmatched')
        self.assertEqual(p._classify_single_item({'regionCodes':'11000'}, ['11440'])[0], 'matched')
        self.assertEqual(p._classify_single_item({'regionCodes':'41110'}, ['11000'])[0], 'unmatched')

    def test_nationwide_and_unknown_are_different(self):
        all_codes = [c for children in p.REGION_DATA['provinces'].values() for c in children]
        item = {'regionCodes': all_codes}
        self.assertEqual(p.policy_region_scope(item)['level'], '전국 공통')
        self.assertEqual(p._classify_single_item(item, ['11440'])[0], 'matched')
        self.assertEqual(p.policy_region_scope({'regionCodes':None})['level'], '지역 확인 필요')
        self.assertEqual(p.policy_region_scope({'regionCodes':['11440','41110']})['level'], '시·군·구')

    def test_full_province_and_district_labels(self):
        self.assertEqual(p.policy_region_scope({'regionCodes':p.REGION_DATA['provinces']['11000']})['label'], '서울특별시 전체')
        self.assertEqual(p.policy_region_scope({'regionCodes':'11440'})['label'], '서울특별시 마포구')

    def test_api_receives_expanded_codes(self):
        with patch.object(p, 'fetch', return_value=(200, {})) as api, patch.object(p, 'on_youth_search_result', return_value={}):
            p.on_youth_search('test', '취업', region_codes=['11000'])
        self.assertEqual(set(api.call_args.args[1]['zipCd'].split(',')), set(p.expand_region_codes(['11000'])))

if __name__ == '__main__': unittest.main()
