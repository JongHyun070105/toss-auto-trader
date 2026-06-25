# Publish manifest

This GitHub copy intentionally includes source, scripts, tests, docs, and safe example config only.

Excluded from publication:

- `.env` and any real credentials
- `data/` runtime/backtest DBs and generated market data
- `logs/`
- `graphify-out/` generated local knowledge graph
- local state file `docs/ACTIVE_STATE_COMPACT.md`
- virtualenv/cache/build artifacts

Safety defaults remain `TOSS_DRY_RUN=true` and `TOSS_LIVE_TRADING=false`.
