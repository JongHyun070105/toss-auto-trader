#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import csv
import datetime as dt
import io
import json
import logging
import math
import os
import sqlite3
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from statistics import mean, median
from typing import Any


DEFAULT_CLASSIC_STRATEGIES = [
    'AdaptiveRSIStrategy',
    'AlphaRSIProStrategy',
    'BBandsStrategy',
    'BuyHoldStrategy',
    'CrossSMAStrategy',
    'DoubleTopStrategy',
    'HybridAlphaRSIStrategy',
    'MACDStrategy',
    'MomentumStrategy',
    'NaiveROCStrategy',
    'NaiveSMAStrategy',
    'ROCMAStrategy',
    'ROCStochStrategy',
    'RSRSStrategy',
    'RiskAverseStrategy',
    'RsiBollingerBandsStrategy',
    'TripleRsiStrategy',
    'TurtleTradingStrategy',
    'VCPStrategy',
]


class UnsupportedExternalEngine(RuntimeError):
    pass


def parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value[:10])


def date_s(value: dt.date | str) -> str:
    return value.isoformat() if isinstance(value, dt.date) else str(value)[:10]


def add_years(day: dt.date, years: int) -> dt.date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)


def build_windows(start: str, end: str, *, include_full: bool = True, include_years: bool = True, rolling_years: list[int] | None = None) -> list[dict]:
    rolling_years = rolling_years or []
    start_d = parse_date(start)
    end_d = parse_date(end)
    windows: list[dict] = []
    if include_full:
        windows.append({'label': 'full', 'start': date_s(start_d), 'end': date_s(end_d), 'kind': 'full'})
    if include_years:
        for year in range(start_d.year, end_d.year + 1):
            ys = max(start_d, dt.date(year, 1, 1))
            ye = min(end_d, dt.date(year, 12, 31))
            if ys <= ye:
                windows.append({'label': f'year_{year}', 'start': date_s(ys), 'end': date_s(ye), 'kind': 'year'})
    for n in rolling_years:
        y = start_d.year
        while True:
            ws = max(start_d, dt.date(y, 1, 1))
            we = min(end_d, add_years(dt.date(y, 1, 1), n) - dt.timedelta(days=1))
            if we > end_d or ws > end_d:
                break
            if (we - ws).days >= 250 * n * 0.65:
                windows.append({'label': f'rolling{n}y_{ws.year}_{we.year}', 'start': date_s(ws), 'end': date_s(we), 'kind': f'rolling{n}y'})
            y += 1
    # Deduplicate same label/start/end when short ranges overlap.
    seen = set()
    out = []
    for w in windows:
        key = (w['label'], w['start'], w['end'])
        if key not in seen:
            seen.add(key)
            out.append(w)
    return out


def asof_universe(
    db_path: str,
    asof_date: str,
    *,
    lookback_bars: int = 60,
    limit: int = 100,
    min_bars: int = 40,
    min_avg_trade_value: float = 0.0,
) -> list[dict]:
    """Select symbols using only candles strictly before the window start.

    This avoids selecting 2021 symbols using 2026 liquidity/survivorship information.
    """
    con = sqlite3.connect(db_path)
    cur = None
    try:
        cur = con.execute(
            """
            WITH ranked AS (
              SELECT symbol, timestamp,
                     CAST(close_price AS REAL) AS close_price,
                     CAST(volume AS REAL) AS volume,
                     ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY timestamp DESC) AS rn
              FROM candle_cache
              WHERE interval='1d'
                AND timestamp < ?
                AND close_price IS NOT NULL
                AND volume IS NOT NULL
            ), windowed AS (
              SELECT symbol, close_price, volume
              FROM ranked
              WHERE rn <= ?
            )
            SELECT symbol,
                   COUNT(*) AS lookback_rows,
                   AVG(close_price * volume) AS avg_trade_value,
                   MIN(close_price) AS min_close,
                   MAX(close_price) AS max_close
            FROM windowed
            GROUP BY symbol
            HAVING lookback_rows >= ? AND avg_trade_value >= ?
            ORDER BY avg_trade_value DESC
            LIMIT ?
            """,
            (asof_date, lookback_bars, min_bars, min_avg_trade_value, limit),
        )
        rows = cur.fetchall()
    finally:
        if cur is not None:
            cur.close()
        con.close()
    return [
        {
            'symbol': str(symbol),
            'asof_date': asof_date,
            'lookback_rows': int(rows_count),
            'avg_trade_value': float(avg_trade_value or 0.0),
            'min_close': float(min_close or 0.0),
            'max_close': float(max_close or 0.0),
            'selection_rule': f'top_{limit}_avg_trade_value_asof_{asof_date}_lookback_{lookback_bars}',
        }
        for symbol, rows_count, avg_trade_value, min_close, max_close in rows
    ]


