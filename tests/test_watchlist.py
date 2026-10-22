import pytest
from screener.watchlist_ui import build_watch_rows
from pathlib import Path
from streamlit.testing.v1 import AppTest
from screener.store import Store
from screener.provider import Provider


def test_watchlist_handles_empty_missing_and_saved_review():
    assert build_watch_rows([], [], [], None) == []
    rows = build_watch_rows(["600001","000001"],
        [{"code":"600001","name":"甲","board":"沪市主板"}],
        [{"code":"600001","outcome":"match","close":11,"snakea":10,"snakea_previous":9}],
        "2026-10-20")
    assert rows[0]["代码"] == "000001" and rows[0]["复盘状态"] == "未覆盖"
    assert rows[1]["复盘状态"] == "入选"
    assert rows[1]["距SNAKEA %"] == pytest.approx(10)


def test_watchlist_rows_show_separate_refreshed_quotes():
    rows = build_watch_rows(["600001"], [], [], None,
                            quotes=[{"code":"600001","name":"甲","price":12.3,
                                     "change_pct":1.2,"quote_time":"2026-10-22 10:01:00"}])
    assert rows[0]["最新价"] == 12.3
    assert rows[0]["涨跌幅 %"] == 1.2
    assert rows[0]["行情时间"] == "2026-10-22 10:01:00"


def test_watchlist_indicators_use_latest_local_daily_history_not_old_review():
    import pandas as pd
    days = pd.bdate_range("2026-09-01", periods=25).strftime("%Y-%m-%d")
    history = {"basis_date":days[-1], "bars":[{"date":day,"open":10,"high":11,
        "low":9,"close":10,"volume":100} for day in days]}
    rows = build_watch_rows(["600001"], [],
        [{"code":"600001","outcome":"match","close":20,"snakea":10,"snakea_previous":10}],
        "2026-09-01", histories={"600001":history})
    assert rows[0]["距SNAKEA %"] == pytest.approx(0)
    assert rows[0]["指标日线日期"] == days[-1]


def test_manual_watchlist_quote_refresh_does_not_replace_market_or_download_history(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREENER_DATA_DIR", str(tmp_path))
    store = Store(tmp_path / "market.db")
    store.set_watchlist(["600001"])
    old = {"rows":[{"code":"600001","price":8}],"fetched_at":"old"}
    store.put("quotes", old)
    calls = []
    def fake_call(self, operation, **kwargs):
        calls.append((operation,kwargs))
        assert operation == "quotes_tencent"
        return {"rows":[{"code":"600001","name":"甲","price":10,"change_pct":2,
                         "volume_ratio":1.2,"amount":10000000,"quote_date":"2026-10-22",
                         "quote_time":"2026-10-22 10:00:00"}],"source":"腾讯公开行情"}
    monkeypatch.setattr(Provider, "call", fake_call)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/"app.py")).run(timeout=20)
    app.radio(key="workspace_page").set_value("自选跟踪").run()
    assert calls == []
    app.checkbox(key="watch_update_daily").uncheck().run()
    app.button(key="watch_refresh_all").click().run()
    assert not app.exception
    assert calls == [("quotes_tencent", {"symbols":["sh600001"]})]
    assert store.get("quotes") == old
    assert store.get("watch_quotes")["rows"][0]["price"] == 10


def test_manual_watchlist_refresh_updates_daily_history_and_keeps_old_on_failure(tmp_path, monkeypatch):
    import pandas as pd
    monkeypatch.setenv("SCREENER_DATA_DIR", str(tmp_path))
    store = Store(tmp_path / "market.db")
    store.set_watchlist(["600001", "600002"])
    old = {"basis_date":"2026-10-20", "bars":[{"date":"2026-10-20","close":8}]}
    store.put("history:600002", old)
    calls = []
    def fake_call(self, operation, **kwargs):
        calls.append((operation, kwargs))
        if operation == "quotes_tencent":
            return {"rows":[{"code":c,"name":c,"price":10,"change_pct":1,
                     "volume_ratio":1.2,"amount":10000000,"quote_date":"2026-10-22",
                     "quote_time":"2026-10-22 15:30:00"} for c in ("600001","600002")],
                    "source":"腾讯公开行情"}
        if kwargs["code"] == "600002":
            raise RuntimeError("该股历史请求失败")
        bars = [{"date":d,"open":10,"high":11,"low":9,"close":10,"volume":100}
                for d in pd.bdate_range(end="2026-10-22", periods=20).strftime("%Y-%m-%d")]
        return {"bars":bars,"basis_date":"2026-10-22","comparable":True,
                "source":"腾讯历史日线","http_requests":2}
    monkeypatch.setattr(Provider, "call", fake_call)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/"app.py")).run(timeout=20)
    app.radio(key="workspace_page").set_value("自选跟踪").run()
    app.button(key="watch_refresh_all").click().run()
    assert not app.exception
    assert [op for op,_ in calls] == ["quotes_tencent","history","history"]
    assert store.get("history:600001")["basis_date"] == "2026-10-22"
    assert store.get("history:600002") == old
