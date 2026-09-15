"""여러 검색 결과의 집계와 화면 목록이 일치하는지 검증한다."""
import copy
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import solar_service as s


def policy(number, status='신청 중'):
    return {'policyNo': number, 'policyName': number,
            '_applyPeriod': {'status': status, 'today': '2026-09-13'}}


def result(items):
    return {'status': 'ok', 'allCandidates': items, 'candidates': items[:4],
            'closedCandidates': [], 'pagesFetched': 1, 'pageErrors': []}


class MergeTest(unittest.TestCase):
    def test_duplicate_and_closed_from_both_searches(self):
        results = [result([policy('a'), policy('b', '신청 마감')]),
                   result([policy('a'), policy('c', '신청 마감')])]
        original = copy.deepcopy(results)
        items, counts = s._merge_search_results(results)
        self.assertEqual([p['policyNo'] for p in items], ['a', 'b', 'c'])
        self.assertEqual(counts['신청 중'], 1)
        self.assertEqual(counts['신청 마감'], 2)
        self.assertEqual(counts['전체 후보 건수'], 3)
        self.assertEqual(results, original)

    def test_limit_after_merge_and_closed_beyond_eighth(self):
        items, counts = s._merge_search_results([
            result([policy(str(i)) for i in range(15)] + [policy('closed', '신청 마감')]),
            result([policy('0')])])
        self.assertEqual(len(items), 13)
        self.assertEqual(counts['신청 중'], 15)
        self.assertEqual(counts['신청 마감'], 1)
        self.assertEqual(counts['표시 후보 건수'], 13)
        self.assertEqual(items[-1]['policyNo'], 'closed')

    def test_empty_or_failed_second_search_keeps_first(self):
        for second in (result([]), {'status': 'error', 'reason': 'timeout'}):
            with self.subTest(second=second):
                items, counts = s._merge_search_results([result([policy('a', '신청 마감')]), second])
                self.assertEqual(len(items), 1)
                self.assertEqual(counts['신청 마감'], 1)
                self.assertEqual(len(counts['검색별 조회 정보']), 2)

    def test_actual_answer_assembly(self):
        call = lambda i: {'id': str(i), 'function': {'name': 'on_youth_search', 'arguments': '{"keyword":"월세"}'}}
        replies = [{'tool_calls': [call(1), call(2)]}, {'content': '답변'}]
        searches = [result([policy('a'), policy('closed', '신청 마감')]), {'status':'error','reason':'timeout'}]
        with patch.object(s, 'complete', side_effect=replies) as model, patch.object(s, 'search', side_effect=searches), patch.dict(os.environ, {'ONE_STEP_SESSION_SECRET':'test-only-secret'}):
            response = s.answer({'query': '월세'})
        self.assertEqual(response['summary']['전체 후보 건수'], 2)
        self.assertEqual(response['summary']['신청 마감'], 1)
        self.assertEqual(len(response['policies']), 2)
        tool_messages = [m for m in model.call_args.args[0] if m['role']=='tool']
        self.assertTrue(all('allCandidates' not in m['content'] for m in tool_messages))

if __name__ == '__main__': unittest.main()
