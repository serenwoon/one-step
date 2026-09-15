"""추천과 대화 상태 검증."""
import json
import os
import sys
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import policy_fetch as pf
import solar_service as svc
from local_ask_server import Router


def policy(number, condition='', **values):
    return {'policyNo': number, 'policyName': '청년 월세 ' + number,
            'supportContent': '월세 지원', 'applyUrl': 'https://example.test/' + number,
            'regionCodes': '11440', 'aplyYmd': '20200101 ~ 20991231',
            'addAplyQlfcCndCn': condition, **values}


def response(rows):
    return {'status': 'ok', 'classifications': {
        'matched': rows, 'filter_only_matched': [], 'region_unknown': []}}


class QualificationTest(unittest.TestCase):
    def test_required_excluded_preferred_and_unknown(self):
        cases = [
            ('재직자 우대', {'employment': 'unemployed'}, 'ok'),
            ('취업 상태 무관', {'employment': 'employed'}, 'ok'),
            ('미취업 청년 대상. 재직자 제외.', {'employment': 'unemployed'}, 'ok'),
            ('미취업 청년 대상. 재직자 제외.', {'employment': 'employed'}, 'ineligible'),
            ('재직자 대상. 대학생 제외.', {'employment': 'employed', 'student': False}, 'ok'),
            ('대학생 대상', {'employment': 'employed', 'student': True}, 'ok'),
            ('대학생 대상. 취업 상태 무관.', {'employment': 'employed', 'student': False}, 'ineligible'),
            ('재직자 대상. 저소득층 우대.', {'employment': 'unemployed'}, 'ineligible'),
            ('재직자 대상', {}, 'needs_check'),
            ('대학생 대상', {'employment': 'employed'}, 'needs_check'),
            ('미취업자 대상', {'employment': 'student'}, 'needs_check'),
            ('재직자 대상', {'employment': ''}, 'needs_check'),
            ('대학생 대상', {'student': 'false'}, 'needs_check'),
            ('학생 제외하지 않음', {'student': True}, 'needs_check'),
            ('재직자 또는 미취업자 대상', {'employment': 'employed'}, 'needs_check'),
            ('가구소득 기준 중위소득 100% 이하', {}, 'needs_check'),
            ('미취업자 대상. 다만 주 15시간 미만 근로자도 가능', {'employment': 'employed'}, 'needs_check'),
        ]
        for text, user, status in cases:
            with self.subTest(text=text, user=user):
                self.assertEqual(pf.policy_qualification_check(policy('p', text), user)['status'], status)

    def test_age_boundaries_and_invalid_input(self):
        item = policy('age', sprtTrgtMinAge='19', sprtTrgtMaxAge='34', sprtTrgtAgeLmtYn='Y')
        for age, expected in [(18, 'ineligible'), (19, 'ok'), (34, 'ok'), (35, 'ineligible'),
                              ('28', 'ok'), ('unknown', 'needs_check'), (True, 'needs_check')]:
            with self.subTest(age=age):
                self.assertEqual(pf.policy_qualification_check(item, {'age': age})['status'], expected)
        self.assertEqual(pf.policy_qualification_check({**item, 'sprtTrgtMinAge': '40'}, {'age': 28})['status'], 'needs_check')
        self.assertEqual(pf.policy_qualification_check({**item, 'addAplyQlfcCndCn': '군복무 기간만큼 연령 연장'}, {'age': 35})['status'], 'needs_check')


