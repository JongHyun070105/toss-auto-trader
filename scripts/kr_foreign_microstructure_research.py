#!/usr/bin/env python3
"""Research-only foreign microstructure features for the Korean gap strategy.

The live trader is never imported. Candidate features use the current official
open plus stock/index observations ending no later than the previous session.
The 2024+ windows are reused diagnostics, not an untouched holdout.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import itertools
import json
import math
import random
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

import kr_external_method_research as external
from kr_broad_strategy_research import Market, Trade, WINDOWS, json_safe, metrics, scoped
from simple_gap_strategy_audit import fetch_kosdaq_index


DEFAULT_DB = "data/edge_research_universe_15y.sqlite3"
DEFAULT_US_DB = "data/us_gap_research.sqlite3"
DEFAULT_OUT_DIR = "data/kr_foreign_microstructure_research"
DEFAULT_SPREAD_HISTORY = "data/spread_history.jsonl"
DEFAULT_PAPER_OBSERVATIONS = "data/paper_observations.jsonl"
DEFAULT_WARNING_AUDIT = (
    "data/kr_foreign_microstructure_research/"
    "krx_kind_historical_warning_audit.json"
)
SELECTION_START = "2011-01-01"
SELECTION_END = "2023-12-31"
TICK_REFORM_DATE = "2023-01-25"
COSTS = external.COSTS


@dataclass(frozen=True, slots=True)
class ForeignEvent(external.ResearchEvent):
    prev_low: float
    prev_gap1: float
    prev_intraday_return1: float
    max_return60: float
    prior_close_to_high252: float
    feature_history252: int
    prev_return1: float
    prev_return10: float
    cs_spread20: float
    roll_spread60: float
    zero_return_share20: float
    dollar_volume_cv20: float
    downside_semivol60: float
    downside_beta60: float
    skew60: float
    parkinson_vol20: float
    yang_zhang_vol20: float
    overnight_sum20: float
    intraday_sum20: float
    historical_gap_z60: float
    feature_history60: int
    market_cs_spread_z60: float
    market_zero_return_z60: float
    market_range_vol_z60: float
    market_gap_mean_z60: float
    market_gap_breadth_z60: float
    official_attention_active: bool = False
    official_warning_active: bool = False
    official_risk_active: bool = False


@dataclass(frozen=True, slots=True)
class ForeignMethod:
    name: str
    family: str
    filter_rule: str = "none"
    rank: str = "lowest_price"
    market_rule: str = "none"
    source_keys: tuple[str, ...] = ()
    universe: str = "anchor"


@dataclass(frozen=True, slots=True)
class ForeignMarket(Market):
    us_session_date: str | None
    qqq_return: float
    spy_return: float
    qqq_range: float
    qqq_vol20: float
    us_history20: int
    kosdaq_us_beta60: float
    kosdaq_us_residual_gap: float
    weekday: int
    trading_day_of_month: int
    trading_days_in_month: int


SOURCES: tuple[dict[str, str], ...] = (
    {
        "key": "corwin_schultz_2012",
        "title": "A Simple Way to Estimate Bid-Ask Spreads from Daily High and Low Prices",
        "url": "https://doi.org/10.1111/j.1540-6261.2012.01729.x",
        "use": "Prior 20 two-day high-low spread estimates; treated as a noisy friction proxy.",
    },
    {
        "key": "roll_1984",
        "title": "A Simple Implicit Measure of the Effective Bid-Ask Spread in an Efficient Market",
        "url": "https://doi.org/10.1111/j.1540-6261.1984.tb03897.x",
        "use": "Prior 60 return-autocovariance spread proxy; relative-return approximation only.",
    },
    {
        "key": "lesmond_ogden_trzcinka_1999",
        "title": "A New Estimate of Transaction Costs",
        "url": "https://doi.org/10.1093/rfs/12.5.1113",
        "use": "Prior 20 zero-return share as a coarse trading-friction proxy, not the full LOT model.",
    },
    {
        "key": "abdi_ranaldo_2017",
        "title": "A Simple Estimation of Bid-Ask Spreads from Daily Close, High, and Low Prices",
        "url": "https://doi.org/10.1093/rfs/hhx084",
        "use": "Supports skepticism about a single daily spread proxy, especially in illiquid stocks.",
    },
    {
        "key": "yang_zhang_2000",
        "title": "Drift-Independent Volatility Estimation Based on High, Low, Open, and Close Prices",
        "url": "https://doi.org/10.1086/209650",
        "use": "Prior 20-session OHLC volatility including overnight jumps.",
    },
    {
        "key": "rogers_satchell_1991",
        "title": "Estimating Variance From High, Low and Closing Prices",
        "url": "https://doi.org/10.1214/aoap/1177005835",
        "use": "Range component inside the Yang-Zhang estimator.",
    },
    {
        "key": "parkinson_1980",
        "title": "The Extreme Value Method for Estimating the Variance of the Rate of Return",
        "url": "https://doi.org/10.1086/296071",
        "use": "Prior 20 high-low range volatility comparison.",
    },
    {
        "key": "ang_hodrick_xing_zhang_2006",
        "title": "The Cross-Section of Volatility and Expected Returns",
        "url": "https://doi.org/10.1111/j.1540-6261.2006.00836.x",
        "use": "Motivates low-volatility and tail-risk filters; horizon mismatch is explicit.",
    },
    {
        "key": "ang_chen_xing_2006",
        "title": "Downside Risk",
        "url": "https://doi.org/10.1093/rfs/hhj035",
        "use": "Prior 60 downside beta and downside semivolatility diagnostics.",
    },
    {
        "key": "lou_polk_skouras_2019",
        "title": "A Tug of War: Overnight versus Intraday Expected Returns",
        "url": "https://doi.org/10.1016/j.jfineco.2019.03.011",
        "use": "Prior 20 overnight and intraday return components; translated to an opening-reversal filter.",
    },
    {
        "key": "lehmann_1990",
        "title": "Fads, Martingales, and Market Efficiency",
        "url": "https://doi.org/10.2307/2937816",
        "use": "Economic rationale for short-horizon reversal after large price changes.",
    },
    {
        "key": "chordia_subrahmanyam_anshuman_2001",
        "title": "Trading Activity and Expected Stock Returns",
        "url": "https://doi.org/10.1016/S0304-405X(00)00080-5",
        "use": "Prior dollar-volume variability as a liquidity-risk diagnostic.",
    },
    {
        "key": "chordia_roll_subrahmanyam_2000",
        "title": "Commonality in Liquidity",
        "url": "https://doi.org/10.1016/S0304-405X(99)00057-4",
        "use": "Warns that stock-level liquidity filters omit market-wide liquidity shocks.",
    },
    {
        "key": "white_2000",
        "title": "A Reality Check for Data Snooping",
        "url": "https://doi.org/10.1111/1468-0262.00152",
        "use": "Studentized circular-block bootstrap diagnostic across declared methods.",
    },
    {
        "key": "hansen_2005",
        "title": "A Test for Superior Predictive Ability",
        "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=264569",
        "use": "Motivates studentization and comparison against a fixed benchmark.",
    },
    {
        "key": "bailey_et_al_2015",
        "title": "The Probability of Backtest Overfitting",
        "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253",
        "use": "Eight-block combinatorially symmetric cross-validation PBO diagnostic.",
    },
    {
        "key": "bailey_lopez_de_prado_2014",
        "title": "The Deflated Sharpe Ratio",
        "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551",
        "use": "Retains the prior approximate DSR diagnostic and its non-IID warning.",
    },
    {
        "key": "berkman_koch_tuttle_zhang_2012",
        "title": "Paying Attention: Overnight Returns and the Hidden Cost of Buying at the Open",
        "url": "https://doi.org/10.1017/S0022109012000270",
        "use": "Supports separating opening-price overreaction from observed spread costs.",
    },
    {
        "key": "amihud_mendelson_1989",
        "title": "Market Microstructure and Price Discovery on the Tokyo Stock Exchange",
        "url": "https://doi.org/10.1016/0922-1425(89)90013-3",
        "use": "Motivates an opening-noise and cross-market price-discovery interpretation.",
    },
    {
        "key": "wang_2013_korean_adr",
        "title": "Is There a Reversal in the Price Discovery Process under Different Market Conditions?",
        "url": "https://doi.org/10.1016/j.pacfin.2012.05.001",
        "use": "Motivates conditioning Korean opening gaps on the latest completed US session.",
    },
    {
        "key": "park_yi_2011",
        "title": "Mispricing of US Shocks in the Korean Stock Market",
        "url": "https://doi.org/10.1111/j.2041-6156.2011.01042.x",
        "use": "Pre-declares large positive and negative completed-US-session splits for Korean opening reversals.",
    },
    {
        "key": "ham_ryu_webb_yu_2023",
        "title": "How Do Investors React to Overnight Returns? Evidence from Korea",
        "url": "https://doi.org/10.1016/j.frl.2023.103779",
        "use": "Motivates nonlinear extreme-gap contrasts instead of assuming that a larger negative gap always reverses more.",
    },
    {
        "key": "aiche_cohen_griskin_2024",
        "title": "Opening Gaps and Intraday Price Adjustment",
        "url": "https://doi.org/10.1007/s10614-023-10363-w",
        "use": "Pre-declares partial-versus-full gap geometry and prior-gap sign transitions; US daily-bar evidence does not establish a Korean reversal sign.",
    },
    {
        "key": "an_huang_li_2022",
        "title": "Overnight Returns and Investor Sentiment in the Chinese Stock Market",
        "url": "https://doi.org/10.3390/jrfm15110534",
        "use": "Pre-declares the completed prior-day intraday-return sign as an adverse-state split; forum-attention mechanisms are not inferred from OHLCV.",
    },
    {
        "key": "hendershott_livdan_rosch_2020",
        "title": "Asset Pricing: A Tale of Night and Day",
        "url": "https://doi.org/10.1016/j.jfineco.2020.06.006",
        "use": "Supports a beta-dependent opening-distortion interpretation while rejecting first-hour claims from daily bars.",
    },
    {
        "key": "kim_cho_2018_lottery",
        "title": "Retail Investors and Lottery-Type Stocks in Korea",
        "url": "https://doi.org/10.29331/JKRAIC.2018.10.18.5.1",
        "use": "Pre-declares prior 60-session maximum return as a lottery-profile exclusion in the low-price universe; it is not assumed to predict one-day reversal directly.",
    },
    {
        "key": "george_hwang_2004_52week_high",
        "title": "The 52-Week High and Momentum Investing",
        "url": "https://doi.org/10.1111/j.1540-6261.2004.00695.x",
        "use": "Pre-declares prior-close distance to the strictly prior 252-session high as a momentum-state split; the paper does not claim one-day Korean gap reversal.",
    },
    {
        "key": "nagel_2012_evaporating_liquidity",
        "title": "Evaporating Liquidity",
        "url": "https://doi.org/10.1093/rfs/hhs066",
        "use": "Pre-declares a prior-day loser interaction with strictly prior market range-volatility stress; the daily Korean proxy is not VIX and is treated as a translation test.",
    },
    {
        "key": "krx_kosdaq_price_limit",
        "title": "KRX KOSDAQ Daily Price Limit",
        "url": "https://global.krx.co.kr/contents/GLB/06/0602/0602020202/GLB0602020202T2.jsp",
        "use": "Rejects naive lower-limit reconstruction because the official base price can differ after corporate actions.",
    },
    {
        "key": "krx_volatility_interruption",
        "title": "KRX Volatility Interruption",
        "url": "https://global.krx.co.kr/contents/GLB/06/0602/0602020204/GLB0602020204T7.jsp",
        "use": "Opening VI can convert trading to a call auction; daily bars cannot verify the execution state.",
    },
    {
        "key": "krx_kind_historical_alerts",
        "title": "KRX KIND Investment Attention, Warning, and Risk History",
        "url": "https://kind.krx.co.kr/investwarn/investattentwarnrisky.do?method=investattentwarnriskyMain",
        "use": "Point-in-time designation and release intervals reproduce the official alert exclusion without using current badges retrospectively.",
    },
    {
        "key": "korea_stt_law_2019",
        "title": "Korean Securities Transaction Tax Enforcement Decree, 2019 Revision",
        "url": "https://www.law.go.kr/LSW/nwRvsLsInfoR.do?lsiSeq=208731",
        "use": "Official 2019 KOSDAQ tax change from 0.30% to 0.25%, applied to trades from 2019-05-30.",
    },
    {
        "key": "korea_stt_moef_2021",
        "title": "MOEF Securities Transaction Tax Rate Reduction",
        "url": "https://whatsnew.moef.go.kr/mec/ots/dif/view.do?comBaseCd=DIFGODEPRT&difGovDepart1=DIFGODR001&difSer=5df48aab-ae37-437c-8e86-d6f1a9ee7823&temp=2021&temp2=HALF001",
        "use": "Official KOSDAQ tax reduction from 0.25% to 0.23% from 2021-01-01.",
    },
    {
        "key": "korea_stt_law_2023_2026",
        "title": "Korean Securities Transaction Tax Enforcement Decree Revision History",
        "url": "https://www.law.go.kr/LSW/lsRvsDocListP.do?chrClsCd=010102&lsId=005028",
        "use": "Official KOSDAQ rates of 0.20% in 2023, 0.18% in 2024, 0.15% in 2025, and 0.20% from 2026.",
    },
    {
        "key": "park_ahn_2025_opening_auction",
        "title": "Investor Behavior and Price Discovery in the Korean Opening Call Auction",
        "url": "https://doi.org/10.37197/ARFR.2025.38.4.3",
        "use": "Order-level Korean evidence that investor groups enter and revise opening-auction orders at different times; daily bars cannot identify that participation.",
    },
    {
        "key": "kim_rhee_1997_price_limits",
        "title": "Price Limit Performance: Evidence from the Tokyo Stock Exchange",
        "url": "https://doi.org/10.1111/j.1540-6261.1997.tb04827.x",
        "use": "Price-limit hits can delay discovery and interfere with trading; limit proximity is a falsification risk, not a reversal signal.",
    },
    {
        "key": "jpx_transaction_methods",
        "title": "JPX Trading Rules of Domestic Stocks",
        "url": "https://www.jpx.co.jp/english/equities/trading/domestic/04.html",
        "use": "Foreign official comparator showing opening call-auction allocation differs from continuous trading.",
    },
    {
        "key": "twse_trading_mechanism",
        "title": "Taiwan Stock Exchange Trading Mechanism",
        "url": "https://www.twse.com.tw/en/products/system/trading.html",
        "use": "Foreign official comparator: opening and volatility-interruption sessions use call auctions with different order constraints.",
    },
    {
        "key": "abdi_2019",
        "title": "Cycles of Declines and Reversals following Overnight Market Declines",
        "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3287680",
        "use": "Tests low- versus high-volatility stock ranking after a completed US-market decline; the original evidence is US-only.",
    },
    {
        "key": "krx_tick_size_current",
        "title": "KRX Equity Quotation Tick Size",
        "url": "https://global.krx.co.kr/contents/GLB/06/0602/0602010201/GLB0602010201T3.jsp",
        "use": "Defines the unified post-reform equity price bands used from 2023-01-25.",
    },
    {
        "key": "krx_kosdaq_tick_size_pre_2023",
        "title": "KRX Introduction to KOSDAQ Market (pre-reform tick table)",
        "url": "https://global.krx.co.kr/contents/GLB/02/0201/0201010304/kosdaq_brochure.pdf",
        "use": "Documents the KOSDAQ-specific tick table used before the 2023 unification.",
    },
    {
        "key": "krx_tick_reform_2023",
        "title": "KRX Business Regulation Enforcement Rules, amendment no. 2094",
        "url": "https://law.krx.co.kr/las/RefBon.jsp?lawid=000111&lawkd=B&pubdt=20230808&pubno=0000021500&reflinkchk=Y",
        "use": "The official supplementary provision sets the amended tick rules' effective date to 2023-01-25.",
    },
    {
        "key": "krx_opening_call_auction",
        "title": "KRX Stock Market Trading Hours and Opening Call Auction",
        "url": "https://global.krx.co.kr/contents/GLB/06/0604/0604010100/GLB0604010100T3.jsp",
        "use": "The official open is the call-auction result; observing that result cannot imply a fill at the same already-determined price.",
    },
    {
        "key": "french_1980",
        "title": "Stock Returns and the Weekend Effect",
        "url": "https://doi.org/10.1016/0304-405X(80)90021-5",
        "use": "Pre-declared weekday splits; not assumed to transfer from the US index to Korean gap events.",
    },
    {
        "key": "ariel_1987",
        "title": "A Monthly Effect in Stock Returns",
        "url": "https://doi.org/10.1016/0304-405X(87)90066-3",
        "use": "Pre-declared first-half and turn-of-month event splits.",
    },
    {
        "key": "lakonishok_smidt_1988",
        "title": "Are Seasonal Anomalies Real? A Ninety-Year Perspective",
        "url": "https://doi.org/10.1093/rfs/1.4.403",
        "use": "Motivates long-window seasonality checks while retaining data-mining warnings.",
    },
    {
        "key": "campbell_grossman_wang_1993",
        "title": "Trading Volume and Serial Correlation in Stock Returns",
        "url": "https://doi.org/10.2307/2118454",
        "use": "Tests prior completed losses jointly with prior completed volume; daily adaptation only.",
    },
    {
        "key": "conrad_hameed_niden_1994",
        "title": "Volume and Autocovariances in Short-Horizon Individual Security Returns",
        "url": "https://doi.org/10.1111/j.1540-6261.1994.tb02455.x",
        "use": "Motivates loser-by-volume interactions while acknowledging the original weekly horizon.",
    },
    {
        "key": "kaul_nimalendran_1990",
        "title": "Price Reversals: Bid-ask Errors or Market Overreaction?",
        "url": "https://doi.org/10.1016/0304-405X(90)90048-5",
        "use": "Treats daily-bar reversal as suspect until it survives friction and adverse-fill tests.",
    },
    {
        "key": "park_1995",
        "title": "A Market Microstructure Explanation for Predictable Variations in Stock Returns following Large Price Changes",
        "url": "https://doi.org/10.2307/2331119",
        "use": "Adds a falsification warning: close-selected reversals can be bid-ask and selection artifacts.",
    },
    {
        "key": "bremer_sweeney_1991",
        "title": "The Reversal of Large Stock-Price Decreases",
        "url": "https://doi.org/10.1111/j.1540-6261.1991.tb02684.x",
        "use": "Tests prior 10-session loser ranks using only prices completed before entry.",
    },
    {
        "key": "bremer_hiraki_sweeney_1997",
        "title": "Predictable Patterns after Large Stock Price Changes on the Tokyo Stock Exchange",
        "url": "https://doi.org/10.2307/2331204",
        "use": "Foreign-market replication for asymmetric recovery after large negative moves; profit caveat retained.",
    },
    {
        "key": "hameed_kang_viswanathan_2010",
        "title": "Stock Market Declines and Liquidity",
        "url": "https://doi.org/10.1111/j.1540-6261.2009.01529.x",
        "use": "Combines completed US-market weakness with prior loser-volume conditions as a stress diagnostic.",
    },
    {
        "key": "brooks_moulton_2004",
        "title": "The Interaction between Opening Call Auctions and Ongoing Trade",
        "url": "https://doi.org/10.1016/j.rfe.2003.12.003",
        "use": "Supports treating the official open as observed auction output, not a guaranteed same-price fill.",
    },
    {
        "key": "biais_hillion_spatt_1999",
        "title": "Price Discovery and Learning during the Preopening Period in the Paris Bourse",
        "url": "https://doi.org/10.1086/250095",
        "use": "Preopening information improves toward the auction; daily data cannot reconstruct indicative-price learning.",
    },
    {
        "key": "cooper_cliff_gulen_2008",
        "title": "Return Differences between Trading and Non-Trading Hours: Like Night and Day",
        "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1004081",
        "use": "Supports separating completed overnight and intraday return components without same-close selection.",
    },
    {
        "key": "heston_sadka_2008",
        "title": "Seasonality in the Cross-Section of Stock Returns",
        "url": "https://doi.org/10.1016/j.jfineco.2007.02.003",
        "use": "Documents longer-horizon same-month seasonality; rejected as a direct one-day gap rule.",
    },
    {
        "key": "mclean_pontiff_2016",
        "title": "Does Academic Research Destroy Stock Return Predictability?",
        "url": "https://doi.org/10.1111/jofi.12365",
        "use": "Requires locked chronological evaluation and forbids promotion from repeatedly inspected 2024+ data.",
    },
    {
        "key": "brown_goetzmann_ibbotson_ross_1992",
        "title": "Survivorship Bias in Performance Studies",
        "url": "https://doi.org/10.1093/rfs/5.4.553",
        "use": "Supports treating survivor-truncated predictability as potentially artificial.",
    },
    {
        "key": "shumway_1997",
        "title": "The Delisting Bias in CRSP Data",
        "url": "https://doi.org/10.1111/j.1540-6261.1997.tb03818.x",
        "use": "Shows that omitted negative delisting returns can be large; current-survivor data cannot supply them.",
    },
    {
        "key": "beaver_mcnichols_price_2007",
        "title": "Delisting Returns and Their Effect on Accounting-Based Market Anomalies",
        "url": "https://doi.org/10.1016/j.jacceco.2006.12.002",
        "use": "Shows that inclusion of delisting firm-years can materially change anomaly returns.",
    },
)


def _market_rows(index_rows: Sequence[dict[str, Any]]) -> list[tuple[str, float]]:
    ordered = sorted(index_rows, key=lambda row: str(row["date"]))
    previous_close: float | None = None
    result: list[tuple[str, float]] = []
    for row in ordered:
        close = float(row["close"])
        result.append(
            (
                str(row["date"]),
                close / previous_close - 1.0 if previous_close else 0.0,
            )
        )
        previous_close = close
    return result


def load_us_market_rows(us_db_path: str) -> dict[str, dict[str, float]]:
    """Load completed SPY/QQQ sessions; Korean dates select a strictly earlier row."""
    sql = """
    SELECT symbol,substr(timestamp,1,10) AS date,
      CAST(high_price AS REAL) AS high_price,
      CAST(low_price AS REAL) AS low_price,
      CAST(close_price AS REAL) AS close_price
    FROM candle_cache
    WHERE interval='1d' AND symbol IN ('SPY','QQQ')
    ORDER BY symbol,timestamp
    """
    connection = sqlite3.connect(f"file:{Path(us_db_path).resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(sql).fetchall()
    finally:
        connection.close()
    by_symbol: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        by_symbol[str(row["symbol"])].append(row)
    result: dict[str, dict[str, float]] = defaultdict(dict)
    for symbol, symbol_rows in by_symbol.items():
        previous_close: float | None = None
        returns: list[float] = []
        for row in symbol_rows:
            close = float(row["close_price"])
            daily_return = close / previous_close - 1.0 if previous_close else 0.0
            returns.append(daily_return)
            recent = returns[max(0, len(returns) - 20) :]
            result[str(row["date"])][f"{symbol.lower()}_return"] = daily_return
            result[str(row["date"])][f"{symbol.lower()}_range"] = (
                float(row["high_price"]) / float(row["low_price"]) - 1.0
                if float(row["low_price"]) > 0
                else 0.0
            )
            result[str(row["date"])][f"{symbol.lower()}_vol20"] = (
                statistics.pstdev(recent) if len(recent) >= 2 else 0.0
            )
            result[str(row["date"])][f"{symbol.lower()}_history20"] = len(recent)
            previous_close = close
    return dict(result)


def _rolling_beta(pairs: Sequence[tuple[float, float]]) -> float:
    if len(pairs) < 20:
        return 0.0
    us_values = [pair[0] for pair in pairs[-60:]]
    kr_values = [pair[1] for pair in pairs[-60:]]
    us_mean = statistics.fmean(us_values)
    kr_mean = statistics.fmean(kr_values)
    variance = statistics.fmean((value - us_mean) ** 2 for value in us_values)
    if variance <= 1e-12:
        return 0.0
    covariance = statistics.fmean(
        (us_value - us_mean) * (kr_value - kr_mean)
        for us_value, kr_value in zip(us_values, kr_values)
    )
    return covariance / variance


def build_markets(
    events: Sequence[ForeignEvent],
    index_rows: Sequence[dict[str, Any]],
    us_db_path: str,
) -> dict[str, ForeignMarket]:
    base_markets = external.build_markets(events, index_rows)
    us_rows = load_us_market_rows(us_db_path)
    us_dates = sorted(
        date for date, row in us_rows.items() if "qqq_return" in row and "spy_return" in row
    )
    index_by_date = {str(row["date"]): row for row in index_rows}
    index_dates = sorted(index_by_date)
    month_dates: dict[str, list[str]] = defaultdict(list)
    for date in index_dates:
        month_dates[date[:7]].append(date)
    month_position = {
        date: (position + 1, len(dates))
        for dates in month_dates.values()
        for position, date in enumerate(dates)
    }
    contexts: dict[str, ForeignMarket] = {}
    pairs: list[tuple[float, float]] = []
    previous_close: float | None = None
    for date in index_dates:
        index = index_by_date[date]
        index_gap = (
            float(index["open"]) / previous_close - 1.0 if previous_close else 0.0
        )
        position = bisect.bisect_left(us_dates, date) - 1
        us_date = us_dates[position] if position >= 0 else None
        us = us_rows.get(us_date or "", {})
        qqq_return = float(us.get("qqq_return", 0.0))
        beta = _rolling_beta(pairs)
        base = base_markets.get(date)
        if base is not None:
            contexts[date] = ForeignMarket(
                **asdict(base),
                us_session_date=us_date,
                qqq_return=qqq_return,
                spy_return=float(us.get("spy_return", 0.0)),
                qqq_range=float(us.get("qqq_range", 0.0)),
                qqq_vol20=float(us.get("qqq_vol20", 0.0)),
                us_history20=int(us.get("qqq_history20", 0.0)),
                kosdaq_us_beta60=beta,
                kosdaq_us_residual_gap=index_gap - beta * qqq_return,
                weekday=datetime.fromisoformat(date).weekday(),
                trading_day_of_month=month_position[date][0],
                trading_days_in_month=month_position[date][1],
            )
        if previous_close is not None and us_date is not None:
            pairs.append((qqq_return, index_gap))
        previous_close = float(index["close"])
    return contexts


def load_feature_rows(
    db_path: str,
    index_rows: Sequence[dict[str, Any]],
    *,
    start: str,
    end: str,
) -> dict[tuple[str, str], dict[str, float | int]]:
    """Load rolling features whose windows all end at t-1."""
    sql = """
    WITH base AS (
      SELECT
        c.symbol,
        substr(c.timestamp,1,10) AS date,
        CAST(c.open_price AS REAL) AS open_price,
        CAST(c.high_price AS REAL) AS high_price,
        CAST(c.low_price AS REAL) AS low_price,
        CAST(c.close_price AS REAL) AS close_price,
        CAST(c.volume AS REAL) AS volume,
        k.market_return,
        LAG(CAST(c.close_price AS REAL),1) OVER w AS prev_close,
        LAG(CAST(c.close_price AS REAL),2) OVER w AS close_lag2,
        LAG(CAST(c.close_price AS REAL),11) OVER w AS close_lag11,
        LAG(CAST(c.open_price AS REAL),1) OVER w AS prev_open,
        LAG(CAST(c.high_price AS REAL),1) OVER w AS prev_high,
        LAG(CAST(c.low_price AS REAL),1) OVER w AS prev_low
      FROM candle_cache c
      JOIN temp.kosdaq_daily k ON k.date=substr(c.timestamp,1,10)
      WHERE c.interval='1d'
      WINDOW w AS (PARTITION BY c.symbol ORDER BY c.timestamp)
    ), daily AS (
      SELECT *,
        close_price/NULLIF(prev_close,0)-1.0 AS stock_return,
        prev_close/NULLIF(close_lag2,0)-1.0 AS lag_stock_return,
        open_price/NULLIF(prev_close,0)-1.0 AS gap_return,
        close_price/NULLIF(open_price,0)-1.0 AS intraday_return,
        close_price*volume AS dollar_volume,
        ln(high_price/NULLIF(low_price,0))*ln(high_price/NULLIF(low_price,0)) AS log_range_sq,
        ln(open_price/NULLIF(prev_close,0)) AS overnight_log,
        ln(close_price/NULLIF(open_price,0)) AS open_close_log,
        ln(high_price/NULLIF(open_price,0))*ln(high_price/NULLIF(close_price,0))
          + ln(low_price/NULLIF(open_price,0))*ln(low_price/NULLIF(close_price,0)) AS rs_var,
        CASE WHEN prev_high>0 AND prev_low>0 AND high_price>0 AND low_price>0 THEN
          ln(high_price/low_price)*ln(high_price/low_price)
          + ln(prev_high/prev_low)*ln(prev_high/prev_low)
        END AS cs_beta,
        CASE WHEN prev_high>0 AND prev_low>0 AND high_price>0 AND low_price>0 THEN
          ln(MAX(high_price,prev_high)/MIN(low_price,prev_low))
          * ln(MAX(high_price,prev_high)/MIN(low_price,prev_low))
        END AS cs_gamma
      FROM base
      WHERE prev_close>0 AND open_price>0 AND high_price>=MAX(open_price,close_price)
        AND low_price>0 AND low_price<=MIN(open_price,close_price)
    ), spread_daily AS (
      SELECT *,
        CASE WHEN cs_beta IS NULL OR cs_gamma IS NULL THEN NULL ELSE
          MAX(0.0,
            (sqrt(2.0*cs_beta)-sqrt(cs_beta))/(3.0-2.0*sqrt(2.0))
            - sqrt(cs_gamma/(3.0-2.0*sqrt(2.0)))
          )
        END AS cs_alpha
      FROM daily
    ), prepared AS (
      SELECT *,
        CASE WHEN cs_alpha IS NULL THEN NULL ELSE
          2.0*(exp(cs_alpha)-1.0)/(1.0+exp(cs_alpha))
        END AS cs_spread,
        stock_return*lag_stock_return AS roll_cross,
        CASE WHEN market_return<0 THEN stock_return END AS down_stock,
        CASE WHEN market_return<0 THEN market_return END AS down_market,
        CASE WHEN market_return<0 THEN stock_return*market_return END AS down_cross,
        CASE WHEN stock_return<0 THEN stock_return*stock_return ELSE 0.0 END AS downside_square,
        CASE WHEN ABS(stock_return)<1e-12 THEN 1.0 ELSE 0.0 END AS zero_return,
        stock_return*stock_return AS return_square,
        stock_return*stock_return*stock_return AS return_cube
      FROM spread_daily
    ), rolling AS (
      SELECT *,
        AVG(cs_spread) OVER w20 AS cs_spread20,
        AVG(zero_return) OVER w20 AS zero_return_share20,
        AVG(dollar_volume) OVER w20 AS dollar_volume_mean20,
        AVG(dollar_volume*dollar_volume) OVER w20 AS dollar_volume_square_mean20,
        AVG(log_range_sq) OVER w20 AS log_range_square_mean20,
        AVG(overnight_log) OVER w20 AS overnight_log_mean20,
        AVG(overnight_log*overnight_log) OVER w20 AS overnight_log_square_mean20,
        AVG(open_close_log) OVER w20 AS open_close_log_mean20,
        AVG(open_close_log*open_close_log) OVER w20 AS open_close_log_square_mean20,
        AVG(rs_var) OVER w20 AS rs_var_mean20,
        SUM(gap_return) OVER w20 AS overnight_sum20,
        SUM(intraday_return) OVER w20 AS intraday_sum20,
        AVG(gap_return) OVER w60 AS gap_mean60,
        AVG(gap_return*gap_return) OVER w60 AS gap_square_mean60,
        AVG(stock_return) OVER w60 AS return_mean60,
        AVG(lag_stock_return) OVER w60 AS lag_return_mean60,
        AVG(roll_cross) OVER w60 AS roll_cross_mean60,
        AVG(return_square) OVER w60 AS return_square_mean60,
        AVG(return_cube) OVER w60 AS return_cube_mean60,
        MAX(stock_return) OVER w60 AS max_return60,
        MAX(high_price) OVER w252 AS high252,
        AVG(downside_square) OVER w60 AS downside_square_mean60,
        AVG(down_stock) OVER w60 AS down_stock_mean60,
        AVG(down_market) OVER w60 AS down_market_mean60,
        AVG(down_market*down_market) OVER w60 AS down_market_square_mean60,
        AVG(down_cross) OVER w60 AS down_cross_mean60,
        COUNT(stock_return) OVER w60 AS feature_history60,
        COUNT(close_price) OVER w252 AS feature_history252
      FROM prepared
      WINDOW
        w20 AS (PARTITION BY symbol ORDER BY date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
        w60 AS (PARTITION BY symbol ORDER BY date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING),
        w252 AS (PARTITION BY symbol ORDER BY date ROWS BETWEEN 252 PRECEDING AND 1 PRECEDING)
    ), market_daily AS (
      SELECT date,
        AVG(cs_spread20) AS market_cs_spread,
        AVG(zero_return_share20) AS market_zero_return,
        AVG(log_range_square_mean20) AS market_range_var,
        AVG(gap_return) AS market_gap_mean,
        AVG(CASE WHEN gap_return<=-0.02 THEN 1.0 ELSE 0.0 END) AS market_gap_breadth
      FROM rolling
      WHERE feature_history60>=40
      GROUP BY date
    ), market_rolling AS (
      SELECT *,
        AVG(market_cs_spread) OVER w AS market_cs_spread_mean60,
        AVG(market_cs_spread*market_cs_spread) OVER w AS market_cs_spread_square_mean60,
        AVG(market_zero_return) OVER w AS market_zero_return_mean60,
        AVG(market_zero_return*market_zero_return) OVER w AS market_zero_return_square_mean60,
        AVG(market_range_var) OVER w AS market_range_var_mean60,
        AVG(market_range_var*market_range_var) OVER w AS market_range_var_square_mean60,
        AVG(market_gap_mean) OVER w AS market_gap_mean_mean60,
        AVG(market_gap_mean*market_gap_mean) OVER w AS market_gap_mean_square_mean60,
        AVG(market_gap_breadth) OVER w AS market_gap_breadth_mean60,
        AVG(market_gap_breadth*market_gap_breadth) OVER w AS market_gap_breadth_square_mean60
      FROM market_daily
      WINDOW w AS (ORDER BY date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING)
    )
    SELECT r.*,m.* FROM rolling r
    JOIN market_rolling m ON m.date=r.date
    WHERE r.date BETWEEN ? AND ? AND r.open_price/r.prev_close-1.0<=-0.02
    ORDER BY r.date,r.symbol
    """
    connection = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute(
            "CREATE TEMP TABLE kosdaq_daily (date TEXT PRIMARY KEY, market_return REAL NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO kosdaq_daily(date,market_return) VALUES (?,?)",
            _market_rows(index_rows),
        )
        rows = connection.execute(sql, (start, end)).fetchall()
    finally:
        connection.close()

    result: dict[tuple[str, str], dict[str, float | int]] = {}
    yz_k = 0.34 / (1.34 + 21.0 / 19.0)

    def market_z(current_key: str, mean_key: str, square_key: str) -> float:
        current = float(row[current_key] or 0.0)
        mean = float(row[mean_key] or 0.0)
        variance = max(0.0, float(row[square_key] or 0.0) - mean**2)
        return (current - mean) / math.sqrt(variance) if variance > 1e-12 else 0.0

    for row in rows:
        history = int(row["feature_history60"] or 0)
        return_mean = float(row["return_mean60"] or 0.0)
        return_variance = max(
            0.0, float(row["return_square_mean60"] or 0.0) - return_mean**2
        )
        return_std = math.sqrt(return_variance)
        third_central = (
            float(row["return_cube_mean60"] or 0.0)
            - 3.0 * return_mean * float(row["return_square_mean60"] or 0.0)
            + 2.0 * return_mean**3
        )
        roll_covariance = float(row["roll_cross_mean60"] or 0.0) - return_mean * float(
            row["lag_return_mean60"] or 0.0
        )
        down_market_mean = float(row["down_market_mean60"] or 0.0)
        down_market_variance = max(
            0.0,
            float(row["down_market_square_mean60"] or 0.0) - down_market_mean**2,
        )
        down_covariance = float(row["down_cross_mean60"] or 0.0) - float(
            row["down_stock_mean60"] or 0.0
        ) * down_market_mean
        dollar_mean = float(row["dollar_volume_mean20"] or 0.0)
        dollar_variance = max(
            0.0,
            float(row["dollar_volume_square_mean20"] or 0.0) - dollar_mean**2,
        )
        gap_mean = float(row["gap_mean60"] or 0.0)
        gap_variance = max(
            0.0, float(row["gap_square_mean60"] or 0.0) - gap_mean**2
        )
        overnight_mean = float(row["overnight_log_mean20"] or 0.0)
        close_mean = float(row["open_close_log_mean20"] or 0.0)
        yz_variance = max(
            0.0,
            float(row["overnight_log_square_mean20"] or 0.0) - overnight_mean**2
            + yz_k
            * (
                float(row["open_close_log_square_mean20"] or 0.0) - close_mean**2
            )
            + (1.0 - yz_k) * float(row["rs_var_mean20"] or 0.0),
        )
        current_gap = float(row["open_price"]) / float(row["prev_close"]) - 1.0
        result[(str(row["date"]), str(row["symbol"]))] = {
            "prev_low": float(row["prev_low"] or row["prev_close"]),
            "prev_gap1": float(row["prev_open"] or row["prev_close"])
            / float(row["close_lag2"] or row["prev_close"])
            - 1.0,
            "prev_intraday_return1": float(row["prev_close"])
            / float(row["prev_open"] or row["prev_close"])
            - 1.0,
            "max_return60": float(row["max_return60"] or 0.0),
            "prior_close_to_high252": float(row["prev_close"])
            / float(row["high252"])
            if float(row["high252"] or 0.0) > 0.0
            else 0.0,
            "feature_history252": int(row["feature_history252"] or 0),
            "prev_return1": float(row["prev_close"]) / float(row["close_lag2"] or row["prev_close"]) - 1.0,
            "prev_return10": float(row["prev_close"]) / float(row["close_lag11"] or row["prev_close"]) - 1.0,
            "cs_spread20": float(row["cs_spread20"] or 0.0),
            "roll_spread60": 2.0 * math.sqrt(max(0.0, -roll_covariance)),
            "zero_return_share20": float(row["zero_return_share20"] or 0.0),
            "dollar_volume_cv20": math.sqrt(dollar_variance) / dollar_mean
            if dollar_mean > 0
            else math.inf,
            "downside_semivol60": math.sqrt(
                max(0.0, float(row["downside_square_mean60"] or 0.0))
            ),
            "downside_beta60": down_covariance / down_market_variance
            if down_market_variance > 1e-12
            else 1.0,
            "skew60": third_central / return_std**3 if return_std > 1e-12 else 0.0,
            "parkinson_vol20": math.sqrt(
                max(0.0, float(row["log_range_square_mean20"] or 0.0))
                / (4.0 * math.log(2.0))
            ),
            "yang_zhang_vol20": math.sqrt(yz_variance),
            "overnight_sum20": float(row["overnight_sum20"] or 0.0),
            "intraday_sum20": float(row["intraday_sum20"] or 0.0),
            "historical_gap_z60": (current_gap - gap_mean) / math.sqrt(gap_variance)
            if gap_variance > 1e-12
            else 0.0,
            "feature_history60": history,
            "market_cs_spread_z60": market_z(
                "market_cs_spread",
                "market_cs_spread_mean60",
                "market_cs_spread_square_mean60",
            ),
            "market_zero_return_z60": market_z(
                "market_zero_return",
                "market_zero_return_mean60",
                "market_zero_return_square_mean60",
            ),
            "market_range_vol_z60": market_z(
                "market_range_var",
                "market_range_var_mean60",
                "market_range_var_square_mean60",
            ),
            "market_gap_mean_z60": market_z(
                "market_gap_mean",
                "market_gap_mean_mean60",
                "market_gap_mean_square_mean60",
            ),
            "market_gap_breadth_z60": market_z(
                "market_gap_breadth",
                "market_gap_breadth_mean60",
                "market_gap_breadth_square_mean60",
            ),
        }
    return result


def load_events(
    db_path: str,
    index_rows: Sequence[dict[str, Any]],
    *,
    start: str,
    end: str,
    warning_intervals: dict[str, list[tuple[str, str, str]]] | None = None,
) -> list[ForeignEvent]:
    base_rows = external.load_events(db_path, index_rows, start=start, end=end)
    feature_rows = load_feature_rows(db_path, index_rows, start=start, end=end)
    neutral = {
        "prev_low": 0.0,
        "prev_gap1": 0.0,
        "prev_intraday_return1": 0.0,
        "max_return60": 0.0,
        "prior_close_to_high252": 0.0,
        "feature_history252": 0,
        "prev_return1": 0.0,
        "prev_return10": 0.0,
        "cs_spread20": 0.0,
        "roll_spread60": 0.0,
        "zero_return_share20": 0.0,
        "dollar_volume_cv20": math.inf,
        "downside_semivol60": 0.0,
        "downside_beta60": 1.0,
        "skew60": 0.0,
        "parkinson_vol20": 0.0,
        "yang_zhang_vol20": 0.0,
        "overnight_sum20": 0.0,
        "intraday_sum20": 0.0,
        "historical_gap_z60": 0.0,
        "feature_history60": 0,
        "market_cs_spread_z60": 0.0,
        "market_zero_return_z60": 0.0,
        "market_range_vol_z60": 0.0,
        "market_gap_mean_z60": 0.0,
        "market_gap_breadth_z60": 0.0,
    }
    intervals = warning_intervals or {}
    result: list[ForeignEvent] = []
    for row in base_rows:
        active = {
            category
            for category, designation_date, release_date in intervals.get(
                row.symbol, []
            )
            if designation_date <= row.date < release_date
        }
        result.append(
            ForeignEvent(
                **asdict(row),
                **feature_rows.get((row.date, row.symbol), neutral),
                official_attention_active="attention" in active,
                official_warning_active="warning" in active,
                official_risk_active="risk" in active,
            )
        )
    return result


def load_official_warning_intervals(
    path: str,
) -> tuple[dict[str, list[tuple[str, str, str]]], dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        return {}, {
            "available": False,
            "path": str(source),
            "reason": "KRX KIND historical warning audit is absent",
            "point_in_time_filter_complete": False,
        }
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {}, {
            "available": False,
            "path": str(source),
            "reason": f"warning audit unreadable: {type(exc).__name__}",
            "point_in_time_filter_complete": False,
        }
    intervals: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    malformed = 0
    for row in payload.get("rows", []):
        symbol = str(row.get("ticker") or "")
        category = str(row.get("category") or "")
        designation = str(row.get("designation_date") or "")
        release = str(row.get("release_date") or "9999-12-31")
        if (
            len(symbol) != 6
            or not symbol.isdigit()
            or category not in {"attention", "warning", "risk"}
            or len(designation) != 10
            or len(release) != 10
            or release <= designation
        ):
            malformed += 1
            continue
        intervals[symbol].add((category, designation, release))
    normalized = {
        symbol: sorted(values, key=lambda value: (value[1], value[2], value[0]))
        for symbol, values in intervals.items()
    }
    interval_count = sum(len(values) for values in normalized.values())
    return normalized, {
        "available": True,
        "path": str(source),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "official_source": payload.get("source", {}),
        "rows_collected": payload.get("rows_collected"),
        "point_in_time_usable_rows": payload.get("point_in_time_usable_rows"),
        "intervals_loaded": interval_count,
        "symbols_loaded": len(normalized),
        "malformed_or_unresolved_rows_skipped": malformed
        + len(payload.get("unresolved_issuer_codes", [])),
        "all_chunk_counts_match": bool(payload.get("all_chunk_counts_match")),
        "ticker_resolution_complete": bool(
            payload.get("ticker_resolution_complete")
        ),
        "selection_2011_2023_filter_complete": bool(
            payload.get("selection_2011_2023_filter_complete")
        ),
        "selection_2011_2023_unresolved_rows": int(
            payload.get("selection_2011_2023_unresolved_rows") or 0
        ),
        "point_in_time_filter_complete": bool(
            payload.get("point_in_time_filter_complete")
        ),
        "release_boundary_rule": payload.get("release_boundary_rule"),
        "known_limits": payload.get("known_limits", []),
    }


def methods() -> list[ForeignMethod]:
    """Coarse, declared hypotheses fixed before reading 2024+ diagnostics."""
    return [
        ForeignMethod("anchor", "anchor"),
        ForeignMethod("cs_spread_bottom_half", "liquidity", "cs_bottom_half", source_keys=("corwin_schultz_2012",)),
        ForeignMethod("rank_low_cs_spread", "liquidity", rank="low_cs", source_keys=("corwin_schultz_2012",)),
        ForeignMethod("zero_return_bottom_two_thirds", "liquidity", "zero_bottom_two_thirds", source_keys=("lesmond_ogden_trzcinka_1999",)),
        ForeignMethod("rank_low_zero_return", "liquidity", rank="low_zero", source_keys=("lesmond_ogden_trzcinka_1999",)),
        ForeignMethod("roll_spread_bottom_half", "liquidity", "roll_bottom_half", source_keys=("roll_1984",)),
        ForeignMethod("rank_low_roll_spread", "liquidity", rank="low_roll", source_keys=("roll_1984",)),
        ForeignMethod("dollar_volume_cv_bottom_half", "liquidity", "dollar_cv_bottom_half", source_keys=("chordia_subrahmanyam_anshuman_2001",)),
        ForeignMethod("rank_low_dollar_volume_cv", "liquidity", rank="low_dollar_cv", source_keys=("chordia_subrahmanyam_anshuman_2001",)),
        ForeignMethod("liquidity_friction_combo", "liquidity", "liquidity_combo", rank="liquidity_composite", source_keys=("corwin_schultz_2012", "lesmond_ogden_trzcinka_1999", "roll_1984")),
        ForeignMethod("rank_liquidity_composite", "liquidity", rank="liquidity_composite", source_keys=("corwin_schultz_2012", "lesmond_ogden_trzcinka_1999", "roll_1984")),
        ForeignMethod("parkinson_vol_bottom_half", "volatility", "parkinson_bottom_half", source_keys=("parkinson_1980",)),
        ForeignMethod("rank_low_parkinson_vol", "volatility", rank="low_parkinson", source_keys=("parkinson_1980",)),
        ForeignMethod("yang_zhang_vol_bottom_half", "volatility", "yang_zhang_bottom_half", source_keys=("yang_zhang_2000", "rogers_satchell_1991")),
        ForeignMethod("rank_low_yang_zhang_vol", "volatility", rank="low_yang_zhang", source_keys=("yang_zhang_2000", "rogers_satchell_1991")),
        ForeignMethod("downside_semivol_bottom_half", "tail_risk", "downside_semivol_bottom_half", source_keys=("ang_chen_xing_2006",)),
        ForeignMethod("rank_low_downside_semivol", "tail_risk", rank="low_downside_semivol", source_keys=("ang_chen_xing_2006",)),
        ForeignMethod("downside_beta_bottom_half", "tail_risk", "downside_beta_bottom_half", source_keys=("ang_chen_xing_2006",)),
        ForeignMethod("rank_low_downside_beta", "tail_risk", rank="low_downside_beta", source_keys=("ang_chen_xing_2006",)),
        ForeignMethod("skew_below_median", "tail_risk", "skew_below_median", source_keys=("ang_hodrick_xing_zhang_2006",)),
        ForeignMethod("rank_low_skew", "tail_risk", rank="low_skew", source_keys=("ang_hodrick_xing_zhang_2006",)),
        ForeignMethod("calm_tail_combo", "tail_risk", "calm_tail_combo", rank="calm_tail_composite", source_keys=("yang_zhang_2000", "ang_chen_xing_2006")),
        ForeignMethod("historical_gap_z_minus2", "gap_surprise", "gap_z_minus2", source_keys=("lehmann_1990",)),
        ForeignMethod("historical_gap_z_minus3", "gap_surprise", "gap_z_minus3", source_keys=("lehmann_1990",)),
        ForeignMethod("rank_historical_gap_surprise", "gap_surprise", rank="gap_surprise", source_keys=("lehmann_1990",)),
        ForeignMethod("prior_overnight_losers", "return_decomposition", "overnight_losers", source_keys=("lou_polk_skouras_2019",)),
        ForeignMethod("prior_intraday_winners", "return_decomposition", "intraday_winners", source_keys=("lou_polk_skouras_2019",)),
        ForeignMethod("tug_of_war_reversal", "return_decomposition", "tug_of_war", rank="tug_of_war", source_keys=("lou_polk_skouras_2019",)),
        ForeignMethod("rank_tug_of_war", "return_decomposition", rank="tug_of_war", source_keys=("lou_polk_skouras_2019",)),
        ForeignMethod(
            "tick_ratio_bottom_half",
            "execution",
            "tick_ratio_bottom_half",
            source_keys=(
                "krx_tick_size_current",
                "krx_kosdaq_tick_size_pre_2023",
                "krx_tick_reform_2023",
            ),
        ),
        ForeignMethod(
            "rank_low_tick_ratio",
            "execution",
            rank="low_tick_ratio",
            source_keys=(
                "krx_tick_size_current",
                "krx_kosdaq_tick_size_pre_2023",
                "krx_tick_reform_2023",
            ),
        ),
        ForeignMethod("qqq_down_1pct", "global_context", market_rule="qqq_down_1pct", source_keys=("wang_2013_korean_adr",)),
        ForeignMethod("qqq_down_2pct", "global_context", market_rule="qqq_down_2pct", source_keys=("wang_2013_korean_adr",)),
        ForeignMethod("spy_down_1pct", "global_context", market_rule="spy_down_1pct", source_keys=("wang_2013_korean_adr",)),
        ForeignMethod("us_broad_down_1pct", "global_context", market_rule="us_broad_down_1pct", source_keys=("wang_2013_korean_adr",)),
        ForeignMethod("qqq_nonpositive", "global_context", market_rule="qqq_nonpositive", source_keys=("wang_2013_korean_adr",)),
        ForeignMethod("kosdaq_us_residual_gap_minus1", "global_context", market_rule="residual_gap_minus1", source_keys=("wang_2013_korean_adr",)),
        ForeignMethod("kosdaq_us_residual_gap_minus2", "global_context", market_rule="residual_gap_minus2", source_keys=("wang_2013_korean_adr",)),
        ForeignMethod("us_overreaction_combo", "global_context", market_rule="us_overreaction_combo", source_keys=("wang_2013_korean_adr", "amihud_mendelson_1989")),
        ForeignMethod("qqq_absolute_shock_1pct", "global_nonlinearity", market_rule="qqq_absolute_1pct", source_keys=("park_yi_2011",)),
        ForeignMethod("qqq_up_1pct", "global_nonlinearity", market_rule="qqq_up_1pct", source_keys=("park_yi_2011",)),
        ForeignMethod("qqq_down_gap_z_not_extreme", "global_nonlinearity", "gap_z_above_minus3", market_rule="qqq_down_1pct", source_keys=("ham_ryu_webb_yu_2023", "park_yi_2011")),
        ForeignMethod("qqq_down_gap_z_extreme", "global_nonlinearity", "gap_z_minus3", market_rule="qqq_down_1pct", source_keys=("ham_ryu_webb_yu_2023", "park_yi_2011")),
        ForeignMethod("qqq_down_rank_low_parkinson", "global_volatility_interaction", rank="low_parkinson", market_rule="qqq_down_1pct", source_keys=("abdi_2019", "parkinson_1980")),
        ForeignMethod("qqq_down_rank_high_parkinson", "global_volatility_interaction", rank="high_parkinson", market_rule="qqq_down_1pct", source_keys=("abdi_2019", "parkinson_1980")),
        ForeignMethod("partial_gap_above_prior_low", "gap_geometry", "partial_gap", source_keys=("aiche_cohen_griskin_2024",)),
        ForeignMethod("full_gap_below_prior_low", "gap_geometry", "full_gap", source_keys=("aiche_cohen_griskin_2024",)),
        ForeignMethod("prior_gap_positive_flip", "gap_sequence", "prior_gap_positive", source_keys=("aiche_cohen_griskin_2024",)),
        ForeignMethod("prior_gap_nonpositive", "gap_sequence", "prior_gap_nonpositive", source_keys=("aiche_cohen_griskin_2024",)),
        ForeignMethod("prior_intraday_loser", "prior_day_state", "prior_intraday_loser", source_keys=("an_huang_li_2022",)),
        ForeignMethod("prior_intraday_winner", "prior_day_state", "prior_intraday_winner", source_keys=("an_huang_li_2022",)),
        ForeignMethod("max60_bottom_two_thirds", "lottery_profile", "max60_bottom_two_thirds", source_keys=("kim_cho_2018_lottery",)),
        ForeignMethod("rank_low_max60", "lottery_profile", rank="low_max60", source_keys=("kim_cho_2018_lottery",)),
        ForeignMethod("max60_top_third_falsification", "lottery_profile", "max60_top_third", source_keys=("kim_cho_2018_lottery",)),
        ForeignMethod("near_52w_high_top_half", "price_anchor_state", "near_52w_high", source_keys=("george_hwang_2004_52week_high",)),
        ForeignMethod("far_from_52w_high_bottom_half", "price_anchor_state", "far_from_52w_high", source_keys=("george_hwang_2004_52week_high",)),
        ForeignMethod("rank_near_52w_high", "price_anchor_state", "history252", rank="near_52w_high", source_keys=("george_hwang_2004_52week_high",)),
        ForeignMethod("prior1_loser_market_vol_stress", "liquidity_crisis_reversal", "prior1_loser_market_vol_high", source_keys=("nagel_2012_evaporating_liquidity",)),
        ForeignMethod("prior1_loser_market_vol_calm", "liquidity_crisis_reversal", "prior1_loser_market_vol_not_high", source_keys=("nagel_2012_evaporating_liquidity",)),
        ForeignMethod("rank_prior1_loss_market_vol_stress", "liquidity_crisis_reversal", "prior1_loser_market_vol_high", rank="prior1_loss", source_keys=("nagel_2012_evaporating_liquidity",)),
        ForeignMethod("market_beta_bottom_half", "day_night_beta", "beta_bottom_half", source_keys=("hendershott_livdan_rosch_2020",)),
        ForeignMethod("rank_low_market_beta", "day_night_beta", rank="low_beta", source_keys=("hendershott_livdan_rosch_2020",)),
        ForeignMethod("market_beta_top_half_falsification", "day_night_beta", "beta_top_half", source_keys=("hendershott_livdan_rosch_2020",)),
        ForeignMethod("exclude_official_warning_risk", "official_alert_state", "exclude_official_warning_risk", source_keys=("krx_kind_historical_alerts",)),
        ForeignMethod("exclude_all_official_alerts", "official_alert_state", "exclude_all_official_alerts", source_keys=("krx_kind_historical_alerts",)),
        ForeignMethod("official_alert_active_falsification", "official_alert_state", "official_alert_active", source_keys=("krx_kind_historical_alerts",)),
        ForeignMethod("market_spread_not_stressed", "market_liquidity", "market_spread_not_stressed", source_keys=("chordia_roll_subrahmanyam_2000", "corwin_schultz_2012")),
        ForeignMethod("market_spread_stressed", "market_liquidity", "market_spread_stressed", source_keys=("chordia_roll_subrahmanyam_2000", "corwin_schultz_2012")),
        ForeignMethod("market_zero_return_not_stressed", "market_liquidity", "market_zero_not_stressed", source_keys=("chordia_roll_subrahmanyam_2000", "lesmond_ogden_trzcinka_1999")),
        ForeignMethod("market_range_vol_high", "market_liquidity", "market_range_vol_high", source_keys=("chordia_roll_subrahmanyam_2000", "yang_zhang_2000")),
        ForeignMethod("market_gap_breadth_high", "market_state", "market_gap_breadth_high", source_keys=("amihud_mendelson_1989",)),
        ForeignMethod("market_gap_breadth_extreme", "market_state", "market_gap_breadth_extreme", source_keys=("amihud_mendelson_1989",)),
        ForeignMethod("market_gap_mean_extreme", "market_state", "market_gap_mean_extreme", source_keys=("amihud_mendelson_1989",)),
        ForeignMethod("exclude_monday", "calendar", market_rule="exclude_monday", source_keys=("french_1980",)),
        ForeignMethod("monday_only", "calendar", market_rule="monday_only", source_keys=("french_1980",)),
        ForeignMethod("tuesday_to_thursday", "calendar", market_rule="tuesday_to_thursday", source_keys=("french_1980",)),
        ForeignMethod("friday_only", "calendar", market_rule="friday_only", source_keys=("french_1980",)),
        ForeignMethod("month_first_half", "calendar", market_rule="month_first_half", source_keys=("ariel_1987",)),
        ForeignMethod("month_second_half", "calendar", market_rule="month_second_half", source_keys=("ariel_1987",)),
        ForeignMethod("turn_of_month", "calendar", market_rule="turn_of_month", source_keys=("lakonishok_smidt_1988",)),
        ForeignMethod("exclude_turn_of_month", "calendar", market_rule="exclude_turn_of_month", source_keys=("lakonishok_smidt_1988",)),
        ForeignMethod("volume_cap_065_anchor", "volume_sensitivity", source_keys=("campbell_grossman_wang_1993", "mclean_pontiff_2016"), universe="volume_cap_065"),
        ForeignMethod("volume_cap_100_anchor", "volume_sensitivity", source_keys=("campbell_grossman_wang_1993", "mclean_pontiff_2016"), universe="volume_cap_100"),
        ForeignMethod("volume_cap_125_anchor", "volume_sensitivity", source_keys=("campbell_grossman_wang_1993", "mclean_pontiff_2016"), universe="volume_cap_125"),
        ForeignMethod("volume_cap_150_anchor", "volume_sensitivity", source_keys=("campbell_grossman_wang_1993", "mclean_pontiff_2016"), universe="volume_cap_150"),
        ForeignMethod("volume_relaxed_anchor", "volume_reversal", source_keys=("campbell_grossman_wang_1993",), universe="volume_relaxed"),
        ForeignMethod("anchor_prior1_loser", "volume_reversal", "prior1_loser", source_keys=("campbell_grossman_wang_1993",)),
        ForeignMethod("volume_relaxed_prior1_loser", "volume_reversal", "prior1_loser", source_keys=("campbell_grossman_wang_1993",), universe="volume_relaxed"),
        ForeignMethod("volume_relaxed_high_volume_prior1_loser", "volume_reversal", "prior1_high_volume_loser", source_keys=("campbell_grossman_wang_1993", "conrad_hameed_niden_1994"), universe="volume_relaxed"),
        ForeignMethod("volume_relaxed_rank_prior1_volume_reversal", "volume_reversal", rank="prior1_volume_reversal", source_keys=("campbell_grossman_wang_1993", "conrad_hameed_niden_1994"), universe="volume_relaxed"),
        ForeignMethod("anchor_prior10_bottom_third", "extreme_loss", "prior10_bottom_third", source_keys=("bremer_sweeney_1991", "bremer_hiraki_sweeney_1997")),
        ForeignMethod("anchor_rank_prior10_loss", "extreme_loss", rank="prior10_loss", source_keys=("bremer_sweeney_1991", "bremer_hiraki_sweeney_1997")),
        ForeignMethod("volume_relaxed_prior10_bottom_third", "extreme_loss", "prior10_bottom_third", source_keys=("bremer_sweeney_1991", "bremer_hiraki_sweeney_1997"), universe="volume_relaxed"),
        ForeignMethod("volume_relaxed_rank_prior10_volume_reversal", "extreme_loss", rank="prior10_volume_reversal", source_keys=("bremer_sweeney_1991", "campbell_grossman_wang_1993"), universe="volume_relaxed"),
        ForeignMethod("volume_relaxed_high_volume_loser_qqq_nonpositive", "stress_liquidity", "prior1_high_volume_loser", market_rule="qqq_nonpositive", source_keys=("hameed_kang_viswanathan_2010", "campbell_grossman_wang_1993"), universe="volume_relaxed"),
    ]


def _quantile(values: Sequence[float], probability: float) -> float:
    finite = sorted(value for value in values if math.isfinite(value))
    if not finite:
        return math.nan
    if len(finite) == 1:
        return finite[0]
    position = (len(finite) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    weight = position - lower
    return finite[lower] * (1.0 - weight) + finite[upper] * weight


def database_universe_audit(db_path: str) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        symbols = connection.execute(
            """
            SELECT symbol,MIN(substr(timestamp,1,10)) AS first_date,
              MAX(substr(timestamp,1,10)) AS last_date,COUNT(*) AS rows
            FROM candle_cache WHERE interval='1d' GROUP BY symbol
            """
        ).fetchall()
        annual = connection.execute(
            """
            SELECT substr(timestamp,1,4) AS year,COUNT(DISTINCT symbol) AS symbols,
              COUNT(*) AS rows
            FROM candle_cache WHERE interval='1d' GROUP BY year ORDER BY year
            """
        ).fetchall()
        intervals = connection.execute(
            "SELECT interval,COUNT(*) AS rows FROM candle_cache GROUP BY interval ORDER BY interval"
        ).fetchall()
    finally:
        connection.close()
    latest_date = max((str(row["last_date"]) for row in symbols), default="")
    latest_month = latest_date[:7]
    ending_before_2025 = sum(str(row["last_date"]) < "2025-01-01" for row in symbols)
    survivor_shaped = bool(symbols) and ending_before_2025 == 0
    return {
        "interval_rows": {
            str(row["interval"]): int(row["rows"]) for row in intervals
        },
        "intraday_rows_available": sum(
            int(row["rows"]) for row in intervals if str(row["interval"]) != "1d"
        ),
        "total_symbols": len(symbols),
        "latest_date": latest_date,
        "symbols_reaching_latest_month": sum(
            str(row["last_date"]).startswith(latest_month) for row in symbols
        ),
        "symbols_ending_before_2025": ending_before_2025,
        "symbols_present_by_end_2011": sum(
            str(row["first_date"]) <= "2011-12-31" for row in symbols
        ),
        "annual_distinct_symbols": {
            str(row["year"]): int(row["symbols"]) for row in annual
        },
        "survivorship_shape_detected": survivor_shaped,
        "interpretation": (
            "No old-only symbols means delisted historical losers are effectively absent; returns are upward biased."
            if survivor_shaped
            else "Old-only symbols are present, but source coverage and historical warning-state completeness still require a separate audit."
        )
        + " A daily-only cache cannot verify a 09:01 fill.",
    }


def survivorship_limit(audit: dict[str, Any]) -> str:
    if audit["survivorship_shape_detected"]:
        return (
            "The primary candle DB is current-survivor-shaped, so historical "
            "delisted losers are effectively missing."
        )
    return (
        "Old-only symbols are present, but historical listing coverage, "
        "warning/VI/halt states, delisting returns, and source normalization "
        "remain incomplete; this is a survivorship sensitivity dataset, not "
        "bias-free ground truth."
    )


def delisted_metadata_exposure_audit(
    db_path: str,
    trades_by_method: dict[str, Sequence[Trade]],
    *,
    start: str,
    end: str,
) -> dict[str, Any]:
    """Measure strategy overlap with the research-only delisted-symbol supplement."""
    connection = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='research_delisted_source_metadata'"
        ).fetchone()
        if table_exists is None:
            return {
                "available": False,
                "reason": "research_delisted_source_metadata table is absent",
                "window": f"{start}~{end}",
                "methods": {},
            }
        rows = connection.execute(
            """
            SELECT symbol,company_name,category,delisting_date,status
            FROM research_delisted_source_metadata
            WHERE status='ok'
            """
        ).fetchall()
    finally:
        connection.close()

    metadata = {
        str(row["symbol"]): {
            "company_name": str(row["company_name"]),
            "category": str(row["category"]),
            "delisting_date": str(row["delisting_date"]),
        }
        for row in rows
    }
    method_rows: dict[str, Any] = {}
    for name, trades in trades_by_method.items():
        scoped_trades = [trade for trade in trades if start <= trade.date <= end]
        overlap = [trade for trade in scoped_trades if trade.symbol in metadata]
        category_counts = Counter(metadata[trade.symbol]["category"] for trade in overlap)
        method_rows[name] = {
            "trades": len(scoped_trades),
            "metadata_overlap_trades": len(overlap),
            "metadata_overlap_share": (
                len(overlap) / len(scoped_trades) if scoped_trades else 0.0
            ),
            "metadata_overlap_symbols": len({trade.symbol for trade in overlap}),
            "metadata_overlap_net_pnl": sum(trade.net_pnl for trade in overlap),
            "category_counts": dict(sorted(category_counts.items())),
        }
    return {
        "available": True,
        "window": f"{start}~{end}",
        "metadata_symbols": len(metadata),
        "lineage_warning": (
            "This is symbol-metadata overlap, not row-level source lineage; it is a "
            "survivorship sensitivity diagnostic only."
        ),
        "methods": method_rows,
    }


def _read_jsonl(path: str) -> tuple[list[dict[str, Any]], int]:
    source = Path(path)
    if not source.exists():
        return [], 0
    rows: list[dict[str, Any]] = []
    malformed = 0
    for line in source.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            malformed += 1
            continue
        if isinstance(value, dict):
            rows.append(value)
        else:
            malformed += 1
    return rows, malformed


def execution_observation_audit(
    spread_history_path: str, paper_observations_path: str
) -> dict[str, Any]:
    spread_rows, spread_malformed = _read_jsonl(spread_history_path)
    paper_rows, paper_malformed = _read_jsonl(paper_observations_path)
    spread_bps: list[float] = []
    spread_symbols: set[str] = set()
    spread_dates: set[str] = set()
    near_open = 0
    kst_times: list[str] = []
    for row in spread_rows:
        spread = row.get("spread")
        observed_at = str(row.get("observed_at") or "")
        symbol = str(row.get("symbol") or "")
        if symbol:
            spread_symbols.add(symbol)
        if len(observed_at) >= 10:
            spread_dates.add(observed_at[:10])
        if observed_at:
            try:
                kst = datetime.fromisoformat(observed_at).astimezone(
                    ZoneInfo("Asia/Seoul")
                )
                minute = kst.hour * 60 + kst.minute
                near_open += 9 * 60 <= minute <= 9 * 60 + 10
                kst_times.append(kst.strftime("%H:%M:%S"))
            except ValueError:
                pass
        if not isinstance(spread, dict) or not spread.get("available"):
            continue
        try:
            spread_bps.append(float(spread["spread_bps"]))
        except (KeyError, TypeError, ValueError):
            continue
    paper_dates = {
        str(row.get("observed_at"))[:10]
        for row in paper_rows
        if row.get("observed_at")
    }
    status_counts = Counter(str(row.get("status") or "unknown") for row in paper_rows)
    sufficient = (
        len(spread_symbols) >= 30
        and len(spread_dates) >= 20
        and near_open >= 100
    )
    return {
        "spread_history": {
            "rows": len(spread_rows),
            "malformed_rows": spread_malformed,
            "symbols": len(spread_symbols),
            "dates": len(spread_dates),
            "available_quotes": len(spread_bps),
            "near_0901_observations": near_open,
            "kst_time_min": min(kst_times) if kst_times else None,
            "kst_time_max": max(kst_times) if kst_times else None,
            "median_spread_bps": statistics.median(spread_bps)
            if spread_bps
            else None,
            "p90_spread_bps": _quantile(spread_bps, 0.9)
            if spread_bps
            else None,
        },
        "paper_observations": {
            "rows": len(paper_rows),
            "malformed_rows": paper_malformed,
            "dates": len(paper_dates),
            "status_counts": dict(sorted(status_counts.items())),
            "orders_sent": sum(bool(row.get("order_sent")) for row in paper_rows),
        },
        "sufficient_to_calibrate_0901_execution": sufficient,
        "interpretation": "Local quote observations are too narrow and off-time to calibrate 09:01 fills.",
    }


def _history(candidates: Sequence[ForeignEvent]) -> list[ForeignEvent]:
    return [row for row in candidates if row.feature_history60 >= 40]


def _history252(candidates: Sequence[ForeignEvent]) -> list[ForeignEvent]:
    return [row for row in candidates if row.feature_history252 >= 252]


def base_passes(
    event: ForeignEvent, market: ForeignMarket, method: ForeignMethod
) -> bool:
    if market.open_vs_sma5 > -0.01:
        return False
    common = (
        event.gap <= -0.05
        and 1000.0 <= event.prev_close <= 8000.0
        and event.open <= 8000.0
        and event.prev_vol_ratio >= 0.0
    )
    volume_caps = {
        "anchor": 0.8,
        "volume_cap_065": 0.65,
        "volume_cap_100": 1.0,
        "volume_cap_125": 1.25,
        "volume_cap_150": 1.5,
        "volume_relaxed": 2.0,
    }
    if method.universe in volume_caps:
        return common and event.prev_vol_ratio < volume_caps[method.universe]
    raise ValueError(f"unknown universe: {method.universe}")


def tick_size(price: float, trade_date: str | None = None) -> float:
    if trade_date is not None and trade_date[:10] < TICK_REFORM_DATE:
        if price < 1000.0:
            return 1.0
        if price < 5000.0:
            return 5.0
        if price < 10000.0:
            return 10.0
        if price < 50000.0:
            return 50.0
        return 100.0
    if price < 2000.0:
        return 1.0
    if price < 5000.0:
        return 5.0
    if price < 20000.0:
        return 10.0
    if price < 50000.0:
        return 50.0
    if price < 200000.0:
        return 100.0
    if price < 500000.0:
        return 500.0
    return 1000.0


def tick_ratio(event: ForeignEvent) -> float:
    return (
        tick_size(event.open, event.date) / event.open
        if event.open > 0
        else math.inf
    )


def apply_filter(candidates: Sequence[ForeignEvent], rule: str) -> list[ForeignEvent]:
    if rule == "none":
        return list(candidates)
    if rule == "exclude_official_warning_risk":
        return [
            row
            for row in candidates
            if not row.official_warning_active and not row.official_risk_active
        ]
    if rule == "exclude_all_official_alerts":
        return [
            row
            for row in candidates
            if not (
                row.official_attention_active
                or row.official_warning_active
                or row.official_risk_active
            )
        ]
    if rule == "official_alert_active":
        return [
            row
            for row in candidates
            if row.official_attention_active
            or row.official_warning_active
            or row.official_risk_active
        ]
    if rule == "history252":
        return _history252(candidates)
    if rule in {"near_52w_high", "far_from_52w_high"}:
        long_history = _history252(candidates)
        if not long_history:
            return []
        cutoff = _quantile(
            [row.prior_close_to_high252 for row in long_history], 0.5
        )
        if rule == "near_52w_high":
            return [
                row
                for row in long_history
                if row.prior_close_to_high252 >= cutoff
            ]
        return [
            row
            for row in long_history
            if row.prior_close_to_high252 < cutoff
        ]
    rows = _history(candidates)
    if not rows:
        return []
    field_rules = {
        "cs_bottom_half": ("cs_spread20", 0.5),
        "zero_bottom_two_thirds": ("zero_return_share20", 2.0 / 3.0),
        "roll_bottom_half": ("roll_spread60", 0.5),
        "dollar_cv_bottom_half": ("dollar_volume_cv20", 0.5),
        "parkinson_bottom_half": ("parkinson_vol20", 0.5),
        "yang_zhang_bottom_half": ("yang_zhang_vol20", 0.5),
        "downside_semivol_bottom_half": ("downside_semivol60", 0.5),
        "downside_beta_bottom_half": ("downside_beta60", 0.5),
        "skew_below_median": ("skew60", 0.5),
        "max60_bottom_two_thirds": ("max_return60", 2.0 / 3.0),
        "beta_bottom_half": ("beta60", 0.5),
    }
    if rule in field_rules:
        field, probability = field_rules[rule]
        cutoff = _quantile([float(getattr(row, field)) for row in rows], probability)
        return [row for row in rows if float(getattr(row, field)) <= cutoff]
    if rule == "liquidity_combo":
        cs = _quantile([row.cs_spread20 for row in rows], 2.0 / 3.0)
        zero = _quantile([row.zero_return_share20 for row in rows], 2.0 / 3.0)
        roll = _quantile([row.roll_spread60 for row in rows], 2.0 / 3.0)
        return [
            row
            for row in rows
            if row.cs_spread20 <= cs
            and row.zero_return_share20 <= zero
            and row.roll_spread60 <= roll
        ]
    if rule == "calm_tail_combo":
        yz = _quantile([row.yang_zhang_vol20 for row in rows], 2.0 / 3.0)
        downside = _quantile([row.downside_semivol60 for row in rows], 2.0 / 3.0)
        skew = _quantile([row.skew60 for row in rows], 2.0 / 3.0)
        return [
            row
            for row in rows
            if row.yang_zhang_vol20 <= yz
            and row.downside_semivol60 <= downside
            and row.skew60 <= skew
        ]
    if rule == "gap_z_minus2":
        return [row for row in rows if row.historical_gap_z60 <= -2.0]
    if rule == "gap_z_minus3":
        return [row for row in rows if row.historical_gap_z60 <= -3.0]
    if rule == "gap_z_above_minus3":
        return [row for row in rows if row.historical_gap_z60 > -3.0]
    if rule == "overnight_losers":
        return [row for row in rows if row.overnight_sum20 < 0.0]
    if rule == "intraday_winners":
        return [row for row in rows if row.intraday_sum20 > 0.0]
    if rule == "tug_of_war":
        return [
            row
            for row in rows
            if row.overnight_sum20 < 0.0 and row.intraday_sum20 > 0.0
        ]
    if rule == "partial_gap":
        return [row for row in rows if row.open >= row.prev_low > 0.0]
    if rule == "full_gap":
        return [row for row in rows if 0.0 < row.open < row.prev_low]
    if rule == "prior_gap_positive":
        return [row for row in rows if row.prev_gap1 > 0.0]
    if rule == "prior_gap_nonpositive":
        return [row for row in rows if row.prev_gap1 <= 0.0]
    if rule == "prior_intraday_loser":
        return [row for row in rows if row.prev_intraday_return1 < 0.0]
    if rule == "prior_intraday_winner":
        return [row for row in rows if row.prev_intraday_return1 >= 0.0]
    if rule == "max60_top_third":
        cutoff = _quantile([row.max_return60 for row in rows], 2.0 / 3.0)
        return [row for row in rows if row.max_return60 > cutoff]
    if rule == "beta_top_half":
        cutoff = _quantile([row.beta60 for row in rows], 0.5)
        return [row for row in rows if row.beta60 > cutoff]
    if rule == "prior1_loser":
        return [row for row in rows if row.prev_return1 < 0.0]
    if rule == "prior1_loser_market_vol_high":
        return [
            row
            for row in rows
            if row.prev_return1 < 0.0 and row.market_range_vol_z60 >= 1.0
        ]
    if rule == "prior1_loser_market_vol_not_high":
        return [
            row
            for row in rows
            if row.prev_return1 < 0.0 and row.market_range_vol_z60 < 1.0
        ]
    if rule == "prior1_high_volume_loser":
        return [
            row
            for row in rows
            if row.prev_return1 < 0.0 and row.prev_vol_ratio >= 0.8
        ]
    if rule == "prior10_bottom_third":
        cutoff = _quantile([row.prev_return10 for row in rows], 1.0 / 3.0)
        return [row for row in rows if row.prev_return10 <= cutoff]
    if rule == "tick_ratio_bottom_half":
        cutoff = _quantile([tick_ratio(row) for row in rows], 0.5)
        return [row for row in rows if tick_ratio(row) <= cutoff]
    market_value = rows[0]
    if rule == "market_spread_not_stressed":
        return rows if market_value.market_cs_spread_z60 <= 0.0 else []
    if rule == "market_spread_stressed":
        return rows if market_value.market_cs_spread_z60 > 0.0 else []
    if rule == "market_zero_not_stressed":
        return rows if market_value.market_zero_return_z60 <= 0.0 else []
    if rule == "market_range_vol_high":
        return rows if market_value.market_range_vol_z60 >= 1.0 else []
    if rule == "market_gap_breadth_high":
        return rows if market_value.market_gap_breadth_z60 >= 1.0 else []
    if rule == "market_gap_breadth_extreme":
        return rows if market_value.market_gap_breadth_z60 >= 2.0 else []
    if rule == "market_gap_mean_extreme":
        return rows if market_value.market_gap_mean_z60 <= -2.0 else []
    raise ValueError(f"unknown filter rule: {rule}")


def _z_scores(candidates: Sequence[ForeignEvent], field: str) -> dict[str, float]:
    values = [float(getattr(row, field)) for row in candidates]
    finite = [value for value in values if math.isfinite(value)]
    mean = statistics.fmean(finite) if finite else 0.0
    std = statistics.pstdev(finite) if len(finite) > 1 else 0.0
    return {
        row.symbol: (float(getattr(row, field)) - mean) / std
        if std > 0 and math.isfinite(float(getattr(row, field)))
        else 0.0
        for row in candidates
    }


def ranked(candidates: Sequence[ForeignEvent], rank: str) -> list[ForeignEvent]:
    rows = list(candidates)
    if rank == "lowest_price":
        return sorted(rows, key=lambda row: (row.open, row.symbol))
    keys = {
        "low_cs": lambda row: row.cs_spread20,
        "low_zero": lambda row: row.zero_return_share20,
        "low_roll": lambda row: row.roll_spread60,
        "low_dollar_cv": lambda row: row.dollar_volume_cv20,
        "low_parkinson": lambda row: row.parkinson_vol20,
        "high_parkinson": lambda row: -row.parkinson_vol20,
        "low_yang_zhang": lambda row: row.yang_zhang_vol20,
        "low_downside_semivol": lambda row: row.downside_semivol60,
        "low_downside_beta": lambda row: row.downside_beta60,
        "low_skew": lambda row: row.skew60,
        "low_max60": lambda row: row.max_return60,
        "near_52w_high": lambda row: -row.prior_close_to_high252,
        "low_beta": lambda row: row.beta60,
        "gap_surprise": lambda row: row.historical_gap_z60,
        "tug_of_war": lambda row: row.overnight_sum20 - row.intraday_sum20,
        "prior1_volume_reversal": lambda row: row.prev_return1
        * max(row.prev_vol_ratio, 0.0),
        "prior1_loss": lambda row: row.prev_return1,
        "prior10_loss": lambda row: row.prev_return10,
        "prior10_volume_reversal": lambda row: row.prev_return10
        * max(row.prev_vol_ratio, 0.0),
        "low_tick_ratio": tick_ratio,
    }
    if rank in keys:
        return sorted(rows, key=lambda row: (keys[rank](row), row.symbol))
    if rank == "liquidity_composite":
        fields = ("cs_spread20", "zero_return_share20", "roll_spread60", "dollar_volume_cv20")
    elif rank == "calm_tail_composite":
        fields = ("yang_zhang_vol20", "downside_semivol60", "skew60")
    else:
        raise ValueError(f"unknown rank: {rank}")
    scores = {row.symbol: 0.0 for row in rows}
    for field in fields:
        z_scores = _z_scores(rows, field)
        for symbol, value in z_scores.items():
            scores[symbol] += value
    return sorted(rows, key=lambda row: (scores[row.symbol], row.symbol))


def market_passes(market: ForeignMarket, rule: str) -> bool:
    if rule == "none":
        return True
    if rule == "exclude_monday":
        return market.weekday != 0
    if rule == "monday_only":
        return market.weekday == 0
    if rule == "tuesday_to_thursday":
        return 1 <= market.weekday <= 3
    if rule == "friday_only":
        return market.weekday == 4
    if rule == "month_first_half":
        return market.trading_day_of_month <= math.ceil(
            market.trading_days_in_month / 2.0
        )
    if rule == "month_second_half":
        return market.trading_day_of_month > math.ceil(
            market.trading_days_in_month / 2.0
        )
    turn_of_month = (
        market.trading_day_of_month <= 3
        or market.trading_day_of_month == market.trading_days_in_month
    )
    if rule == "turn_of_month":
        return turn_of_month
    if rule == "exclude_turn_of_month":
        return not turn_of_month
    if market.us_session_date is None or market.us_history20 < 20:
        return False
    if rule == "qqq_down_1pct":
        return market.qqq_return <= -0.01
    if rule == "qqq_down_2pct":
        return market.qqq_return <= -0.02
    if rule == "spy_down_1pct":
        return market.spy_return <= -0.01
    if rule == "us_broad_down_1pct":
        return market.qqq_return <= -0.01 and market.spy_return <= -0.01
    if rule == "qqq_nonpositive":
        return market.qqq_return <= 0.0
    if rule == "qqq_absolute_1pct":
        return abs(market.qqq_return) >= 0.01
    if rule == "qqq_up_1pct":
        return market.qqq_return >= 0.01
    if rule == "residual_gap_minus1":
        return market.kosdaq_us_residual_gap <= -0.01
    if rule == "residual_gap_minus2":
        return market.kosdaq_us_residual_gap <= -0.02
    if rule == "us_overreaction_combo":
        return market.qqq_return <= -0.01 and market.kosdaq_us_residual_gap <= -0.01
    raise ValueError(f"unknown market rule: {rule}")


def simulate(
    events: Sequence[ForeignEvent],
    markets: dict[str, ForeignMarket],
    method: ForeignMethod,
    *,
    roundtrip_cost: float,
    execution_model: str = "reference",
) -> list[Trade]:
    grouped: dict[str, list[ForeignEvent]] = defaultdict(list)
    for event in events:
        market = markets.get(event.date)
        if (
            market is not None
            and market_passes(market, method.market_rule)
            and base_passes(event, market, method)
        ):
            grouped[event.date].append(event)
    last_market_date = max(markets) if markets else ""
    trades: list[Trade] = []
    external_method = external.Method(method.name)
    for date in sorted(grouped):
        candidates = apply_filter(grouped[date], method.filter_rule)
        selected = ranked(candidates, method.rank)
        if not selected:
            continue
        if (
            execution_model == "adverse"
            and selected[0].high < selected[0].open * 1.005
        ):
            continue
        trade = external._trade_from_single(
            selected[0],
            markets[date],
            external_method,
            roundtrip_cost=roundtrip_cost,
            execution_model=execution_model,
            last_market_date=last_market_date,
        )
        if trade is not None:
            trades.append(trade)
    return trades


def daily_bar_path_audit(
    events: Sequence[ForeignEvent],
    markets: dict[str, ForeignMarket],
    method: ForeignMethod,
    *,
    start: str = "0000-01-01",
    end: str = "9999-12-31",
) -> dict[str, Any]:
    """Count stop/take path ambiguity without pretending daily bars reveal order."""
    grouped: dict[str, list[ForeignEvent]] = defaultdict(list)
    for event in events:
        market = markets.get(event.date)
        if (
            start <= event.date <= end
            and
            market is not None
            and market_passes(market, method.market_rule)
            and base_passes(event, market, method)
        ):
            grouped[event.date].append(event)
    counts: Counter[str] = Counter()
    optimistic_ordering_uplift = 0.0
    for date in sorted(grouped):
        selected = ranked(
            apply_filter(grouped[date], method.filter_rule), method.rank
        )
        if not selected:
            continue
        event = selected[0]
        stop = event.open * (1.0 - 0.0225)
        take = event.open * (1.0 + 0.12)
        stop_hit = event.low <= stop
        take_hit = event.high >= take
        if stop_hit and take_hit:
            counts["both_stop_and_take"] += 1
            quantity = int(external.CAPITAL // event.open)
            optimistic_ordering_uplift += quantity * (take - stop)
        elif stop_hit:
            counts["stop_only"] += 1
        elif take_hit:
            counts["take_only"] += 1
        else:
            counts["neither"] += 1
    total = sum(counts.values())
    ambiguous = counts["both_stop_and_take"]
    return {
        "method": method.name,
        "window": f"{start}~{end}",
        "selected_days": total,
        "stop_only": counts["stop_only"],
        "take_only": counts["take_only"],
        "both_stop_and_take": ambiguous,
        "neither": counts["neither"],
        "ambiguous_share": ambiguous / total if total else None,
        "reference_path_assumption": "stop first whenever the daily low and high hit both thresholds",
        "optimistic_take_first_uplift_before_cost": optimistic_ordering_uplift,
        "intraday_order_is_observed": False,
    }


def break_even_cost_diagnostic(trades: Sequence[Trade]) -> dict[str, Any]:
    invested = sum(trade.invested for trade in trades)
    gross = sum(trade.gross_pnl for trade in trades)
    break_even = gross / invested if invested > 0 else None
    return {
        "trades": len(trades),
        "gross_pnl_before_cost": gross,
        "invested_notional_sum": invested,
        "break_even_roundtrip_cost": break_even,
        "margin_over_harsh_cost": break_even - COSTS["harsh"]
        if break_even is not None
        else None,
        "not_a_fill_cost_estimate": True,
    }


def kosdaq_transaction_tax_rate(trade_date: str) -> float:
    """Date-aware KOSDAQ sell tax from official Korean revisions."""
    if trade_date < "2019-05-30":
        return 0.0030
    if trade_date < "2021-01-01":
        return 0.0025
    if trade_date < "2023-01-01":
        return 0.0023
    if trade_date < "2024-01-01":
        return 0.0020
    if trade_date < "2025-01-01":
        return 0.0018
    if trade_date < "2026-01-01":
        return 0.0015
    return 0.0020


def apply_date_aware_costs(
    trades: Sequence[Trade], *, commission_per_side: float = 0.0001
) -> list[Trade]:
    """Apply dated sell tax plus an explicit commission assumption to trade gross PnL."""
    adjusted: list[Trade] = []
    for trade in trades:
        sell_notional = trade.quantity * trade.exit
        cost = (
            trade.invested * commission_per_side
            + sell_notional * commission_per_side
            + sell_notional * kosdaq_transaction_tax_rate(trade.date)
        )
        net = trade.gross_pnl - cost
        adjusted.append(
            Trade(
                **{
                    **asdict(trade),
                    "net_pnl": net,
                    "net_return_on_capital": net / external.CAPITAL,
                }
            )
        )
    return adjusted


def historical_cost_schedule_diagnostic(
    reference_trades: Sequence[Trade], tick1_trades: Sequence[Trade]
) -> dict[str, Any]:
    def windows(trades: Sequence[Trade]) -> dict[str, Any]:
        return {
            name: asdict(metrics(scoped(trades, start, end)))
            for name, (start, end) in WINDOWS.items()
        }

    reference_adjusted = apply_date_aware_costs(reference_trades)
    tick1_adjusted = apply_date_aware_costs(tick1_trades)
    return {
        "sell_tax_schedule": {
            "through_2019_05_29": 0.0030,
            "2019_05_30_through_2020": 0.0025,
            "2021_through_2022": 0.0023,
            "2023": 0.0020,
            "2024": 0.0018,
            "2025": 0.0015,
            "2026_plus_current_rule": 0.0020,
        },
        "commission_per_side_assumption": 0.0001,
        "reference_execution": windows(reference_adjusted),
        "one_tick_adverse_execution": windows(tick1_adjusted),
        "interpretation": (
            "Date-aware tax is more historically grounded than a constant cost, but "
            "the commission is an explicit assumption and one tick still omits queue, "
            "spread depth, VI, and rejected orders."
        ),
    }


def paired_selection_change_audit(
    candidate_trades: Sequence[Trade],
    anchor_trades: Sequence[Trade],
    events: Sequence[ForeignEvent],
    *,
    start: str,
    end: str,
) -> dict[str, Any]:
    """Describe changed selections and concentration without tuning a new cutoff."""
    candidate = {
        trade.date: trade for trade in candidate_trades if start <= trade.date <= end
    }
    anchor = {
        trade.date: trade for trade in anchor_trades if start <= trade.date <= end
    }
    feature_map = {(row.date, row.symbol): row for row in events}
    rows: list[dict[str, Any]] = []
    yearly_difference: defaultdict[str, float] = defaultdict(float)
    for current in sorted(set(candidate) | set(anchor)):
        candidate_trade = candidate.get(current)
        anchor_trade = anchor.get(current)
        candidate_symbol = candidate_trade.symbol if candidate_trade else None
        anchor_symbol = anchor_trade.symbol if anchor_trade else None
        if candidate_symbol == anchor_symbol:
            continue
        difference = (candidate_trade.net_pnl if candidate_trade else 0.0) - (
            anchor_trade.net_pnl if anchor_trade else 0.0
        )
        candidate_event = feature_map.get((current, candidate_symbol))
        anchor_event = feature_map.get((current, anchor_symbol))
        yearly_difference[current[:4]] += difference
        rows.append(
            {
                "date": current,
                "candidate_symbol": candidate_symbol,
                "anchor_symbol": anchor_symbol,
                "candidate_net_pnl": candidate_trade.net_pnl
                if candidate_trade
                else 0.0,
                "anchor_net_pnl": anchor_trade.net_pnl if anchor_trade else 0.0,
                "pnl_difference": difference,
                "candidate_max_return60": candidate_event.max_return60
                if candidate_event
                else None,
                "anchor_max_return60": anchor_event.max_return60
                if anchor_event
                else None,
            }
        )
    total_difference = sum(row["pnl_difference"] for row in rows)
    positive = sorted(
        (row["pnl_difference"] for row in rows if row["pnl_difference"] > 0.0),
        reverse=True,
    )
    positive_total = sum(positive)
    top5_positive = sum(positive[:5])
    candidate_max = [
        float(row["candidate_max_return60"])
        for row in rows
        if row["candidate_max_return60"] is not None
    ]
    anchor_max = [
        float(row["anchor_max_return60"])
        for row in rows
        if row["anchor_max_return60"] is not None
    ]
    return {
        "window": f"{start}~{end}",
        "candidate_trade_dates": len(candidate),
        "anchor_trade_dates": len(anchor),
        "changed_selection_dates": len(rows),
        "candidate_missing_dates": sum(date not in candidate for date in anchor),
        "anchor_missing_dates": sum(date not in anchor for date in candidate),
        "changed_selection_total_pnl_difference": total_difference,
        "positive_changed_dates": sum(row["pnl_difference"] > 0.0 for row in rows),
        "negative_changed_dates": sum(row["pnl_difference"] < 0.0 for row in rows),
        "zero_changed_dates": sum(row["pnl_difference"] == 0.0 for row in rows),
        "top5_positive_difference_share": (
            top5_positive / positive_total if positive_total > 0.0 else None
        ),
        "difference_after_removing_top5_positive_changed_dates": (
            total_difference - top5_positive
        ),
        "candidate_max60_median_on_changed_dates": _quantile(candidate_max, 0.5),
        "anchor_max60_median_on_changed_dates": _quantile(anchor_max, 0.5),
        "yearly_pnl_difference": dict(sorted(yearly_difference.items())),
        "largest_positive_changes": sorted(
            rows, key=lambda row: row["pnl_difference"], reverse=True
        )[:10],
        "largest_negative_changes": sorted(
            rows, key=lambda row: row["pnl_difference"]
        )[:10],
        "post_selection_diagnostic_only": True,
    }


def _round_up_tick(price: float, trade_date: str | None = None) -> float:
    unit = tick_size(price, trade_date)
    return math.ceil((price - 1e-12) / unit) * unit


def _round_down_tick(price: float, trade_date: str | None = None) -> float:
    unit = tick_size(price, trade_date)
    return math.floor((price + 1e-12) / unit) * unit


def _tick_stress_trade(
    event: ForeignEvent,
    market: ForeignMarket,
    *,
    roundtrip_cost: float,
    adverse_ticks: int,
) -> Trade | None:
    entry = _round_up_tick(
        event.open + adverse_ticks * tick_size(event.open, event.date),
        event.date,
    )
    if event.high < entry:
        return None
    quantity = int(external.CAPITAL // entry)
    if quantity <= 0:
        return None
    stop = entry * (1.0 - 0.0225)
    take = entry * (1.0 + 0.12)
    if event.low <= stop:
        exit_price = _round_down_tick(
            stop - adverse_ticks * tick_size(stop, event.date), event.date
        )
        reason = f"tick{adverse_ticks}_stop"
    elif event.high >= _round_up_tick(take, event.date):
        exit_price = _round_down_tick(
            take - adverse_ticks * tick_size(take, event.date), event.date
        )
        reason = f"tick{adverse_ticks}_take"
    else:
        exit_price = _round_down_tick(
            event.close - adverse_ticks * tick_size(event.close, event.date),
            event.date,
        )
        reason = f"tick{adverse_ticks}_close"
    exit_price = max(0.0, exit_price)
    invested = quantity * entry
    gross = quantity * (exit_price - entry)
    net = gross - invested * roundtrip_cost
    return Trade(
        date=event.date,
        exit_date=event.date,
        symbol=event.symbol,
        entry=entry,
        exit=exit_price,
        quantity=quantity,
        invested=invested,
        gross_pnl=gross,
        net_pnl=net,
        net_return_on_capital=net / external.CAPITAL,
        reason=reason,
        gap=event.gap,
        avg_dollar_volume20=event.avg_dollar_volume20,
        avg_range20=event.ivol60,
        prev_return5=event.prev_return20,
        market_open_vs_sma5=market.open_vs_sma5,
    )


def execution_reachability_audit(
    events: Sequence[ForeignEvent],
    markets: dict[str, ForeignMarket],
    method: ForeignMethod,
    *,
    start: str,
    end: str,
) -> dict[str, Any]:
    grouped: dict[str, list[ForeignEvent]] = defaultdict(list)
    for event in events:
        market = markets.get(event.date)
        if (
            start <= event.date <= end
            and market is not None
            and market_passes(market, method.market_rule)
            and base_passes(event, market, method)
        ):
            grouped[event.date].append(event)
    selected: list[ForeignEvent] = []
    for current in sorted(grouped):
        ranked_rows = ranked(
            apply_filter(grouped[current], method.filter_rule), method.rank
        )
        if ranked_rows:
            selected.append(ranked_rows[0])
    half_percent_reached = sum(
        row.high >= row.open * 1.005 for row in selected
    )
    tick1_reached = sum(
        row.high
        >= _round_up_tick(
            row.open + tick_size(row.open, row.date), row.date
        )
        for row in selected
    )
    tick2_reached = sum(
        row.high
        >= _round_up_tick(
            row.open + 2 * tick_size(row.open, row.date), row.date
        )
        for row in selected
    )
    return {
        "window": f"{start}~{end}",
        "selected_daily_bar_events": len(selected),
        "adverse_half_percent_price_reached": half_percent_reached,
        "adverse_half_percent_no_fill_proxy": len(selected) - half_percent_reached,
        "one_tick_price_reached": tick1_reached,
        "one_tick_no_fill_proxy": len(selected) - tick1_reached,
        "two_tick_price_reached": tick2_reached,
        "two_tick_no_fill_proxy": len(selected) - tick2_reached,
        "same_open_fill_observed": False,
        "interpretation": "A daily high can reject unreachable limits but cannot prove post-signal fill time, queue priority, or whether the low occurred before entry.",
    }


def simulate_tick_stress(
    events: Sequence[ForeignEvent],
    markets: dict[str, ForeignMarket],
    method: ForeignMethod,
    *,
    roundtrip_cost: float,
    adverse_ticks: int,
) -> list[Trade]:
    if adverse_ticks < 1:
        raise ValueError("adverse_ticks must be positive")
    grouped: dict[str, list[ForeignEvent]] = defaultdict(list)
    for event in events:
        market = markets.get(event.date)
        if (
            market is not None
            and market_passes(market, method.market_rule)
            and base_passes(event, market, method)
        ):
            grouped[event.date].append(event)
    trades: list[Trade] = []
    for date in sorted(grouped):
        candidates = apply_filter(grouped[date], method.filter_rule)
        selected = ranked(candidates, method.rank)
        if not selected:
            continue
        trade = _tick_stress_trade(
            selected[0],
            markets[date],
            roundtrip_cost=roundtrip_cost,
            adverse_ticks=adverse_ticks,
        )
        if trade is not None:
            trades.append(trade)
    return trades


def evaluate_method_bundle(
    events: Sequence[ForeignEvent], markets: dict[str, ForeignMarket], method: ForeignMethod
) -> tuple[dict[str, Any], dict[str, list[Trade]]]:
    profiles = {
        label: simulate(events, markets, method, roundtrip_cost=cost)
        for label, cost in COSTS.items()
    }
    adverse = simulate(
        events,
        markets,
        method,
        roundtrip_cost=COSTS["harsh"],
        execution_model="adverse",
    )
    tick1 = simulate_tick_stress(
        events,
        markets,
        method,
        roundtrip_cost=COSTS["harsh"],
        adverse_ticks=1,
    )
    tick2 = simulate_tick_stress(
        events,
        markets,
        method,
        roundtrip_cost=COSTS["harsh"],
        adverse_ticks=2,
    )
    harsh = profiles["harsh"]
    score = external._pretest_score(harsh)
    evaluation = {
        "method": asdict(method),
        "pretest_score": score,
        "pretest_passed": math.isfinite(score),
        "profiles": {
            label: external.window_payload(trades)
            for label, trades in profiles.items()
        },
        "adverse_harsh": external.window_payload(adverse),
        "tick1_harsh": external.window_payload(tick1),
        "tick2_harsh": external.window_payload(tick2),
    }
    return evaluation, {
        "harsh": harsh,
        "adverse": adverse,
        "tick1": tick1,
        "tick2": tick2,
    }


def evaluate_method(
    events: Sequence[ForeignEvent], markets: dict[str, ForeignMarket], method: ForeignMethod
) -> dict[str, Any]:
    return evaluate_method_bundle(events, markets, method)[0]


def _daily_matrix(
    trades_by_name: dict[str, Sequence[Trade]], market_dates: Sequence[str]
) -> tuple[list[str], dict[str, list[float]]]:
    dates = [date for date in market_dates if SELECTION_START <= date <= SELECTION_END]
    matrix: dict[str, list[float]] = {}
    for name, trades in trades_by_name.items():
        pnl = defaultdict(float)
        for trade in trades:
            if SELECTION_START <= trade.date <= SELECTION_END:
                pnl[trade.date] += trade.net_return_on_capital
        matrix[name] = [pnl[date] for date in dates]
    return dates, matrix


def cscv_pbo_diagnostic(
    trades_by_name: dict[str, Sequence[Trade]], market_dates: Sequence[str], blocks: int = 8
) -> dict[str, Any]:
    dates, matrix = _daily_matrix(trades_by_name, market_dates)
    names = sorted(matrix)
    if len(dates) < blocks or len(names) < 2 or blocks % 2:
        return {"available": False, "reason": "insufficient observations or methods"}
    block_rows = [list(chunk) for chunk in _split_indices(len(dates), blocks)]
    below_median = 0
    logits: list[float] = []
    selections: Counter[str] = Counter()
    combinations = list(itertools.combinations(range(blocks), blocks // 2))
    for train_blocks in combinations:
        train_set = set(train_blocks)
        train_idx = [idx for block in train_set for idx in block_rows[block]]
        test_idx = [
            idx for block in range(blocks) if block not in train_set for idx in block_rows[block]
        ]
        train_scores = {
            name: statistics.fmean(matrix[name][idx] for idx in train_idx) for name in names
        }
        selected = max(names, key=lambda name: (train_scores[name], name))
        selections[selected] += 1
        test_scores = {
            name: statistics.fmean(matrix[name][idx] for idx in test_idx) for name in names
        }
        ordered = sorted(names, key=lambda name: (test_scores[name], name))
        rank = ordered.index(selected)
        percentile = (rank + 1.0) / (len(names) + 1.0)
        below_median += percentile <= 0.5
        logits.append(math.log(percentile / (1.0 - percentile)))
    return {
        "available": True,
        "selection_window": f"{SELECTION_START}~{SELECTION_END}",
        "blocks": blocks,
        "combinations": len(combinations),
        "methods": len(names),
        "pbo": below_median / len(combinations),
        "median_oos_logit": statistics.median(logits),
        "selected_counts": dict(selections.most_common()),
        "independent_significance_claim": False,
    }


def _split_indices(length: int, blocks: int) -> list[range]:
    base, extra = divmod(length, blocks)
    result: list[range] = []
    start = 0
    for block in range(blocks):
        size = base + (1 if block < extra else 0)
        result.append(range(start, start + size))
        start += size
    return result


def studentized_reality_check(
    trades_by_name: dict[str, Sequence[Trade]],
    market_dates: Sequence[str],
    *,
    samples: int = 1000,
    block_length: int = 10,
    seed: int = 20260718,
) -> dict[str, Any]:
    dates, matrix = _daily_matrix(trades_by_name, market_dates)
    anchor = matrix.get("anchor", [])
    differentials: dict[str, list[float]] = {}
    observed: dict[str, float] = {}
    for name, values in matrix.items():
        if name == "anchor":
            continue
        diff = [value - base for value, base in zip(values, anchor)]
        std = statistics.pstdev(diff) if len(diff) > 1 else 0.0
        if std <= 1e-12:
            continue
        differentials[name] = diff
        observed[name] = math.sqrt(len(diff)) * statistics.fmean(diff) / std
    if not differentials:
        return {"available": False, "reason": "no non-degenerate alternatives"}
    observed_max = max(observed.values())
    centered = {
        name: [value - statistics.fmean(values) for value in values]
        for name, values in differentials.items()
    }
    standard_deviations = {
        name: statistics.pstdev(values) for name, values in differentials.items()
    }
    rng = random.Random(seed)
    exceedances = 0
    length = len(dates)
    for _ in range(samples):
        indices: list[int] = []
        while len(indices) < length:
            start = rng.randrange(length)
            indices.extend((start + offset) % length for offset in range(block_length))
        indices = indices[:length]
        bootstrap_max = -math.inf
        for name, values in centered.items():
            mean = sum(values[idx] for idx in indices) / length
            statistic = math.sqrt(length) * mean / standard_deviations[name]
            bootstrap_max = max(bootstrap_max, statistic)
        exceedances += bootstrap_max >= observed_max
    best = max(observed, key=lambda name: (observed[name], name))
    return {
        "available": True,
        "selection_window": f"{SELECTION_START}~{SELECTION_END}",
        "bootstrap": "centered circular blocks, studentized White/Hansen-style diagnostic",
        "samples": samples,
        "block_length": block_length,
        "alternatives": len(differentials),
        "best_method": best,
        "observed_max_t": observed_max,
        "familywise_p_value": (exceedances + 1.0) / (samples + 1.0),
        "independent_significance_claim": False,
    }


def walk_forward_method_selection(
    trades_by_name: dict[str, Sequence[Trade]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    selected_counts: Counter[str] = Counter()
    selected_total = 0.0
    anchor_total = 0.0
    for test_year in range(2016, 2024):
        train_start = f"{test_year - 5}-01-01"
        train_end = f"{test_year - 1}-12-31"
        test_start = f"{test_year}-01-01"
        test_end = f"{test_year}-12-31"
        eligible: list[tuple[float, str]] = []
        for name, trades in trades_by_name.items():
            train = scoped(trades, train_start, train_end)
            train_metrics = metrics(train)
            without_top = external.missed_winners(train, 0.25)
            if (
                train_metrics.trades >= 20
                and train_metrics.total_pnl > 0
                and without_top.total_pnl > 0
                and float(train_metrics.profit_factor or 0.0) > 1.0
            ):
                score = train_metrics.total_pnl - 0.5 * train_metrics.cash_mdd
                eligible.append((score, name))
        selected = max(eligible)[1] if eligible else "anchor"
        selected_counts[selected] += 1
        selected_test = metrics(scoped(trades_by_name[selected], test_start, test_end))
        anchor_test = metrics(scoped(trades_by_name["anchor"], test_start, test_end))
        selected_total += selected_test.total_pnl
        anchor_total += anchor_test.total_pnl
        rows.append(
            {
                "test_year": test_year,
                "training_window": f"{train_start}~{train_end}",
                "selected_method": selected,
                "selected_test_pnl": selected_test.total_pnl,
                "anchor_test_pnl": anchor_test.total_pnl,
                "selected_test_trades": selected_test.trades,
                "anchor_test_trades": anchor_test.trades,
            }
        )
    return {
        "selection_data_ends": SELECTION_END,
        "main_selection_functional_replicated": False,
        "status": "approximate rolling-origin diagnostic only",
        "mismatch": "uses a five-year total-PnL-minus-MDD rule because the full 8-year train plus 5-year validation design cannot be rolled inside 2011-2023",
        "years": rows,
        "selected_counts": dict(selected_counts.most_common()),
        "walk_forward_selected_total_pnl": selected_total,
        "fixed_anchor_total_pnl": anchor_total,
        "walk_forward_minus_anchor": selected_total - anchor_total,
        "independent_significance_claim": False,
    }


def yearly_method_leaders(
    trades_by_name: dict[str, Sequence[Trade]],
    method_names: Sequence[str],
    *,
    start: str,
    end: str,
) -> dict[str, Any]:
    years = range(int(start[:4]), int(end[:4]) + 1)
    rows: list[dict[str, Any]] = []
    leaders: Counter[str] = Counter()
    for year in years:
        year_start = max(start, f"{year}-01-01")
        year_end = min(end, f"{year}-12-31")
        pnl = {
            name: sum(
                trade.net_pnl
                for trade in trades_by_name[name]
                if year_start <= trade.date <= year_end
            )
            for name in method_names
        }
        leader = max(method_names, key=lambda name: (pnl[name], name))
        leaders[leader] += 1
        rows.append(
            {
                "year": year,
                "leader": leader,
                "leader_pnl": pnl[leader],
                "anchor_pnl": pnl.get("anchor"),
                "pnl_by_method": pnl,
            }
        )
    return {
        "window": f"{start}~{end}",
        "methods": list(method_names),
        "leader_counts": dict(leaders.most_common()),
        "years": rows,
        "stable_single_winner": len(leaders) == 1,
    }


def paired_block_bootstrap_difference(
    candidate: Sequence[Trade],
    anchor: Sequence[Trade],
    market_dates: Sequence[str],
    *,
    start: str,
    end: str,
    samples: int = 5000,
    block_length: int = 10,
    seed: int = 20260718,
) -> dict[str, Any]:
    dates = [date for date in market_dates if start <= date <= end]
    candidate_pnl = defaultdict(float)
    anchor_pnl = defaultdict(float)
    for trade in candidate:
        if start <= trade.date <= end:
            candidate_pnl[trade.date] += trade.net_pnl
    for trade in anchor:
        if start <= trade.date <= end:
            anchor_pnl[trade.date] += trade.net_pnl
    differences = [candidate_pnl[date] - anchor_pnl[date] for date in dates]
    if not differences:
        return {"available": False, "reason": "empty comparison window"}
    rng = random.Random(seed)
    totals: list[float] = []
    length = len(differences)
    for _ in range(samples):
        indices: list[int] = []
        while len(indices) < length:
            block_start = rng.randrange(length)
            indices.extend(
                (block_start + offset) % length for offset in range(block_length)
            )
        totals.append(sum(differences[idx] for idx in indices[:length]))
    yearly_difference: dict[str, float] = defaultdict(float)
    for current, difference in zip(dates, differences):
        yearly_difference[current[:4]] += difference
    return {
        "available": True,
        "window": f"{start}~{end}",
        "samples": samples,
        "block_length": block_length,
        "point_estimate_pnl_difference": sum(differences),
        "bootstrap_median": statistics.median(totals),
        "bootstrap_p025": _quantile(totals, 0.025),
        "bootstrap_p975": _quantile(totals, 0.975),
        "probability_candidate_beats_anchor": sum(total > 0 for total in totals)
        / len(totals),
        "nonzero_difference_days": sum(abs(value) > 1e-12 for value in differences),
        "yearly_pnl_difference": dict(sorted(yearly_difference.items())),
        "positive_years": sum(value > 0 for value in yearly_difference.values()),
        "negative_years": sum(value < 0 for value in yearly_difference.values()),
        "independent_significance_claim": False,
    }


def paired_block_bootstrap_sensitivity(
    candidate: Sequence[Trade],
    anchor: Sequence[Trade],
    market_dates: Sequence[str],
    *,
    start: str,
    end: str,
    samples: int = 1000,
    block_lengths: Sequence[int] = (5, 10, 20),
    seed: int = 20260718,
) -> dict[str, Any]:
    return {
        "window": f"{start}~{end}",
        "samples_per_block_length": samples,
        "results": {
            str(block_length): paired_block_bootstrap_difference(
                candidate,
                anchor,
                market_dates,
                start=start,
                end=end,
                samples=samples,
                block_length=block_length,
                seed=seed + block_length,
            )
            for block_length in block_lengths
        },
        "independent_significance_claim": False,
    }


def leave_one_year_out_difference(
    candidate: Sequence[Trade],
    anchor: Sequence[Trade],
    *,
    start: str,
    end: str,
) -> dict[str, Any]:
    years = list(range(int(start[:4]), int(end[:4]) + 1))
    yearly: dict[int, float] = {}
    for year in years:
        year_start = max(start, f"{year}-01-01")
        year_end = min(end, f"{year}-12-31")
        candidate_pnl = sum(
            trade.net_pnl
            for trade in candidate
            if year_start <= trade.date <= year_end
        )
        anchor_pnl = sum(
            trade.net_pnl
            for trade in anchor
            if year_start <= trade.date <= year_end
        )
        yearly[year] = candidate_pnl - anchor_pnl
    total = sum(yearly.values())
    omitted = [
        {
            "omitted_year": year,
            "omitted_year_difference": yearly[year],
            "remaining_difference": total - yearly[year],
        }
        for year in years
    ]
    remaining = [row["remaining_difference"] for row in omitted]
    return {
        "window": f"{start}~{end}",
        "point_estimate_pnl_difference": total,
        "yearly_pnl_difference": {str(year): yearly[year] for year in years},
        "leave_one_year_out": omitted,
        "minimum_remaining_difference": min(remaining) if remaining else None,
        "maximum_remaining_difference": max(remaining) if remaining else None,
        "all_leave_one_year_out_positive": bool(remaining)
        and all(value > 0 for value in remaining),
        "independent_significance_claim": False,
    }


def tick_random_rank_benchmark(
    events: Sequence[ForeignEvent],
    markets: dict[str, ForeignMarket],
    *,
    start: str,
    end: str,
    samples: int = 2000,
    seed: int = 20260718,
) -> dict[str, Any]:
    method = methods()[0]
    by_date: dict[str, list[float]] = defaultdict(list)
    for event in events:
        market = markets.get(event.date)
        if (
            market is None
            or not (start <= event.date <= end)
            or not base_passes(event, market, method)
        ):
            continue
        trade = _tick_stress_trade(
            event,
            market,
            roundtrip_cost=COSTS["harsh"],
            adverse_ticks=2,
        )
        if trade is not None:
            by_date[event.date].append(trade.net_pnl)
    actual = metrics(
        scoped(
            simulate_tick_stress(
                events,
                markets,
                method,
                roundtrip_cost=COSTS["harsh"],
                adverse_ticks=2,
            ),
            start,
            end,
        )
    ).total_pnl
    rng = random.Random(seed)
    totals = [sum(rng.choice(values) for values in by_date.values()) for _ in range(samples)]
    return {
        "window": f"{start}~{end}",
        "execution": "current KRX price bands, two adverse ticks each side plus 1.35% cost",
        "candidate_days": len(by_date),
        "samples": samples,
        "anchor_lowest_price_pnl": actual,
        "random_median_pnl": statistics.median(totals) if totals else None,
        "random_p95_pnl": _quantile(totals, 0.95) if totals else None,
        "probability_random_beats_anchor": sum(total >= actual for total in totals)
        / len(totals)
        if totals
        else None,
    }


def _selection_comparison(row: dict[str, Any]) -> dict[str, float]:
    windows = ("train_2011_2018", "validation_2019_2023")
    return {
        "harsh_total_pnl": sum(
            row["profiles"]["harsh"][window]["metrics"]["total_pnl"]
            for window in windows
        ),
        "adverse_total_pnl": sum(
            row["adverse_harsh"][window]["metrics"]["total_pnl"]
            for window in windows
        ),
        "tick2_total_pnl": sum(
            row["tick2_harsh"][window]["metrics"]["total_pnl"]
            for window in windows
        ),
        "top25_removed_total_pnl": sum(
            row["profiles"]["harsh"][window]["miss_top_winners_25pct"][
                "total_pnl"
            ]
            for window in windows
        ),
        "max_window_mdd": max(
            row["profiles"]["harsh"][window]["metrics"]["mdd_on_capital"]
            for window in windows
        ),
    }


def selection_influence_check(
    candidate: Sequence[Trade],
    anchor: Sequence[Trade],
    *,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    def in_window(trade: Trade) -> bool:
        return (start is None or trade.date >= start) and (
            end is None or trade.date <= end
        )

    candidate_by_date = {
        trade.date: trade.net_pnl for trade in candidate if in_window(trade)
    }
    anchor_by_date = {
        trade.date: trade.net_pnl for trade in anchor if in_window(trade)
    }
    differences = [
        candidate_by_date.get(current, 0.0) - anchor_by_date.get(current, 0.0)
        for current in sorted(set(candidate_by_date) | set(anchor_by_date))
    ]
    changed = [value for value in differences if abs(value) > 1e-12]
    positives = sorted((value for value in changed if value > 0.0), reverse=True)
    negatives = [value for value in changed if value < 0.0]
    total = sum(changed)
    top5 = sum(positives[:5])
    after_top5 = total - top5
    positive_total = sum(positives)
    checks = {
        "changed_dates_at_least_20": len(changed) >= 20,
        "positive_changed_dates_exceed_negative": len(positives) > len(negatives),
        "difference_after_top5_positive": after_top5 > 0.0,
    }
    return {
        "window": {"start": start, "end": end},
        "changed_dates": len(changed),
        "positive_changed_dates": len(positives),
        "negative_changed_dates": len(negatives),
        "total_pnl_difference": total,
        "top5_positive_difference_share": top5 / positive_total
        if positive_total > 0.0
        else None,
        "difference_after_removing_top5_positive_dates": after_top5,
        "checks": checks,
        "passed": all(checks.values()),
        "status": "post-hoc conservative veto; cannot authorize a positive claim",
    }


def _trade_profile_comparison(
    harsh: Sequence[Trade],
    adverse: Sequence[Trade],
    tick2: Sequence[Trade],
) -> dict[str, float]:
    windows = (WINDOWS["train_2011_2018"], WINDOWS["validation_2019_2023"])
    harsh_windows = [scoped(harsh, *window) for window in windows]
    adverse_windows = [scoped(adverse, *window) for window in windows]
    tick2_windows = [scoped(tick2, *window) for window in windows]
    return {
        "harsh_total_pnl": sum(metrics(rows).total_pnl for rows in harsh_windows),
        "adverse_total_pnl": sum(
            metrics(rows).total_pnl for rows in adverse_windows
        ),
        "tick2_total_pnl": sum(metrics(rows).total_pnl for rows in tick2_windows),
        "top25_removed_total_pnl": sum(
            external.missed_winners(rows, 0.25).total_pnl
            for rows in harsh_windows
        ),
        "max_window_mdd": max(
            metrics(rows).mdd_on_capital for rows in harsh_windows
        ),
    }


def _circular_resample_dates(
    dates: Sequence[str], block_length: int, rng: random.Random
) -> list[str]:
    if not dates:
        return []
    sampled: list[str] = []
    while len(sampled) < len(dates):
        start = rng.randrange(len(dates))
        sampled.extend(
            dates[(start + offset) % len(dates)] for offset in range(block_length)
        )
    return sampled[: len(dates)]


def _resample_trade_profile(
    by_date: dict[str, list[Trade]],
    target_dates: Sequence[str],
    source_dates: Sequence[str],
) -> list[Trade]:
    rows: list[Trade] = []
    for target, source in zip(target_dates, source_dates):
        rows.extend(
            replace(trade, date=target, exit_date=target)
            for trade in by_date.get(source, [])
        )
    return rows


def selection_functional_block_stability(
    harsh_trades: dict[str, Sequence[Trade]],
    adverse_trades: dict[str, Sequence[Trade]],
    tick2_trades: dict[str, Sequence[Trade]],
    market_dates: Sequence[str],
    *,
    observed_selected: str | None,
    samples: int = 100,
    block_length: int = 10,
    seed: int = 20260719,
) -> dict[str, Any]:
    train_dates = [
        current
        for current in market_dates
        if WINDOWS["train_2011_2018"][0]
        <= current
        <= WINDOWS["train_2011_2018"][1]
    ]
    validation_dates = [
        current
        for current in market_dates
        if WINDOWS["validation_2019_2023"][0]
        <= current
        <= WINDOWS["validation_2019_2023"][1]
    ]
    names = sorted(set(harsh_trades) & set(adverse_trades) & set(tick2_trades))
    if not train_dates or not validation_dates or "anchor" not in names:
        return {"available": False, "reason": "selection windows or anchor absent"}

    def indexed(source: dict[str, Sequence[Trade]]):
        result: dict[str, dict[str, list[Trade]]] = {}
        for name, trades in source.items():
            rows: dict[str, list[Trade]] = defaultdict(list)
            for trade in trades:
                if SELECTION_START <= trade.date <= SELECTION_END:
                    rows[trade.date].append(trade)
            result[name] = dict(rows)
        return result

    indexed_harsh = indexed(harsh_trades)
    indexed_adverse = indexed(adverse_trades)
    indexed_tick2 = indexed(tick2_trades)
    rng = random.Random(seed)
    selected_counts: Counter[str] = Counter()
    passer_counts: Counter[str] = Counter()
    any_passer = 0
    selected_passed = 0
    observed_selected_passed = 0
    no_eligible = 0
    for _ in range(samples):
        target_dates = train_dates + validation_dates
        source_dates = _circular_resample_dates(
            train_dates, block_length, rng
        ) + _circular_resample_dates(validation_dates, block_length, rng)
        synthetic: dict[str, dict[str, list[Trade]]] = {}
        for name in names:
            synthetic[name] = {
                "harsh": _resample_trade_profile(
                    indexed_harsh[name], target_dates, source_dates
                ),
                "adverse": _resample_trade_profile(
                    indexed_adverse[name], target_dates, source_dates
                ),
                "tick2": _resample_trade_profile(
                    indexed_tick2[name], target_dates, source_dates
                ),
            }
        anchor_comparison = _trade_profile_comparison(**synthetic["anchor"])
        scores: dict[str, float] = {}
        passers: set[str] = set()
        for name in names:
            if name == "anchor":
                continue
            profile = synthetic[name]
            score = external._pretest_score(profile["harsh"])
            if not math.isfinite(score):
                continue
            scores[name] = score
            candidate = _trade_profile_comparison(**profile)
            influence = selection_influence_check(
                profile["harsh"], synthetic["anchor"]["harsh"]
            )
            checks = (
                candidate["harsh_total_pnl"]
                > anchor_comparison["harsh_total_pnl"],
                candidate["adverse_total_pnl"]
                > anchor_comparison["adverse_total_pnl"],
                candidate["tick2_total_pnl"]
                > anchor_comparison["tick2_total_pnl"],
                candidate["top25_removed_total_pnl"]
                > anchor_comparison["top25_removed_total_pnl"],
                candidate["max_window_mdd"]
                <= anchor_comparison["max_window_mdd"],
                influence["passed"],
            )
            if all(checks):
                passers.add(name)
                passer_counts[name] += 1
        if not scores:
            no_eligible += 1
            continue
        selected = max(scores, key=lambda name: (scores[name], name))
        selected_counts[selected] += 1
        if passers:
            any_passer += 1
        if selected in passers:
            selected_passed += 1
        if observed_selected is not None and observed_selected in passers:
            observed_selected_passed += 1
    return {
        "available": True,
        "selection_window": f"{SELECTION_START}~{SELECTION_END}",
        "samples": samples,
        "block_length": block_length,
        "methods": len(names),
        "selection_functional": "exact pretest score plus harsh/adverse/two-tick/top25/MDD and paired-influence veto",
        "selected_counts": dict(selected_counts.most_common()),
        "incremental_passer_counts": dict(passer_counts.most_common()),
        "no_pretest_eligible_samples": no_eligible,
        "probability_any_incremental_passer": any_passer / samples,
        "probability_score_winner_also_passes": selected_passed / samples,
        "observed_selected": observed_selected,
        "probability_observed_selected_passes": observed_selected_passed / samples,
        "recent_2024_plus_gate_included": False,
        "previously_searched_hypotheses_outside_manifest_included": False,
        "confirmatory_p_value": None,
        "interpretation": "This measures block-resampled selection stability, not statistical significance; unrecorded prior searches and the reused recent period prevent confirmation.",
    }


def selection_decision(
    evaluations: Sequence[dict[str, Any]],
    harsh_trades: dict[str, Sequence[Trade]] | None = None,
) -> dict[str, Any]:
    anchor = next(row for row in evaluations if row["method"]["name"] == "anchor")
    eligible = [
        row
        for row in evaluations
        if row["method"]["name"] != "anchor" and row["pretest_passed"]
    ]
    if not eligible:
        return {
            "selected_on_2011_2023": None,
            "recommended_research_strategy": "anchor",
            "historical_incremental_gate_passed": False,
            "historical_gate_passed": False,
            "live_change_accepted": False,
            "reason": "no foreign-method candidate passed the fixed train/validation gate",
        }
    selected = max(eligible, key=lambda row: (row["pretest_score"], row["method"]["name"]))
    anchor_selection = _selection_comparison(anchor)
    fixed_checks: dict[str, dict[str, bool]] = {}
    influence_checks: dict[str, dict[str, Any]] = {}
    for row in eligible:
        name = row["method"]["name"]
        candidate = _selection_comparison(row)
        fixed_checks[name] = {
            "harsh_total_beats_anchor": candidate["harsh_total_pnl"]
            > anchor_selection["harsh_total_pnl"],
            "adverse_total_beats_anchor": candidate["adverse_total_pnl"]
            > anchor_selection["adverse_total_pnl"],
            "tick2_total_beats_anchor": candidate["tick2_total_pnl"]
            > anchor_selection["tick2_total_pnl"],
            "top25_removed_beats_anchor": candidate["top25_removed_total_pnl"]
            > anchor_selection["top25_removed_total_pnl"],
            "max_window_mdd_not_worse": candidate["max_window_mdd"]
            <= anchor_selection["max_window_mdd"],
        }
        if harsh_trades is not None and name in harsh_trades:
            influence = selection_influence_check(
                harsh_trades[name],
                harsh_trades["anchor"],
                start=SELECTION_START,
                end=SELECTION_END,
            )
            influence_checks[name] = influence
            fixed_checks[name].update(influence["checks"])
    incremental_passers = sorted(
        name for name, checks in fixed_checks.items() if all(checks.values())
    )
    near_gate = max(
        eligible,
        key=lambda row: (
            sum(fixed_checks[row["method"]["name"]].values()),
            row["pretest_score"],
            row["method"]["name"],
        ),
    )
    total_leader = max(
        eligible,
        key=lambda row: (
            _selection_comparison(row)["harsh_total_pnl"],
            row["method"]["name"],
        ),
    )
    recent_windows = ("test_pre_nxt_2024_20250303", "post_nxt_20250304_2026")
    comparisons: dict[str, Any] = {}
    passed = True
    for window in recent_windows:
        candidate_harsh = selected["profiles"]["harsh"][window]
        anchor_harsh = anchor["profiles"]["harsh"][window]
        candidate_extreme = selected["profiles"]["extreme"][window]
        candidate_adverse = selected["adverse_harsh"][window]
        anchor_adverse = anchor["adverse_harsh"][window]
        candidate_tick = selected["tick2_harsh"][window]
        anchor_tick = anchor["tick2_harsh"][window]
        checks = {
            "harsh_beats_anchor": candidate_harsh["metrics"]["total_pnl"]
            > anchor_harsh["metrics"]["total_pnl"],
            "extreme_positive": candidate_extreme["metrics"]["total_pnl"] > 0,
            "top25_removed_positive": candidate_harsh["miss_top_winners_25pct"]["total_pnl"] > 0,
            "adverse_beats_anchor": candidate_adverse["metrics"]["total_pnl"]
            > anchor_adverse["metrics"]["total_pnl"],
            "two_tick_stress_beats_anchor": candidate_tick["metrics"]["total_pnl"]
            > anchor_tick["metrics"]["total_pnl"],
        }
        passed = passed and all(checks.values())
        comparisons[window] = checks
    historical_incremental_passed = bool(incremental_passers)
    return {
        "selected_on_2011_2023": selected["method"]["name"],
        "selection_status": "diagnostic_best_pretest_score_only",
        "selection_score": selected["pretest_score"],
        "historical_total_leader": total_leader["method"]["name"],
        "near_gate_shadow_candidate": near_gate["method"]["name"],
        "historical_incremental_passers": incremental_passers,
        "historical_incremental_gate_passed": historical_incremental_passed,
        "best_pretest_fixed_checks": fixed_checks[selected["method"]["name"]],
        "historical_total_leader_fixed_checks": fixed_checks[
            total_leader["method"]["name"]
        ],
        "near_gate_shadow_fixed_checks": fixed_checks[near_gate["method"]["name"]],
        "paired_influence_robustness": influence_checks,
        "historical_gate_passed": historical_incremental_passed and passed,
        "recent_reused_diagnostic": comparisons,
        "recommended_research_strategy": "anchor",
        "shadow_only_not_live": near_gate["method"]["name"],
        "live_change_accepted": False,
        "reason": "no candidate beat anchor across total, adverse, two-tick, top-winner-removal, MDD, and paired-influence checks"
        if not historical_incremental_passed
        else "2024+ is reused and cannot authorize a live change",
    }


def _file_fingerprint(path: str) -> dict[str, Any]:
    source = Path(path).resolve()
    stat = source.stat()
    sample_size = 1024 * 1024
    sample_digest = hashlib.sha256()
    with source.open("rb") as handle:
        sample_digest.update(handle.read(sample_size))
        if stat.st_size > sample_size:
            handle.seek(max(0, stat.st_size - sample_size))
            sample_digest.update(handle.read(sample_size))
    full_digest = hashlib.sha256()
    with source.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            full_digest.update(chunk)
    return {
        "sample_sha256": sample_digest.hexdigest(),
        "full_sha256": full_digest.hexdigest(),
        "size_bytes": stat.st_size,
    }


def source_fingerprints(
    db_path: str,
    us_db_path: str,
    index_rows: Sequence[dict[str, Any]],
    declared: Sequence[ForeignMethod],
) -> dict[str, Any]:
    base = external.source_fingerprints(db_path, index_rows)
    base["external_script_sha256"] = base.pop("script_sha256")
    base["script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    base["database_full"] = _file_fingerprint(db_path)
    base["us_database"] = _file_fingerprint(us_db_path)
    manifest = json.dumps(
        [asdict(method) for method in declared],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    base["method_manifest_sha256"] = hashlib.sha256(manifest).hexdigest()
    base["dependency_script_sha256"] = {
        "kr_external_method_research.py": hashlib.sha256(
            Path(external.__file__).read_bytes()
        ).hexdigest(),
    }
    return base


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# KR Foreign Microstructure Research",
        "",
        f"- generated: `{payload['generated_at']}`",
        f"- events: `{payload['event_rows']}` / market days: `{payload['market_days']}`",
        f"- foreign primary sources: `{len(payload['sources'])}`",
        f"- declared methods: `{payload['methods_tested']}` / new alternatives: `{payload['new_hypotheses']}`",
        f"- selected on 2011-2023: `{payload['decision']['selected_on_2011_2023']}`",
        f"- historical gate passed: `{payload['decision']['historical_gate_passed']}`",
        f"- live change accepted: `{payload['decision']['live_change_accepted']}`",
        "",
        "## Harsh-cost windows",
        "",
        "| method | family | validation pnl | pre-NXT pnl | post-NXT pnl | post-NXT MDD |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in payload["evaluations"]:
        harsh = row["profiles"]["harsh"]
        validation = harsh["validation_2019_2023"]["metrics"]
        pre_nxt = harsh["test_pre_nxt_2024_20250303"]["metrics"]
        post_nxt = harsh["post_nxt_20250304_2026"]["metrics"]
        lines.append(
            f"| {row['method']['name']} | {row['method']['family']} | "
            f"{validation['total_pnl']:,.0f} | {pre_nxt['total_pnl']:,.0f} | "
            f"{post_nxt['total_pnl']:,.0f} | {post_nxt['mdd_on_capital']*100:.1f}% |"
        )
    lines.extend(["", "## Sources", ""])
    for source in payload["sources"]:
        lines.append(f"- [{source['title']}]({source['url']}): {source['use']}")
    lines.extend(
        [
            "",
            "## Limits",
            "",
            *[f"- {limit}" for limit in payload["limits"]],
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Foreign microstructure research for Korean daily candles; no order endpoints"
    )
    parser.add_argument("--db-path", default=DEFAULT_DB)
    parser.add_argument("--us-db-path", default=DEFAULT_US_DB)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--spread-history", default=DEFAULT_SPREAD_HISTORY)
    parser.add_argument("--paper-observations", default=DEFAULT_PAPER_OBSERVATIONS)
    parser.add_argument("--warning-audit", default=DEFAULT_WARNING_AUDIT)
    parser.add_argument("--start", default="2011-01-01")
    parser.add_argument("--end", default="2026-07-16")
    parser.add_argument("--bootstrap-samples", type=int, default=1000)
    args = parser.parse_args()

    index_rows = fetch_kosdaq_index(args.start, args.end)
    warning_intervals, warning_audit = load_official_warning_intervals(
        args.warning_audit
    )
    events = load_events(
        args.db_path,
        index_rows,
        start=args.start,
        end=args.end,
        warning_intervals=warning_intervals,
    )
    warning_audit["candidate_event_flags"] = {
        "attention": sum(row.official_attention_active for row in events),
        "warning": sum(row.official_warning_active for row in events),
        "risk": sum(row.official_risk_active for row in events),
        "any": sum(
            row.official_attention_active
            or row.official_warning_active
            or row.official_risk_active
            for row in events
        ),
    }
    markets = build_markets(events, index_rows, args.us_db_path)
    declared = methods()
    bundles = {
        method.name: evaluate_method_bundle(events, markets, method)
        for method in declared
    }
    evaluations = [bundles[method.name][0] for method in declared]
    harsh_trades = {
        method.name: bundles[method.name][1]["harsh"] for method in declared
    }
    adverse_harsh_trades = {
        method.name: bundles[method.name][1]["adverse"] for method in declared
    }
    tick1_harsh_trades = {
        method.name: bundles[method.name][1]["tick1"] for method in declared
    }
    tick2_harsh_trades = {
        method.name: bundles[method.name][1]["tick2"] for method in declared
    }
    declared_by_name = {method.name: method for method in declared}
    market_dates = sorted(markets)
    decision = selection_decision(evaluations, harsh_trades)
    sensitivity_samples = max(200, args.bootstrap_samples)
    selected_name = decision["selected_on_2011_2023"]
    selected_bootstrap: dict[str, Any] = {
        "available": False,
        "reason": "no method passed the fixed 2011-2023 selection gate",
    }
    if selected_name is not None:
        selected_bootstrap = {
            "selected_method": selected_name,
            "selection_2011_2023": paired_block_bootstrap_difference(
                harsh_trades[selected_name],
                harsh_trades["anchor"],
                market_dates,
                start=SELECTION_START,
                end=SELECTION_END,
            ),
            "reused_recent_2024_plus": paired_block_bootstrap_difference(
                harsh_trades[selected_name],
                harsh_trades["anchor"],
                market_dates,
                start="2024-01-01",
                end=args.end,
            ),
            "selection_block_length_sensitivity": paired_block_bootstrap_sensitivity(
                harsh_trades[selected_name],
                harsh_trades["anchor"],
                market_dates,
                start=SELECTION_START,
                end=SELECTION_END,
                samples=sensitivity_samples,
            ),
            "selection_leave_one_year_out": leave_one_year_out_difference(
                harsh_trades[selected_name],
                harsh_trades["anchor"],
                start=SELECTION_START,
                end=SELECTION_END,
            ),
        }
    total_leader_name = decision.get("historical_total_leader")
    total_leader_bootstrap: dict[str, Any] = {
        "available": False,
        "reason": "no historical total-PnL leader was available",
    }
    if total_leader_name is not None:
        total_leader_bootstrap = {
            "candidate": total_leader_name,
            "selection_2011_2023": paired_block_bootstrap_difference(
                harsh_trades[total_leader_name],
                harsh_trades["anchor"],
                market_dates,
                start=SELECTION_START,
                end=SELECTION_END,
            ),
            "reused_recent_2024_plus": paired_block_bootstrap_difference(
                harsh_trades[total_leader_name],
                harsh_trades["anchor"],
                market_dates,
                start="2024-01-01",
                end=args.end,
            ),
            "selection_block_length_sensitivity": paired_block_bootstrap_sensitivity(
                harsh_trades[total_leader_name],
                harsh_trades["anchor"],
                market_dates,
                start=SELECTION_START,
                end=SELECTION_END,
                samples=sensitivity_samples,
            ),
            "selection_leave_one_year_out": leave_one_year_out_difference(
                harsh_trades[total_leader_name],
                harsh_trades["anchor"],
                start=SELECTION_START,
                end=SELECTION_END,
            ),
        }
    shadow_name = decision.get("near_gate_shadow_candidate")
    shadow_bootstrap: dict[str, Any] = {
        "available": False,
        "reason": "no near-gate shadow candidate was available",
    }
    if shadow_name is not None:
        shadow_bootstrap = {
            "candidate": shadow_name,
            "selection_2011_2023": paired_block_bootstrap_difference(
                harsh_trades[shadow_name],
                harsh_trades["anchor"],
                market_dates,
                start=SELECTION_START,
                end=SELECTION_END,
            ),
            "reused_recent_2024_plus": paired_block_bootstrap_difference(
                harsh_trades[shadow_name],
                harsh_trades["anchor"],
                market_dates,
                start="2024-01-01",
                end=args.end,
            ),
            "selection_block_length_sensitivity": paired_block_bootstrap_sensitivity(
                harsh_trades[shadow_name],
                harsh_trades["anchor"],
                market_dates,
                start=SELECTION_START,
                end=SELECTION_END,
                samples=sensitivity_samples,
            ),
            "selection_leave_one_year_out": leave_one_year_out_difference(
                harsh_trades[shadow_name],
                harsh_trades["anchor"],
                start=SELECTION_START,
                end=SELECTION_END,
            ),
        }
    diagnostic_names = list(
        dict.fromkeys(
            name
            for name in ("anchor", selected_name, total_leader_name, shadow_name)
            if name is not None
        )
    )
    volume_method_names = (
        "volume_cap_065_anchor",
        "anchor",
        "volume_cap_100_anchor",
        "volume_cap_125_anchor",
        "volume_cap_150_anchor",
        "volume_relaxed_anchor",
    )
    universe_audit = database_universe_audit(args.db_path)
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "db_path": args.db_path,
        "requested_start": args.start,
        "requested_end": args.end,
        "source_fingerprints": source_fingerprints(
            args.db_path, args.us_db_path, index_rows, declared
        ),
        "run_configuration": {
            "argv": sys.argv,
            "selection_window": f"{SELECTION_START}~{SELECTION_END}",
            "reused_diagnostic_window": f"2024-01-01~{args.end}",
            "bootstrap_samples": args.bootstrap_samples,
            "cost_profiles": COSTS,
            "method_manifest": [asdict(method) for method in declared],
            "warning_audit": args.warning_audit,
            "outcome_label": "conditional daily-bar outcome, not executable 09:01 PnL",
        },
        "database_universe_audit": universe_audit,
        "official_warning_interval_audit": warning_audit,
        "delisted_metadata_exposure_audit": {
            "selection_2011_2023": delisted_metadata_exposure_audit(
                args.db_path,
                harsh_trades,
                start=SELECTION_START,
                end=SELECTION_END,
            ),
            "reused_recent_2024_plus": delisted_metadata_exposure_audit(
                args.db_path,
                harsh_trades,
                start="2024-01-01",
                end=args.end,
            ),
        },
        "execution_observation_audit": execution_observation_audit(
            args.spread_history, args.paper_observations
        ),
        "execution_reachability_audit": {
            name: {
                "selection_2011_2023": execution_reachability_audit(
                    events,
                    markets,
                    declared_by_name[name],
                    start=SELECTION_START,
                    end=SELECTION_END,
                ),
                "reused_recent_2024_plus": execution_reachability_audit(
                    events,
                    markets,
                    declared_by_name[name],
                    start="2024-01-01",
                    end=args.end,
                ),
            }
            for name in diagnostic_names
        },
        "event_rows": len(events),
        "feature_complete_rows": sum(row.feature_history60 >= 40 for row in events),
        "market_days": len(markets),
        "strictly_prior_us_context_days": sum(
            market.us_session_date is not None and market.us_session_date < market.date
            for market in markets.values()
        ),
        "sources": list(SOURCES),
        "methods_tested": len(declared),
        "new_hypotheses": len(declared) - 1,
        "families": sorted({method.family for method in declared if method.family != "anchor"}),
        "pretest_passed": sum(row["pretest_passed"] for row in evaluations),
        "evaluations": evaluations,
        "decision": decision,
        "deflated_sharpe_diagnostic": external.deflated_sharpe_diagnostic(
            harsh_trades, market_dates
        ),
        "cscv_pbo_diagnostic": cscv_pbo_diagnostic(harsh_trades, market_dates),
        "reality_check_diagnostic": studentized_reality_check(
            harsh_trades,
            market_dates,
            samples=args.bootstrap_samples,
        ),
        "selection_functional_block_stability": selection_functional_block_stability(
            harsh_trades,
            adverse_harsh_trades,
            tick2_harsh_trades,
            market_dates,
            observed_selected=selected_name,
            samples=min(max(50, args.bootstrap_samples), 200),
        ),
        "random_rank_benchmarks": [
            external.random_rank_benchmark(
                events, markets, start=SELECTION_START, end=SELECTION_END
            ),
            external.random_rank_benchmark(events, markets, start="2024-01-01", end=args.end),
        ],
        "tick_random_rank_benchmarks": [
            tick_random_rank_benchmark(
                events, markets, start=SELECTION_START, end=SELECTION_END
            ),
            tick_random_rank_benchmark(
                events, markets, start="2024-01-01", end=args.end
            ),
        ],
        "walk_forward_method_selection": walk_forward_method_selection(harsh_trades),
        "selected_vs_anchor_block_bootstrap": selected_bootstrap,
        "historical_total_leader_vs_anchor_block_bootstrap": total_leader_bootstrap,
        "near_gate_shadow_vs_anchor_block_bootstrap": shadow_bootstrap,
        "daily_bar_path_ambiguity": {
            name: {
                "selection_2011_2023": daily_bar_path_audit(
                    events,
                    markets,
                    declared_by_name[name],
                    start=SELECTION_START,
                    end=SELECTION_END,
                ),
                "reused_recent_2024_plus": daily_bar_path_audit(
                    events,
                    markets,
                    declared_by_name[name],
                    start="2024-01-01",
                    end=args.end,
                ),
            }
            for name in diagnostic_names
        },
        "break_even_cost_diagnostics": {
            name: {
                "selection_2011_2023": break_even_cost_diagnostic(
                    scoped(harsh_trades[name], SELECTION_START, SELECTION_END)
                ),
                "reused_recent_2024_plus": break_even_cost_diagnostic(
                    scoped(harsh_trades[name], "2024-01-01", args.end)
                ),
            }
            for name in diagnostic_names
        },
        "historical_cost_schedule_diagnostic": {
            "source_keys": [
                "korea_stt_law_2019",
                "korea_stt_moef_2021",
                "korea_stt_law_2023_2026",
            ],
            "methods": {
                name: historical_cost_schedule_diagnostic(
                    harsh_trades[name],
                    simulate_tick_stress(
                        events,
                        markets,
                        declared_by_name[name],
                        roundtrip_cost=0.0,
                        adverse_ticks=1,
                    ),
                )
                for name in diagnostic_names
            },
        },
        "paired_selection_change_audit": {
            name: {
                "selection_2011_2023": paired_selection_change_audit(
                    harsh_trades[name],
                    harsh_trades["anchor"],
                    events,
                    start=SELECTION_START,
                    end=SELECTION_END,
                ),
                "reused_recent_2024_plus": paired_selection_change_audit(
                    harsh_trades[name],
                    harsh_trades["anchor"],
                    events,
                    start="2024-01-01",
                    end=args.end,
                ),
            }
            for name in diagnostic_names
            if name != "anchor"
        },
        "volume_threshold_yearly_stability": {
            "selection_2011_2023": yearly_method_leaders(
                harsh_trades,
                volume_method_names,
                start=SELECTION_START,
                end=SELECTION_END,
            ),
            "reused_recent_2024_plus": yearly_method_leaders(
                harsh_trades,
                volume_method_names,
                start="2024-01-01",
                end=args.end,
            ),
        },
        "limits": [
            survivorship_limit(universe_audit),
            "The research cache contains daily bars only, so it cannot reconstruct the 09:01 quote, queue, or fill path.",
            "Official KIND attention/warning/risk intervals are reconstructed when the audit is complete; historical VI, halt, venue, queue, and broker warning payloads remain unavailable.",
            "KRX determines the official daily open in a call auction; seeing that output does not grant a same-price 09:01 fill.",
            "Daily high/low cannot identify stop/take order, queue position, or executable size.",
            "Corwin-Schultz and Roll values are noisy low-frequency spread proxies, not observed Toss spreads.",
            "Foreign papers generally study US portfolios and longer horizons; these filters are translations, not exact replications.",
            "The 2024+ period has already been inspected repeatedly and is not an untouched holdout.",
            "US context always uses the latest completed session with a date strictly before the Korean session.",
            "Tick stress uses the KRX pre-reform KOSDAQ table through 2023-01-24 and the unified table from 2023-01-25; the pre-reform table is directly documented in a 2015 brochure and is assumed unchanged back to 2011.",
            "PBO, DSR, and the block bootstrap are diagnostics on sparse correlated returns, not independent proof.",
            "The fixed incremental gate was added as a conservative rejection rule after the first scoring pass; it cannot create a positive claim.",
            "No research result in this run changes the live trader, cron, or order parameters.",
        ],
    }
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "kr_foreign_microstructure_research.json").write_text(
        json.dumps(json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (out / "kr_foreign_microstructure_research.md").write_text(
        render_markdown(payload), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "out_dir": str(out),
                "events": len(events),
                "methods": len(declared),
                "pretest_passed": payload["pretest_passed"],
                "selected": payload["decision"]["selected_on_2011_2023"],
                "historical_gate_passed": payload["decision"]["historical_gate_passed"],
                "live_change_accepted": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
