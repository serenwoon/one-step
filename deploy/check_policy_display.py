"""신청 기간 경계와 링크가 섞인 답변의 회귀 검증."""
import datetime as dt
import sys
import unittest
from pathlib import Path
from html.parser import HTMLParser
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import solar_service as s

class DisplayTest(unittest.TestCase):
    def period(self, raw, day='2026-09-13T12:00:00+09:00'):
        return s._normalize_apply_period({'aplyYmd': raw}, dt.datetime.fromisoformat(day))['status']

    def test_ranges(self):
        for raw, status in [('20260913 ~ 20260913', '신청 중'),
                            ('20260914~20260930', '신청 예정'),
                            ('20260330 ~ 20260529', '신청 마감'),
                            ('2026-09-01 ~ 2026-09-30', '신청 중'),
                            ('20260230~20260930', '확인 필요'),
                            ('20260930~20260901', '확인 필요'),
                            ('상시 / 예산 소진 시', '확인 필요'),
                            ('20260901~', '확인 필요'),
                            ('', '확인 필요')]:
            with self.subTest(raw=raw): self.assertEqual(self.period(raw), status)

    def test_closing_time(self):
        raw = '20260901~20260913 12:00'
        self.assertEqual(self.period(raw, '2026-09-13T11:59:00+09:00'), '신청 중')
        self.assertEqual(self.period(raw), '신청 마감')
        self.assertEqual(self.period('20260901~20260913 25:00'), '확인 필요')

    def test_korean_date_boundary(self):
        self.assertEqual(self.period('20260914~20260915', '2026-09-13T15:00:00+00:00'), '신청 중')

    def test_mixed_links(self):
        class Links(HTMLParser):
            def __init__(self): super().__init__(); self.links=[]; self.tags=[]
            def handle_starttag(self, tag, attrs):
                self.tags.append(tag)
                if tag == 'a': self.links.append(dict(attrs))
        parser=Links()
        parser.feed(s._safe_render_reply('https://a.com [링크](https://b.com) [](https://c.com) <img src=x onerror=alert(1)>'))
        self.assertEqual([x['href'] for x in parser.links], ['https://a.com','https://b.com','https://c.com'])
        self.assertNotIn('img',parser.tags)
        self.assertTrue(all(x['target']=='_blank' for x in parser.links))

if __name__ == '__main__': unittest.main()