def load_symbol_frame(db_path: str, symbol: str, start: str, end: str):
    import pandas as pd

    con = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            """
            SELECT timestamp AS date,
                   CAST(open_price AS REAL) AS open,
                   CAST(high_price AS REAL) AS high,
                   CAST(low_price AS REAL) AS low,
                   CAST(close_price AS REAL) AS close,
                   CAST(volume AS REAL) AS volume
            FROM candle_cache
            WHERE interval='1d' AND symbol=? AND timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp ASC
            """,
            con,
            params=(symbol, start, end),
            parse_dates=['date'],
        )
    finally:
        con.close()
    if df.empty:
        return df
    df = df.dropna(subset=['open', 'high', 'low', 'close'])
    df = df[(df[['open', 'high', 'low', 'close']] > 0).all(axis=1)]
    df['volume'] = df['volume'].fillna(0)
    return df.set_index('date')


def data_quality_flags(df) -> dict:
    if df is None or len(df) == 0:
        return {'bars': 0, 'zero_volume_days': None, 'limit_move_proxy_days': None, 'max_calendar_gap_days': None}
    pct = df['close'].pct_change().abs()
    gaps = df.index.to_series().diff().dt.days.dropna()
    return {
        'bars': int(len(df)),
        'zero_volume_days': int((df['volume'] <= 0).sum()) if 'volume' in df else None,
        # KRX/KOSDAQ ordinary daily limit is often near 30%; use 29% as a proxy for limit-lock risk.
        'limit_move_proxy_days': int((pct >= 0.29).sum()),
        'huge_gap_proxy_days': int(((df['open'] / df['close'].shift(1) - 1).abs() >= 0.15).sum()),
        'max_calendar_gap_days': int(gaps.max()) if len(gaps) else 0,
    }


def fetch_kosdaq_index(start: str, end: str):
    import pandas as pd

    start_ymd = start[:10].replace('-', '')
    end_ymd = end[:10].replace('-', '')
    query = urllib.parse.urlencode({'startDateTime': f'{start_ymd}0000', 'endDateTime': f'{end_ymd}0000'})
    url = f'https://api.stock.naver.com/chart/domestic/index/KOSDAQ/day?{query}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.naver.com/'})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    rows = []
    for row in data or []:
        try:
            rows.append({
                'date': pd.to_datetime(str(row['localDate'])),
                'open': float(row['openPrice']),
                'high': float(row['highPrice']),
                'low': float(row['lowPrice']),
                'close': float(row['closePrice']),
                'volume': float(row.get('accumulatedTradingVolume') or 0),
            })
        except Exception:
            continue
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index('date').sort_index()


def close_return(df, start: str, end: str) -> float | None:
    if df is None or df.empty:
        return None
    sub = df.loc[start:end]
    if len(sub) < 2:
        return None
    return float(sub['close'].iloc[-1] / sub['close'].iloc[0] - 1)


def setup_external_engine(ai_trader_repo: str | None):
    if ai_trader_repo:
        repo = Path(ai_trader_repo).expanduser().resolve()
        if not repo.exists():
            raise UnsupportedExternalEngine(f'ai-trader repo not found: {repo}')
        sys.path.insert(0, str(repo))
    try:
        import backtrader as bt  # noqa: F401
        from ai_trader.backtesting.strategies import classic
    except Exception as exc:
        raise UnsupportedExternalEngine(
            'ai-trader/backtrader import failed. Run inside the external ai-trader venv or pass --ai-trader-repo.'
        ) from exc
    logging.disable(logging.CRITICAL)
    return classic


def load_strategy_classes(classic_module, requested: list[str]) -> dict[str, Any]:
    available = {name: getattr(classic_module, name) for name in getattr(classic_module, '__all__', []) if hasattr(classic_module, name)}
    if requested == ['all']:
        names = [name for name in DEFAULT_CLASSIC_STRATEGIES if name in available]
    else:
        names = requested
    missing = [name for name in names if name not in available]
    if missing:
        raise UnsupportedExternalEngine(f'Missing ai-trader classic strategies: {missing}')
    return {name: available[name] for name in names}


