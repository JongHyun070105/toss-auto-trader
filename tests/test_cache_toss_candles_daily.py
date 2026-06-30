import importlib.util
import unittest
from pathlib import Path


def load_cache_toss_candles_daily():
    path = Path(__file__).resolve().parents[1] / "scripts" / "cache_toss_candles_daily.py"
    spec = importlib.util.spec_from_file_location("cache_toss_candles_daily", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CacheTossCandlesDailyTests(unittest.TestCase):
    def test_normalize_daily_timestamp_matches_existing_db_key(self):
        mod = load_cache_toss_candles_daily()
        self.assertEqual(
            mod.normalize_daily_timestamp("2026-06-30T00:00:00.000+09:00"),
            "2026-06-30T00:00:00+09:00",
        )
        self.assertEqual(
            mod.normalize_daily_timestamp("2026-06-30T00:00:00+09:00"),
            "2026-06-30T00:00:00+09:00",
        )

    def test_normalize_candle_marks_source_toss(self):
        mod = load_cache_toss_candles_daily()
        row = mod.normalize_candle({"timestamp": "2026-06-30T00:00:00.000+09:00", "closePrice": "100"})
        self.assertEqual(row["timestamp"], "2026-06-30T00:00:00+09:00")
        self.assertEqual(row["currency"], "KRW")
        self.assertEqual(row["source"], "toss")


if __name__ == "__main__":
    unittest.main()
