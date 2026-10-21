"""Persistent daily history, overlapping incremental refresh and qfq rebase detection."""
from datetime import datetime
import json
import uuid
from .store import now, CHINA
from .validation import validate


def provider_source(history):
    if history.get("provider_source"):
        return history["provider_source"]
    source = history.get("source", "")
    return "tencent" if "腾讯" in source else "eastmoney" if "东方财富" in source else None


def closed_snapshot(history, target):
    try:
        stamp = datetime.fromisoformat(history["fetched_at"])
        if stamp.tzinfo is None:
            return False
        cutoff = datetime.fromisoformat(target+"T15:30:00").replace(tzinfo=CHINA)
        return stamp >= cutoff
    except (KeyError, ValueError, TypeError):
        return False


class HistoryCache:
    def __init__(self, store, request):
        self.store, self.request = store, request

    def refresh(self, code, board, target, source, allow_closed_cache=True):
        key = "history:"+code
        old = self.store.get(key) or {}
        try:
            validate("history", old, {})
            usable = provider_source(old) == source
        except (ValueError, TypeError):
            usable = False
        old_bars = old.get("bars", []) if usable else []
        available = [b for b in old_bars if b["date"] <= target]
        if (allow_closed_cache and len(available) >= 15 and available[-1]["date"] == target
                and closed_snapshot(old, target)):
            return old | {"bars":available, "basis_date":target, "cache_mode":"local",
                          "comparable":old.get("comparable", False) and old["basis_date"] == target}
        incremental = len(old_bars) >= 15 and old_bars[-1]["date"] <= target
        args = dict(code=code, board=board, date=target, source=source)
        if incremental:
            args["start_date"] = old_bars[-5]["date"]
        fresh = self.request("history", **args)
        validate("history", fresh, args)
        mode = "full"
        if incremental:
            old_map = {b["date"]:b for b in old_bars}
            new_map = {b["date"]:b for b in fresh["bars"]}
            overlap = [b["date"] for b in old_bars[-5:-1]]
            changed = any(d not in new_map or any(
                abs(old_map[d][k]-new_map[d][k]) > .005
                for k in ("open","high","low","close")) for d in overlap)
            if changed:
                args["start_date"] = old_bars[0]["date"]
                fresh = self.request("history", **args)
                validate("history", fresh, args)
                if len(fresh["bars"]) < 15:
                    raise ValueError("前复权变化后返回历史不足，已保留旧缓存")
                mode = "rebase"
            else:
                end = fresh["basis_date"]
                merged = old_map | new_map
                fresh = fresh | {"bars":[merged[d] for d in sorted(merged) if d <= end]}
                mode = "incremental"
        fresh = fresh | {"fetched_at":now(), "provider_source":source, "cache_mode":mode}
        validate("history", fresh, args)
        # Recheck inside the write transaction: another window may have refreshed
        # this stock while the network request was in flight.
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM documents WHERE key=?", (key,)).fetchone()
            current = json.loads(row[0]) if row else {}
            current_date = current.get("basis_date")
            if not isinstance(current_date, str) or fresh["basis_date"] >= current_date:
                if mode == "rebase" and row:
                    db.execute("INSERT INTO documents VALUES(?,?)",
                               ("history:revision:"+code+":"+uuid.uuid4().hex, row[0]))
                db.execute("INSERT OR REPLACE INTO documents VALUES(?,?)",
                           (key, json.dumps(fresh, ensure_ascii=False, allow_nan=False)))
        return fresh
