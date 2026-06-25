from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path, factory=ClosingConnection)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db(db_path: str) -> None:
    with connect(db_path) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                last_price TEXT NOT NULL,
                currency TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'toss',
                raw_json TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_prices_symbol_time ON prices(symbol, timestamp);

            CREATE TABLE IF NOT EXISTS paper_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                cash_krw TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS paper_positions (
                account_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                quantity TEXT NOT NULL,
                average_price TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (account_id, symbol),
                FOREIGN KEY(account_id) REFERENCES paper_accounts(id)
            );

            CREATE TABLE IF NOT EXISTS paper_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity TEXT NOT NULL,
                price TEXT NOT NULL,
                amount TEXT NOT NULL,
                fee_amount TEXT NOT NULL DEFAULT '0',
                tax_amount TEXT NOT NULL DEFAULT '0',
                status TEXT NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(account_id) REFERENCES paper_accounts(id)
            );

            CREATE TABLE IF NOT EXISTS strategy_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                confidence REAL NOT NULL,
                reason TEXT NOT NULL,
                price TEXT,
                cash_amount TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS decision_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                branch TEXT NOT NULL DEFAULT 'default',
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                execution TEXT NOT NULL,
                reason TEXT NOT NULL,
                confidence REAL NOT NULL,
                price TEXT,
                cash_amount TEXT,
                market_context_json TEXT NOT NULL,
                result_json TEXT NOT NULL,
                outcome_json TEXT,
                loss REAL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_decision_events_symbol_time ON decision_events(symbol, created_at);

            CREATE TABLE IF NOT EXISTS api_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint TEXT NOT NULL,
                params_json TEXT,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS news_context (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                query TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                source TEXT,
                published_at TEXT,
                sentiment REAL,
                summary TEXT,
                raw_json TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_news_context_provider_query_time ON news_context(provider, query, created_at);

            CREATE TABLE IF NOT EXISTS candle_cache (
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                open_price TEXT NOT NULL,
                high_price TEXT NOT NULL,
                low_price TEXT NOT NULL,
                close_price TEXT NOT NULL,
                volume TEXT NOT NULL,
                currency TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                PRIMARY KEY(symbol, interval, timestamp)
            );
            CREATE INDEX IF NOT EXISTS idx_candle_cache_symbol_interval_time ON candle_cache(symbol, interval, timestamp);

            CREATE TABLE IF NOT EXISTS strategy_registry (
                symbol TEXT NOT NULL,
                selected_branch TEXT NOT NULL,
                avg_loss REAL NOT NULL,
                events INTEGER NOT NULL,
                evidence_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(symbol)
            );

            CREATE TABLE IF NOT EXISTS backtest_aggregates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_label TEXT NOT NULL,
                branch TEXT NOT NULL,
                symbol TEXT NOT NULL,
                metric TEXT NOT NULL,
                value TEXT NOT NULL,
                context_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_backtest_aggregates_run ON backtest_aggregates(run_label, branch, symbol, metric);
            """
        )
        paper_order_fee_cols = {row[1] for row in con.execute("PRAGMA table_info(paper_orders)").fetchall()}
        if "fee_amount" not in paper_order_fee_cols:
            con.execute("ALTER TABLE paper_orders ADD COLUMN fee_amount TEXT NOT NULL DEFAULT '0'")
        if "tax_amount" not in paper_order_fee_cols:
            con.execute("ALTER TABLE paper_orders ADD COLUMN tax_amount TEXT NOT NULL DEFAULT '0'")
        decision_cols = {row[1] for row in con.execute("PRAGMA table_info(decision_events)").fetchall()}
        if "branch" not in decision_cols:
            con.execute("ALTER TABLE decision_events ADD COLUMN branch TEXT NOT NULL DEFAULT 'default'")
        if "outcome_json" not in decision_cols:
            con.execute("ALTER TABLE decision_events ADD COLUMN outcome_json TEXT")
        if "loss" not in decision_cols:
            con.execute("ALTER TABLE decision_events ADD COLUMN loss REAL")
        con.execute("CREATE INDEX IF NOT EXISTS idx_decision_events_branch_time ON decision_events(branch, created_at)")


def ensure_paper_account(db_path: str, name: str = "default", initial_cash_krw: Decimal = Decimal("10000")) -> int:
    init_db(db_path)
    with connect(db_path) as con:
        row = con.execute("SELECT id FROM paper_accounts WHERE name = ?", (name,)).fetchone()
        if row:
            return int(row["id"])
        cur = con.execute(
            "INSERT INTO paper_accounts(name, cash_krw, created_at) VALUES (?, ?, ?)",
            (name, str(initial_cash_krw), utc_now()),
        )
        return int(cur.lastrowid)


def insert_price(db_path: str, item: dict[str, Any], source: str = "toss") -> None:
    with connect(db_path) as con:
        con.execute(
            """INSERT INTO prices(symbol, timestamp, last_price, currency, source, raw_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                item["symbol"],
                item.get("timestamp") or utc_now(),
                str(item["lastPrice"]),
                item.get("currency", "KRW"),
                source,
                json.dumps(item, ensure_ascii=False),
                utc_now(),
            ),
        )
        # Lightweight migrations for DBs created before outcome/branch tracking.
        cols = {row[1] for row in con.execute("PRAGMA table_info(decision_events)").fetchall()}
        if "branch" not in cols:
            con.execute("ALTER TABLE decision_events ADD COLUMN branch TEXT NOT NULL DEFAULT 'default'")
        if "outcome_json" not in cols:
            con.execute("ALTER TABLE decision_events ADD COLUMN outcome_json TEXT")
        if "loss" not in cols:
            con.execute("ALTER TABLE decision_events ADD COLUMN loss REAL")


