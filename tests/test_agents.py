import unittest

from toss_auto_trader.agents import news_analyst


class AgentTests(unittest.TestCase):
    def test_news_analyst_blocks_negative_news(self):
        op = news_analyst([{"title": "투자경고 우려 급락"}], {"selection": {"news_min_score": 45}})
        self.assertEqual(op.action, "HOLD")

    def test_news_analyst_allows_positive_news(self):
        op = news_analyst([{"title": "자사주 취득과 수주 성장 기대"}], {})
        self.assertEqual(op.action, "ALLOW")


if __name__ == "__main__":
    unittest.main()
