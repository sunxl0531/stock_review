from datetime import date, timedelta
import pytest
from screener.store import Store
from screener.history_cache import HistoryCache

DAYS = [(date(2026, 10, 1)+timedelta(days=i)).isoformat() for i in range(21)]

def data(days, price=20):
    return dict(basis_date=days[-1], comparable=True, source="腾讯历史日线",
                bars=[dict(date=d, open=price, close=price, high=price+1, low=price-1, volume=100) for d in days],
                fetched_at=days[-1]+"T16:00:00+08:00")

def test_incremental_request_keeps_old_bars_and_replaces_overlap(tmp_path):
    store = Store(tmp_path/"cache.db")
    store.put("history:600001", data(DAYS[:20]))
    calls = []
    def request(op, **args):
        calls.append(args)
        return data(DAYS[15:])
    result = HistoryCache(store, request).refresh("600001","沪市主板",DAYS[-1],"tencent")
    assert len(calls) == 1
    assert calls[0]["start_date"] == DAYS[15]
    assert [b["date"] for b in result["bars"]] == DAYS
    assert result["cache_mode"] == "incremental"
    assert Store(tmp_path/"cache.db").get("history:600001")["bars"] == result["bars"]

def test_closed_snapshot_reuse_makes_no_request(tmp_path):
    store = Store(tmp_path/"cache.db")
    store.put("history:600001", data(DAYS))
    def forbidden(*args, **kwargs):
        raise AssertionError("收盘缓存不应重复下载")
    result = HistoryCache(store, forbidden).refresh("600001","沪市主板",DAYS[-1],"tencent")
    assert result["cache_mode"] == "local"
    assert result["fetched_at"] == DAYS[-1]+"T16:00:00+08:00"

def test_intraday_last_bar_update_is_not_misclassified_as_rebase(tmp_path):
    store = Store(tmp_path/"cache.db")
    old = data(DAYS)
    old["fetched_at"] = DAYS[-1]+"T12:00:00+08:00"
    store.put("history:600001", old)
    fresh = data(DAYS[-5:])
    fresh["bars"][-1].update(close=21, high=22)
    calls = []
    def request(*args, **kwargs):
        calls.append(kwargs)
        return fresh
    result = HistoryCache(store, request).refresh("600001","沪市主板",DAYS[-1],"tencent")
    assert len(calls) == 1
    assert result["cache_mode"] == "incremental"
    assert result["bars"][-1]["close"] == 21

def test_qfq_change_refetches_before_merging(tmp_path):
    store = Store(tmp_path/"cache.db")
    old = data(DAYS[:20])
    store.put("history:600001", old)
    calls = []
    def request(*args, **kwargs):
        calls.append(kwargs)
        return data(DAYS[15:] if len(calls)==1 else DAYS, price=10)
    result = HistoryCache(store, request).refresh("600001","沪市主板",DAYS[-1],"tencent")
    assert result["cache_mode"] == "rebase"
    assert calls[1]["start_date"] == DAYS[0]
    assert all(b["close"] == 10 for b in result["bars"])
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM documents WHERE key LIKE 'history:revision:%'").fetchone()[0] == 1

def test_failed_rebase_preserves_old_cache(tmp_path):
    store = Store(tmp_path/"cache.db")
    old = data(DAYS[:20])
    store.put("history:600001", old)
    calls = []
    def request(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) > 1:
            raise RuntimeError("接口失败")
        return data(DAYS[15:], price=10)
    with pytest.raises(RuntimeError):
        HistoryCache(store, request).refresh("600001","沪市主板",DAYS[-1],"tencent")
    assert store.get("history:600001") == old

def test_old_target_does_not_overwrite_newer_cache(tmp_path):
    store = Store(tmp_path/"cache.db")
    old = data(DAYS)
    store.put("history:600001", old)
    result = HistoryCache(store, lambda *a,**k:data(DAYS[:18])).refresh(
        "600001","沪市主板",DAYS[17],"tencent",allow_closed_cache=False)
    assert result["basis_date"] == DAYS[17]
    assert store.get("history:600001") == old

def test_source_switch_fetches_full_window(tmp_path):
    store = Store(tmp_path/"cache.db")
    store.put("history:600001", data(DAYS))
    calls = []
    def request(*args, **kwargs):
        calls.append(kwargs)
        return data(DAYS) | {"source":"东方财富历史日线"}
    result = HistoryCache(store, request).refresh("600001","沪市主板",DAYS[-1],"eastmoney")
    assert "start_date" not in calls[0]
    assert result["cache_mode"] == "full"

def test_missing_latest_bar_does_not_relabel_old_data_as_current(tmp_path):
    store = Store(tmp_path/"cache.db")
    old = data(DAYS)
    old["fetched_at"] = DAYS[-1]+"T12:00:00+08:00"
    store.put("history:600001", old)
    result = HistoryCache(store, lambda *a,**k:data(DAYS[-5:-1])).refresh(
        "600001","沪市主板",DAYS[-1],"tencent")
    assert result["basis_date"] == DAYS[-2]
    assert result["bars"][-1]["date"] == DAYS[-2]
    assert store.get("history:600001") == old

def test_other_window_newer_history_is_not_overwritten(tmp_path):
    store = Store(tmp_path/"cache.db")
    store.put("history:600001", data(DAYS[:18]))
    def request(*args, **kwargs):
        store.put("history:600001", data(DAYS))
        return data(DAYS[13:20])
    result = HistoryCache(store, request).refresh("600001","沪市主板",DAYS[19],"tencent")
    assert result["basis_date"] == DAYS[19]
    assert store.get("history:600001")["basis_date"] == DAYS[20]
