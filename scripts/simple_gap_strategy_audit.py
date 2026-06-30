#!/usr/bin/env python3
"""Second-pass audit for scripts/simple_gap_trader.py.

Read-only historical approximation:
- stock filters use only previous-day stock candle data where the live bot does so
- entry is signal-day open_price, exit is signal-day close_price
- one daily top candidate is selected by largest gap-down that is affordable by capital
- fixed-capital metrics account for integer quantity and idle cash

The live bot enters near 09:01 using Toss real-time prices, so this daily-candle
backtest is not an exact fill simulator. It is an evidence gate for whether the
idea deserves live/paper-forward monitoring.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = "data/edge_research_universe_15y.sqlite3"
DEFAULT_OUT = "data/simple_gap_strategy_audit_latest.json"
ROUND_TRIP_COST_DEFAULT = 0.0035


def pct(value: float | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "N/A"
    return f"{value * 100:+.3f}%"


def max_drawdown_multiplicative(returns: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns:
        equity *= max(0.0, 1.0 + r)
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)
    return max_dd


def max_drawdown_additive(returns: list[float]) -> float:
    """Drawdown for fixed-capital trade returns where unused cash stays idle."""
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns:
        equity += r
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)
    return max_dd


def compounded_return(returns: list[float]) -> float:
    equity = 1.0
    for r in returns:
        equity *= max(0.0, 1.0 + r)
    return equity - 1.0


def profit_factor_from_returns(returns: list[float]) -> float | None:
    gains = sum(r for r in returns if r > 0)
    losses = -sum(r for r in returns if r < 0)
    if losses <= 0:
        return None if gains <= 0 else float("inf")
    return gains / losses


def summarize_invested_returns(trades: list[dict[str, Any]], *, roundtrip_cost: float, slippage: float = 0.0) -> dict[str, Any]:
    """Return stats on invested amount. Useful for signal quality, not account PnL."""
    if not trades:
        return {
            "trades": 0,
            "avg_raw_return": None,
            "avg_net_return": None,
            "median_net_return": None,
            "win_rate_net": None,
            "compounded_net_return": None,
            "max_drawdown_net": None,
            "profit_factor_net": None,
            "avg_alpha_after_cost": None,
            "best_net_return": None,
            "worst_net_return": None,
        }
    raw = [float(t["raw_return"]) for t in trades]
    market = [float(t.get("market_return", 0.0)) for t in trades]
    net = [r - roundtrip_cost - slippage for r in raw]
    alpha = [n - m for n, m in zip(net, market)]
    wins = [r for r in net if r > 0]
    return {
        "trades": len(trades),
        "avg_raw_return": statistics.mean(raw),
        "avg_net_return": statistics.mean(net),
        "median_net_return": statistics.median(net),
        "win_rate_net": len(wins) / len(net),
        "compounded_net_return": compounded_return(net),
        "max_drawdown_net": max_drawdown_multiplicative(net),
        "profit_factor_net": profit_factor_from_returns(net),
        "avg_alpha_after_cost": statistics.mean(alpha),
        "best_net_return": max(net),
        "worst_net_return": min(net),
    }


def enrich_capital_trades(
    trades: list[dict[str, Any]], *, capital: float, roundtrip_cost: float, slippage: float = 0.0
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    total_cost = roundtrip_cost + slippage
    for t in trades:
        open_price = float(t["open_price"])
        close_price = float(t["close_price"])
        if open_price <= 0 or capital < open_price:
            continue
        qty = int(capital // open_price)
        if qty <= 0:
            continue
        invested = qty * open_price
        gross_pnl = qty * (close_price - open_price)
        cost = invested * total_cost
        net_pnl = gross_pnl - cost
        row = dict(t)
        row.update(
            {
                "capital_krw": capital,
                "quantity": qty,
                "invested_krw": invested,
                "cash_used_pct": invested / capital,
                "gross_pnl_krw": gross_pnl,
                "cost_krw": cost,
                "net_pnl_krw": net_pnl,
                "net_return_on_capital": net_pnl / capital,
            }
        )
        enriched.append(row)
    return enriched


def summarize_capital_trades(
    trades: list[dict[str, Any]], *, capital: float, roundtrip_cost: float, slippage: float = 0.0
) -> dict[str, Any]:
    """Fixed-capital account stats. This is the primary live-budget proxy."""
    enriched = enrich_capital_trades(trades, capital=capital, roundtrip_cost=roundtrip_cost, slippage=slippage)
    if not enriched:
        return {
            "trades": 0,
            "capital_krw": capital,
            "avg_net_return_on_capital": None,
            "median_net_return_on_capital": None,
            "win_rate_net": None,
            "cumulative_return_on_capital": None,
            "compounded_return_on_capital": None,
            "max_drawdown_on_capital": None,
            "profit_factor_net_pnl": None,
            "avg_cash_used_pct": None,
            "avg_net_pnl_krw": None,
            "total_net_pnl_krw": None,
            "best_net_return_on_capital": None,
            "worst_net_return_on_capital": None,
        }
    rets = [float(t["net_return_on_capital"]) for t in enriched]
    pnls = [float(t["net_pnl_krw"]) for t in enriched]
    gains = sum(p for p in pnls if p > 0)
    losses = -sum(p for p in pnls if p < 0)
    return {
        "trades": len(enriched),
        "capital_krw": capital,
        "avg_net_return_on_capital": statistics.mean(rets),
        "median_net_return_on_capital": statistics.median(rets),
        "win_rate_net": sum(1 for p in pnls if p > 0) / len(enriched),
        "cumulative_return_on_capital": sum(rets),
        "compounded_return_on_capital": compounded_return(rets),
        "max_drawdown_on_capital": max_drawdown_additive(rets),
        "profit_factor_net_pnl": None if losses <= 0 else gains / losses,
        "avg_cash_used_pct": statistics.mean(float(t["cash_used_pct"]) for t in enriched),
        "avg_net_pnl_krw": statistics.mean(pnls),
        "total_net_pnl_krw": sum(pnls),
        "best_net_return_on_capital": max(rets),
        "worst_net_return_on_capital": min(rets),
    }


def by_year_capital(trades: list[dict[str, Any]], *, capital: float, roundtrip_cost: float) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        grouped[str(t["date"])[:4]].append(t)
    return [{"year": year, **summarize_capital_trades(rows, capital=capital, roundtrip_cost=roundtrip_cost)} for year, rows in sorted(grouped.items())]


def fetch_kosdaq_index(start: str, end: str) -> list[dict[str, Any]]:
    start_ymd = (start or "2011-01-01")[:10].replace("-", "")
    end_ymd = (end or datetime.now().strftime("%Y-%m-%d"))[:10].replace("-", "")
    query = urllib.parse.urlencode({"startDateTime": f"{start_ymd}0000", "endDateTime": f"{end_ymd}2359"})
    url = f"https://api.stock.naver.com/chart/domestic/index/KOSDAQ/day?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com/"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    rows = []
    for r in data or []:
        date_raw = str(r.get("localDate") or "")
        if len(date_raw) != 8:
            continue
        rows.append(
            {
                "date": f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}",
                "close": float(str(r.get("closePrice", 0)).replace(",", "")),
                "open": float(str(r.get("openPrice", 0)).replace(",", "")),
            }
        )
    rows.sort(key=lambda x: x["date"])
    return rows


def kosdaq_prev_close_gate(index_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    gate: dict[str, dict[str, Any]] = {}
    closes = [float(r["close"]) for r in index_rows]
    for i in range(5, len(index_rows)):
        prev_close = closes[i - 1]
        prev_sma5 = statistics.mean(closes[i - 5 : i])
        gate[index_rows[i]["date"]] = {
            "ok": prev_close >= prev_sma5,
            "prev_close": prev_close,
            "prev_sma5": prev_sma5,
        }
    return gate


def load_market_returns(db_path: str) -> dict[str, float]:
    con = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    try:
        rows = con.execute(
            """
            SELECT substr(timestamp,1,10) AS date,
                   AVG((CAST(close_price AS REAL) - CAST(open_price AS REAL)) / CAST(open_price AS REAL)) AS market_return
            FROM candle_cache
            WHERE interval='1d' AND CAST(open_price AS REAL) > 0 AND CAST(close_price AS REAL) > 0
            GROUP BY substr(timestamp,1,10)
            """
        ).fetchall()
    finally:
        con.close()
    return {str(d): float(r or 0.0) for d, r in rows}


def broad_gap_threshold(primary_gap: float, sensitivity_gaps: list[float]) -> float:
    """Least restrictive threshold for SQL prefilter when condition is gap <= threshold."""
    return max([primary_gap, *sensitivity_gaps])


def load_candidate_rows(args) -> list[dict[str, Any]]:
    # gap condition is `gap_return <= threshold`; the broad query must use the
    # least restrictive/largest threshold so later in-memory filters can narrow
    # to -3%, -4%, -5%, etc. Using min() here would silently turn the primary
    # -3% audit into a -5% subset.
    broad_gap = broad_gap_threshold(args.gap_threshold, args.sensitivity_gaps)
    broad_vol = max(args.prev_vol_ratio_max, max(args.sensitivity_vol_ratios))
    params: list[Any] = []
    where = ["prev_count = 20", "prev_close > 0", "open_price > 0", "close_price > 0", "avg_prev20_volume > 0"]
    if args.start:
        where.append("date >= ?")
        params.append(args.start)
    if args.end:
        where.append("date <= ?")
        params.append(args.end)
    where.extend(
        [
            "prev_close >= ?",
            "prev_close <= ?",
            "((open_price - prev_close) / prev_close) <= ?",
            "(prev_volume / avg_prev20_volume) < ?",
        ]
    )
    params.extend([args.min_price, args.max_price, broad_gap, broad_vol])
    sql = f"""
    WITH enriched AS (
      SELECT
        symbol,
        substr(timestamp,1,10) AS date,
        CAST(open_price AS REAL) AS open_price,
        CAST(close_price AS REAL) AS close_price,
        CAST(volume AS REAL) AS volume,
        LAG(CAST(close_price AS REAL)) OVER (PARTITION BY symbol ORDER BY timestamp) AS prev_close,
        LAG(CAST(volume AS REAL)) OVER (PARTITION BY symbol ORDER BY timestamp) AS prev_volume,
        AVG(CAST(volume AS REAL)) OVER (PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 21 PRECEDING AND 2 PRECEDING) AS avg_prev20_volume,
        COUNT(CAST(volume AS REAL)) OVER (PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 21 PRECEDING AND 2 PRECEDING) AS prev_count
      FROM candle_cache
      WHERE interval='1d'
    )
    SELECT symbol, date, open_price, close_price, prev_close, prev_volume, avg_prev20_volume,
           ((open_price - prev_close) / prev_close) AS gap_return,
           ((close_price - open_price) / open_price) AS raw_return,
           (prev_volume / avg_prev20_volume) AS prev_vol_ratio
    FROM enriched
    WHERE {' AND '.join(where)}
    ORDER BY date ASC, gap_return ASC
    """
    con = sqlite3.connect(f"file:{Path(args.db_path).resolve()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(sql, params).fetchall()
    finally:
        con.close()
    return [dict(r) for r in rows]


def apply_simple_filters(rows: list[dict[str, Any]], *, gap_threshold: float, prev_vol_ratio_max: float) -> list[dict[str, Any]]:
    return [r for r in rows if float(r["gap_return"]) <= gap_threshold and float(r["prev_vol_ratio"]) < prev_vol_ratio_max]


def select_daily_top(rows: list[dict[str, Any]], *, capital: float) -> tuple[list[dict[str, Any]], int]:
    by_date_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_date_rows[str(r["date"])].append(r)
    selected = []
    skipped_no_affordable = 0
    for date in sorted(by_date_rows):
        candidates = sorted(by_date_rows[date], key=lambda x: (float(x["gap_return"]), str(x["symbol"])))
        pick = next((c for c in candidates if float(c["open_price"]) <= capital), None)
        if pick is None:
            skipped_no_affordable += 1
            continue
        selected.append(pick)
    return selected, skipped_no_affordable


def add_market_return(rows: list[dict[str, Any]], market_returns: dict[str, float]) -> None:
    for r in rows:
        r["market_return"] = float(market_returns.get(str(r["date"]), 0.0))


def compact_trade(t: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "date": t["date"],
        "symbol": t["symbol"],
        "open_price": round(float(t["open_price"]), 3),
        "close_price": round(float(t["close_price"]), 3),
        "gap_return": float(t["gap_return"]),
        "raw_return": float(t["raw_return"]),
        "prev_vol_ratio": float(t["prev_vol_ratio"]),
    }
    for key in ["quantity", "invested_krw", "net_pnl_krw", "net_return_on_capital", "cash_used_pct"]:
        if key in t:
            row[key] = int(t[key]) if key == "quantity" else float(t[key])
    return row


def promotion_decision(portfolio: dict[str, Any]) -> dict[str, Any]:
    reasons = []
    pass_any = False
    for key, item in portfolio.items():
        s = item["summary"]
        passed = (
            s["trades"] >= 50
            and (s["avg_net_return_on_capital"] or 0) > 0
            and (s["median_net_return_on_capital"] or 0) > 0
            and (s["win_rate_net"] or 0) > 0.5
            and (s["profit_factor_net_pnl"] or 0) > 1.05
        )
        pass_any = pass_any or passed
        if not passed:
            reasons.append(
                f"capital={key}: trades={s['trades']}, avg_cap_net={pct(s['avg_net_return_on_capital'])}, "
                f"median_cap_net={pct(s['median_net_return_on_capital'])}, win={pct(s['win_rate_net'])}, "
                f"pf={s['profit_factor_net_pnl']}"
            )
    return {
        "live_order_allowed_by_audit": False,
        "paper_forward_allowed": True,
        "historical_edge_gate_passed": pass_any,
        "decision": "candidate for stricter paper-forward review, not direct live approval" if pass_any else "monitor/paper-forward only",
        "reasons": reasons[:8],
    }


def run(args) -> dict[str, Any]:
    market_returns = load_market_returns(args.db_path)
    candidates_broad = load_candidate_rows(args)
    primary = apply_simple_filters(candidates_broad, gap_threshold=args.gap_threshold, prev_vol_ratio_max=args.prev_vol_ratio_max)
    add_market_return(primary, market_returns)

    try:
        index_rows = fetch_kosdaq_index(args.start or "2011-01-01", args.end or datetime.now().strftime("%Y-%m-%d"))
        gate = kosdaq_prev_close_gate(index_rows)
        guarded = [r for r in primary if gate.get(str(r["date"]), {}).get("ok")]
        index_status = {
            "available": True,
            "rows": len(index_rows),
            "start": index_rows[0]["date"] if index_rows else None,
            "end": index_rows[-1]["date"] if index_rows else None,
            "guard_model": "previous KOSDAQ close >= previous 5-close SMA (no-lookahead daily approximation)",
        }
    except Exception as exc:
        guarded = list(primary)
        index_status = {
            "available": False,
            "reason": f"{type(exc).__name__}: {exc}",
            "guard_model": "unavailable; primary rows reported without index guard",
        }
    add_market_return(guarded, market_returns)

    portfolio: dict[str, Any] = {}
    for capital in [float(c) for c in args.capitals]:
        selected, skipped = select_daily_top(guarded, capital=capital)
        add_market_return(selected, market_returns)
        enriched = enrich_capital_trades(selected, capital=capital, roundtrip_cost=args.roundtrip_cost)
        portfolio[str(int(capital))] = {
            "capital_krw": capital,
            "skipped_signal_days_no_affordable_share": skipped,
            "summary": summarize_capital_trades(selected, capital=capital, roundtrip_cost=args.roundtrip_cost),
            "invested_return_summary": summarize_invested_returns(selected, roundtrip_cost=args.roundtrip_cost),
            "by_year": by_year_capital(selected, capital=capital, roundtrip_cost=args.roundtrip_cost),
            "slippage_sensitivity": [
                {"extra_slippage": slip, **summarize_capital_trades(selected, capital=capital, roundtrip_cost=args.roundtrip_cost, slippage=slip)}
                for slip in [0.0, 0.001, 0.002, 0.003, 0.005]
            ],
            "sample_worst_trades": [compact_trade(t) for t in sorted(enriched, key=lambda x: float(x["net_return_on_capital"]))[:10]],
            "sample_best_trades": [compact_trade(t) for t in sorted(enriched, key=lambda x: float(x["net_return_on_capital"]), reverse=True)[:10]],
        }

    sensitivity = []
    for gap in sorted(args.sensitivity_gaps, reverse=True):
        for vol in sorted(args.sensitivity_vol_ratios):
            rows = apply_simple_filters(candidates_broad, gap_threshold=gap, prev_vol_ratio_max=vol)
            add_market_return(rows, market_returns)
            sensitivity.append(
                {
                    "gap_threshold": gap,
                    "prev_vol_ratio_max": vol,
                    "all_signals_invested_return": summarize_invested_returns(rows, roundtrip_cost=args.roundtrip_cost),
                }
            )

    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "research_no_send_daily_candle_backtest",
        "source_db": args.db_path,
        "window": {"start": args.start or None, "end": args.end or None},
        "assumptions": {
            "entry": "signal-day open_price (daily approximation of 09:01 market entry)",
            "exit": "signal-day close_price (daily approximation of 15:20/close exit)",
            "daily_selection": "one most negative gap candidate per day, skipping names above account capital",
            "stock_filters": {
                "prev_close_min": args.min_price,
                "prev_close_max": args.max_price,
                "gap_threshold": args.gap_threshold,
                "prev_vol_ratio_max": args.prev_vol_ratio_max,
            },
            "roundtrip_cost": args.roundtrip_cost,
            "primary_metric": "fixed-capital integer-quantity net return on total account capital",
        },
        "kosdaq_index_guard": index_status,
        "all_signals_no_daily_top_invested_return": {
            "before_index_guard": summarize_invested_returns(primary, roundtrip_cost=args.roundtrip_cost),
            "after_index_guard": summarize_invested_returns(guarded, roundtrip_cost=args.roundtrip_cost),
        },
        "daily_top_by_capital": portfolio,
        "sensitivity_no_index_guard_all_signals": sensitivity,
        "promotion_decision": promotion_decision(portfolio),
        "caveats": [
            "Daily OHLC cannot reproduce the exact 09:01 live fill; open-to-close is a proxy.",
            "KOSDAQ guard is no-lookahead previous-close SMA approximation, not live intraday index value.",
            "Historical pass is not direct live-order approval; use live logs/paper-forward monitoring as the next gate.",
        ],
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return report


def parse_csv_floats(raw: str) -> list[float]:
    return [float(x.strip()) for x in raw.split(",") if x.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit simple_gap_trader.py with daily candle backtest")
    ap.add_argument("--db-path", default=DEFAULT_DB_PATH)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="")
    ap.add_argument("--min-price", type=float, default=5000)
    ap.add_argument("--max-price", type=float, default=50000)
    ap.add_argument("--gap-threshold", type=float, default=-0.03)
    ap.add_argument("--prev-vol-ratio-max", type=float, default=1.0)
    ap.add_argument("--roundtrip-cost", type=float, default=ROUND_TRIP_COST_DEFAULT)
    ap.add_argument("--capitals", type=parse_csv_floats, default=parse_csv_floats("10000,30000,100000,1000000"))
    ap.add_argument("--sensitivity-gaps", type=parse_csv_floats, default=parse_csv_floats("-0.02,-0.03,-0.04,-0.05"))
    ap.add_argument("--sensitivity-vol-ratios", type=parse_csv_floats, default=parse_csv_floats("0.5,0.75,1.0,1.25"))
    args = ap.parse_args()
    report = run(args)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