class ProfileTest(unittest.TestCase):
    def test_user_statements_and_corrections(self):
        p = svc.update_profile({}, {}, '만 28세. 서울 마포구. 미취업입니다. 월세 지원을 찾고 싶어요.', pf.REGION_DATA)
        self.assertEqual(p['region_codes'], ['11440'])
        self.assertEqual(p['age'], 28)
        self.assertEqual(p['employment'], 'unemployed')
        self.assertEqual(p['purpose'], '주거')
        p = svc.update_profile(p, {}, '이제 취업했어요. 대학생이고 재학 중이에요.', pf.REGION_DATA)
        self.assertEqual(p['employment'], 'employed')
        self.assertTrue(p['student'])
        self.assertEqual(p['purpose'], '주거')
        self.assertEqual(svc.update_profile(p, {'employment': None}, '다시 찾아줘', pf.REGION_DATA)['employment'], None)
        self.assertEqual(svc.update_profile(p, {}, '부산 정책도 있어?', pf.REGION_DATA)['region_codes'], ['11440'])
        self.assertEqual(svc.update_profile(p, {}, '부산으로 이사했어요', pf.REGION_DATA)['region_codes'], ['26000'])

    def test_student_negative_statements(self):
        for text in ('학생은 아니에요.', '학생이 아니에요.', '재학 중은 아니에요.'):
            with self.subTest(text=text):
                p = svc.update_profile({'student': True}, {}, text, pf.REGION_DATA)
                self.assertFalse(p['student'])
                reply = svc._grounded_reply([], [{'status': 'ok'}], {
                    **p, 'age': 27, 'region_codes': ['11440'],
                    'employment': 'unemployed', 'purpose': '취업'})
                self.assertNotIn('재학 중인가요?', reply)

    def test_no_assistant_hypothetical_or_third_party_profile(self):
        self.assertEqual(svc.update_profile({}, {}, '친구가 만 40세이고 재직 중이에요.', pf.REGION_DATA), {})
        self.assertNotIn('employment', svc.update_profile({}, {}, '미취업자 대상 정책 알려줘', pf.REGION_DATA))
        self.assertIsNone(pf.normalize_profile({'purpose': []})['purpose'])


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.key = patch.object(pf, 'load_api_keys', return_value={'ON_YOUTH_API_KEY': 'local-test'})
        self.key.start()
        self.addCleanup(self.key.stop)

    def test_real_search_filters_counts_dates_and_unknown(self):
        rows = [policy('unemployed', '미취업자 대상'), policy('employed', '재직자 대상'),
                policy('student', '대학생 대상'),
                policy('closed', aplyYmd='20200101 ~ 20201231'),
                policy('other', policyName='창업 지원', supportContent='창업 사업화')]
        with patch.object(pf, 'on_youth_search_classified', return_value=response(rows)):
            result = svc.search({'keyword': '청년', 'region_codes': ['11440'],
                                 'user_info': {'employment': 'unemployed', 'purpose': '주거'}})
        candidates = result['allCandidates']
        self.assertEqual({p['policyNo'] for p in candidates}, {'unemployed', 'student', 'other'})
        self.assertEqual(next(p for p in candidates if p['policyNo'] == 'student')['_qual']['status'], 'needs_check')
        self.assertEqual(result['summary']['전체 후보 건수'], 3)
        self.assertEqual(result['openCandidateCount'], 3)

    def test_http_chat_uses_profile_and_preserves_corrections(self):
        rows = [policy('job', '재직자 대상'), policy('nojob', '미취업자 대상')]
        server = ThreadingHTTPServer(('127.0.0.1', 0), Router)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f'http://127.0.0.1:{server.server_port}/ask'
        def send(data):
            req = urllib.request.Request(url, data=json.dumps(data).encode(), headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=10) as res:
                return json.load(res)
        def model(messages, tools, deadline):
            if not any(m['role'] == 'tool' for m in messages):
                # 사용자 정보와 다른 도구 인자.
                return {'tool_calls': [{'id': 'one', 'function': {'name': 'on_youth_search', 'arguments': json.dumps({
                    'keyword': '월세', 'region_codes': ['26000'], 'user_info': {'employment': 'employed'}})}}]}
            return {'content': '가짜정책에 무조건 신청 가능해요.'}
        with patch.dict(os.environ, {'ONE_STEP_SESSION_SECRET': 'local-test-only'}), \
             patch.object(pf, 'on_youth_search_classified', return_value=response(rows)) as api, \
             patch.object(svc, 'complete', side_effect=model):
            first = send({'query': '월세 정책 추천해줘', 'profile': {
                'age': 28, 'employment': 'unemployed', 'region_codes': ['11440'], 'purpose': '주거'}})
            self.assertEqual([p['policyNo'] for p in first['policies']], ['nojob'])
            self.assertEqual(api.call_args.args[2], ['11440'])
            self.assertNotIn('가짜정책', first['reply'])
            second = send({'query': '이제 취업했어요. 다시 추천해줘', 'conversation': first['conversation']})
            self.assertEqual([p['policyNo'] for p in second['policies']], ['job'])
            self.assertEqual(second['profile']['age'], 28)
            self.assertEqual(second['profile']['employment'], 'employed')
            self.assertEqual(second['profile']['purpose'], '주거')

    def test_signed_profile_survives_trim_and_rejects_tampering(self):
        with patch.dict(os.environ, {'ONE_STEP_SESSION_SECRET': 'local-test-only'}):
            token = svc.encode_state([{'role': 'user', 'content': '계속'}] * 20, {'age': 28})
            messages, profile = svc.decode_session(token)
            self.assertEqual(len(messages), 12)
            self.assertEqual(profile['age'], 28)
            with self.assertRaises(svc.ServiceError):
                svc.decode_session(token[:-1] + ('0' if token[-1] != '0' else '1'))


