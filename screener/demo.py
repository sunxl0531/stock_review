"""Clearly labelled synthetic data, kept in a separate database."""
from datetime import date, timedelta
from .core import BOARDS

def seed(store):
    if store.get("quotes"):
        return
    today = date(2026, 10, 19)
    days = [(today - timedelta(days=i)).isoformat() for i in range(200, -1, -1)
            if (today - timedelta(days=i)).weekday() < 5]
    store.put("calendar", {"days": days})
    dirs, quotes = {b: [] for b in ("沪市主板", "科创板", "深圳", "北交所")}, []
    for i, board in enumerate(BOARDS):
        for j in range(5):
            code = ("600", "000", "300", "688", "920")[i] + f"{j+1:03d}"
            price = round(12 + i * 5 + j * 0.7, 2)
            row = {"code": code, "name": ("*ST" if j == 4 else "") + f"演示股票{i+1}-{j+1}",
                   "board": board, "listed": days[0] if j != 3 else days[-30]}
            dirs["深圳" if board in ("深市主板", "创业板") else board].append(row)
            quotes.append(row | {"price": price, "change_pct": round(-2 + j*2.4 + i*0.3, 2),
                                "volume_ratio": round(0.8 + j*0.5, 2), "amount": (j+1)*60000000,
                                "quote_date": today.isoformat(), "quote_time": "2026-10-19 15:00:00"})
            bars = [{"date": d, "open": round(price*(0.83+k*0.001), 2), "close": round(price*(0.84+k*0.001), 2),
                     "high": round(price*(0.85+k*0.001), 2), "low": round(price*(0.82+k*0.001), 2),
                     "volume": 10000+k*113+(k%7)*400} for k, d in enumerate(days[-100:])]
            store.put("history:"+code, {"bars": bars, "basis_date": today.isoformat(), "comparable": True})
    for board, rows in dirs.items():
        store.put("directory:"+board, {"rows": rows, "fetched_at": "演示样例"})
    store.put("quotes", {"rows": quotes, "source": "合成演示数据（非真实行情）", "fetched_at": "2026-10-19T15:00:00+08:00"})
    store.put("suspensions", {"date": today.isoformat(), "records": []})
