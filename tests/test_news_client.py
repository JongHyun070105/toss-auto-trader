import unittest

from toss_auto_trader.news_client import _strip_html, NewsItem


class NewsClientTests(unittest.TestCase):
    def test_strip_html_naver_markup(self):
        self.assertEqual(_strip_html('<b>삼성전자</b> &amp; AI'), '삼성전자 & AI')

    def test_news_item_as_dict(self):
        item = NewsItem(provider='x', title='t', url='u', sentiment=0.1)
        data = item.as_dict()
        self.assertEqual(data['provider'], 'x')
        self.assertEqual(data['sentiment'], 0.1)


if __name__ == '__main__':
    unittest.main()
