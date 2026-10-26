"""Local search and statistics; no network side effects."""
import math


def search_stocks(rows, query):
    query = "".join(query.split()).casefold()
    return [r for r in rows if not query or query in str(r.get("code", "")).casefold()
            or query in "".join((r.get("name") or "").split()).casefold()]


def market_statistics(rows, field, target):
    groups = {}
    for row in rows:
        name = row.get(field) or "未分类"
        group = groups.setdefault(name, {"分组":name,"股票数":0,"上涨":0,"下跌":0,"平盘":0,"未知":0})
        group["股票数"] += 1
        value = row.get("change_pct")
        valid = isinstance(value, (int, float)) and math.isfinite(value) and row.get("quote_date") == target
        group["未知" if not valid else "上涨" if value > 0 else "下跌" if value < 0 else "平盘"] += 1
    for group in groups.values():
        known = group["股票数"]-group["未知"]
        group["上涨占比 %"] = round(100*group["上涨"]/known, 1) if known else None
    return list(groups.values())
