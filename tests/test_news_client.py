import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from toss_auto_trader import db
from toss_auto_trader.news_client import _strip_html, NewsClientError, NewsHub, NewsItem


class NewsClientTests(unittest.TestCase):
    def test_strip_html_naver_markup(self):
        self.assertEqual(_strip_html('<b>삼성전자</b> &amp; AI'), '삼성전자 & AI')

    def test_news_item_as_dict(self):
        item = NewsItem(provider='x', title='t', url='u', sentiment=0.1)
        data = item.as_dict()
        self.assertEqual(data['provider'], 'x')
        self.assertEqual(data['sentiment'], 0.1)

    def test_insert_news_items_dedupes_same_provider_query_title_url_published_at(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'news.sqlite3'
            item = NewsItem(provider='naver', title='AAA 공급계약 수주', url='https://example.com/a', published_at='2026-01-01').as_dict()
            first = db.insert_news_items(str(path), 'AAA 주가', [item])
            second = db.insert_news_items(str(path), 'AAA 주가', [item])
            self.assertEqual(first, 1)
            self.assertEqual(second, 0)
            self.assertEqual(db.summary(str(path))['news_count'], 1)

    def test_opendart_disclosures_paginates_and_maps_receipt_metadata(self):
        hub = NewsHub()
        hub.limiters["opendart"].policy.min_interval_seconds = 0
        responses = [
            {
                "status": "000",
                "total_page": 2,
                "list": [
                    {
                        "rcept_no": "202607300001",
                        "rcept_dt": "20260730",
                        "stock_code": "123456",
                        "corp_name": "테스트전자",
                        "report_nm": "유상증자결정",
                    }
                ],
            },
            {
                "status": "000",
                "total_page": 2,
                "list": [
                    {
                        "rcept_no": "202607290001",
                        "rcept_dt": "20260729",
                        "stock_code": "654321",
                        "corp_name": "샘플",
                        "report_nm": "단일판매공급계약체결",
                    }
                ],
            },
        ]

        with patch.dict("os.environ", {"OPENDART_API_KEY": "x"}, clear=False):
            with patch.object(hub, "_request_json", side_effect=responses) as request:
                items = hub.opendart_disclosures(
                    begin_date="2026-07-27",
                    end_date="2026-07-30",
                    max_pages=2,
                )

        self.assertEqual(request.call_count, 2)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].provider, "opendart")
        self.assertEqual(items[0].published_at, "2026-07-30")
        self.assertEqual(items[0].raw["stock_code"], "123456")
        self.assertIn("202607300001", items[0].url)

    def test_opendart_requires_key(self):
        hub = NewsHub()
        with patch.dict("os.environ", {"OPENDART_API_KEY": "", "DART_API_KEY": ""}, clear=False):
            with self.assertRaises(NewsClientError):
                hub.opendart_disclosures(begin_date="2026-07-30", end_date="2026-07-30")


if __name__ == '__main__':
    unittest.main()