class FallbackTest(unittest.TestCase):
    def run_search(self, responses):
        with patch.object(pf, 'load_api_keys', return_value={'ON_YOUTH_API_KEY': 'test'}), \
             patch.object(pf, 'on_youth_search_classified', side_effect=responses) as api:
            result = svc.search({'keyword': '월세', 'region_codes': ['11440'],
                                 'user_info': {'purpose': '주거', 'employment': 'unemployed'}})
        return result, api

    def test_existing_candidates_skip_fallback(self):
        result, api = self.run_search([response([policy('first'), policy('second'), policy('third')])])
        self.assertEqual(api.call_count, 1)
        self.assertNotIn('fallback', result)

    def test_empty_search_tries_only_one_alternative(self):
        result, api = self.run_search([response([]), response([])])
        self.assertEqual(api.call_count, 2)
        self.assertNotEqual(api.call_args_list[0].args[1], api.call_args_list[1].args[1])
        self.assertEqual(result['fallback']['status'], 'ok')
        self.assertEqual(result['allCandidates'], [])
        self.assertEqual(len(svc._merge_search_results([result])[1]['검색별 조회 정보']), 2)

    def test_fallback_uses_same_filters_and_counts(self):
        rows = [policy('open'), policy('closed', aplyYmd='20200101~20201231'),
                policy('employed', '재직자 대상')]
        result, api = self.run_search([response([]), response(rows)])
        self.assertEqual(api.call_count, 2)
        self.assertEqual(api.call_args.args[2], ['11440'])
        self.assertEqual([p['policyNo'] for p in result['candidates']], ['open'])
        self.assertEqual(result['summary']['신청 중'], 1)
        self.assertEqual(result['summary']['전체 후보 건수'], 1)
        self.assertFalse(any('광역 조회' in r for r in result['candidates'][0]['_qual']['needsCheckReasons']))

    def test_fallback_errors_are_preserved(self):
        for second in ({'status': 'error', 'keyword': '주거', 'reason': '연결 실패'},
                       {**response([]), 'pageErrors': [{'page': 2, 'reason': '실패'}]}):
            with self.subTest(second=second):
                result, api = self.run_search([response([]), second])
                self.assertEqual(api.call_count, 2)
                self.assertIn('일부 조회', svc._grounded_reply([], [result], {}))


class RegionSearchTest(unittest.TestCase):
    def test_keyword_normalization_reaches_api(self):
        cases = [('서울', '장학'), (' 서울시 ', '장학'), ('구로구', '장학'),
                 ('서울특별시 구로구', '장학'), ('경기도', '장학'),
                 ('구로구 장학', '장학'), ('교육', '교육'), ('서울장학재단', '서울장학재단')]
        for keyword, expected in cases:
            with self.subTest(keyword=keyword), \
                 patch.object(pf, 'load_api_keys', return_value={'ON_YOUTH_API_KEY': 'test'}), \
                 patch.object(pf, 'on_youth_search_classified', return_value=response([])) as api:
                svc.search({'keyword': keyword, 'region_codes': ['11530'],
                            'user_info': {'purpose': '교육', 'student': True}}, allow_fallback=False)
                self.assertEqual(api.call_args.args[1:3], (expected, ['11530']))

    def test_sparse_results_are_merged_with_alternative(self):
        with patch.object(pf, 'load_api_keys', return_value={'ON_YOUTH_API_KEY': 'test'}), \
             patch.object(pf, 'on_youth_search_classified', side_effect=[response([policy('first')]),
                 response([policy('first'), policy('second')])]):
            result = svc.search({'keyword': '월세', 'user_info': {'purpose': '주거'}})
        self.assertEqual({p['policyNo'] for p in result['candidates']}, {'first', 'second'})
        self.assertEqual(result['summary']['전체 후보 건수'], 2)

    def test_invalid_keyword_returns_error(self):
        for keyword in (123, True, [], {}, None, '   '):
            with self.subTest(keyword=keyword):
                self.assertEqual(svc.search({'keyword': keyword})['status'], 'error')

    def test_student_education_fallback_searches_scholarships(self):
        with patch.object(pf, 'load_api_keys', return_value={'ON_YOUTH_API_KEY': 'test'}), \
             patch.object(pf, 'on_youth_search_classified', side_effect=[response([]), response([
                 policy('scholarship', policyName='대학생 장학 지원', supportContent='대학생 장학 지원')])]) as api:
            result = svc.search({'keyword': '교육', 'region_codes': ['11000'],
                                 'user_info': {'purpose': '교육', 'student': True}})
        self.assertEqual([call.args[1] for call in api.call_args_list], ['교육', '장학'])
        self.assertEqual([p['policyNo'] for p in result['candidates']], ['scholarship'])

    def test_zero_age_range_is_unrestricted_but_other_rules_remain(self):
        item = policy('age', sprtTrgtMinAge='0', sprtTrgtMaxAge='0', sprtTrgtAgeLmtYn='Y')
        for age in (0, 25, 65):
            self.assertEqual(pf.policy_qualification_check(item, {'age': age})['status'], 'ok')
        numeric = {**item, 'sprtTrgtMinAge': 0, 'sprtTrgtMaxAge': 0}
        self.assertEqual(pf.policy_qualification_check(numeric, {'age': 25})['status'], 'ok')
        item['addAplyQlfcCndCn'] = '대학생 제외'
        self.assertEqual(pf.policy_qualification_check(item, {'age': 25, 'student': True})['status'], 'ineligible')

    def test_broad_narrow_restore_uses_real_classification(self):
        rows = [policy('guro', regionCodes='11530'), policy('gangnam', regionCodes='11680'),
                policy('seoul', regionCodes='11000'), policy('gyeonggi', regionCodes='41000'),
                policy('suwon', regionCodes='41110'), policy('national', regionCodes=list(pf.REGION_DATA['provinces']))]
        profile = {'purpose': '주거', 'region_codes': ['11000']}
        profiles = [profile]
        profile = svc.update_profile(profile, {}, '지금 구로구 살고 있어', pf.REGION_DATA)
        profiles.append(profile)
        profiles.append(svc.update_profile(profile, {'region_codes': ['11000']}, '다시 찾아줘', pf.REGION_DATA))
        profiles.append({'purpose': '주거', 'region_codes': ['41000']})
        expected = [{'guro', 'gangnam', 'seoul', 'national'}, {'guro', 'seoul', 'national'},
                    {'guro', 'gangnam', 'seoul', 'national'}, {'gyeonggi', 'suwon', 'national'}]
        with patch.object(pf, 'load_api_keys', return_value={'ON_YOUTH_API_KEY': 'test'}), \
             patch.object(pf, 'on_youth_search_multi', return_value={'status': 'ok', 'results': rows}):
            for profile, wanted in zip(profiles, expected):
                result = svc.search({'keyword': '월세', 'region_codes': profile['region_codes'],
                                     'user_info': profile}, allow_fallback=False)
                self.assertEqual({p['policyNo'] for p in result['candidates']}, wanted)
                if profile['region_codes'] == ['11000']:
                    district = next(p for p in result['candidates'] if p['policyNo'] == 'gangnam')
                    self.assertTrue(any('광역 조회' in r for r in district['_qual']['needsCheckReasons']))


