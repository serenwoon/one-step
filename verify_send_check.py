#!/usr/bin/env python3
"""로컬 통합 서버에서 send-check 웹 연결과 API 응답 구조를 검증한다.
Solar API 호출만 목업으로 대체하되, 키는 one-step .env에서 읽어 실제 코드 경로를 통과한다.
/ask는 api.ask.answer를 목업으로 대체해 정책 카드/빈 검색 안내 응답을 확인한다.
"""
import unittest
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import solar_service as ss_mod
import skills.send_check.check_draft as cd_mod
from local_ask_server import Router
from policy_fetch import load_env


def _load_upstage_key():
    hermes_env_path = Path.home() / '.hermes' / 'profiles' / 'one-step' / '.env'
    env = load_env(str(hermes_env_path))
    key = (env.get('UPSTAGE_API_KEY') or '').strip()
    if key:
        os.environ['UPSTAGE_API_KEY'] = key
        return True
    return False


def mock_complete_ok(messages, tools, deadline, **kwargs):
    return {'content': json.dumps({'inspection': '문의 의도는 잘 전달돼요. 확인할 항목을 구체적으로 쓰면 더 명확해요.',
                                  'recommendedDraft': '안녕하세요. 신청 자격과 필요한 서류를 안내해 주실 수 있을까요?'}, ensure_ascii=False)}


def mock_complete_error(messages, tools, deadline, **kwargs):
    raise ss_mod.ServiceError(500, '모델 응답 중 문제가 생겼어요.')


def mock_answer_policies(data):
    return {
        'reply': '청년 취업 지원 정책 2건을 찾았어요.',
        'conversation': 'state-with-policies',
        'profile': None,
        'policies': [
            {
                'policyName': '서울시 청년 취업 지원',
                'orgName': '서울특별시 청년취업지원센터',
                '_org': '서울특별시 청년취업지원센터',
                '_applyPeriod': {'status': '신청 중', 'raw': '2026-09-01 ~ 2026-12-31', 'today': '2026-09-13'},
                '_qual': {'matchedReasons': ['연령 조건 유사'], 'needsCheckReasons': ['최종 자격은 공고 확인']},
                '_relevance': {'status': 'matched', 'reason': '취업 지원 목적과 유사한 정책'},
                'applyUrl': 'https://example.com/apply-seoul',
            },
            {
                'policyName': '경기 청년 구직 지원',
                'orgName': '경기도 일자리재단',
                '_org': '경기도 일자리재단',
                '_applyPeriod': {'status': '신청 중', 'raw': '2026-08-15 ~ 2026-11-30', 'today': '2026-09-13'},
                '_qual': {'matchedReasons': ['구직 활동'], 'needsCheckReasons': ['거주지 확인']},
                '_relevance': {'status': 'matched', 'reason': '취업 목적과 일치'},
                'applyUrl': 'https://example.com/apply-gg',
            },
        ],
        'summary': {
            '전체 후보 건수': 5,
            '표시 후보 건수': 2,
            '검색별 조회 정보': [{'status': 'ok', 'keyword': '청년 취업 지원', 'fetchedCount': 5, 'matchedCount': 5}],
        },
        'query': '',
    }


def mock_answer_empty(data):
    return {
        'reply': '이번 범위에서는 조건에 맞는 접수 중 정책을 찾지 못했어요.',
        'conversation': 'state-empty',
        'profile': None,
        'policies': [],
        'summary': {
            '검색별 조회 정보': [{'status': 'ok', 'keyword': '청년 취업 지원', 'fetchedCount': 3, 'matchedCount': 0}],
        },
        'query': '',
    }


