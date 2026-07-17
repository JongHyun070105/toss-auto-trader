import importlib.util
import tempfile
import unittest
from pathlib import Path

from toss_auto_trader.toss_client import TossApiError


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

    def test_stock_not_found_is_soft_skip(self):
        mod = load_cache_toss_candles_daily()
        exc = TossApiError(
            404,
            "Not Found",
            '{"error":{"code":"stock-not-found","message":"종목을 찾을 수 없습니다."}}',
        )
        self.assertEqual(mod.toss_error_code(exc), "stock-not-found")
        self.assertTrue(mod.is_soft_skip_error(exc))

    def test_non_stock_not_found_is_hard_failure(self):
        mod = load_cache_toss_candles_daily()
        exc = TossApiError(500, "Server Error", '{"error":{"code":"internal"}}')
        self.assertFalse(mod.is_soft_skip_error(exc))

    def test_load_unsupported_symbols_ignores_comments_and_blanks(self):
        mod = load_cache_toss_candles_daily()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "unsupported.txt"
            path.write_text("# stale\n230360\n\n101390\n", encoding="utf-8")

            self.assertEqual(mod.load_unsupported_symbols(str(path)), {"230360", "101390"})

    def test_record_unsupported_symbols_deduplicates_existing_file(self):
        mod = load_cache_toss_candles_daily()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "unsupported.txt"
            path.write_text("230360\n", encoding="utf-8")

            recorded = mod.record_unsupported_symbols(str(path), {"101390", "230360"})

            self.assertEqual(recorded, ["101390"])
            self.assertEqual(path.read_text(encoding="utf-8").splitlines(), ["101390", "230360"])

    def test_load_symbols_skips_known_unsupported_before_limit(self):
        mod = load_cache_toss_candles_daily()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "symbols.txt"
            path.write_text("111111\n230360\n222222\n333333\n", encoding="utf-8")

            symbols = mod.load_symbols(str(path), limit=2, skip_symbols={"230360"})

            self.assertEqual(symbols, ["111111", "222222"])

    def test_stale_latest_symbols_reports_symbols_behind_run_latest(self):
        mod = load_cache_toss_candles_daily()

        rows = mod.stale_latest_symbols({"111111": "2026-07-08", "203690": "2026-07-07"})

        self.assertEqual(rows, [{"symbol": "203690", "latest_date": "2026-07-07", "run_latest_date": "2026-07-08"}])


if __name__ == "__main__":
    unittest.main()
