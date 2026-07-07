from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from kosdaq_sma5_gate_deep_dive import IndexCandle, dates_for_slice, gate_rows  # noqa: E402


class KosdaqSma5GateDeepDiveTests(unittest.TestCase):
    def test_gate_rows_live_open_uses_previous_four_closes(self) -> None:
        rows = [
            IndexCandle("2026-01-01", 100.0, 100.0),
            IndexCandle("2026-01-02", 102.0, 102.0),
            IndexCandle("2026-01-03", 104.0, 104.0),
            IndexCandle("2026-01-04", 106.0, 106.0),
            IndexCandle("2026-01-05", 108.0, 108.0),
            IndexCandle("2026-01-06", 110.0, 111.0),
        ]

        result = gate_rows(rows)["2026-01-06"]

        self.assertAlmostEqual(result.live_sma5_at_open, 106.0)
        self.assertAlmostEqual(result.open_vs_live_sma5, 110.0 / 106.0 - 1.0)
        self.assertAlmostEqual(result.prev_sma5, 104.0)
        self.assertAlmostEqual(result.prev_close_vs_prev_sma5, 108.0 / 104.0 - 1.0)

    def test_dates_for_slice_splits_live_open_above_and_below(self) -> None:
        rows = [
            IndexCandle("2026-01-01", 100.0, 100.0),
            IndexCandle("2026-01-02", 100.0, 100.0),
            IndexCandle("2026-01-03", 100.0, 100.0),
            IndexCandle("2026-01-04", 100.0, 100.0),
            IndexCandle("2026-01-05", 100.0, 100.0),
            IndexCandle("2026-01-06", 102.0, 101.0),
            IndexCandle("2026-01-07", 98.0, 99.0),
        ]
        gates = gate_rows(rows)

        self.assertEqual(dates_for_slice(gates, "live_open_above"), {"2026-01-06"})
        self.assertEqual(dates_for_slice(gates, "live_open_below"), {"2026-01-07"})


if __name__ == "__main__":
    unittest.main()
