from __future__ import annotations

import argparse
from dataclasses import replace
import copy
import json
from pathlib import Path
import time
from decimal import Decimal
from typing import Sequence

from . import db
from .collector import collect_account_snapshot, collect_exchange_rate, collect_prices, decide_from_recent_prices, get_candles_on_demand
from .config import Settings
from .decision_engine import evaluate_symbol_from_candles, execute_paper_decision, mark_decision_outcome
from .lab_config import load_simple_yaml
from .live_order import (
    build_buy_limit_payloads,
    parse_pair_slots,
    redact_order_result,
    required_confirmation,
    validate_candidate_for_live,
    validate_fresh_orderbooks,
)
from .market import CycleCache, fallback_market_open, is_open_from_calendar
from .news_client import NewsClientError, NewsHub
from .orderbook_utils import best_spread_from_orderbook as _best_spread_from_orderbook
from .paper import PaperBroker, fee_kwargs_from_cfg
from .screener import load_seed_csv, screen_low_price_candidates
from .strategy import Signal
from .toss_client import TossApiError, TossInvestClient


def scrub_output(obj):
    if isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
            key = k.lower()
            if key in {"accountno", "account_no"}:
                cleaned[k] = "[REDACTED]"
            elif "secret" in key or ("token" in key and key not in {"token", "token_type"}):
                cleaned[k] = "[REDACTED]"
            else:
                cleaned[k] = scrub_output(v)
        return cleaned
    if isinstance(obj, list):
        return [scrub_output(x) for x in obj]
    return obj


def print_json(obj) -> None:
    print(json.dumps(scrub_output(obj), ensure_ascii=False, indent=2, default=str))


def cmd_init_db(args) -> None:
    settings = Settings.from_env()
    db.init_db(settings.db_path)
    db.ensure_paper_account(settings.db_path, initial_cash_krw=Decimal(str(args.initial_cash)))
    print_json({"ok": True, "db_path": settings.db_path, "summary": db.summary(settings.db_path)})


def cmd_summary(args) -> None:
    settings = Settings.from_env()
    db.init_db(settings.db_path)
    print_json(db.summary(settings.db_path))


def cmd_api_smoke(args) -> None:
    settings = Settings.from_env()
    db.init_db(settings.db_path)
    client = TossInvestClient(settings)
    out = {"token": "requesting"}
    token = client.issue_token()
    out["token"] = {"token_type": token.token_type, "expires_at": token.expires_at}
    accounts = client.get_accounts()
    db.insert_snapshot(settings.db_path, "/api/v1/accounts", accounts)
    out["accounts"] = accounts
    symbols = args.symbols.split(",") if args.symbols else ["005930"]
    prices = client.get_prices(symbols)
    for item in prices.get("result", []):
        db.insert_price(settings.db_path, item)
    db.insert_snapshot(settings.db_path, "/api/v1/prices", prices, {"symbols": symbols})
    out["prices"] = prices
    print_json(out)


def cmd_collect_price(args) -> None:
    settings = Settings.from_env()
    symbols = args.symbols.split(",")
    print_json(collect_prices(settings, symbols))



def best_spread_from_orderbook(payload: dict) -> dict:
    return _best_spread_from_orderbook(payload)


def cmd_orderbook(args) -> None:
    settings = Settings.from_env()
    client = TossInvestClient(settings)
    payload = client.get_orderbook(args.symbol)
    print_json({"symbol": args.symbol, "spread": best_spread_from_orderbook(payload), "orderbook": payload if args.raw else None})


def cmd_collect_macro(args) -> None:
    settings = Settings.from_env()
    print_json(collect_exchange_rate(settings, args.base_currency, args.quote_currency))


def cmd_account_snapshot(args) -> None:
    settings = Settings.from_env()
    print_json(collect_account_snapshot(settings, args.account_seq, args.currency))


def cmd_loop(args) -> None:
    settings = Settings.from_env()
    db.init_db(settings.db_path)
    symbols = args.symbols.split(",")
    outputs = []
    for i in range(args.iterations):
        tick = {"iteration": i + 1}
        if not args.offline:
            tick["prices"] = collect_prices(settings, symbols)
            if args.collect_macro:
                tick["exchangeRate"] = collect_exchange_rate(settings)
        broker = PaperBroker(settings.db_path, initial_cash_krw=Decimal(str(args.initial_cash)))
        decisions = []
        for symbol in symbols:
            signal = decide_from_recent_prices(settings.db_path, symbol, Decimal(str(args.trade_cash)))
            execution = broker.execute_signal(signal)
            decisions.append({"signal": signal.__dict__, "execution": execution})
        tick["decisions"] = decisions
        tick["summary"] = db.summary(settings.db_path)
        outputs.append(tick)
        if i < args.iterations - 1 and args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)
    print_json(outputs)



def load_bot_config(path: str) -> dict:
    return load_simple_yaml(path) if path else load_simple_yaml("config.example.yaml")


def cmd_candles(args) -> None:
    settings = Settings.from_env()
    print_json(get_candles_on_demand(settings, args.symbol, args.interval, args.count, persist_snapshot=args.persist_snapshot))