def _redact_sensitive(obj: Any) -> Any:
    if isinstance(obj, dict):
        redacted = {}
        for key, value in obj.items():
            if key.lower() in {"accountno", "account_no"}:
                text = str(value)
                redacted[key] = "***" + text[-4:] if len(text) >= 4 else "***"
            else:
                redacted[key] = _redact_sensitive(value)
        return redacted
    if isinstance(obj, list):
        return [_redact_sensitive(item) for item in obj]
    return obj


def insert_snapshot(db_path: str, endpoint: str, response: dict[str, Any], params: Optional[dict[str, Any]] = None) -> None:
    safe_response = _redact_sensitive(response)
    safe_params = _redact_sensitive(params or {})
    with connect(db_path) as con:
        con.execute(
            "INSERT INTO api_snapshots(endpoint, params_json, response_json, created_at) VALUES (?, ?, ?, ?)",
            (endpoint, json.dumps(safe_params, ensure_ascii=False), json.dumps(safe_response, ensure_ascii=False), utc_now()),
        )


def recent_prices(db_path: str, symbol: str, limit: int = 20) -> list[Decimal]:
    with connect(db_path) as con:
        rows = con.execute(
            "SELECT last_price FROM prices WHERE symbol = ? ORDER BY timestamp DESC, id DESC LIMIT ?",
            (symbol, limit),
        ).fetchall()
    return [Decimal(str(r["last_price"])) for r in reversed(rows)]


def log_decision(db_path: str, symbol: str, side: str, confidence: float, reason: str, price: Any, cash_amount: Any) -> None:
    with connect(db_path) as con:
        con.execute(
            """INSERT INTO strategy_decisions(symbol, side, confidence, reason, price, cash_amount, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (symbol, side, confidence, reason, str(price) if price is not None else None, str(cash_amount), utc_now()),
        )


def log_decision_event(
    db_path: str,
    *,
    symbol: str,
    side: str,
    execution: str,
    reason: str,
    confidence: float,
    price: Any,
    cash_amount: Any,
    market_context: dict[str, Any],
    result: dict[str, Any],
    branch: str = "default",
) -> int:
    with connect(db_path) as con:
        cur = con.execute(
            """INSERT INTO decision_events(
                   branch, symbol, side, execution, reason, confidence, price, cash_amount,
                   market_context_json, result_json, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                branch,
                symbol,
                side,
                execution,
                reason,
                confidence,
                str(price) if price is not None else None,
                str(cash_amount),
                json.dumps(_redact_sensitive(market_context), ensure_ascii=False),
                json.dumps(_redact_sensitive(result), ensure_ascii=False),
                utc_now(),
            ),
        )
        return int(cur.lastrowid)


