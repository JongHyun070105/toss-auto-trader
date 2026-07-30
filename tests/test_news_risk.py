import unittest

from toss_auto_trader.news_risk import assess_news_snapshot, parse_news_timestamp


class NewsRiskTests(unittest.TestCase):
    def test_parse_naver_rfc_timestamp_to_kst(self):
        parsed = parse_news_timestamp("Thu, 30 Jul 2026 08:20:00 +0900")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.isoformat(), "2026-07-30T08:20:00+09:00")

    def test_hard_risk_requires_entity_time_and_age_relevance(self):
        items = [
            {
                "provider": "opendart",
                "title": "테스트전자 유상증자 결정",
                "summary": "자금 조달 계획",
                "published_at": "Thu, 30 Jul 2026 08:20:00 +0900",
            },
            {
                "provider": "naver",
                "title": "다른회사 거래정지",
                "summary": "관련 없는 기사",
                "published_at": "Thu, 30 Jul 2026 08:10:00 +0900",
            },
            {
                "provider": "naver",
                "title": "테스트전자 상장폐지",
                "summary": "미래 기사",
                "published_at": "Thu, 30 Jul 2026 09:10:00 +0900",
            },
        ]

        result = assess_news_snapshot(
            items,
            decision_at="2026-07-30T09:01:00+09:00",
            observed_at="2026-07-30T09:03:00+09:00",
            entity_names=["테스트전자"],
        )

        self.assertEqual(result["eligible_items"], 1)
        self.assertEqual(result["hard_risk_items"], 1)
        self.assertEqual(result["shadow_decision"], "risk_veto")
        self.assertFalse(result["point_in_time_valid"])
        self.assertFalse(result["promotion_eligible_observation"])
        self.assertFalse(result["live_order_allowed"])

    def test_general_news_hard_keyword_is_manual_review_only(self):
        result = assess_news_snapshot(
            [
                {
                    "provider": "naver",
                    "title": "테스트전자 유상증자 결정",
                    "summary": "자금 조달 계획",
                    "published_at": "Thu, 30 Jul 2026 08:20:00 +0900",
                }
            ],
            decision_at="2026-07-30T09:01:00+09:00",
            observed_at="2026-07-30T08:55:00+09:00",
            entity_names=["테스트전자"],
        )

        self.assertEqual(result["hard_risk_items"], 0)
        self.assertEqual(result["review_risk_items"], 1)
        self.assertEqual(result["shadow_decision"], "manual_review")

    def test_resolved_risk_phrase_does_not_trigger_keyword_veto(self):
        result = assess_news_snapshot(
            [
                {
                    "provider": "naver",
                    "title": "11억 들여 관리종목 피한 테스트전자",
                    "summary": "위기 해소",
                    "published_at": "Sun, 27 Jul 2026 08:02:00 +0900",
                }
            ],
            decision_at="2026-07-29T09:01:00+09:00",
            observed_at="2026-07-29T08:55:00+09:00",
            entity_names=["테스트전자"],
        )

        self.assertEqual(result["hard_risk_items"], 0)
        self.assertEqual(result["review_risk_items"], 0)
        self.assertEqual(result["shadow_decision"], "no_veto_evidence")

    def test_positive_news_does_not_approve_live_order(self):
        result = assess_news_snapshot(
            [
                {
                    "provider": "opendart",
                    "title": "단일판매 공급계약 체결",
                    "summary": "테스트전자",
                    "published_at": "2026-07-30",
                }
            ],
            decision_at="2026-07-30T09:01:00+09:00",
            observed_at="2026-07-30T08:55:00+09:00",
            entity_names=["테스트전자"],
        )

        self.assertEqual(result["positive_context_items"], 1)
        self.assertEqual(result["shadow_decision"], "no_veto_evidence")
        self.assertTrue(result["point_in_time_valid"])
        self.assertFalse(result["live_order_allowed"])

    def test_no_news_is_not_reported_as_approval(self):
        result = assess_news_snapshot(
            [],
            decision_at="2026-07-30T09:01:00+09:00",
            observed_at="2026-07-30T08:55:00+09:00",
            entity_names=["테스트전자"],
        )

        self.assertEqual(result["shadow_decision"], "no_eligible_news")
        self.assertFalse(result["live_order_allowed"])

    def test_article_timestamp_after_observation_is_ineligible(self):
        result = assess_news_snapshot(
            [
                {
                    "provider": "opendart",
                    "title": "테스트전자 유상증자 결정",
                    "summary": "테스트전자",
                    "published_at": "2026-07-30T08:58:00+09:00",
                }
            ],
            decision_at="2026-07-30T09:01:00+09:00",
            observed_at="2026-07-30T08:55:00+09:00",
            entity_names=["테스트전자"],
        )

        self.assertEqual(result["eligible_items"], 0)
        self.assertFalse(result["items"][0]["published_before_observation"])

    def test_item_specific_prefetch_time_can_be_promotion_eligible(self):
        result = assess_news_snapshot(
            [
                {
                    "provider": "opendart",
                    "title": "테스트전자 유상증자 결정",
                    "summary": "테스트전자",
                    "published_at": "2026-07-29",
                    "observed_at": "2026-07-30T08:55:00+09:00",
                }
            ],
            decision_at="2026-07-30T09:01:00+09:00",
            observed_at="2026-07-30T09:05:00+09:00",
            entity_names=["테스트전자"],
        )

        self.assertFalse(result["point_in_time_valid"])
        self.assertEqual(result["promotion_eligible_items"], 1)
        self.assertTrue(result["items"][0]["point_in_time_valid"])


if __name__ == "__main__":
    unittest.main()
