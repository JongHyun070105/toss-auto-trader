import unittest
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from toss_auto_trader.market import kr_observation_window_guard
from toss_auto_trader.orderbook_utils import market_impact_from_orderbook, timestamp_staleness


class GuardUtilityTests(unittest.TestCase):
    def test_market_impact_detects_top_level_exhaustion(self):
        payload = {
            'result': {
                'timestamp': '2026-06-24T10:00:00.000+09:00',
                'asks': [
                    {'price': '1000', 'volume': '1'},
                    {'price': '1010', 'volume': '10'},
                ],
                'bids': [{'price': '990', 'volume': '10'}],
            }
        }
        impact = market_impact_from_orderbook(payload, buy_cash_krw=Decimal('5000'), levels=2)
        self.assertTrue(impact['target_exceeds_top_level'])
        self.assertTrue(Decimal(impact['impact_bps']) > 0)
        self.assertTrue(impact['full_fill_within_levels'])

    def test_timestamp_staleness_guard(self):
        payload = {'result': {'timestamp': '2026-06-24T10:00:00.000+09:00', 'asks': [], 'bids': []}}
        now = datetime(2026, 6, 24, 10, 0, 0, 700000, tzinfo=ZoneInfo('Asia/Seoul'))
        stale = timestamp_staleness(payload, max_stale_ms=500, now=now)
        self.assertFalse(stale['ok'])
        self.assertGreater(stale['stale_ms'], 500)

    def test_kr_observation_window_blocks_auction_edges(self):
        kst = ZoneInfo('Asia/Seoul')
        self.assertFalse(kr_observation_window_guard(when=datetime(2026, 6, 24, 9, 3, tzinfo=kst))['ok'])
        self.assertTrue(kr_observation_window_guard(when=datetime(2026, 6, 24, 9, 6, tzinfo=kst))['ok'])
        self.assertFalse(kr_observation_window_guard(when=datetime(2026, 6, 24, 15, 25, tzinfo=kst))['ok'])


if __name__ == '__main__':
    unittest.main()
