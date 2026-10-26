import pandas as pd
import pytest
from screener.indicators import add_indicators, make_detail_chart


def test_macd_recurrence_and_exclusive_panel():
    prices = [10, 12, 11, 15] * 10
    rows = [dict(date=str(d.date()), open=p, high=p+1, low=p-1, close=p, volume=100)
            for d,p in zip(pd.bdate_range("2026-01-01", periods=len(prices)), prices)]
    df = add_indicators(rows)
    fast = slow = prices[0]
    dea = 0
    expected = []
    for price in prices:
        fast += (price-fast)*2/13
        slow += (price-slow)*2/27
        dif = fast-slow
        dea += (dif-dea)*2/10
        expected.append((dif, dea, 2*(dif-dea)))
    assert df[["DIF","DEA","MACD"]].to_numpy() == pytest.approx(__import__("numpy").array(expected))
    chart = make_detail_chart(df, display_bars=10, panel="MACD")
    names = {t.name for t in chart.data}
    assert {"DIF", "DEA", "MACD"} <= names
    assert "成交量（手）" not in names
    assert "MACD" not in {t.name for t in make_detail_chart(df).data}
    assert list(next(t for t in chart.data if t.name == "DIF").y) == pytest.approx(df.DIF.tail(10))


def test_statistics_separate_missing_and_stale_quotes():
    from screener.workspace import market_statistics, search_stocks
    rows = [dict(code="002050",name="三花智控",board="深市主板",industry="制造业",change_pct=2,quote_date="2026-10-23"),
            dict(code="600000",name="浦发银行",board="沪市主板",industry="金融业",change_pct=-1,quote_date="2026-10-23"),
            dict(code="600001",name="测试",board="沪市主板",industry="金融业",change_pct=0,quote_date="2026-10-22"),
            dict(code="600002",name="测试2",board="沪市主板",industry="金融业",change_pct=None)]
    groups = {r["分组"]:r for r in market_statistics(rows,"board","2026-10-23")}
    assert groups["沪市主板"]["下跌"] == 1
    assert groups["沪市主板"]["未知"] == 2
    assert groups["沪市主板"]["平盘"] == 0
    assert search_stocks(rows," 三花 ")[0]["code"] == "002050"
    assert search_stocks(rows,"2050")[0]["name"] == "三花智控"
    assert search_stocks(rows,"不存在") == []


def test_all_market_search_and_watch_selection_are_offline(tmp_path, monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from screener.store import Store
    from screener.demo import seed
    from screener.provider import Provider
    monkeypatch.setenv("SCREENER_DATA_DIR", str(tmp_path))
    store = Store(tmp_path/"market.db")
    seed(store)
    directory = store.get("directory:深圳")
    directory["rows"][0]["name"] = "三花智控"
    store.put("directory:深圳", directory)
    quotes = store.get("quotes")
    next(r for r in quotes["rows"] if r["code"] == "000001")["name"] = "三花智控"
    store.put("quotes", quotes)
    store.set_watchlist(["000001", "600001"])
    def forbidden(*a, **k):
        raise AssertionError("浏览不能请求接口")
    monkeypatch.setattr(Provider, "call", forbidden)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/"app.py")).run()
    app.radio(key="workspace_page").set_value("股票筛选").run()
    app.text_input(key="stock_search").set_value("三花").run()
    assert app.selectbox(key="detail_stock").value == "000001"
    app.radio(key="workspace_page").set_value("自选跟踪").run()
    app.text_input(key="watch_search").set_value("三花").run()
    assert not app.exception
    assert app.selectbox(key="watch_detail").value == "000001"
    app.text_input(key="watch_search").set_value("").run()
    app.session_state["watch_table:"] = {"selection":{"rows":[1], "columns":[], "cells":[]}}
    app.run()
    assert app.selectbox(key="watch_detail").value == "600001"
    assert any("600001" in h.value for h in app.subheader)
    app.radio(key="watch_panel").set_value("MACD").run()
    assert not app.exception


def test_local_review_has_no_provider_calls_and_marks_missing(tmp_path, monkeypatch):
    from screener.demo import seed
    from screener.store import Store
    from screener.provider import Provider
    from screener.review import ReviewRepository, ReviewRunner
    store = Store(tmp_path/"test.db")
    seed(store)
    store.put("history:600001", {})
    monkeypatch.setattr(Provider, "call", lambda *a, **k: pytest.fail("Local review made a network call"))
    repo = ReviewRepository(store)
    runner = ReviewRunner(repo)
    run = runner.create(dict(boards=["沪市主板"], source="tencent", requested_date="2026-10-19",
        workers=5, local_only=True, exclude_st=False, exclude_new=False))
    runner.run(run["id"])
    assert repo.get(run["id"])["status"] == "done"
    assert repo.result(run["id"], "600001")["outcome"] == "unknown"
    assert len(repo.results(run["id"])) == 5


def test_full_data_job_downloads_every_stock_and_preserves_failed_history(tmp_path, monkeypatch):
    from screener.store import Store
    from screener.service import Service
    from screener.data_refresh import MarketRefresh
    from screener.review import ReviewRepository
    from screener.demo import seed
    store = Store(tmp_path/"test.db")
    seed(store)
    old = store.get("history:600001")
    calls = []
    class FakeProvider:
        def call(self, op, **kw):
            calls.append((op,kw))
            if op == "calendar":
                return store.get("calendar")
            if op == "directory":
                return store.get("directory:"+kw["board"])
            if op == "quotes_tencent":
                return store.get("quotes")
            if op == "suspensions":
                return store.get("suspensions")
            if op == "history":
                if kw["code"] == "600001":
                    raise ValueError("测试失败")
                return store.get("history:"+kw["code"])
            raise AssertionError(op)
    monkeypatch.setattr("screener.data_refresh.now", lambda:"2026-10-19T16:00:00+08:00")
    repo = ReviewRepository(store)
    assert repo.claim("market-data", "test")
    store.put("market:refresh", dict(status="running", processed=0, total=0, errors=[], success=0, missing=0))
    MarketRefresh(store, Service(store, FakeProvider())).run("test", 5, "tencent", "eastmoney")
    state = store.get("market:refresh")
    assert state["processed"] == 25 and state["success"] == 24
    assert state["status"] == "partial"
    assert store.get("history:600001") == old
    assert repo.active() is None
    assert {k["code"] for op,k in calls if op == "history"} == {r["code"] for r in Service(store).directory()}


def test_removing_a_searched_watch_stock_keeps_hidden_stocks(tmp_path, monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from screener.store import Store
    from screener.demo import seed
    monkeypatch.setenv("SCREENER_DATA_DIR", str(tmp_path))
    store = Store(tmp_path/"market.db")
    seed(store)
    store.set_watchlist(["600001", "600002"])
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/"app.py")).run()
    app.radio(key="workspace_page").set_value("自选跟踪").run()
    app.text_input(key="watch_search").set_value("600001").run()
    app.button(key="watch_remove").click().run()
    assert store.watchlist() == ["600002"]
