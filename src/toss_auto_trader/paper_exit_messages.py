from __future__ import annotations

from toss_auto_trader.paper_exit_models import PaperEvent


def event_float(event: PaperEvent, key: str) -> float:
    raw = event.get(key)
    try:
        return float(str(raw).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def format_paper_event(event: PaperEvent) -> str | None:
    event_name = str(event.get("event") or "")
    symbol = str(event.get("symbol") or "")
    name = str(event.get("name") or symbol)
    match event_name:
        case "paper_reentry_threshold":
            return (
                f"  📝 [paper-only] [{symbol}] {name} 손절 후 추가하락 -{event_float(event, 'drop_pct') * 100.0:.0f}% 도달 "
                f"| 손절매도 기준 {event_float(event, 'base_exit_price'):,.0f}원 "
                f"| 가상진입 {event_float(event, 'paper_entry_price'):,.0f}원 | 실주문 없음"
            )
        case "paper_reentry_outcome":
            return (
                f"  🧾 [paper-only] [{symbol}] {name} 재진입 가설 {event.get('horizon') or ''} 결과 "
                f"| 가상진입 {event_float(event, 'paper_entry_price'):,.0f}원 "
                f"| 평가가 {event_float(event, 'outcome_price'):,.0f}원 "
                f"| 수익률 {event_float(event, 'outcome_return_pct'):+.2f}%"
            )
        case "paper_exit_price_snapshot":
            return (
                f"  🧾 [paper-only] [{symbol}] {name} 매도 후 가격관찰 {event.get('horizon') or ''} "
                f"| 현재 {event_float(event, 'outcome_price'):,.0f}원 "
                f"| 매도가 대비 {event_float(event, 'return_from_exit_pct'):+.2f}% "
                f"| 진입가 대비 {event_float(event, 'return_from_entry_pct'):+.2f}%"
            )
        case "paper_missed_upside_threshold":
            return (
                f"  📝 [paper-only] [{symbol}] {name} 익절 후 추가상승 +{event_float(event, 'rise_pct') * 100.0:.0f}% 도달 "
                f"| 익절매도 기준 {event_float(event, 'base_exit_price'):,.0f}원 "
                f"| 계속 보유 가정 {event_float(event, 'paper_hold_price'):,.0f}원 | 실주문 없음"
            )
        case "paper_missed_upside_outcome":
            return (
                f"  🧾 [paper-only] [{symbol}] {name} 익절 후 추가상승 가설 {event.get('horizon') or ''} 결과 "
                f"| 기준 {event_float(event, 'paper_hold_price'):,.0f}원 "
                f"| 평가가 {event_float(event, 'outcome_price'):,.0f}원 "
                f"| 이후 수익률 {event_float(event, 'outcome_return_pct'):+.2f}%"
            )
        case _:
            return None
