import unittest

from toss_auto_trader.rate_limit import RateLimiter, RateLimitPolicy


class RateLimiterTests(unittest.TestCase):
    def test_min_interval_blocks_immediate_second_call(self):
        limiter = RateLimiter(RateLimitPolicy(min_interval_seconds=5, max_calls_per_minute=10, cooldown_seconds=60))
        self.assertTrue(limiter.can_call(now=100.0))
        limiter.record_call(now=100.0)
        self.assertFalse(limiter.can_call(now=101.0))
        self.assertTrue(limiter.can_call(now=105.0))

    def test_429_cooldown_blocks_calls(self):
        limiter = RateLimiter(RateLimitPolicy(min_interval_seconds=1, max_calls_per_minute=10, cooldown_seconds=30))
        limiter.record_429(now=100.0)
        self.assertFalse(limiter.can_call(now=120.0))
        self.assertTrue(limiter.can_call(now=131.0))


if __name__ == "__main__":
    unittest.main()