def cmd_agent_tick(args) -> None:
    settings = Settings.from_env()
    cfg = load_bot_config(args.config)
    db.init_db(settings.db_path)
    cache = CycleCache()
    client = TossInvestClient(settings)
    market_open = True
    if args.respect_market_hours:
        country = args.market_country.upper()
        try:
            cal = cache.get_or_set(f"calendar:{country}", lambda: client.get_market_calendar(country))
            market_open = is_open_from_calendar(cal, country=country)
        except Exception:
            market_open = fallback_market_open(country=country)
    if not market_open and not args.force:
        print_json({"skipped": True, "reason": "market closed", "summary": db.summary(settings.db_path)})
        return
    outputs = []
    for symbol in args.symbols.split(","):
        candles = cache.get_or_set(
            f"candles:{symbol}:{args.interval}:{args.count}",
            lambda symbol=symbol: get_candles_on_demand(settings, symbol, args.interval, args.count).get("result", {}).get("candles", []),
        )
        decision = evaluate_symbol_from_candles(settings.db_path, symbol, candles, cfg, Decimal(str(args.trade_cash)))
        result = execute_paper_decision(settings.db_path, decision, Decimal(str(args.trade_cash)), cfg, branch="api_agent")
        outputs.append({"decision": decision, "execution": result["execution"], "event_id": result["event_id"]})
    print_json({"outputs": outputs, "summary": db.summary(settings.db_path)})


def branch_config(base_cfg: dict, branch: str) -> dict:
    cfg = copy.deepcopy(base_cfg)
    cfg.setdefault("selection", {})
    if branch == "technical_aggressive":
        cfg["selection"]["sideways_min_score"] = 55
        cfg["selection"]["min_confidence"] = 0.55
        cfg["selection"]["technical_buy_score"] = 40
    elif branch == "balanced_momentum":
        cfg["selection"]["sideways_min_score"] = 62
        cfg["selection"]["min_confidence"] = 0.62
        cfg["selection"]["technical_buy_score"] = 55
        cfg.setdefault("paper", {})["daily_max_orders"] = 2
    elif branch == "balanced_momentum_v2":
        cfg["selection"]["sideways_min_score"] = 58
        cfg["selection"]["min_confidence"] = 0.58
        cfg["selection"]["technical_buy_score"] = 52
        cfg["selection"]["rsi_overheat_block"] = 75
        cfg.setdefault("paper", {})["daily_max_orders"] = 2
    elif branch == "fee_aware_momentum":
        cfg["selection"]["sideways_min_score"] = 68
        cfg["selection"]["min_confidence"] = 0.68
        cfg["selection"]["technical_buy_score"] = 62
        cfg["selection"]["rsi_overheat_block"] = 72
        cfg["selection"]["news_min_score"] = 48
        cfg.setdefault("paper", {})["daily_max_orders"] = 1
    elif branch == "ultra_conservative":
        cfg["selection"]["sideways_min_score"] = 82
        cfg["selection"]["min_confidence"] = 0.82
        cfg["selection"]["technical_buy_score"] = 75
        cfg["selection"]["rsi_overheat_block"] = 68
        cfg["selection"]["news_min_score"] = 55
        cfg.setdefault("paper", {})["daily_max_orders"] = 1
    elif branch == "observation_first":
        cfg["selection"]["sideways_min_score"] = 95
        cfg["selection"]["min_confidence"] = 0.95
    else:  # conservative_guarded
        cfg["selection"]["sideways_min_score"] = 70
        cfg["selection"]["min_confidence"] = 0.70
    return cfg


def synthetic_candles(iteration: int, base: Decimal) -> tuple[list[dict], Decimal]:
    candles = []
    price = base
    for n in range(80):
        drift = Decimal("1") + (Decimal(iteration % 3 - 1) * Decimal("0.001")) + (Decimal(n % 5 - 2) * Decimal("0.0005"))
        open_p = price
        close_p = max(Decimal("1"), price * drift)
        high = max(open_p, close_p) * Decimal("1.002")
        low = min(open_p, close_p) * Decimal("0.998")
        candles.insert(0, {"timestamp": db.utc_now(), "openPrice": str(open_p), "highPrice": str(high), "lowPrice": str(low), "closePrice": str(close_p), "volume": str(1000+n), "currency": "KRW"})
        price = close_p
    future_drift = Decimal("1") + (Decimal((iteration + 1) % 3 - 1) * Decimal("0.001"))
    future_price = max(Decimal("1"), price * future_drift)
    return candles, future_price


def cmd_learning_sim(args) -> None:
    settings = Settings.from_env()
    cfg = load_bot_config(args.config)
    db.init_db(settings.db_path)
    base = Decimal(str(args.base_price))
    branches = [b.strip() for b in args.branches.split(",") if b.strip()]
    outputs = []
    for i in range(args.iterations):
        candles, future_price = synthetic_candles(i, base)
        for branch in branches:
            cfg_b = branch_config(cfg, branch)
            decision = evaluate_symbol_from_candles(settings.db_path, args.symbol, candles, cfg_b, Decimal(str(args.trade_cash)))
            result = execute_paper_decision(settings.db_path, decision, Decimal(str(args.trade_cash)), cfg_b, branch=branch)
            entry = Decimal(str(decision.get("features", {}).get("last_close") or "0"))
            effective_side = decision["side"] if result["execution"].startswith("FILLED") else "HOLD"
            outcome = mark_decision_outcome(settings.db_path, result["event_id"], side=effective_side, entry_price=entry, future_price=future_price, cfg=cfg_b)
            outputs.append({"iteration": i + 1, "branch": branch, "side": decision["side"], "effective_side": effective_side, "score": decision["score"], "execution": result["execution"], "loss": outcome["loss"]})
        if (i + 1) % max(1, args.status_every) == 0:
            print_json({"status": "progress", "iteration": i + 1, "summary": db.summary(settings.db_path)})
        if i < args.iterations - 1 and args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)
    print_json({"done": True, "outputs_tail": outputs[-12:], "summary": db.summary(settings.db_path)})