class SolarReasoningTest(unittest.TestCase):
    def item(self, number='p'):
        return policy(number, '소득 요건 공고 확인',
                      _qual={'status': 'needs_check', 'matchedReasons': [],
                             'needsCheckReasons': ['소득 요건 확인 필요']},
                      _applyPeriod={'status': '신청 중', 'raw': '20200101 ~ 20991231'})

    def choice(self, number='p', **values):
        return {'policyNo': number, 'purposes': ['주거'], 'reason': '방값 부담을 줄이는 데 도움이 될 수 있어요.',
                'evidence': '소득 요건 공고 확인', **values}

    def test_profile_interpretation_uses_quotes_and_explicit_input(self):
        query = '지난달 회사를 그만뒀고 방값이 부담돼요.'
        updates = [{'field': 'employment', 'value': 'unemployed', 'source': '지난달 회사를 그만뒀고'},
                   {'field': 'purpose', 'value': '주거', 'source': '방값이 부담돼요.'},
                   {'field': 'age', 'value': 27, 'source': query}]
        result = svc.interpret_profile({}, updates, query, {})
        self.assertEqual(result, {'employment': 'unemployed', 'purpose': '주거'})
        self.assertEqual(svc.interpret_profile({'employment': 'employed'}, updates, query,
                                              {'employment': 'employed'})['employment'], 'employed')
        self.assertEqual(svc.interpret_profile({}, updates, '친구가 ' + query, {}), {})
        self.assertEqual(svc.interpret_profile({}, updates, '안녕하세요', {}), {})

    def test_profile_does_not_invent_a_district(self):
        source = '서울에 살고 있어요'
        update = {'field': 'region_codes', 'value': ['11440'], 'source': source}
        self.assertEqual(svc.interpret_profile({}, [update], source, {}), {})
        update['value'] = ['11000']
        self.assertEqual(svc.interpret_profile({}, [update], source, {})['region_codes'], ['11000'])

    def test_model_selection_preserves_reason_and_source_facts(self):
        rows = [self.item('a'), self.item('b')]
        content = json.dumps({'recommendations': [self.choice('b')]})
        selected = svc.choose_policies(content, rows, {})
        self.assertEqual([p['policyNo'] for p in selected], ['b'])
        reply = svc._grounded_reply(selected, [{'status': 'ok'}], {})
        self.assertIn('방값 부담을 줄이는 데 도움이 될 수 있어요.', reply)
        self.assertIn('https://example.test/b', reply)
        self.assertIn('소득 요건 확인 필요', reply)
        self.assertNotIn('_recommendation', rows[1])

    def test_invalid_model_evidence_or_claims_are_rejected(self):
        for choice in (self.choice('invented'), self.choice(evidence='없는 지원 내용'),
                       self.choice(reason='매달 999만원을 받아요.'),
                       self.choice(reason='신청 가능해요.'),
                       self.choice(reason='https://fake.example 에 신청하세요')):
            with self.subTest(choice=choice):
                self.assertIsNone(svc.choose_policies(json.dumps({'recommendations': [choice]}), [self.item()], {}))
        for status in ('신청 마감', '확인 필요'):
            item = self.item()
            item['_applyPeriod']['status'] = status
            self.assertIsNone(svc.choose_policies(json.dumps({'recommendations': [self.choice()]}), [item], {}))

    def test_duplicate_types_and_whitespace_in_evidence(self):
        choice = self.choice(evidence='소득 요건\n공고 확인')
        content = json.dumps({'recommendations': [choice, choice]})
        selected = svc.choose_policies(content, [self.item()], {})
        self.assertEqual([item['policyNo'] for item in selected], ['p'])
        choice['evidence'] = '소득 확인'
        self.assertIsNone(svc.choose_policies(json.dumps({'recommendations': [choice]}), [self.item()], {}))

    def test_fallback_cards_match_reply_and_summary(self):
        rows = [self.item(str(i)) for i in range(5)]
        responses = [{'tool_calls': [{'id': 'one', 'function': {'name': 'on_youth_search',
                      'arguments': '{"keyword":"월세","profile_updates":[]}'}}]},
                     {'content': 'invalid comparison'}]
        with patch.dict(os.environ, {'ONE_STEP_SESSION_SECRET': 'local-test-only'}), \
             patch.object(svc, 'complete', side_effect=responses), \
             patch.object(svc, 'search', return_value={'status': 'ok', 'allCandidates': rows, 'candidates': rows}):
            result = svc.answer({'query': '월세 정책 찾아줘', 'profile': {'region_codes': ['11000']}})
        self.assertEqual(len(result['policies']), 3)
        self.assertEqual(result['summary']['표시 후보 건수'], 3)
        self.assertEqual(result['summary']['전체 후보 건수'], 5)
        self.assertEqual(result['profile']['region_codes'], ['11000'])

    def test_empty_selection_does_not_reintroduce_irrelevant_policies(self):
        self.assertEqual(svc.choose_policies('{"recommendations":[]}', [self.item()], {}), [])
        content = json.dumps({'recommendations': [self.choice(purposes=['창업'])]})
        self.assertEqual(svc.choose_policies(content, [self.item()], {'purpose': '주거'}), [])

    def test_answer_interprets_situation_before_search_and_uses_selection(self):
        query = '지난달 회사를 그만뒀고 방값이 부담돼요. 지원을 찾아줘.'
        updates = [{'field': 'employment', 'value': 'unemployed', 'source': '회사를 그만뒀고'},
                   {'field': 'purpose', 'value': '주거', 'source': '방값이 부담돼요.'}]
        responses = [{'tool_calls': [{'id': 'one', 'function': {'name': 'on_youth_search',
                     'arguments': json.dumps({'keyword': '월세', 'profile_updates': updates})}}]},
                     {'content': json.dumps({'recommendations': [self.choice('b')]})}]
        rows = [self.item('a'), self.item('b')]
        result = {'status': 'ok', 'allCandidates': rows, 'candidates': rows}
        with patch.dict(os.environ, {'ONE_STEP_SESSION_SECRET': 'local-test-only'}), \
             patch.object(svc, 'complete', side_effect=responses) as model, \
             patch.object(svc, 'search', return_value=result) as search:
            answer = svc.answer({'query': query})
        self.assertEqual(model.call_count, 2)
        self.assertIn(svc._load_send_check_guidance(), model.call_args_list[0].args[0][0]['content'])
        self.assertEqual(search.call_args.args[0]['user_info']['employment'], 'unemployed')
        self.assertEqual(answer['profile']['purpose'], '주거')
        self.assertEqual([p['policyNo'] for p in answer['policies']], ['b'])
        self.assertEqual(answer['summary']['표시 후보 건수'], 1)
        self.assertEqual(answer['summary']['전체 후보 건수'], 2)
        self.assertIn('방값 부담을 줄이는 데 도움이 될 수 있어요.', answer['reply'])

    def test_input_guidance_is_required_and_separate_from_draft_review(self):
        guidance = svc._load_send_check_guidance()
        self.assertIn('profile_updates', guidance)
        self.assertNotIn('# send-check', guidance)
        with patch('builtins.open', side_effect=FileNotFoundError):
            with self.assertRaises(svc.ServiceError):
                svc._load_send_check_guidance()

    def test_links_and_html_are_rendered_safely(self):
        text = '[신청](https://example.test/apply) <script>alert(1)</script>'
        self.assertEqual(svc._MARKDOWN_LINK_RE.findall(text), [('신청', 'https://example.test/apply')])
        self.assertEqual(svc._LINK_RE.findall(text), ['https://example.test/apply'])
        rendered = svc._safe_render_reply(text)
        self.assertIn('href="https://example.test/apply"', rendered)
        self.assertNotIn('<script>', rendered)
        self.assertIn('&lt;script&gt;', rendered)

    def test_history_and_company_context_do_not_crash_or_erase_requirements(self):
        for clause in ('졸업자 대상', '수료자 제외',
                       '학생이 취업한 기업이 대기업인 경우 장려금을 지급할 수 없습니다.'):
            with self.subTest(clause=clause):
                result = pf.policy_qualification_check(policy('p', clause), {'student': False})
                self.assertEqual(result['status'], 'needs_check')
        result = pf.policy_qualification_check(policy('p', '학생 대상 기업 현장실습 지원'), {'student': False})
        self.assertEqual(result['status'], 'ineligible')