def install_kr_cost_model(cerebro, bt, *, buy_commission_bps: float, sell_commission_bps: float, sell_tax_bps: float):
    class KRCostCommissionInfo(bt.CommInfoBase):
        params = (
            ('buy_commission', buy_commission_bps / 10000.0),
            ('sell_commission', sell_commission_bps / 10000.0),
            ('sell_tax', sell_tax_bps / 10000.0),
            ('stocklike', True),
            ('commtype', bt.CommInfoBase.COMM_PERC),
        )

        def _getcommission(self, size, price, pseudoexec):
            rate = self.p.buy_commission if size > 0 else self.p.sell_commission + self.p.sell_tax
            return abs(size) * price * rate

    cerebro.broker.addcommissioninfo(KRCostCommissionInfo())


def run_backtest_one(
    df,
    strategy_cls,
    *,
    cash: float,
    buy_commission_bps: float,
    sell_commission_bps: float,
    sell_tax_bps: float,
    slippage_bps: float,
    half_spread_bps: float,
):
    import backtrader as bt
    import numpy as np

    if len(df) < 80:
        return {'ok': False, 'reason': 'insufficient_bars', 'bars': int(len(df))}
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(cash)
    install_kr_cost_model(
        cerebro,
        bt,
        buy_commission_bps=buy_commission_bps,
        sell_commission_bps=sell_commission_bps,
        sell_tax_bps=sell_tax_bps,
    )
    slip = max(0.0, (slippage_bps + half_spread_bps) / 10000.0)
    if slip:
        cerebro.broker.set_slippage_perc(slip, slip_open=True, slip_limit=True, slip_match=True, slip_out=False)
    data = bt.feeds.PandasData(dataname=df, timeframe=bt.TimeFrame.Days)
    cerebro.adddata(data)
    cerebro.addstrategy(strategy_cls)
    cerebro.addsizer(bt.sizers.PercentSizer, percents=95)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='timereturn')
    initial_value = cerebro.broker.getvalue()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        strat = cerebro.run()[0]
    final_value = cerebro.broker.getvalue()
    total_return = float(final_value / initial_value - 1)
    dd = strat.analyzers.drawdown.get_analysis()
    trade = strat.analyzers.trades.get_analysis()
    returns = strat.analyzers.returns.get_analysis()
    daily_returns = list(strat.analyzers.timereturn.get_analysis().values())
    daily_returns = [float(x) for x in daily_returns if x is not None]
    daily_vol = float(np.std(daily_returns, ddof=1)) if len(daily_returns) > 1 else None
    annualized_vol = daily_vol * math.sqrt(252) if daily_vol is not None else None
    total_trades = int(trade.get('total', {}).get('total', 0) or 0) if isinstance(trade, dict) else 0
    won = int(trade.get('won', {}).get('total', 0) or 0) if isinstance(trade, dict) else 0
    lost = int(trade.get('lost', {}).get('total', 0) or 0) if isinstance(trade, dict) else 0
    mdd_pct = dd.get('max', {}).get('drawdown') if isinstance(dd, dict) else None
    mdd_frac = float(mdd_pct) / 100.0 if mdd_pct is not None else None
    return {
        'ok': True,
        'bars': int(len(df)),
        'return': total_return,
        'final_value': float(final_value),
        'max_drawdown_pct': float(mdd_pct) if mdd_pct is not None else None,
        'return_to_mdd': total_return / mdd_frac if mdd_frac and mdd_frac > 0 else None,
        'annualized_volatility': annualized_vol,
        'return_to_volatility': total_return / annualized_vol if annualized_vol and annualized_vol > 0 else None,
        'sharpe': strat.analyzers.sharpe.get_analysis().get('sharperatio'),
        'rtot': returns.get('rtot') if isinstance(returns, dict) else None,
        'rnorm': returns.get('rnorm') if isinstance(returns, dict) else None,
        'trades': total_trades,
        'won': won,
        'lost': lost,
        'win_rate': won / total_trades if total_trades else None,
    }


def num_stats(vals: list[float]) -> dict:
    vals = [float(v) for v in vals if v is not None and not math.isnan(float(v))]
    if not vals:
        return {'count': 0, 'avg': None, 'median': None, 'min': None, 'max': None, 'positive_rate': None}
    return {
        'count': len(vals),
        'avg': mean(vals),
        'median': median(vals),
        'min': min(vals),
        'max': max(vals),
        'positive_rate': sum(1 for v in vals if v > 0) / len(vals),
    }


