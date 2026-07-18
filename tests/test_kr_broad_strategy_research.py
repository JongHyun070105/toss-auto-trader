import unittest

import kr_broad_strategy_research as kr


def event(**overrides):
    values={
        "date":"2026-01-02","symbol":"TEST","prev_close":2000.0,"open":1800.0,"high":2050.0,
        "low":1700.0,"close":1950.0,"gap":-0.10,"prev_vol_ratio":0.5,
        "avg_dollar_volume20":500_000_000.0,"avg_range20":0.05,"prev_return1":-0.01,
        "prev_return5":-0.05,"prev_return20":0.02,"prev_close_location":0.5,
        "future":((1,"2026-01-05",1980.0),(3,"2026-01-07",2100.0),(5,"2026-01-09",2200.0)),
    }
    values.update(overrides); return kr.Event(**values)


def market(**overrides):
    values={"date":"2026-01-02","open_vs_sma5":-0.02,"index_gap":-0.01,"gap2_count":20,"gap5_count":5}
    values.update(overrides); return kr.Market(**values)


class KrBroadStrategyResearchTests(unittest.TestCase):
    def test_anchor_filters_use_only_open_and_prior_features(self):
        cfg=kr.anchor_config()
        self.assertTrue(kr.passes(event(gap=-0.06),market(),cfg))
        self.assertFalse(kr.passes(event(prev_vol_ratio=0.9),market(),cfg))
        self.assertFalse(kr.passes(event(avg_dollar_volume20=1),market(),kr.replace(cfg,min_dollar_volume=100)))
        self.assertFalse(kr.passes(event(),market(open_vs_sma5=0),cfg))

    def test_gap_floor_and_market_floor_reject_extreme_crashes(self):
        cfg=kr.replace(kr.anchor_config(),gap_min=-0.15,index_gap_min=-0.03)
        self.assertFalse(kr.passes(event(gap=-0.20),market(),cfg))
        self.assertFalse(kr.passes(event(),market(index_gap=-0.04),cfg))

    def test_stop_is_conservative_when_stop_and_take_both_touch(self):
        data=kr.exit_for(event(open=100,low=95,high=120),kr.anchor_config())
        self.assertEqual(data,("2026-01-02",97.75,"stop"))

    def test_holding_period_uses_future_close(self):
        cfg=kr.replace(kr.anchor_config(),exit_days=3,stop_loss=None,take_profit=None)
        self.assertEqual(kr.exit_for(event(),cfg),("2026-01-07",2100.0,"hold_3d"))

    def test_integer_quantity_and_cost_are_applied(self):
        cfg=kr.replace(kr.anchor_config(),market_max=None,stop_loss=None,take_profit=None,roundtrip_cost=0.01)
        trades=kr.simulate([event(open=1800,close=1980)],{"2026-01-02":market()},cfg)
        self.assertEqual(trades[0].quantity,5)
        self.assertAlmostEqual(trades[0].net_pnl,5*180-5*1800*0.01)

    def test_rank_is_deterministic(self):
        cfg=kr.replace(kr.anchor_config(),market_max=None,stop_loss=None,take_profit=None,rank="highest_liquidity")
        rows=[event(symbol="LOW",avg_dollar_volume20=100),event(symbol="HIGH",avg_dollar_volume20=1000)]
        self.assertEqual(kr.simulate(rows,{"2026-01-02":market()},cfg)[0].symbol,"HIGH")


if __name__=="__main__":
    unittest.main()