def cmd_cache_candles(args) -> None:
    settings = Settings.from_env()
    db.init_db(settings.db_path)
    client = TossInvestClient(settings)
    outputs = []
    for symbol in [s.strip() for s in args.symbols.split(",") if s.strip()]:
        before = args.before or None
        total = 0
        pages = []
        for page in range(args.pages):
            resp = client.get_candles(symbol, args.interval, min(args.count, 200), before=before, adjusted=not args.unadjusted)
            result = resp.get("result", {})
            candles = result.get("candles", [])
            inserted = db.insert_candles(settings.db_path, symbol, args.interval, candles)
            total += inserted
            pages.append({"page": page + 1, "fetched": len(candles), "inserted_or_replaced": inserted, "nextBefore": result.get("nextBefore")})
            before = result.get("nextBefore")
            if not candles or not before:
                break
            if args.sleep_seconds > 0:
                time.sleep(args.sleep_seconds)
        outputs.append({"symbol": symbol, "interval": args.interval, "total_inserted_or_replaced": total, "cached_count": db.candle_cache_count(settings.db_path, symbol, args.interval), "pages": pages})
    print_json({"outputs": outputs, "summary": db.summary(settings.db_path)})


def cmd_historical_backtest(args) -> None:
    settings = Settings.from_env()
    cfg = load_bot_config(args.config)
    db.init_db(settings.db_path)
    branches = [b.strip() for b in args.branches.split(",") if b.strip()]
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    outputs = []
    for symbol in symbols:
        candles_all = db.cached_candles(settings.db_path, symbol, args.interval, ascending=True)
        if args.max_bars and len(candles_all) > args.max_bars:
            candles_all = candles_all[-args.max_bars:]
        if len(candles_all) < args.window + 2:
            outputs.append({"symbol": symbol, "skipped": True, "reason": f"need at least {args.window + 2} cached candles", "cached": len(candles_all)})
            continue
        for idx in range(args.window, len(candles_all) - args.horizon):
            window = list(reversed(candles_all[idx - args.window:idx]))  # evaluate_symbol expects newest-first candles
            future = candles_all[idx + args.horizon]
            entry = Decimal(str(candles_all[idx - 1]["closePrice"]))
            future_price = Decimal(str(future["closePrice"]))
            for branch in branches:
                cfg_b = branch_config(cfg, branch)
                cfg_b.setdefault("paper", {})["initial_cash_krw"] = Decimal(str(args.initial_cash))
                cfg_b.setdefault("paper", {})["max_order_krw"] = Decimal(str(args.max_order))
                # Historical replay evaluates many past days in one real runtime day; disable runtime-date order cap here.
                cfg_b.setdefault("paper", {})["daily_max_orders"] = int(args.historical_daily_max_orders)
                cfg_b.setdefault("paper", {})["simulated_now"] = candles_all[idx - 1]["timestamp"]
                account_branch = f"hist:{symbol}:{branch}"
                broker = PaperBroker(
                    settings.db_path,
                    account_name=account_branch,
                    initial_cash_krw=Decimal(str(args.initial_cash)),
                    max_order_krw=Decimal(str(args.max_order)),
                    daily_max_orders=int(args.historical_daily_max_orders),
                    simulated_now=candles_all[idx - 1]["timestamp"],
                    **fee_kwargs_from_cfg(cfg_b),
                )
                held_qty, avg_price = broker.position(symbol)
                current_price = entry
                risk_cfg = cfg_b.get("risk", {})
                stop = Decimal(str(risk_cfg.get("stop_loss_pct", 0.03)))
                take = Decimal(str(risk_cfg.get("take_profit_pct", 0.06)))
                exit_reason = None
                if held_qty > 0 and avg_price > 0:
                    if current_price <= avg_price * (Decimal("1") - stop):
                        exit_reason = f"historical stop-loss current={current_price} avg={avg_price} stop={stop}"
                    elif current_price >= avg_price * (Decimal("1") + take):
                        exit_reason = f"historical take-profit current={current_price} avg={avg_price} take={take}"
                if exit_reason:
                    sell_signal = Signal(symbol=symbol, side="SELL", reason=exit_reason, confidence=1.0, limit_price=current_price, cash_amount=Decimal("0"))
                    execution = broker.execute_signal(sell_signal)
                    event_id = db.log_decision_event(
                        settings.db_path,
                        symbol=symbol,
                        side="SELL",
                        execution=execution,
                        reason=exit_reason,
                        confidence=1.0,
                        price=current_price,
                        cash_amount=Decimal("0"),
                        market_context={"features": {"last_close": str(current_price)}, "exit": True},
                        result={"execution": execution},
                        branch=account_branch,
                    )
                    outcome = mark_decision_outcome(settings.db_path, event_id, side="SELL" if execution.startswith("FILLED") else "HOLD", entry_price=avg_price, future_price=current_price, cfg=cfg_b)
                    outputs.append({"symbol": symbol, "idx": idx, "timestamp": candles_all[idx - 1]["timestamp"], "branch": branch, "side": "SELL", "effective_side": "SELL" if execution.startswith("FILLED") else "HOLD", "execution": execution, "score": 100, "loss": outcome["loss"]})
                    continue
                decision = evaluate_symbol_from_candles(settings.db_path, symbol, window, cfg_b, Decimal(str(args.trade_cash)))
                result = execute_paper_decision(settings.db_path, decision, Decimal(str(args.trade_cash)), cfg_b, branch=account_branch)
                effective_side = decision["side"] if result["execution"].startswith("FILLED") else "HOLD"
                outcome = mark_decision_outcome(settings.db_path, result["event_id"], side=effective_side, entry_price=entry, future_price=future_price, cfg=cfg_b)
                outputs.append({"symbol": symbol, "idx": idx, "timestamp": candles_all[idx - 1]["timestamp"], "branch": branch, "side": decision["side"], "effective_side": effective_side, "execution": result["execution"], "score": decision["score"], "loss": outcome["loss"]})
            if len(outputs) % max(1, args.status_every) == 0:
                print_json({"status": "progress", "outputs": len(outputs), "summary": db.summary(settings.db_path)})
    print_json({"done": True, "outputs_tail": outputs[-12:], "summary": db.summary(settings.db_path)})




