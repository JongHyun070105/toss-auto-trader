import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import scripts.simple_gap_news_shadow as news_script
from scripts.simple_gap_news_shadow import _append_snapshot, load_candidate_snapshot
from scripts.vi_reopen_shadow import parse_cost_profiles
from toss_auto_trader.news_prefetch import append_prefetch_snapshot, build_prefetch_snapshot


class ShadowResearchScriptTests(unittest.TestCase):
    def test_news_candidate_snapshot_uses_actual_selected_order_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.jsonl"
            rows = [
                {
                    "trade_date": "2026-07-30",
                    "symbol": "A",
                    "decision": "candidate",
                    "captured_at": "2026-07-30T09:01:10+09:00",
                    "first_minute_open": 1200,
                },
                {
                    "trade_date": "2026-07-30",
                    "symbol": "B",
                    "decision": "candidate",
                    "captured_at": "2026-07-30T09:01:11+09:00",
                    "first_minute_open": 1100,
                },
                {
                    "trade_date": "2026-07-30",
                    "symbol": "B",
                    "decision": "selected_for_order",
                    "candidate_rank": 1,
                    "captured_at": "2026-07-30T09:01:20+09:00",
                },
            ]
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

            result = load_candidate_snapshot(path, "2026-07-30")

        self.assertEqual(result["decision_at"], "2026-07-30T09:01:20+09:00")
        self.assertEqual([row["symbol"] for row in result["candidates"]], ["B", "A"])
        self.assertEqual(result["candidates"][0]["candidate_rank"], 1)

    def test_news_snapshot_writer_is_idempotent_for_same_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "news.jsonl"
            snapshot = {
                "trade_date": "2026-07-30",
                "decision_at": "2026-07-30T09:01:20+09:00",
                "providers": ["naver"],
            }

            first = _append_snapshot(path, snapshot)
            second = _append_snapshot(path, snapshot)

        self.assertTrue(first)
        self.assertFalse(second)

    def test_vi_cost_profile_parser_requires_named_values(self):
        self.assertEqual(parse_cost_profiles("base:0.35,harsh:1.35"), {"base": 0.35, "harsh": 1.35})
        with self.assertRaises(ValueError):
            parse_cost_profiles("0.35")

    def test_news_shadow_uses_preopen_disclosure_without_live_dart_call(self):
        class FakeTossClient:
            def __init__(self, _settings):
                pass

            def get_stocks(self, symbols):
                return {"result": [{"symbol": symbol, "name": "테스트전자"} for symbol in symbols]}

        class FailingNewsHub:
            def opendart_disclosures(self, **_kwargs):
                raise AssertionError("prefetch path must not call live OpenDART")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit = root / "audit.jsonl"
            prefetch = root / "prefetch.jsonl"
            audit.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "trade_date": "2026-07-30",
                                "symbol": "123456",
                                "decision": "candidate",
                                "captured_at": "2026-07-30T09:01:10+09:00",
                                "first_minute_open": 1000,
                            }
                        ),
                        json.dumps(
                            {
                                "trade_date": "2026-07-30",
                                "symbol": "123456",
                                "decision": "selected_for_order",
                                "candidate_rank": 1,
                                "captured_at": "2026-07-30T09:01:20+09:00",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            snapshot = build_prefetch_snapshot(
                [
                    {
                        "provider": "opendart",
                        "stock_code": "123456",
                        "corp_name": "테스트전자",
                        "title": "유상증자결정",
                        "summary": "테스트전자",
                        "published_at": "2026-07-30",
                    }
                ],
                trade_date="2026-07-30",
                observed_at="2026-07-30T08:55:00+09:00",
                begin_date="2026-07-27",
                end_date="2026-07-30",
            )
            append_prefetch_snapshot(prefetch, snapshot)

            output = io.StringIO()
            with patch.object(news_script, "TossInvestClient", FakeTossClient):
                with patch.object(news_script, "NewsHub", FailingNewsHub):
                    with redirect_stdout(output):
                        exit_code = news_script.main(
                            [
                                "--date",
                                "2026-07-30",
                                "--audit",
                                str(audit),
                                "--prefetch",
                                str(prefetch),
                                "--providers",
                                "opendart",
                                "--print-only",
                            ]
                        )

        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["counts"]["risk_veto"], 1)
        self.assertEqual(report["provider_status"]["opendart"]["source"], "preopen_prefetch")
        self.assertEqual(report["candidates"][0]["assessment"]["promotion_eligible_items"], 1)
        self.assertFalse(report["order_sent"])


if __name__ == "__main__":
    unittest.main()
