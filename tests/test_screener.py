import unittest
from decimal import Decimal

from toss_auto_trader.screener import score_news_titles
from toss_auto_trader.cli import parse_pair_spec


class ScreenerScoringTests(unittest.TestCase):
    def test_news_score_rewards_positive_and_penalizes_negative(self):
        self.assertGreater(score_news_titles(["자사주 취득 성장 기대"]), Decimal("0"))
        self.assertLess(score_news_titles(["투자경고 우려 급락"]), Decimal("0"))

    def test_parse_pair_spec(self):
        self.assertEqual(parse_pair_spec("336570:6000+462860:4000"), [("336570", Decimal("6000")), ("462860", Decimal("4000"))])


if __name__ == "__main__":
    unittest.main()