def parse_pair_spec(raw: str) -> list[tuple[str, Decimal]]:
    return [(part.split(":", 1)[0].strip(), Decimal(part.split(":", 1)[1].strip())) for part in raw.split("+") if part.strip()]


def cmd_portfolio_pair_backtest(args) -> None:
    settings = Settings.from_env()
    cfg = load_bot_config(args.config)
    db.init_db(settings.db_path)
    branches = [b.strip() for b in args.branches.split(",") if b.strip()]
    outputs = []
    slot_initials: dict[str, Decimal] = {}
    slot_groups: dict[str, str] = {}
    brokers: dict[str, PaperBroker] = {}
    compact_skipped = 0
    compact_counts: dict[tuple[str, str, str], int] = {}
    for pair_i, raw_pair in enumerate([p.strip() for p in args.pairs.split(",") if p.strip()], 1):
        pair = parse_pair_spec(raw_pair)
        raw_candles = {sym: db.cached_candles(settings.db_path, sym, args.interval, ascending=True) for sym, _ in pair}
        common_ts = sorted(set.intersection(*(set(c["timestamp"] for c in candles) for candles in raw_candles.values()))) if raw_candles else []
        if args.exclude_last_bars:
            common_ts = common_ts[:-args.exclude_last_bars]
        if args.max_bars:
            common_ts = common_ts[-args.max_bars:]
        if len(common_ts) < args.window + 2:
            outputs.append({"pair": raw_pair, "skipped": True, "aligned": len(common_ts), "cached": {k: len(v) for k, v in raw_candles.items()}})
            continue
        ts_set = set(common_ts)
        candles_by_symbol = {sym: [c for c in candles if c["timestamp"] in ts_set] for sym, candles in raw_candles.items()}
        usable = len(common_ts)
        for idx in range(args.window, usable - args.horizon):
            for branch in branches:
                cfg_b = branch_config(cfg, branch)
                cfg_b.setdefault("paper", {})["initial_cash_krw"] = Decimal(str(args.initial_cash))
                cfg_b.setdefault("paper", {})["max_order_krw"] = Decimal(str(args.max_order))
                cfg_b.setdefault("paper", {})["daily_max_orders"] = int(args.historical_daily_max_orders)
                cfg_b.setdefault("paper", {})["simulated_now"] = common_ts[idx - 1]
                pair_branch = f"pair:{pair_i}:{branch}"
                for symbol, slot_cash in pair:
                    cfg_trade = cfg_b
                    account_branch = pair_branch
                    initial_cash = Decimal(str(args.initial_cash))
                    max_order = Decimal(str(args.max_order))
                    if args.isolated_slots:
                        cfg_trade = copy.deepcopy(cfg_b)
                        cfg_trade.setdefault("paper", {})["initial_cash_krw"] = slot_cash
                        cfg_trade.setdefault("paper", {})["max_order_krw"] = slot_cash
                        cfg_trade.setdefault("paper", {})["simulated_now"] = common_ts[idx - 1]
                        account_branch = f"{pair_branch}:{symbol}"
                        initial_cash = slot_cash
                        max_order = slot_cash
                        slot_initials[account_branch] = slot_cash
                        slot_groups[account_branch] = pair_branch
                    candles_all = candles_by_symbol[symbol]
                    window = list(reversed(candles_all[idx - args.window:idx]))
                    entry = Decimal(str(candles_all[idx - 1]["closePrice"]))
                    future_price = Decimal(str(candles_all[idx + args.horizon]["closePrice"]))
                    broker = brokers.get(account_branch)
                    if broker is None:
                        broker = PaperBroker(settings.db_path, account_name=account_branch, initial_cash_krw=initial_cash, max_order_krw=max_order, daily_max_orders=int(args.historical_daily_max_orders), simulated_now=common_ts[idx - 1], **fee_kwargs_from_cfg(cfg_trade))
                        brokers[account_branch] = broker
                    else:
                        broker.simulated_now = common_ts[idx - 1]
                    held_qty, avg_price = broker.position(symbol)
                    risk_cfg = cfg_b.get("risk", {})
                    stop = Decimal(str(risk_cfg.get("stop_loss_pct", 0.03)))
                    take = Decimal(str(risk_cfg.get("take_profit_pct", 0.06)))
                    exit_reason = None
                    if held_qty > 0 and avg_price > 0:
                        if entry <= avg_price * (Decimal("1") - stop):
                            exit_reason = f"portfolio stop-loss current={entry} avg={avg_price} stop={stop}"
                        elif entry >= avg_price * (Decimal("1") + take):
                            exit_reason = f"portfolio take-profit current={entry} avg={avg_price} take={take}"
                    if exit_reason:
                        execution = broker.execute_signal(Signal(symbol=symbol, side="SELL", reason=exit_reason, confidence=1.0, limit_price=entry, cash_amount=Decimal("0")))
                        event_id = db.log_decision_event(settings.db_path, symbol=symbol, side="SELL", execution=execution, reason=exit_reason, confidence=1.0, price=entry, cash_amount=Decimal("0"), market_context={"pair": raw_pair, "exit": True}, result={"execution": execution}, branch=account_branch)
                        outcome = mark_decision_outcome(settings.db_path, event_id, side="SELL" if execution.startswith("FILLED") else "HOLD", entry_price=avg_price, future_price=entry, cfg=cfg_trade)
                        outputs.append({"pair": raw_pair, "symbol": symbol, "branch": branch, "side": "SELL", "execution": execution, "loss": outcome["loss"]})
                        continue
                    decision = evaluate_symbol_from_candles(settings.db_path, symbol, window, cfg_trade, slot_cash)
                    if args.compact_events and decision["side"] == "HOLD":
                        compact_skipped += 1
                        compact_counts[(raw_pair, account_branch, symbol)] = compact_counts.get((raw_pair, account_branch, symbol), 0) + 1
                        outputs.append({"pair": raw_pair, "symbol": symbol, "branch": branch, "side": "HOLD", "effective_side": "HOLD", "execution": "SKIPPED_COMPACT_HOLD", "loss": None})
                        continue
                    result = execute_paper_decision(settings.db_path, decision, slot_cash, cfg_trade, branch=account_branch, broker=broker)
                    effective_side = decision["side"] if result["execution"].startswith("FILLED") else "HOLD"
                    outcome = mark_decision_outcome(settings.db_path, result["event_id"], side=effective_side, entry_price=entry, future_price=future_price, cfg=cfg_trade)
                    outputs.append({"pair": raw_pair, "symbol": symbol, "branch": branch, "side": decision["side"], "effective_side": effective_side, "execution": result["execution"], "loss": outcome["loss"]})
            if len(outputs) % max(1, args.status_every) == 0:
                print_json({"status": "progress", "outputs": len(outputs), "summary": db.summary(settings.db_path)})
    pair_summaries = []
    slot_summaries = []
    grouped: dict[str, dict[str, Decimal]] = {}
    with db.connect(settings.db_path) as con:
        accounts = con.execute("SELECT id, name, cash_krw FROM paper_accounts WHERE name LIKE 'pair:%' ORDER BY name").fetchall()
        for acc in accounts:
            positions = con.execute("SELECT symbol, quantity, average_price FROM paper_positions WHERE account_id = ?", (acc["id"],)).fetchall()
            equity = Decimal(str(acc["cash_krw"]))
            for pos in positions:
                candles = db.cached_candles(settings.db_path, pos["symbol"], args.interval, ascending=False)
                last = Decimal(str(candles[0]["closePrice"])) if candles else Decimal(str(pos["average_price"]))
                equity += Decimal(str(pos["quantity"])) * last
            if args.isolated_slots:
                initial = slot_initials.get(acc["name"], Decimal(str(args.initial_cash)))
                group = slot_groups.get(acc["name"], ":".join(acc["name"].split(":")[:3]))
                grouped.setdefault(group, {"cash": Decimal("0"), "equity": Decimal("0"), "initial": Decimal("0")})
                grouped[group]["cash"] += Decimal(str(acc["cash_krw"]))
                grouped[group]["equity"] += equity
                grouped[group]["initial"] += initial
                slot_summaries.append({"account": acc["name"], "cash": acc["cash_krw"], "equity": str(equity), "pnl": str(equity - initial)})
            else:
                pair_summaries.append({"account": acc["name"], "cash": acc["cash_krw"], "equity": str(equity), "pnl": str(equity - Decimal(str(args.initial_cash)))})
    if args.isolated_slots:
        pair_summaries = [{"account": k, "cash": str(v["cash"]), "equity": str(v["equity"]), "pnl": str(v["equity"] - v["initial"])} for k, v in sorted(grouped.items())]
    if args.compact_events and compact_counts:
        run_label = f"portfolio_pair:{'isolated' if args.isolated_slots else 'shared'}:w{args.window}:h{args.horizon}:x{args.exclude_last_bars}"
        for (raw_pair, branch_name, symbol), count in compact_counts.items():
            db.insert_backtest_aggregate(settings.db_path, run_label=run_label, branch=branch_name, symbol=symbol, metric="compact_hold_count", value=count, context={"pair": raw_pair})
    print_json({"done": True, "isolated_slots": args.isolated_slots, "compact_events": args.compact_events, "compact_skipped": compact_skipped, "outputs_tail": outputs[-12:], "pair_summaries": pair_summaries, "slot_summaries": slot_summaries[-12:], "summary": db.summary(settings.db_path)})