class EmptyResultsTest(unittest.TestCase):
    def test_counts_come_from_filter_stages(self):
        rows = [policy('unknown', aplyYmd=''), policy('closed', aplyYmd='20200101~20200102'),
                policy('future', aplyYmd='20990101~20991231'), policy('ineligible'), policy('open')]
        def qualify(item, profile):
            return {'status': 'ineligible' if item['policyNo'] == 'ineligible' else 'ok',
                    'matchedReasons': [], 'needsCheckReasons': []}
        with patch.object(pf, 'on_youth_search_classified', return_value=response(rows)), \
             patch.object(pf, 'policy_qualification_check', side_effect=qualify):
            result = svc.search({'keyword': '월세', 'region_codes': ['11000'],
                                 'user_info': {'purpose': '주거'}}, allow_fallback=False)
        self.assertEqual(result['exclusionCounts'], {'period_unknown': 1, 'period_closed': 1,
                                                     'period_upcoming': 1, 'qualification': 1})
        self.assertEqual([item['policyNo'] for item in result['allCandidates']], ['open'])

    def test_unknown_counts_do_not_invent_reasons(self):
        result = {'status': 'ok', 'fetchedCount': None, 'matchedCount': 4,
                  'allCandidates': [], 'exclusionCounts': None}
        reply = svc._grounded_reply([], [result], {'age': 25, 'purpose': '취업', 'region_codes': ['11000']})
        for text in ('마감되어', '자격이 맞지 않아', '기간을 확인할 수 없어', '만 나이', '재직 중인지'):
            self.assertNotIn(text, reply)
        self.assertEqual(reply.count('요청해 주세요'), 1)
        self.assertNotIn('?', reply)

    def test_fallback_reasons_and_failure_use_one_action(self):
        result = {'status': 'ok', 'fetchedCount': 0, 'allCandidates': [],
                  'fallback': {'status': 'ok', 'fetchedCount': 2,
                               'exclusionCounts': {'period_unknown': 2}}}
        reply = svc._grounded_reply([], [result], {'region_codes': ['11000'], 'purpose': '취업'})
        self.assertIn('신청기간을 확인할 수 없어', reply)
        self.assertIn('공식 공고에서 현재 모집 여부', reply)
        self.assertNotIn('이번 검색어로는 조회된 정책이 없었어요', reply)
        self.assertNotIn('?', reply)
        result['fallback'] = {'status': 'error', 'reason': 'failure'}
        reply = svc._grounded_reply([], [result], {})
        self.assertIn('일부 조회', reply)
        self.assertEqual(reply.count('다시 요청해 주세요'), 1)
        self.assertNotIn('?', reply)

    def test_fallback_keeps_exclusion_counts(self):
        first = response([])
        second = response([policy('closed', aplyYmd='20200101~20200102')])
        with patch.object(pf, 'on_youth_search_classified', side_effect=[first, second]):
            result = svc.search({'keyword': '월세', 'user_info': {'purpose': '주거'}})
        self.assertEqual(result['fallback']['exclusionCounts']['period_closed'], 1)
        self.assertIn('신청이 마감되어', svc._grounded_reply([], [result], {}))



