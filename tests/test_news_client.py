import tempfile
import unittest
from pathlib import Path

from toss_auto_trader import db
from toss_auto_trader.news_client import _strip_html, NewsItem


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


if __name__ == '__main__':
    unittest.main()