def cmd_select_best_branches(args) -> None:
    settings = Settings.from_env()
    results = db.update_strategy_registry_from_losses(settings.db_path, min_events=args.min_events)
    print_json({"selected": results, "registry": db.strategy_registry(settings.db_path), "summary": db.summary(settings.db_path)})

def cmd_screen_low_kr(args) -> None:
    settings = Settings.from_env()
    db.init_db(settings.db_path)
    client = TossInvestClient(settings)
    seed_rows = load_seed_csv(args.seed_csv, limit=args.seed_limit)
    result = screen_low_price_candidates(
        client,
        seed_rows=seed_rows,
        max_price=Decimal(str(args.max_price)),
        six_bucket=Decimal(str(args.six_bucket)),
        four_bucket=Decimal(str(args.four_bucket)),
        max_candidates=args.max_candidates,
        fetch_candles=not args.no_candles,
        fetch_news=not args.no_news,
        news_limit=args.news_limit,
        exclude_inverse_leverage=not args.allow_inverse_leverage,
    )
    print_json(result)

def cmd_news_cycle(args) -> None:
    settings = Settings.from_env()
    db.init_db(settings.db_path)
    hub = NewsHub()
    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    queries = [q.strip() for q in args.queries.split("|") if q.strip()]
    if args.max_queries > 0:
        queries = queries[: args.max_queries]
    results = []
    for provider in providers:
        for query in queries:
            try:
                if provider == "naver":
                    items = hub.naver_news(query, display=args.limit)
                elif provider == "marketaux":
                    items = hub.marketaux_news(query, limit=min(args.limit, 3), language=args.language)
                elif provider == "finnhub":
                    items = hub.finnhub_market_news(category=args.finnhub_category)[: args.limit]
                elif provider == "alphavantage":
                    items = hub.alphavantage_news(tickers=args.alpha_tickers, limit=min(args.limit, 5))
                else:
                    results.append({"provider": provider, "query": query, "error": "unknown provider"})
                    continue
                count = db.insert_news_items(settings.db_path, query, [item.as_dict() for item in items])
                results.append({"provider": provider, "query": query, "inserted": count, "titles": [item.title for item in items[:3]]})
            except Exception as exc:
                results.append({"provider": provider, "query": query, "error": str(exc)})
            if args.sleep_seconds > 0:
                time.sleep(args.sleep_seconds)
    print_json({"results": results, "summary": db.summary(settings.db_path)})