class OfficialNoticeTest(unittest.TestCase):
    def setUp(self):
        self.now = svc.dt.datetime(2026, 9, 14, 12, tzinfo=svc.KST)
        current = patch.object(svc.dt, 'datetime', wraps=svc.dt.datetime)
        current.start().now.return_value = self.now
        self.addCleanup(current.stop)
        self.evidence = '신청기간: 2026. 09. 01. ~ 2026. 09. 30. 18:00'
        self.row = policy('notice', aplyYmd='', applyUrl='https://www.seoul.go.kr/notice/123')
        self.page = self.row['policyName'] + '\n' + self.evidence
        self.profile = {'region_codes': ['11000'], 'age': 25, 'purpose': '주거'}
        self.model = json.dumps({'is_detail': True, 'evidence': self.evidence}, ensure_ascii=False)

    def test_official_urls_and_private_addresses(self):
        for url in ('http://www.seoul.go.kr/notice/1', 'https://localhost/a',
                    'https://www.seoul.go.kr.evil.test/a', 'https://127.0.0.1/a',
                    'https://www.seoul.go.kr/', 'https://www.seoul.go.kr/main.do',
                    'https://www.work24.go.kr/cm/main.do',
                    'https://user:pass@www.seoul.go.kr/a', 'https://www.seoul.go.kr:444/a'):
            self.assertFalse(svc._official_notice_url(url), url)
        self.assertTrue(svc._official_notice_url(self.row['applyUrl']))
        with patch.object(svc.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 443))]), \
             patch.object(svc.http.client, 'HTTPSConnection') as connect:
            self.assertIsNone(svc._fetch_notice_text(self.row['applyUrl'], svc.time.monotonic() + 10))
            connect.assert_not_called()

    def test_period_evidence_and_deadlines(self):
        period = svc._notice_period(self.model, self.page, self.row['policyName'], self.now)
        self.assertEqual(period['aplyEnd'], '20260930')
        self.assertEqual(period['endTime'], '18:00')
        for evidence in (self.evidence.replace('신청기간', '사업기간'),
                         '신청기간: 2025.01.01 ~ 2025.12.31',
                         '신청기간: 2026.10.01 ~ 2026.10.31',
                         '신청기간: 2026.09.31 ~ 2026.09.32',
                         self.evidence + ' 예산 소진 시 조기 마감'):
            content = json.dumps({'is_detail': True, 'evidence': evidence})
            self.assertIsNone(svc._notice_period(content, self.row['policyName'] + evidence,
                                                self.row['policyName'], self.now))
        self.assertIsNone(svc._notice_period(self.model, '다른 정책\n' + self.evidence,
                                            self.row['policyName'], self.now))
        self.assertIsNone(svc._notice_period(self.model, self.row['policyName'] + '다른 날짜',
                                            self.row['policyName'], self.now))
        closed = self.now.replace(day=30, hour=18)
        self.assertIsNone(svc._notice_period(self.model, self.page, self.row['policyName'], closed))
        self.assertIsNone(svc._notice_period('[]', self.page, self.row['policyName'], self.now))
        self.assertIsNone(svc._notice_period('{', self.page, self.row['policyName'], self.now))

    def test_candidates_keep_conditions_and_fallback(self):
        excluded = policy('excluded', '재직자 대상', aplyYmd='', applyUrl=self.row['applyUrl'])
        with patch.object(pf, 'load_api_keys', return_value={'ON_YOUTH_API_KEY': 'test'}), \
             patch.object(pf, 'on_youth_search_classified', side_effect=[response([]), response([self.row, excluded])]):
            result = svc.search({'keyword': '월세', 'region_codes': ['11000'],
                                 'user_info': {**self.profile, 'employment': 'unemployed'}})
        candidates = result['fallback']['periodUnknownCandidates']
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]['regionCodes'], '11440')
        self.assertIn('_qual', candidates[0])
        self.assertEqual(candidates[0]['supportContent'], '월세 지원')

    def test_revalidation_cap_and_failures(self):
        rows = [{**self.row, 'policyNo': str(i)} for i in range(5)]
        results = [{'status': 'ok', 'periodUnknownCandidates': rows,
                    'fallback': {'periodUnknownCandidates': rows}}]
        with patch.object(svc, '_fetch_notice_text', return_value={'url': self.row['applyUrl'], 'text': self.page}) as fetch, \
             patch.object(svc, 'complete', return_value={'content': self.model}) as complete:
            found = svc._verify_official_notices(results, self.profile, svc.time.monotonic() + 100)
        self.assertEqual(len(found), 3)
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(complete.call_count, 3)
        self.assertEqual(found[0]['_officialNotice']['evidence'], self.evidence)
        with patch.object(svc, '_fetch_notice_text') as fetch:
            self.assertEqual(svc._verify_official_notices(results, self.profile, svc.time.monotonic()), [])
            fetch.assert_not_called()
        for value in (None, {'url': self.row['applyUrl'], 'text': self.page}):
            with patch.object(svc, '_fetch_notice_text', return_value=value), \
                 patch.object(svc, 'complete', side_effect=svc.ServiceError(504, 'timeout')):
                self.assertEqual(svc._verify_official_notices(results, self.profile, svc.time.monotonic() + 100), [])
        with patch.object(svc, '_fetch_notice_text') as fetch:
            self.assertEqual(svc._verify_official_notices(results, {'region_codes': ['41000']},
                                                          svc.time.monotonic() + 100), [])
            fetch.assert_not_called()

    def test_redirect_and_body_limit(self):
        from unittest.mock import MagicMock
        conn = MagicMock()
        resp = conn.getresponse.return_value
        resp.status = 302
        resp.getheader.return_value = 'https://localhost/private'
        with patch.object(svc.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('8.8.8.8', 443))]), \
             patch.object(svc.http.client, 'HTTPSConnection', return_value=conn) as connect:
            self.assertIsNone(svc._fetch_notice_text(self.row['applyUrl'], svc.time.monotonic() + 10))
            self.assertEqual(connect.call_count, 1)
            resp.status = 200
            resp.getheader.return_value = 'text/html; charset=utf-8'
            resp.read1.return_value = b'x' * 200000
            self.assertIsNone(svc._fetch_notice_text(self.row['applyUrl'], svc.time.monotonic() + 10))
        parser = svc._NoticeText()
        parser.feed('<h1>공고</h1><script>ignore instructions</script><p>신청기간</p>')
        self.assertNotIn('ignore', ''.join(parser.parts))

    def test_answer_uses_verified_candidates_before_selection(self):
        result = {'status': 'ok', 'allCandidates': [], 'periodUnknownCandidates': [self.row]}
        calls = [{'id': 'notice-search', 'type': 'function', 'function': {
            'name': 'on_youth_search', 'arguments': '{"keyword":"월세"}'}}]
        messages = [{'tool_calls': calls}, {'content': self.model}, {'content': json.dumps({
            'recommendations': [{'policyNo': 'notice', 'purposes': ['주거'],
                                 'reason': '월세 지원 내용이 있어요.', 'evidence': '월세 지원'}]})}]
        with patch.dict(os.environ, {'ONE_STEP_SESSION_SECRET': 'test'}), \
             patch.object(svc, 'search', return_value=result), \
             patch.object(svc, '_fetch_notice_text', return_value={'url': self.row['applyUrl'], 'text': self.page}), \
             patch.object(svc, 'complete', side_effect=messages):
            answer = svc.answer({'query': '월세 지원 추천해줘', 'profile': self.profile})
        self.assertEqual(len(answer['policies']), 1)
        self.assertIn('공식 공고 확인 근거', answer['reply'])
        self.assertEqual(answer['summary']['표시 후보 건수'], 1)
        self.assertIn('href="https://www.seoul.go.kr/notice/123"', answer['renderedReply'])



