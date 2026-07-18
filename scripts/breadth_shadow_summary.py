#!/usr/bin/env python3
"""Summarize paper-only breadth4 observations without account or order data."""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


DEFAULT_LOG = Path("logs") / "simple_gap_breadth_shadow.jsonl"


def load_events(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    events = []
    for line in target.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("date"):
            events.append(event)
    return events


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    by_date: dict[str, dict[str, dict[str, Any]]] = {}
    for event in events:
        date = str(event["date"])
        bucket = by_date.setdefault(date, {})
        if event.get("event") == "breadth_shadow_open_snapshot":
            bucket["open"] = event
        elif event.get("event") == "breadth_shadow_official_reconciliation":
            bucket["official"] = event
    paired = []
    for date, bucket in sorted(by_date.items()):
        opened = bucket.get("open") or {}
        official = bucket.get("official") or {}
        if opened.get("provisional_gap5_count") is None or official.get("official_gap5_count") is None:
            continue
        provisional_count = int(opened["provisional_gap5_count"])
        official_count = int(official["official_gap5_count"])
        threshold = int(official.get("threshold") or opened.get("threshold") or 4)
        paired.append({
            "date": date,
            "provisional_count": provisional_count,
            "official_count": official_count,
            "count_error": provisional_count - official_count,
            "provisional_pass": provisional_count >= threshold,
            "official_pass": official_count >= threshold,
            "decision_match": (provisional_count >= threshold) == (official_count >= threshold),
        })
    errors = [row["count_error"] for row in paired]
    return {
        "open_observation_dates": sum("open" in bucket for bucket in by_date.values()),
        "official_reconciliation_dates": sum("official" in bucket for bucket in by_date.values()),
        "paired_dates": len(paired),
        "decision_match_rate": (
            sum(row["decision_match"] for row in paired) / len(paired) if paired else None
        ),
        "mean_count_error": statistics.mean(errors) if errors else None,
        "median_count_error": statistics.median(errors) if errors else None,
        "rows": paired,
    }


def render(summary: dict[str, Any]) -> str:
    match_rate = summary["decision_match_rate"]
    match = "표본 없음" if match_rate is None else f"{match_rate * 100:.1f}%"
    mean_error = summary["mean_count_error"]
    median_error = summary["median_count_error"]
    lines = [
        "# Breadth4 Shadow Summary",
        "",
        f"- 09:01 관찰일: `{summary['open_observation_dates']}`",
        f"- 사후확정일: `{summary['official_reconciliation_dates']}`",
        f"- 짝지어진 날짜: `{summary['paired_dates']}`",
        f"- 통과/미달 판정 일치율: `{match}`",
        f"- 평균 개수 오차(09:01-공식): `{mean_error if mean_error is not None else '표본 없음'}`",
        f"- 중앙값 개수 오차: `{median_error if median_error is not None else '표본 없음'}`",
        "",
        "| 날짜 | 09:01 현재가 | 공식 시가 | 오차 | 판정 일치 |",
        "|---|---:|---:|---:|---|",
    ]
    for row in summary["rows"]:
        lines.append(
            f"| {row['date']} | {row['provisional_count']} | {row['official_count']} | "
            f"{row['count_error']:+d} | {'예' if row['decision_match'] else '아니오'} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize breadth4 paper-only observations")
    parser.add_argument("--log-path", default=str(DEFAULT_LOG))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    summary = summarize(load_events(args.log_path))
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(render(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