def cmd_seed_price(args) -> None:
    settings = Settings.from_env()
    db.init_db(settings.db_path)
    for raw_price in args.prices.split(","):
        item = {
            "symbol": args.symbol,
            "timestamp": db.utc_now(),
            "lastPrice": raw_price.strip(),
            "currency": "KRW",
        }
        db.insert_price(settings.db_path, item, source="manual")
    print_json({"ok": True, "summary": db.summary(settings.db_path)})


def cmd_paper_tick(args) -> None:
    settings = Settings.from_env()
    broker = PaperBroker(settings.db_path, initial_cash_krw=Decimal(str(args.initial_cash)))
    signal = decide_from_recent_prices(settings.db_path, args.symbol, Decimal(str(args.trade_cash)))
    execution = broker.execute_signal(signal)
    print_json({"signal": signal.__dict__, "execution": execution, "summary": db.summary(settings.db_path)})


def cmd_order_dry_run(args) -> None:
    settings = replace(Settings.from_env(), dry_run=True, live_trading=False)
    client = TossInvestClient(settings)
    payload = {
        "clientOrderId": args.client_order_id,
        "symbol": args.symbol,
        "side": args.side,
        "orderType": "LIMIT",
        "quantity": str(args.quantity),
        "price": str(args.price),
    }
    print_json(client.create_order(str(args.account_seq), payload))


def _read_json_or_none(path: str) -> dict | None:
    p = Path(path)
    if not p.exists():
        return None
    return json.loads(p.read_text())