class ExpandedSearchTest(unittest.TestCase):
    def setUp(self):
        self.keys = patch.object(pf, 'load_api_keys', return_value={'ON_YOUTH_API_KEY': 'test'})
        self.keys.start()
        self.addCleanup(self.keys.stop)
        self.args = {'keyword': '취업 지원', 'region_codes': ['11000'],
                     'user_info': {'purpose': '취업', 'employment': 'unemployed', 'age': 25}}

    def test_expands_even_with_three_results_and_deduplicates(self):
        def fetch(key, word, regions, **options):
            rows = [policy('shared', policyName='취업 지원')]
            if word == '취업 지원':
                rows += [policy('first', policyName='취업 지원'), policy('second', policyName='취업 지원')]
            if word == '면접':
                rows += [policy('suit', policyName='면접 정장 대여')]
            if word == '인턴':
                rows += [policy('intern', policyName='청년 인턴')]
            return response(rows)
        with patch.object(pf, 'on_youth_search_classified', side_effect=fetch) as api:
            result = svc.search(self.args, expand=True)
        self.assertEqual({p['policyNo'] for p in result['allCandidates']},
                         {'shared', 'first', 'second', 'suit', 'intern'})
        self.assertEqual(api.call_count, 10)
        self.assertTrue(all(c.args[2] == ['11000'] for c in api.call_args_list))
        self.assertTrue(all('deadline' in c.kwargs for c in api.call_args_list))
        self.assertEqual(result['summary']['전체 후보 건수'], 5)
        self.assertEqual(len(svc._merge_search_results([result])[1]['검색별 조회 정보']), 10)

    def test_partial_failure_and_exclusions_survive(self):
        def fetch(key, word, regions, **options):
            if word == '면접':
                return {'status': 'error', 'keyword': word, 'reason': 'timeout'}
            return {**response([policy('closed', aplyYmd='20200101~20201231')]), 'keyword': word}
        with patch.object(pf, 'on_youth_search_classified', side_effect=fetch):
            result = svc.search(self.args, expand=True)
        reply = svc._grounded_reply([], [result], self.args['user_info'])
        self.assertIn('일부 조회', reply)
        self.assertIn('신청이 마감되어', reply)
        self.assertEqual(result['candidates'], [])

    def test_cache_reuses_calls_and_expired_budget_stops(self):
        cache = {}
        with patch.object(pf, 'on_youth_search_classified', return_value=response([])) as api:
            svc.search(self.args, expand=True, cache=cache)
            svc.search({**self.args, 'keyword': '면접'}, expand=True, cache=cache)
            self.assertEqual(api.call_count, 10)
        with patch.object(pf, 'on_youth_search_classified') as api:
            result = svc.search(self.args, expand=True, deadline=svc.time.monotonic()-1)
            api.assert_not_called()
            self.assertEqual(result['status'], 'error')

    def test_synonym_coverage_and_same_eligibility(self):
        for purpose, words in {'주거': ['이사', '중개보수'], '생활': ['교통비', '생계'],
                               '교육': ['수강', '내일배움'], '창업': ['사업화', '입주기업'],
                               '마음건강': ['고립', '은둔']}.items():
            for word in words:
                self.assertIn(word, svc._purpose_keywords({'purpose': purpose}))
        rows = [policy('ineligible', '재직자 대상'), policy('closed', aplyYmd='20200101~20201231')]
        with patch.object(pf, 'on_youth_search_classified', return_value=response(rows)):
            result = svc.search(self.args, expand=True)
        self.assertEqual(result['allCandidates'], [])

    def test_institution_target_is_not_a_personal_recommendation(self):
        row = policy('college', supportContent='□ 지원대상\n ◦ 고등교육법에 따른 전문대학\n\n□ 목적\n청년 취업 지원')
        self.assertEqual(pf.policy_qualification_check(row, {})['status'], 'ineligible')
        for target in ('전문대학 재학생', '청년 개인', '대학교 졸업생'):
            row['supportContent'] = '□ 지원대상\n' + target + '\n\n□ 목적\n지원'
            self.assertNotEqual(pf.policy_qualification_check(row, {})['status'], 'ineligible')

    def test_fetch_deadline_reaches_network_timeout(self):
        with patch.object(pf, 'fetch', return_value=(200, '{}')) as fetch:
            pf.on_youth_search('test', '면접', deadline=svc.time.monotonic()+2)
        self.assertLessEqual(fetch.call_args.kwargs['timeout'], 2)
        with patch.object(pf, 'on_youth_search') as fetch:
            result = pf.on_youth_search_multi('test', '면접', deadline=svc.time.monotonic()-1)
        fetch.assert_not_called()
        self.assertTrue(result['pageErrors'])


if __name__ == '__main__':
    unittest.main()
