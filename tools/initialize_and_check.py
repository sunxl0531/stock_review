"""Explicit one-off real-market integration validation. Not run at app startup."""
from pathlib import Path
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from screener.store import Store
from screener.service import Service
from screener.core import Filters, screen

def report(**kwargs):
    print(json.dumps(kwargs, ensure_ascii=True), flush=True)

service = Service(Store(Path(__file__).resolve().parents[1] / "data" / "market.db"))
for board in ("沪市主板", "科创板", "深圳", "北交所"):
    try:
        report(board=board, count=service.refresh_basic("directory", board))
    except Exception as exc:
        report(board=board, error=str(exc))
        if any(k in str(exc).lower() for k in ("429", "403", "quota", "限流")):
            sys.exit(1)
for label, action in [("calendar", lambda: service.refresh_basic("calendar")),
                      ("quotes", lambda: service.refresh_quotes("tencent")),
                      ("suspensions", service.refresh_suspensions),
                      ("history_000001", lambda: service.fetch_history("000001"))]:
    try:
        report(operation=label, count=action())
    except Exception as exc:
        report(operation=label, error=str(exc))
        if any(k in str(exc).lower() for k in ("429", "403", "quota", "限流")):
            sys.exit(1)
rows = service.rows()
result = screen(rows, Filters(), service.store.get("calendar", {}).get("days", []), {}, service.as_of())
report(total=len(rows), matched=sum(r["result"]=="匹配" for r in result),
       unknown=sum(r["result"]=="无法判定" for r in result), as_of=service.as_of())