def _append_jsonl(path: str, row: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def cmd_order_live_send(args) -> None:
    """Separate live-order path. Default is review-only; real send is gated."""
    if args.side != "BUY":
        print_json({"ok": False, "order_sent": False, "errors": ["only BUY candidate entry is implemented; SELL requires a separate holdings/exit gate"]})
        raise SystemExit(2)

    data = json.loads(Path(args.path).read_text())
    candidates = data.get("candidates", [])
    if not candidates:
        print_json({"ok": False, "order_sent": False, "errors": ["no candidates"]})
        raise SystemExit(2)
    try:
        candidate = candidates[args.candidate_index]
    except IndexError:
        print_json({"ok": False, "order_sent": False, "errors": [f"candidate index out of range: {args.candidate_index}"]})
        raise SystemExit(2)

    stress_report = _read_json_or_none(args.stress_path) if args.require_stress_ok else None
    validation = validate_candidate_for_live(
        data,
        candidate,
        require_spread_ok=True,
        require_observation_ok=True,
        require_stress_ok=args.require_stress_ok,
        require_edge_ok=True,
        stress_report=stress_report,
    )
    extra_errors: list[str] = []
    if args.candidate_name and candidate.get("name") != args.candidate_name:
        extra_errors.append("candidate_name_mismatch")
    if args.candidate_fingerprint and validation.fingerprint != args.candidate_fingerprint:
        extra_errors.append("candidate_fingerprint_mismatch")

    base_report = {
        "mode": "live_order_review_or_send",
        "ok": validation.ok and not extra_errors,
        "order_sent": False,
        "candidate_name": candidate.get("name"),
        "candidate_pair": candidate.get("pair"),
        "candidate_fingerprint": validation.fingerprint,
        "required_confirm": validation.required_confirm,
        "validation_errors": validation.errors + extra_errors,
        "validation_warnings": validation.warnings,
        "live_safety": {
            "default_is_plan_only": True,
            "really_send_required": True,
            "exact_confirm_required": True,
            "env_required": {"TOSS_DRY_RUN": "false", "TOSS_LIVE_TRADING": "true"},
        },
    }
    if validation.errors or extra_errors:
        print_json(base_report)
        raise SystemExit(2)

    settings = Settings.from_env()
    client = TossInvestClient(settings)
    orderbooks: dict[str, dict] = {}
    for symbol, _cash in parse_pair_slots(candidate.get("pair", "")):
        orderbooks[symbol] = client.get_orderbook(symbol)
    ob_errors, ob_warnings, ob_details = validate_fresh_orderbooks(
        candidate,
        orderbooks,
        max_stale_ms=args.max_stale_ms,
        market_impact_levels=args.market_impact_levels,
    )
    if ob_errors:
        base_report.update({"ok": False, "fresh_orderbook_errors": ob_errors, "fresh_orderbook_warnings": ob_warnings, "fresh_orderbook": ob_details})
        print_json(base_report)
        raise SystemExit(2)

    payloads = build_buy_limit_payloads(
        candidate,
        orderbooks,
        client_order_id_prefix=args.client_order_id_prefix,
        limit_buffer_bps=Decimal(str(args.limit_buffer_bps)),
    )
    send_payloads = [
        {k: v for k, v in payload.items() if k in {"clientOrderId", "symbol", "side", "orderType", "quantity", "price"}}
        for payload in payloads
    ]
    base_report.update({
        "ok": True,
        "fresh_orderbook_warnings": ob_warnings,
        "fresh_orderbook": ob_details,
        "payloads": payloads,
    })

    if not args.really_send:
        base_report.update({"plan_only": True, "next_step": "review payloads; rerun with --really-send and exact --confirm only after human approval"})
        print_json(base_report)
        return

    if args.confirm != required_confirmation(candidate):
        base_report.update({"ok": False, "validation_errors": ["confirm_string_mismatch"], "plan_only": False})
        print_json(base_report)
        raise SystemExit(2)
    if len(send_payloads) > 1 and not args.allow_multi_leg:
        base_report.update({"ok": False, "validation_errors": ["multi_leg_live_send_requires_--allow-multi-leg"]})
        print_json(base_report)
        raise SystemExit(2)
    if settings.dry_run or not settings.live_trading:
        base_report.update({"ok": False, "validation_errors": ["env_not_live:TOSS_DRY_RUN=false_and_TOSS_LIVE_TRADING=true_required"]})
        print_json(base_report)
        raise SystemExit(2)
    account_seq = args.account_seq or settings.account_seq
    if not account_seq:
        base_report.update({"ok": False, "validation_errors": ["account_seq_required"]})
        print_json(base_report)
        raise SystemExit(2)

    results = []
    for payload in send_payloads:
        results.append({"payload": payload, "result": client.create_order(str(account_seq), payload)})
    audit = {
        "created_at": db.utc_now(),
        "candidate_fingerprint": validation.fingerprint,
        "candidate_name": candidate.get("name"),
        "candidate_pair": candidate.get("pair"),
        "payloads": send_payloads,
        "results": redact_order_result(results),
    }
    _append_jsonl(args.approval_log, audit)
    base_report.update({"ok": True, "order_sent": True, "results": redact_order_result(results), "approval_log": args.approval_log})
    print_json(base_report)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Toss auto-trader lab")
    sub = parser.add_subparsers(required=True)

    p = sub.add_parser("init-db")
    p.add_argument("--initial-cash", default="10000")
    p.set_defaults(func=cmd_init_db)

    p = sub.add_parser("summary")
    p.set_defaults(func=cmd_summary)

    p = sub.add_parser("api-smoke", help="read-only token/accounts/prices smoke test")
    p.add_argument("--symbols", default="005930")
    p.set_defaults(func=cmd_api_smoke)

    p = sub.add_parser("collect-price")
    p.add_argument("--symbols", required=True)
    p.set_defaults(func=cmd_collect_price)

    p = sub.add_parser("collect-macro")
    p.add_argument("--base-currency", default="USD")
    p.add_argument("--quote-currency", default="KRW")
    p.set_defaults(func=cmd_collect_macro)

    p = sub.add_parser("orderbook", help="read-only best bid/ask spread check")
    p.add_argument("--symbol", required=True)
    p.add_argument("--raw", action="store_true")
    p.set_defaults(func=cmd_orderbook)

    p = sub.add_parser("candles")
    p.add_argument("--symbol", required=True)
    p.add_argument("--interval", choices=["1m", "1d"], default="1d")
    p.add_argument("--count", type=int, default=100)
    p.add_argument("--persist-snapshot", action="store_true")
    p.set_defaults(func=cmd_candles)

    p = sub.add_parser("cache-candles")
    p.add_argument("--symbols", required=True)
    p.add_argument("--interval", choices=["1m", "1d"], default="1d")
    p.add_argument("--count", type=int, default=200)
    p.add_argument("--pages", type=int, default=1)
    p.add_argument("--before")
    p.add_argument("--sleep-seconds", type=float, default=1.0)
    p.add_argument("--unadjusted", action="store_true")
    p.set_defaults(func=cmd_cache_candles)

    p = sub.add_parser("historical-backtest")
    p.add_argument("--symbols", required=True)
    p.add_argument("--config", default="config.example.yaml")
    p.add_argument("--interval", choices=["1m", "1d"], default="1d")
    p.add_argument("--window", type=int, default=80)
    p.add_argument("--horizon", type=int, default=1)
    p.add_argument("--max-bars", type=int, default=0)
    p.add_argument("--trade-cash", default="300000")
    p.add_argument("--initial-cash", default="1000000")
    p.add_argument("--max-order", default="300000")
    p.add_argument("--status-every", type=int, default=100)
    p.add_argument("--historical-daily-max-orders", type=int, default=1000000)
    p.add_argument("--branches", default="conservative_guarded,balanced_momentum_v2,balanced_momentum,technical_aggressive,observation_first")
    p.set_defaults(func=cmd_historical_backtest)

    p = sub.add_parser("agent-tick")
    p.add_argument("--symbols", required=True)
    p.add_argument("--config", default="config.example.yaml")
    p.add_argument("--interval", choices=["1m", "1d"], default="1d")
    p.add_argument("--count", type=int, default=100)
    p.add_argument("--trade-cash", default="1000")
    p.add_argument("--market-country", choices=["KR", "US"], default="KR")
    p.add_argument("--respect-market-hours", action="store_true", default=True)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_agent_tick)

    p = sub.add_parser("learning-sim")
    p.add_argument("--symbol", default="SIM001")
    p.add_argument("--config", default="config.example.yaml")
    p.add_argument("--iterations", type=int, default=20)
    p.add_argument("--sleep-seconds", type=float, default=0)
    p.add_argument("--status-every", type=int, default=3)
    p.add_argument("--base-price", default="1000")
    p.add_argument("--trade-cash", default="3000")
    p.add_argument("--branches", default="conservative_guarded,balanced_momentum,technical_aggressive,observation_first")
    p.set_defaults(func=cmd_learning_sim)


    p = sub.add_parser("portfolio-pair-backtest")
    p.add_argument("--pairs", required=True, help="comma separated pairs like 336570:6000+462860:4000")
    p.add_argument("--config", default="config.example.yaml")
    p.add_argument("--interval", choices=["1m", "1d"], default="1d")
    p.add_argument("--window", type=int, default=60)
    p.add_argument("--horizon", type=int, default=1)
    p.add_argument("--max-bars", type=int, default=180)
    p.add_argument("--initial-cash", default="10000")
    p.add_argument("--max-order", default="6000")
    p.add_argument("--status-every", type=int, default=1000)
    p.add_argument("--historical-daily-max-orders", type=int, default=1000000)
    p.add_argument("--branches", default="fee_aware_momentum,balanced_momentum_v2,balanced_momentum,technical_aggressive,ultra_conservative,conservative_guarded,observation_first")
    p.add_argument("--isolated-slots", action="store_true", help="run each symbol slot in its own sub-account, then aggregate pair equity")
    p.add_argument("--compact-events", action="store_true", help="skip logging ordinary HOLD events to reduce backtest DB size")
    p.add_argument("--exclude-last-bars", type=int, default=0, help="walk-forward: drop the latest N aligned bars before applying max-bars")
    p.set_defaults(func=cmd_portfolio_pair_backtest)

    p = sub.add_parser("select-best-branches")
    p.add_argument("--min-events", type=int, default=20)
    p.set_defaults(func=cmd_select_best_branches)

    p = sub.add_parser("screen-low-kr")
    p.add_argument("--seed-csv", default="data/naver_low_price_candidates.csv")
    p.add_argument("--seed-limit", type=int, default=20)
    p.add_argument("--max-price", default="10000")
    p.add_argument("--six-bucket", default="6000")
    p.add_argument("--four-bucket", default="4000")
    p.add_argument("--max-candidates", type=int, default=12)
    p.add_argument("--news-limit", type=int, default=2)
    p.add_argument("--no-candles", action="store_true")
    p.add_argument("--no-news", action="store_true")
    p.add_argument("--allow-inverse-leverage", action="store_true")
    p.set_defaults(func=cmd_screen_low_kr)

    p = sub.add_parser("news-cycle")
    p.add_argument("--providers", default="naver,marketaux,finnhub")
    p.add_argument("--queries", default="KOSPI market macro economy|Samsung Electronics stock Korea market")
    p.add_argument("--limit", type=int, default=3)
    p.add_argument("--max-queries", type=int, default=0, help="cap queries per run; 0 means all")
    p.add_argument("--sleep-seconds", type=float, default=0.0, help="sleep between provider/query calls to avoid 429")
    p.add_argument("--language", default="en")
    p.add_argument("--finnhub-category", default="general")
    p.add_argument("--alpha-tickers", default="AAPL,MSFT,NVDA")
    p.set_defaults(func=cmd_news_cycle)

    p = sub.add_parser("account-snapshot")
    p.add_argument("--account-seq")
    p.add_argument("--currency", default="KRW")
    p.set_defaults(func=cmd_account_snapshot)

    p = sub.add_parser("loop", help="collect prices and run paper decisions repeatedly")
    p.add_argument("--symbols", required=True)
    p.add_argument("--iterations", type=int, default=1)
    p.add_argument("--sleep-seconds", type=float, default=0)
    p.add_argument("--trade-cash", default="1000")
    p.add_argument("--initial-cash", default="10000")
    p.add_argument("--offline", action="store_true", help="skip API collection; use existing DB prices")
    p.add_argument("--collect-macro", action="store_true", help="also collect USD/KRW exchange rate")
    p.set_defaults(func=cmd_loop)

    p = sub.add_parser("seed-price", help="insert manual prices for offline paper testing")
    p.add_argument("--symbol", required=True)
    p.add_argument("--prices", required=True, help="comma-separated prices")
    p.set_defaults(func=cmd_seed_price)

    p = sub.add_parser("paper-tick")
    p.add_argument("--symbol", required=True)
    p.add_argument("--trade-cash", default="1000")
    p.add_argument("--initial-cash", default="10000")
    p.set_defaults(func=cmd_paper_tick)

    p = sub.add_parser("order-dry-run", help="build order payload; does not send while DRY_RUN=true")
    p.add_argument("--account-seq", required=True)
    p.add_argument("--client-order-id", required=True)
    p.add_argument("--symbol", required=True)
    p.add_argument("--side", choices=["BUY", "SELL"], required=True)
    p.add_argument("--quantity", required=True)
    p.add_argument("--price", required=True)
    p.set_defaults(func=cmd_order_dry_run)

    p = sub.add_parser("order-live-send", help="review or send a gated live BUY candidate; default is plan-only")
    p.add_argument("--path", default="data/live_paper_candidates.json")
    p.add_argument("--candidate-index", type=int, default=0)
    p.add_argument("--candidate-name", default="")
    p.add_argument("--candidate-fingerprint", default="")
    p.add_argument("--stress-path", default="data/stress_test_latest.json")
    p.add_argument("--no-require-stress-ok", dest="require_stress_ok", action="store_false")
    p.add_argument("--side", choices=["BUY", "SELL"], default="BUY")
    p.add_argument("--account-seq")
    p.add_argument("--client-order-id-prefix", default="tossbot")
    p.add_argument("--limit-buffer-bps", default="0")
    p.add_argument("--max-stale-ms", type=int, default=500)
    p.add_argument("--market-impact-levels", type=int, default=5)
    p.add_argument("--really-send", action="store_true")
    p.add_argument("--confirm", default="")
    p.add_argument("--allow-multi-leg", action="store_true")
    p.add_argument("--approval-log", default="data/live_order_approval_log.jsonl")
    p.set_defaults(func=cmd_order_live_send, require_stress_ok=True)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