def aggregate_rows(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        if row.get('ok'):
            grouped.setdefault((row['window'], row['strategy']), []).append(row)
    out = []
    for (window, strategy), items in sorted(grouped.items()):
        returns = [r['return'] for r in items]
        excess = [r['excess_return_vs_kosdaq'] for r in items if r.get('excess_return_vs_kosdaq') is not None]
        mdds = [r['max_drawdown_pct'] for r in items if r.get('max_drawdown_pct') is not None]
        ret_vol = [r['return_to_volatility'] for r in items if r.get('return_to_volatility') is not None]
        ret_mdd = [r['return_to_mdd'] for r in items if r.get('return_to_mdd') is not None]
        out.append({
            'window': window,
            'strategy': strategy,
            'symbols': len(items),
            'return': num_stats(returns),
            'excess_return_vs_kosdaq': num_stats(excess),
            'max_drawdown_pct': num_stats(mdds),
            'return_to_volatility': num_stats(ret_vol),
            'return_to_mdd': num_stats(ret_mdd),
        })
    return out


def stability_summary(aggregates: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for row in aggregates:
        grouped.setdefault(row['strategy'], []).append(row)
    out = []
    for strategy, items in sorted(grouped.items()):
        med_returns = [r['return']['median'] for r in items if r['return']['median'] is not None]
        med_excess = [r['excess_return_vs_kosdaq']['median'] for r in items if r['excess_return_vs_kosdaq']['median'] is not None]
        pos_return_windows = [r['return']['positive_rate'] for r in items if r['return']['positive_rate'] is not None]
        out.append({
            'strategy': strategy,
            'windows': len(items),
            'median_window_return': median(med_returns) if med_returns else None,
            'min_window_median_return': min(med_returns) if med_returns else None,
            'median_window_excess_vs_kosdaq': median(med_excess) if med_excess else None,
            'positive_universe_window_rate_avg': mean(pos_return_windows) if pos_return_windows else None,
            'research_gate': 'exploratory_only_requires_future_holdout',
        })
    out.sort(key=lambda x: (
        x.get('median_window_excess_vs_kosdaq') if x.get('median_window_excess_vs_kosdaq') is not None else -999,
        x.get('median_window_return') if x.get('median_window_return') is not None else -999,
    ), reverse=True)
    return out


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text('')
        return
    keys = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description='Run external ai-trader classic strategies over as-of KR universes with conservative KR cost assumptions.')
    ap.add_argument('--db-path', default='data/edge_research_universe_long.sqlite3')
    ap.add_argument('--ai-trader-repo', default=os.environ.get('AI_TRADER_REPO', '/tmp/ai-trader-eval'))
    ap.add_argument('--out', default='data/ai_trader_sweep/latest.json')
    ap.add_argument('--start', default='2020-10-07')
    ap.add_argument('--end', default='2026-06-24')
    ap.add_argument('--max-symbols-per-window', type=int, default=20)
    ap.add_argument('--lookback-bars', type=int, default=60)
    ap.add_argument('--min-lookback-bars', type=int, default=40)
    ap.add_argument('--min-window-bars', type=int, default=120)
    ap.add_argument('--min-avg-trade-value', type=float, default=0.0)
    ap.add_argument('--strategies', default='all', help='Comma-separated classic strategy names or all')
    ap.add_argument('--include-full', action='store_true')
    ap.add_argument('--no-years', action='store_true')
    ap.add_argument('--rolling-years', default='1,2,3')
    ap.add_argument('--cash', type=float, default=1_000_000)
    ap.add_argument('--buy-commission-bps', type=float, default=4.0)
    ap.add_argument('--sell-commission-bps', type=float, default=4.0)
    ap.add_argument('--sell-tax-bps', type=float, default=18.0)
    ap.add_argument('--slippage-bps', type=float, default=5.0)
    ap.add_argument('--half-spread-bps', type=float, default=5.0)
    ap.add_argument('--limit-symbols-total', type=int, default=0, help='Debug cap across all symbol-window pairs')
    args = ap.parse_args()

    classic = setup_external_engine(args.ai_trader_repo)
    requested = [x.strip() for x in args.strategies.split(',') if x.strip()] or ['all']
    strategies = load_strategy_classes(classic, requested)
    rolling = [int(x) for x in args.rolling_years.split(',') if x.strip()] if args.rolling_years else []
    windows = build_windows(args.start, args.end, include_full=args.include_full, include_years=not args.no_years, rolling_years=rolling)
    kosdaq = fetch_kosdaq_index(args.start, args.end)

    rows: list[dict] = []
    selections: list[dict] = []
    run_count = 0
    for window in windows:
        selected = asof_universe(
            args.db_path,
            window['start'],
            lookback_bars=args.lookback_bars,
            limit=args.max_symbols_per_window,
            min_bars=args.min_lookback_bars,
            min_avg_trade_value=args.min_avg_trade_value,
        )
        selections.append({'window': window, 'symbols': selected})
        kosdaq_return = close_return(kosdaq, window['start'], window['end'])
        for sel in selected:
            if args.limit_symbols_total and run_count >= args.limit_symbols_total:
                break
            df = load_symbol_frame(args.db_path, sel['symbol'], window['start'], window['end'])
            quality = data_quality_flags(df)
            if len(df) < args.min_window_bars:
                continue
            for strategy_name, strategy_cls in strategies.items():
                try:
                    result = run_backtest_one(
                        df,
                        strategy_cls,
                        cash=args.cash,
                        buy_commission_bps=args.buy_commission_bps,
                        sell_commission_bps=args.sell_commission_bps,
                        sell_tax_bps=args.sell_tax_bps,
                        slippage_bps=args.slippage_bps,
                        half_spread_bps=args.half_spread_bps,
                    )
                except Exception as exc:
                    result = {'ok': False, 'reason': f'{type(exc).__name__}: {exc}', 'bars': len(df)}
                result.update({
                    'window': window['label'],
                    'window_kind': window['kind'],
                    'window_start': window['start'],
                    'window_end': window['end'],
                    'symbol': sel['symbol'],
                    'strategy': strategy_name,
                    'kosdaq_return': kosdaq_return,
                    'excess_return_vs_kosdaq': (result.get('return') - kosdaq_return) if result.get('ok') and kosdaq_return is not None else None,
                    'asof_avg_trade_value': sel['avg_trade_value'],
                    **{f'data_{k}': v for k, v in quality.items()},
                })
                rows.append(result)
            run_count += 1
        if args.limit_symbols_total and run_count >= args.limit_symbols_total:
            break

    aggregates = aggregate_rows(rows)
    stability = stability_summary(aggregates)
    report = {
        'mode': 'external_ai_trader_asof_universe_sweep_no_send',
        'live_order_allowed': False,
        'external_engine': {
            'repo': args.ai_trader_repo,
            'license': 'GPL-3.0; private/internal modification is okay, but distribution or code mixing requires GPL review',
            'boundary': 'external_optional_engine_imported_from_configured_repo_or_venv',
        },
        'config': vars(args),
        'cost_model': {
            'buy_commission_bps': args.buy_commission_bps,
            'sell_commission_bps': args.sell_commission_bps,
            'sell_tax_bps': args.sell_tax_bps,
            'slippage_bps': args.slippage_bps,
            'half_spread_bps': args.half_spread_bps,
            'execution_limits': 'limit-up/down and halts are measured as risk proxies, not fully simulated fills',
        },
        'windows': windows,
        'selection_summary': [
            {'window': x['window']['label'], 'count': len(x['symbols']), 'top_symbols': x['symbols'][:5]}
            for x in selections
        ],
        'strategies': list(strategies),
        'rows_count': len(rows),
        'aggregates': aggregates,
        'stability_summary': stability,
        'warnings': [
            'This is exploratory. Do not promote any strategy without a later unseen/future holdout.',
            'Universe selection is as-of by window start, but delisted symbols absent from the local DB can still create survivorship bias.',
            'KR tax/commission/slippage are modeled; limit-lock/halts/orderbook depth are only risk proxies in this sweep.',
            'Running all strategies repeatedly on the same history is a search procedure; top results are hypotheses, not proof.',
        ],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    write_csv(out.with_suffix('.rows.csv'), rows)
    write_csv(out.with_suffix('.aggregates.csv'), aggregates)
    print(json.dumps({
        'out': str(out),
        'rows_count': len(rows),
        'windows': len(windows),
        'strategies': list(strategies),
        'top_stability': stability[:10],
    }, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