def post(base, path, body, timeout=6):
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    req = urllib.request.Request(
        base + path, data=data,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return None, (str(e) or 'unknown').encode()


def get(base, path, timeout=3):
    try:
        with urllib.request.urlopen(base + path, timeout=timeout) as r:
            return r.status, r.read()
    except Exception as e:
        return None, (str(e) or 'unknown').encode()


def run():
    if not _load_upstage_key():
        print('[경고] one-step .env에서 UPSTAGE_API_KEY를 읽지 못함. check_draft 실제 경로 확인이 제한됨.')
        print('       이 경우 solar_service.calling_key()가 빈 키를 반환해 check_draft가 Solar 호출 전에 종료됨.')
    else:
        print('[키] one-step .env에서 UPSTAGE_API_KEY를 읽어 프로세스에 설정함 (값은 출력하지 않음)')

    server = ThreadingHTTPServer(('127.0.0.1', 0), Router)
    port = server.server_port
    thr = threading.Thread(target=server.serve_forever, daemon=True)
    thr.start()
    base = f'http://127.0.0.1:{port}'
    print(f'[서버] http://127.0.0.1:{port}')
    results = []

    # 1) 정적 미리보기
    s, b = get(base, '/')
    results.append(('GET /', s, b))
    html = b.decode('utf-8', 'replace')
    has_check_button = '문의 문구 점검' in html
    has_modal = 'id="check-modal"' in html
    has_check_endpoint_js = "/api/check_draft" in html
    results.append(('HTML 점검 버튼/모달/엔드포인트', has_check_button, has_modal, has_check_endpoint_js))

    # 2) GET /api/check_draft (프론트는 POST만 쓰지만, 라우트가 POST 전용인지 확인용)
    s, b = get(base, '/api/check_draft')
    results.append(('GET /api/check_draft', s, b))

    # 3) POST /api/check_draft - 정상 초안 (키 있음 + complete 목업)
    with patch.object(ss_mod, 'complete', mock_complete_ok):
        s, b = post(base, '/api/check_draft', {
            'draft': '안녕하세요. 이 정책의 신청 자격과 필요한 서류를 확인하고 싶습니다. 안내 부탁드립니다.',
            'keyword': '청년 취업 지원',
            'policyChoice': '서울시 청년 취업 지원',
            'policyContext': {'name': '서울시 청년 취업 지원', 'org': '서울특별시 청년취업지원센터', 'note': ''},
        })
    results.append(('POST check_draft 정상', s, b))

    # 4) POST /api/check_draft - 빈 초안
    with patch.object(ss_mod, 'complete', mock_complete_ok):
        s, b = post(base, '/api/check_draft', {
            'draft': '',
            'keyword': '',
            'policyChoice': '',
            'policyContext': None,
        })
    results.append(('POST check_draft 빈 초안', s, b))

    # 5) POST /api/check_draft - API 오류(Solar 호출 실패)
    with patch.object(ss_mod, 'complete', mock_complete_error):
        s, b = post(base, '/api/check_draft', {
            'draft': '안녕하세요. 신청 자격과 서류를 확인하고 싶습니다.',
            'keyword': '청년 취업 지원',
            'policyChoice': '서울시 청년 취업 지원',
            'policyContext': {'name': '서울시 청년 취업 지원', 'org': '서울특별시 청년취업지원센터', 'note': ''},
        })
    results.append(('POST check_draft API 오류', s, b))

    # 6) POST /ask - 정책 2건 있는 응답
    with patch('api.ask.answer', side_effect=mock_answer_policies):
        s, b = post(base, '/ask', {
            'query': '청년 취업 지원 정책을 찾아주세요.',
            'conversation': None,
            'profile': None,
        })
    results.append(('POST /ask 정책 있음 응답', s, b))

    # 7) POST /ask - 정책 0건 + 조회 성공(빈 검색 안내)
    with patch('api.ask.answer', side_effect=mock_answer_empty):
        s, b = post(base, '/ask', {
            'query': ' 청년 취업 지원 정책을 찾아주세요.',
            'conversation': None,
            'profile': None,
        })
    results.append(('POST /ask 정책 없음 응답', s, b))

    server.shutdown()
    server.server_close()
    thr.join(timeout=3)

    print('\n========== 결과 ==========')
    for item in results:
        label = item[0]
        if label.startswith('HTML'):
            print(f'\n[{label}]')
            print(' 점검 버튼 포함:', item[1])
            print(' 모달 포함:', item[2])
            print(' /api/check_draft 호출 코드 포함:', item[3])
            continue
        status = item[1]
        body = item[2]
        text = body.decode('utf-8', 'replace')
        try:
            data = json.loads(text)
            print(f'\n[{label}] 상태={status}')
            print(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception:
            print(f'\n[{label}] 상태={status} 본문(앞 300자)=')
            print(text[:300])

    print('\n========== 해석 ==========')
    normal = next((it for it in results if it[0] == 'POST check_draft 정상'), None)
    empty = next((it for it in results if it[0] == 'POST check_draft 빈 초안'), None)
    apierr = next((it for it in results if it[0] == 'POST check_draft API 오류'), None)
    ask_policies = next((it for it in results if it[0] == 'POST /ask 정책 있음 응답'), None)
    ask_empty = next((it for it in results if it[0] == 'POST /ask 정책 없음 응답'), None)

    def claim(cond, ok, ng):
        print(('OK ' if cond else 'NG ') + (ok if cond else ng))

    key_ok = os.environ.get('UPSTAGE_API_KEY')
    print('\n[전제] one-step 키 설정:', '있음' if key_ok else '없음')

    if normal:
        nd = json.loads(normal[2])
        claim(nd.get('status') == 'ok', '정상 초안: status=ok', f'정상 초안: status={nd.get("status")}')
        claim('check' in nd and isinstance(nd.get('check'), dict), '정상 초안: check 객체 있음', '정상 초안: check 객체 없음')
        claim(bool(nd.get('check', {}).get('inspection')), '정상 초안: 점검 문장 있음', '정상 초안: 점검 문장 없음')
        claim(nd.get('check', {}).get('draft') == '안녕하세요. 이 정책의 신청 자격과 필요한 서류를 확인하고 싶습니다. 안내 부탁드립니다.',
              '정상 초안: 원본 초안 보존됨', '정상 초안: 원본 초안 불일치')
        claim(nd.get('check', {}).get('policyChoice') == '서울시 청년 취업 지원',
              '정상 초안: 정책명 전달됨', '정상 초안: 정책명 불일치')
        claim(nd.get('preservedDraft') and nd.get('preservedDraft').get('draft') == nd.get('check', {}).get('draft'),
              '정상 초안: preservedDraft에 초안 보존됨', '정상 초안: 초안 보존 불일치')

    if empty:
        ed = json.loads(empty[2])
        claim(ed.get('status') == 'error' and '초안' in ed.get('reason', ''),
              '빈 초안: API가 error + 초안 입력 안내 반환', f'빈 초안: API 반환이 다름 ({ed.get("status")}/{ed.get("reason")})')

    if apierr:
        claim(apierr[0] == 500, 'API 오류: 500 반환', f'API 오류: 상태가 {apierr[0]} (500 아님)')
        claim(json.loads(apierr[2]).get('error') == '점검 처리 중 문제가 생겼어요. 다시 시도해 주세요.',
              'API 오류: 프론트가 쓸 수 있는 오류 메시지 반환', f'API 오류: 오류 메시지 다름 ({json.loads(apierr[2])})')

    if ask_policies:
        ad = json.loads(ask_policies[2])
        claim(ad.get('policies') and len(ad.get('policies', [])) >= 2,
              '정책 있음 응답: policies 배열 2건 이상', f'정책 있음 응답: policies 부족 ({len(ad.get("policies") or [])})')
        first = ad.get('policies', [{}])[0]
        claim(first.get('policyName'), '정책 있음 응답: 정책명 있음', '정책 있음 응답: 정책명 없음')
        claim(bool(first.get('orgName') or first.get('_org')),
              '정책 있음 응답: 기관명(orgName/_org) 있음', '정책 있음 응답: 기관명 없음')
        claim(ad.get('query') in (None, ''),
              '정책 있음 응답: query 없음 — 프론트는 입력한 text로 정책 카드 키워드 전달', '정책 있음 응답: query가 있음')
        second = ad.get('policies', [{}])[1]
        claim(second.get('policyName') and second.get('orgName'),
              '정책 있음 응답: 두 번째 카드도 정책명·기관명 있음', '정책 있음 응답: 두 번째 카드 정보 부족')

    if ask_empty:
        ed2 = json.loads(ask_empty[2])
        claim(not ed2.get('policies') or len(ed2.get('policies', [])) == 0,
              '정책 없음 응답: policies 0건', '정책 없음 응답: 정책이 있음')
        claim(any(it.get('status') == 'ok' for it in ed2.get('summary', {}).get('검색별 조회 정보', [])),
              '정책 없음 응답: 조회 성공인데 후보 없음 — 프론트가 빈 검색 안내를 띄움', '정책 없음 응답: 조회 성공 정황이 없음')

    print('\n Hinweis: 위 확인은 서버 코드와 응답 구조 기준이다.')
    print(' “HTML 점검 버튼 포함=True”는 코드 수준이며, 브라우저에서 실제 클릭·모달·전송·수정 후 재점검·복사가 동작하는지와는 구분한다.')
    print(' “실제 후보 없음 → 테스트용 카드” 구분 화면은 브라우저 렌더링 검증이 필요하다. 지금은 정책 없음 응답에서 프론트가 빈 검색 안내를 띄우는 구조만 확인했다.')
    print(' 브라우저 동작 검증은 로컬 서버에서 실제 index.html을 열어 정책 카드·모달·전송·오류 화면을 직접 확인하는 단계로 남는다.')


class SendCheckTest(unittest.TestCase):
    def setUp(self):
        key = patch.dict(os.environ, {'UPSTAGE_API_KEY': 'test-only', 'ONE_STEP_SESSION_SECRET': 'test-only'})
        key.start()
        self.addCleanup(key.stop)

    def test_short_inquiry_is_checked_by_solar(self):
        draft = '신청 자격을 확인하고 싶습니다.'
        with patch.object(ss_mod, 'complete', return_value={'content': json.dumps({'inspection': '검증용 점검 결과', 'recommendedDraft': draft})}) as model:
            result = cd_mod.check_draft('', '정책', draft, {'name': '정책'})
        self.assertEqual(model.call_count, 1)
        messages = model.call_args.args[0]
        self.assertIn('입력 조건 추출로 전환하지 않는다', messages[0]['content'])
        self.assertNotIn('profile_updates', messages[-1]['content'])
        self.assertEqual(result['check']['draft'], draft)
        self.assertEqual(result['check']['inspection'], '검증용 점검 결과')

    def test_empty_and_invalid_context_do_not_call_solar(self):
        with patch.object(ss_mod, 'complete') as model:
            for keyword, draft, context in [('', '', None), ([], '문의합니다.', None),
                                             ('', '문의합니다.', {'name': []})]:
                result = cd_mod.check_draft(keyword, '', draft, context)
                self.assertEqual(result['status'], 'error')
        model.assert_not_called()

    def test_generate_uses_profile_and_returns_separate_draft(self):
        content = {'inspection': '알려준 상황을 바탕으로 문의를 준비했어요.',
                   'recommendedDraft': '안녕하세요. 만 25세 미취업 상태입니다. 신청 조건을 확인하고 싶습니다.'}
        with patch.object(ss_mod, 'complete', return_value={'content': json.dumps(content)}) as model:
            result = cd_mod.check_draft('', '장학사업', '', {'name': '장학사업'},
                                        action='generate', profile={'age': 25, 'employment': 'unemployed'})
        self.assertEqual(result['check']['draft'], '')
        self.assertEqual(result['check']['recommendedDraft'], content['recommendedDraft'])
        sent = json.loads(model.call_args.args[0][-1]['content'])
        self.assertEqual(sent['profile']['age'], 25)
        self.assertNotIn('income', sent['profile'])
        with patch.object(ss_mod, 'complete') as model:
            self.assertEqual(cd_mod.check_draft('', '', '', action='generate')['status'], 'error')
            model.assert_not_called()

    def test_check_uses_current_draft_without_old_profile(self):
        draft = '저는 26세 대학생입니다. 신청 서류를 문의합니다.'
        with patch.object(ss_mod, 'complete', return_value={'content': json.dumps({
                'inspection': '신청 서류를 묻는 정중한 문장이에요.', 'recommendedDraft': draft})}) as model:
            result = cd_mod.check_draft('', '장학사업', draft, profile={'age': 25})
        self.assertEqual(result['check']['draft'], draft)
        sent = json.loads(model.call_args.args[0][-1]['content'])
        self.assertEqual(sent['profile'], {})
        self.assertEqual(sent['draft'], draft)
        self.assertEqual(model.call_args.kwargs['response_format'], {'type': 'json_object'})

    def test_bad_output_and_invented_amount_are_rejected(self):
        for content in ('[]', 'not json', json.dumps({'inspection': '점검', 'recommendedDraft': ''}),
                        json.dumps({'inspection': '점검', 'recommendedDraft': '제 소득은 999만원입니다.'})):
            with patch.object(ss_mod, 'complete', return_value={'content': content}):
                result = cd_mod.check_draft('', '정책', '신청 조건을 문의합니다.')
            self.assertEqual(result['status'], 'error')

    def test_http_generate_preserves_original(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Router)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with patch.object(ss_mod, 'complete', mock_complete_ok):
                status, body = post('http://127.0.0.1:' + str(server.server_port), '/api/check_draft',
                                    {'action': 'generate', 'draft': '', 'policyChoice': '청년 지원'})
            result = json.loads(body)
            self.assertEqual(status, 200)
            self.assertEqual(result['status'], 'ok')
            self.assertEqual(result['preservedDraft']['draft'], '')
            self.assertTrue(result['check']['recommendedDraft'])
        finally:
            server.shutdown()
            server.server_close()

    def test_solar_failure_and_blank_response(self):
        with patch.object(ss_mod, 'complete', side_effect=ss_mod.ServiceError(502, '연결 실패')):
            self.assertEqual(cd_mod.check_draft('', '', '서류를 확인하고 싶습니다.')['status'], 'error')
        with patch.object(ss_mod, 'complete', return_value={'content': ''}):
            self.assertEqual(cd_mod.check_draft('', '', '서류를 확인하고 싶습니다.')['status'], 'error')

    def test_generate_invents_career_then_regenerates_clean(self):
        first = {'inspection': '점검', 'recommendedDraft': '저는 3년 경력이고 월 200만원 소득입니다. 신청 절차를 문의드립니다.'}
        second = {'inspection': '다시 점검', 'recommendedDraft': '신청 절차와 필요한 서류를 문의드립니다.'}
        with patch.object(ss_mod, 'complete', side_effect=[
            {'content': json.dumps(first)},
            {'content': json.dumps(second)},
        ]) as model:
            result = cd_mod.check_draft('', '청년 지원', '', {'name': '청년 지원'},
                                       action='generate', profile={'age': 25})
        self.assertEqual(model.call_count, 2)
        self.assertEqual(result['status'], 'ok')
        self.assertNotIn('경력', result['check']['recommendedDraft'])
        self.assertNotIn('200만원', result['check']['recommendedDraft'])
        self.assertIn('신청 절차', result['check']['recommendedDraft'])

    def test_generate_invents_income_twice_preserves_draft_and_errors(self):
        bad = {'inspection': '점검', 'recommendedDraft': '저는 연 3000만원 소득이고 청년입니다.'}
        with patch.object(ss_mod, 'complete', return_value={'content': json.dumps(bad)}):
            result = cd_mod.check_draft('', '청년 지원', '안녕하세요.', {'name': '청년 지원'},
                                       action='generate', profile={'age': 25})
        self.assertEqual(result['status'], 'error')
        self.assertIn('입력하지 않은 개인 정보', result['reason'])
        self.assertNotIn('경력', result['reason'])

    def test_check_preserves_original_and_does_not_invent_facts(self):
        draft = '신청 자격을 확인하고 싶습니다.'
        with patch.object(ss_mod, 'complete', return_value={'content': json.dumps({
                'inspection': '신청 자격을 묻는 정중한 문장이에요.',
                'recommendedDraft': '신청 자격을 확인하고 싶습니다.'})}):
            result = cd_mod.check_draft('', '장학사업', draft, profile={'age': 25})
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['check']['draft'], draft)
        self.assertNotIn('재학', result['check']['recommendedDraft'])
        self.assertNotIn('소득', result['check']['recommendedDraft'])


    def test_fact_questions_and_user_provided_facts(self):
        for text, profile, draft in (
            ('경력 3년이 필요한가요? 소득 기준과 준비 서류를 알려주세요.', {}, ''),
            ('3년 경력이 필요한가요?', {}, ''),
            ('저는 25세이고 미취업 상태입니다.', {'age': 25, 'employment': 'unemployed'}, ''),
            ('저는 3년 경력입니다. 신청 절차를 알려주세요.', {}, '저는 3년 경력입니다.'),
        ):
            with self.subTest(text=text):
                self.assertTrue(cd_mod._check_no_invented_personal_facts(text, profile, draft, {})[0])
        for text in ('저는 3년 경력입니다.', '저는 취업을 희망합니다.', '저는 경력이 없어요.'):
            self.assertFalse(cd_mod._check_no_invented_personal_facts(
                text, {}, '', {'note': '3년 경력. 취업을 희망합니다. 경력이 없어요.'})[0])
        self.assertFalse(cd_mod._check_no_invented_personal_facts(
            '저는 25세입니다.', {'age': 25}, '저는 26세입니다.', {})[0])

    def test_check_retries_once_and_preserves_original(self):
        draft = '신청 절차를 문의드립니다.'
        bad = {'content': json.dumps({'inspection': '점검', 'recommendedDraft': '저는 경력이 없어요.'})}
        good = {'content': json.dumps({'inspection': '정중한 문의예요.', 'recommendedDraft': draft})}
        for responses, expected in (([good], 'ok'), ([bad, good], 'ok'), ([bad, bad], 'error')):
            with patch.object(ss_mod, 'complete', side_effect=responses) as model:
                result = cd_mod.check_draft('', '지원', draft)
            self.assertEqual(result['status'], expected)
            self.assertEqual(model.call_count, len(responses))
            deadlines = [call.kwargs['deadline'] for call in model.call_args_list]
            self.assertEqual(len(set(deadlines)), 1)
            if expected == 'ok':
                self.assertEqual(result['check']['draft'], draft)
            else:
                self.assertNotIn('check', result)
                self.assertIn('유지', result['reason'])


if __name__ == '__main__':
    unittest.main()