def update_decision_outcome(db_path: str, decision_event_id: int, outcome: dict[str, Any], loss: float) -> None:
    with connect(db_path) as con:
        con.execute(
            "UPDATE decision_events SET outcome_json = ?, loss = ? WHERE id = ?",
            (json.dumps(_redact_sensitive(outcome), ensure_ascii=False), float(loss), decision_event_id),
        )




def latest_news_items(db_path: str, limit: int = 10) -> list[dict[str, Any]]:
    init_db(db_path)
    with connect(db_path) as con:
        rows = con.execute(
            "SELECT provider, query, title, url, source, published_at, sentiment, summary, created_at FROM news_context ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_strategy_registry_from_losses(db_path: str, min_events: int = 20) -> list[dict[str, Any]]:
    init_db(db_path)
    with connect(db_path) as con:
        rows = con.execute(
            """SELECT branch, COUNT(*) AS events, AVG(loss) AS avg_loss
               FROM decision_events
               WHERE loss IS NOT NULL AND branch LIKE 'hist:%'
               GROUP BY branch
               HAVING events >= ?
               ORDER BY avg_loss ASC""",
            (min_events,),
        ).fetchall()
        best_by_symbol: dict[str, dict[str, Any]] = {}
        for r in rows:
            branch = r["branch"]
            parts = branch.split(":", 2)
            if len(parts) != 3:
                continue
            _, symbol, strategy = parts
            item = {"symbol": symbol, "selected_branch": strategy, "avg_loss": float(r["avg_loss"]), "events": int(r["events"]), "source_branch": branch}
            if symbol not in best_by_symbol or item["avg_loss"] < best_by_symbol[symbol]["avg_loss"]:
                best_by_symbol[symbol] = item
        for symbol, item in best_by_symbol.items():
            con.execute(
                """INSERT INTO strategy_registry(symbol, selected_branch, avg_loss, events, evidence_json, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(symbol) DO UPDATE SET
                     selected_branch=excluded.selected_branch,
                     avg_loss=excluded.avg_loss,
                     events=excluded.events,
                     evidence_json=excluded.evidence_json,
                     updated_at=excluded.updated_at""",
                (symbol, item["selected_branch"], item["avg_loss"], item["events"], json.dumps(item, ensure_ascii=False), utc_now()),
            )
        return list(best_by_symbol.values())


def strategy_registry(db_path: str) -> list[dict[str, Any]]:
    init_db(db_path)
    with connect(db_path) as con:
        rows = con.execute("SELECT * FROM strategy_registry ORDER BY avg_loss ASC").fetchall()
    return [dict(r) for r in rows]

def insert_candles(db_path: str, symbol: str, interval: str, candles: list[dict[str, Any]]) -> int:
    init_db(db_path)
    inserted = 0
    with connect(db_path) as con:
        for c in candles:
            ts = c.get("timestamp")
            if not ts:
                continue
            cur = con.execute(
                """INSERT OR REPLACE INTO candle_cache(
                       symbol, interval, timestamp, open_price, high_price, low_price, close_price, volume, currency, raw_json, fetched_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    symbol,
                    interval,
                    ts,
                    str(c.get("openPrice", c.get("open_price", "0"))),
                    str(c.get("highPrice", c.get("high_price", "0"))),
                    str(c.get("lowPrice", c.get("low_price", "0"))),
                    str(c.get("closePrice", c.get("close_price", "0"))),
                    str(c.get("volume", "0")),
                    c.get("currency", "KRW"),
                    json.dumps(_redact_sensitive(c), ensure_ascii=False),
                    utc_now(),
                ),
            )
            inserted += cur.rowcount
    return inserted


def cached_candles(db_path: str, symbol: str, interval: str = "1d", limit: int | None = None, ascending: bool = True) -> list[dict[str, Any]]:
    init_db(db_path)
    order = "ASC" if ascending else "DESC"
    sql = f"SELECT * FROM candle_cache WHERE symbol = ? AND interval = ? ORDER BY timestamp {order}"
    params: list[Any] = [symbol, interval]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    with connect(db_path) as con:
        rows = con.execute(sql, params).fetchall()
    return [
        {
            "timestamp": r["timestamp"],
            "openPrice": r["open_price"],
            "highPrice": r["high_price"],
            "lowPrice": r["low_price"],
            "closePrice": r["close_price"],
            "volume": r["volume"],
            "currency": r["currency"],
        }
        for r in rows
    ]


def candle_cache_count(db_path: str, symbol: str | None = None, interval: str | None = None) -> int:
    init_db(db_path)
    where = []
    params: list[Any] = []
    if symbol:
        where.append("symbol = ?"); params.append(symbol)
    if interval:
        where.append("interval = ?"); params.append(interval)
    sql = "SELECT COUNT(*) AS c FROM candle_cache" + (" WHERE " + " AND ".join(where) if where else "")
    with connect(db_path) as con:
        return int(con.execute(sql, params).fetchone()["c"])

def insert_news_items(db_path: str, query: str, items: list[dict[str, Any]]) -> int:
    init_db(db_path)
    inserted = 0
    with connect(db_path) as con:
        for item in items:
            provider = item.get("provider", "unknown")
            title = item.get("title", "")
            url = item.get("url", "")
            published_at = item.get("published_at")
            existing = con.execute(
                """SELECT id FROM news_context
                   WHERE provider = ? AND query = ? AND title = ? AND url = ?
                     AND COALESCE(published_at, '') = COALESCE(?, '')
                   LIMIT 1""",
                (provider, query, title, url, published_at),
            ).fetchone()
            if existing:
                continue
            con.execute(
                """INSERT INTO news_context(
                       provider, query, title, url, source, published_at, sentiment, summary, raw_json, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    provider,
                    query,
                    title,
                    url,
                    item.get("source"),
                    published_at,
                    item.get("sentiment"),
                    item.get("summary"),
                    json.dumps(_redact_sensitive(item.get("raw", {})), ensure_ascii=False),
                    utc_now(),
                ),
            )
            inserted += 1
    return inserted


def prune_prices(db_path: str, keep_per_symbol: int = 500) -> int:
    # Keep prices as a bounded cache only. Long-term learning should use decision_events.
    with connect(db_path) as con:
        cur = con.execute(
            """DELETE FROM prices
               WHERE id IN (
                 SELECT id FROM (
                   SELECT id, ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY timestamp DESC, id DESC) AS rn
                   FROM prices
                 ) WHERE rn > ?
               )""",
            (keep_per_symbol,),
        )
        return int(cur.rowcount if cur.rowcount is not None else 0)


def summary(db_path: str) -> dict[str, Any]:
    init_db(db_path)
    with connect(db_path) as con:
        account = con.execute("SELECT * FROM paper_accounts WHERE name = 'default'").fetchone()
        price_count = con.execute("SELECT COUNT(*) AS c FROM prices").fetchone()["c"]
        decision_count = con.execute("SELECT COUNT(*) AS c FROM strategy_decisions").fetchone()["c"]
        decision_event_count = con.execute("SELECT COUNT(*) AS c FROM decision_events").fetchone()["c"]
        order_count = con.execute("SELECT COUNT(*) AS c FROM paper_orders").fetchone()["c"]
        news_count = con.execute("SELECT COUNT(*) AS c FROM news_context").fetchone()["c"]
        candle_count = con.execute("SELECT COUNT(*) AS c FROM candle_cache").fetchone()["c"]
        registry_count = con.execute("SELECT COUNT(*) AS c FROM strategy_registry").fetchone()["c"]
        positions = [dict(r) for r in con.execute("SELECT * FROM paper_positions").fetchall()]
        branch_losses = [dict(r) for r in con.execute(
            "SELECT branch, COUNT(*) AS events, AVG(loss) AS avg_loss FROM decision_events WHERE loss IS NOT NULL GROUP BY branch ORDER BY avg_loss ASC"
        ).fetchall()]
    return {
        "account": dict(account) if account else None,
        "price_count": price_count,
        "decision_count": decision_count,
        "decision_event_count": decision_event_count,
        "paper_order_count": order_count,
        "news_count": news_count,
        "candle_count": candle_count,
        "strategy_registry_count": registry_count,
        "positions": positions,
        "branch_losses": branch_losses,
    }


def insert_backtest_aggregate(db_path: str, *, run_label: str, branch: str, symbol: str, metric: str, value: Any, context: dict[str, Any] | None = None) -> None:
    init_db(db_path)
    with connect(db_path) as con:
        con.execute(
            """INSERT INTO backtest_aggregates(run_label, branch, symbol, metric, value, context_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (run_label, branch, symbol, metric, str(value), json.dumps(context or {}, ensure_ascii=False), utc_now()),
        )
