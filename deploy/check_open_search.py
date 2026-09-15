"""접수 중 후보를 다음 페이지에서 찾고 기존 결과를 보존하는지 검증한다."""
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import policy_fetch as p
import solar_service as s


class OpenSearchTest(unittest.TestCase):
    def fetch(self, key, keyword, page_size, page_num, region_codes):
        raw = '20260101 ~ 20261231' if page_num == 4 else '20200101 ~ 20201231'
        return {'status': 'ok', 'results': [{'policyNo': str(page_num), 'aplyYmd': raw}],
                'totalCount': 10, 'allMatchingResultsFetched': False}

    def preferred(self, item):
        now = s.dt.datetime(2026, 9, 13, tzinfo=s.KST)
        return s._normalize_apply_period(item, now)['status'] == '신청 중'

    def run_search(self, **kwargs):
        return p.on_youth_search_multi('test', '월세', max_pages=3, page_size=1,
                                      preferred=self.preferred, extra_pages=3, **kwargs)

    def test_next_page_and_stop_when_open_found(self):
        with patch.object(p, 'on_youth_search', side_effect=self.fetch) as api:
            result = self.run_search()
        self.assertEqual([c.kwargs['page_num'] for c in api.call_args_list], [1, 2, 3, 4])
        self.assertEqual(len(result['results']), 4)
        self.assertFalse(result['allMatchingResultsFetched'])

    def test_unknown_period_does_not_stop_search(self):
        def unknown(*args, **kwargs):
            result = self.fetch(*args, **kwargs)
            result['results'][0]['aplyYmd'] = '상시 모집'
            return result
        with patch.object(p, 'on_youth_search', side_effect=unknown) as api:
            result = self.run_search()
        self.assertEqual(api.call_count, 6)
        self.assertFalse(result['allMatchingResultsFetched'])

    def test_extra_page_error_keeps_existing_results(self):
        def failed(*args, **kwargs):
            return {'status': 'error', 'reason': 'timeout'} if kwargs['page_num'] == 4 else self.fetch(*args, **kwargs)
        with patch.object(p, 'on_youth_search', side_effect=failed):
            result = self.run_search()
        self.assertEqual(len(result['results']), 3)
        self.assertEqual(result['pageErrors'][0]['page'], 4)

    def test_service_does_not_stop_for_wrong_or_unknown_region(self):
        seen = []
        def classified(*args, **kwargs):
            choose = kwargs['preferred']
            for classification in ('unmatched', 'region_unknown', 'matched'):
                with patch.object(p, '_classify_single_item', return_value=(classification, 'test')):
                    seen.append(choose({'aplyYmd': '20260101 ~ 20261231'}))
            return {'status': 'error', 'reason': 'test'}
        now = s.dt.datetime(2026, 9, 13, tzinfo=s.KST)
        with patch.object(p, 'load_api_keys', return_value={'ON_YOUTH_API_KEY': 'test'}), \
             patch.object(p, 'on_youth_search_classified', side_effect=classified), \
             patch.object(s, '_normalize_apply_period', return_value={'status': '신청 중'}):
            s.search({'keyword': '월세', 'region_codes': ['11440']})
        self.assertEqual(seen, [False, False, True])

    def test_only_open_candidates_sorted_by_start_date(self):
        rows = [
            {'policyNo': 'old', 'aplyYmd': '20260101 ~ 20261231'},
            {'policyNo': 'closed', 'aplyYmd': '20250101 ~ 20251231'},
            {'policyNo': 'unknown', 'aplyYmd': '상시 모집'},
            {'policyNo': 'future', 'aplyYmd': '20270101 ~ 20271231'},
            {'policyNo': 'new', 'aplyYmd': '20260901 ~ 20260930'},
        ]
        result = {'status': 'ok', 'classifications': {
            'matched': rows, 'filter_only_matched': [], 'region_unknown': []}}
        normalize = s._normalize_apply_period
        now = s.dt.datetime(2026, 9, 13, tzinfo=s.KST)
        with patch.object(p, 'load_api_keys', return_value={'ON_YOUTH_API_KEY': 'test'}), \
             patch.object(p, 'on_youth_search_classified', return_value=result), \
             patch.object(s, '_normalize_apply_period', side_effect=lambda item, _: normalize(item, now)):
            found = s.search({'keyword': '지원'})
        self.assertEqual([item['policyNo'] for item in found['allCandidates']], ['new', 'old'])
        self.assertEqual(found['closedCandidates'], [])
        self.assertEqual(found['summary']['신청 중'], 2)
        displayed, summary = s._merge_search_results([found])
        self.assertEqual([item['policyNo'] for item in displayed], ['new', 'old'])
        self.assertEqual(summary['신청 마감'], 0)

    def test_search_request_rejects_unverified_model_reply(self):
        with patch.object(s, 'complete', return_value={'content': '검색했어요'}) as model:
            with self.assertRaises(s.ServiceError):
                s.answer({'query': '신청 중인 정책 검색해줘'})
        self.assertEqual(model.call_args.args[1], 'required')

    def test_exhausted_results_and_time_limit(self):
        with patch.object(p, 'on_youth_search', side_effect=self.fetch) as api:
            self.run_search(extension_deadline=time.monotonic() - 1)
        self.assertEqual(api.call_count, 3)
        with patch.object(p, 'on_youth_search', return_value={
                'status': 'ok', 'results': [], 'totalCount': 0,
                'allMatchingResultsFetched': True}) as api:
            result = self.run_search()
        self.assertEqual(api.call_count, 1)
        self.assertTrue(result['allMatchingResultsFetched'])

if __name__ == '__main__':
    unittest.main()
