"""Explicit refresh transactions; normal reads never invoke a provider."""
from .provider import Provider, day, code
from .store import now
from .validation import validate

class Service:
    def __init__(self, store, provider=None):
        self.store, self.provider = store, provider or Provider()

    def request(self, operation, **kwargs):
        try:
            result = self.provider.call(operation, **kwargs)
            validate(operation, result, kwargs)
            self.store.log(operation, True, f"HTTP请求数: {result.get('http_requests', '未知')}")
            return result
        except Exception as exc:
            self.store.log(operation, False, exc)
            raise

    def directory(self):
        rows = []
        for board in ("沪市主板", "科创板", "深圳", "北交所"):
            rows.extend(self.store.get("directory:" + board, {}).get("rows", []))
        return rows

    def refresh_basic(self, operation, board=None):
        with self.store.task_lock():
            data = self.request(operation, **({"board": board} if board else {}))
            items = data.get("rows" if operation == "directory" else "days", [])
            if not items:
                raise ValueError("基础资料为空，未替换缓存")
            self.store.put("directory:" + board if board else "calendar", data | {"fetched_at": now()})
            return len(items)

    def refresh_quotes(self, source="eastmoney"):
        with self.store.task_lock():
            args = {}
            if source == "tencent":
                args["symbols"] = [("sh" if r["board"] in ("沪市主板", "科创板") else "bj" if r["board"] == "北交所" else "sz") + r["code"] for r in self.directory() if r.get("board")]
            data = self.request("quotes_" + source, **args)
            rows = data.get("rows", [])
            if not rows or len({r["code"] for r in rows}) != len(rows):
                raise ValueError("行情为空或有重复代码，未替换缓存")
            self.store.put("quotes", data | {"fetched_at": now()})
            return len(rows)

    def refresh_watchlist_quotes(self, codes, preserve_other=False):
        from .history import history_symbol
        selected = sorted(set(codes))
        if not selected:
            return 0
        with self.store.task_lock():
            boards = {r["code"]:r.get("board") for r in self.directory()}
            symbols = [history_symbol(stock_code, boards.get(stock_code)) for stock_code in selected]
            data = self.request("quotes_tencent", symbols=symbols)
            if any(r["code"] not in selected for r in data["rows"]):
                raise ValueError("自选行情返回了未请求的股票，旧缓存已保留")
            stamp = now()
            old = {r["code"]:r for r in self.store.get("watch_quotes", {}).get("rows", []) if preserve_other or r["code"] in selected}
            old.update({r["code"]:r | {"fetched_at":stamp} for r in data["rows"]})
            self.store.put("watch_quotes", {"rows":[old[c] for c in sorted(old)],
                                            "source":data.get("source", "腾讯公开行情"), "fetched_at":stamp})
            return len(data["rows"])

    def as_of(self):
        snapshot = self.store.get("quotes", {})
        dates = [r["quote_date"] for r in snapshot.get("rows", []) if r.get("quote_date")]
        if dates:
            return max(dates)
        fetched = snapshot.get("fetched_at", now())[:10]
        days = [d for d in self.store.get("calendar", {}).get("days", []) if d <= fetched]
        return max(days) if days else fetched

    def refresh_suspensions(self):
        with self.store.task_lock():
            data = self.request("suspensions", date=self.as_of())
            self.store.put("suspensions", data | {"fetched_at": now()})
            return len(data.get("records", []))

    def fetch_history(self, stock_code, source="tencent", target_date=None):
        from .history_cache import HistoryCache
        if source not in ("tencent", "eastmoney"):
            raise ValueError("未知历史数据来源")
        with self.store.task_lock():
            board = next((r.get("board") for r in self.directory() if r["code"] == stock_code), None)
            data = HistoryCache(self.store, self.request).refresh(stock_code, board, target_date or self.as_of(), source,
                                                                allow_closed_cache=False)
            return len(data.get("bars", []))

    def rows(self):
        directory = {r["code"]: r for r in self.directory()}
        snapshot = self.store.get("quotes", {})
        quotes = {r["code"]: r for r in snapshot.get("rows", [])}
        suspension = self.store.get("suspensions", {})
        as_of = self.as_of()
        states = {}
        # Unknown/ambiguous intervals cannot be asserted as suspended or trading.
        for r in suspension.get("records", []):
            try:
                stock_code = code(r.get("代码", ""))
            except ValueError:
                continue
            start, resume = day(r.get("停牌时间")), day(r.get("预计复牌时间"))
            until = day(r.get("停牌截止时间"))
            if not start:
                states[stock_code] = None
            elif start <= as_of and resume is not None and resume <= as_of:
                # An expected resumption date is not an actual trading-state confirmation.
                states[stock_code] = None
            elif start <= as_of and (resume is None or as_of < resume) and (until is None or as_of <= until):
                states[stock_code] = True
        rows = []
        for stock_code in sorted(set(directory) | set(quotes)):
            row = directory.get(stock_code, {"code": stock_code}) | quotes.get(stock_code, {})
            row.update(fetched_at=snapshot.get("fetched_at"), source=snapshot.get("source"),
                       suspended=states.get(stock_code, False) if suspension.get("date") == as_of else None,
                       status_date=suspension.get("date"))
            rows.append(row)
        return rows

    def histories(self, codes):
        return {c: h for c in codes if (h := self.store.get("history:" + c))}
