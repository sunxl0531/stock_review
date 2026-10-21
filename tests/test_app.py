from streamlit.testing.v1 import AppTest
from screener.provider import Provider
from pathlib import Path
APP = str(Path(__file__).resolve().parents[1] / "app.py")

def test_empty_app_is_usable_without_network(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREENER_DATA_DIR", str(tmp_path))
    def forbidden(*args, **kwargs):
        raise AssertionError("普通页面操作不能联网")
    monkeypatch.setattr(Provider, "call", forbidden)
    app = AppTest.from_file(APP).run(timeout=20)
    assert not app.exception
    app.radio(key="workspace_page").set_value("股票筛选").run()
    assert any("暂无行情" in i.value for i in app.info)
    app.checkbox(key="exclude_st").uncheck().run()
    assert not app.exception

def test_demo_is_explicit_and_filterable(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREENER_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(APP).run(timeout=20)
    app.radio(key="workspace_page").set_value("股票筛选").run()
    app.toggle(key="demo").set_value(True).run()
    assert not app.exception
    assert any("演示" in w.value for w in app.warning)
    assert len(app.dataframe) > 0
    app.checkbox(key="use_change").check().run()
    assert not app.exception
    assert app.selectbox(key="history_source").value.startswith("腾讯")
    assert {"MA5","MA10","MA20","SNAKEA"} <= {metric.label for metric in app.metric}
    app.checkbox(key="chart_ma").uncheck().run()
    assert not app.exception
    app.checkbox(key="chart_snakea").uncheck().run()
    assert not app.exception

def test_indicator_filters_are_offline_and_persist(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREENER_DATA_DIR", str(tmp_path))
    def forbidden(*args, **kwargs):
        raise AssertionError("切换指标筛选不能联网")
    monkeypatch.setattr(Provider, "call", forbidden)
    app = AppTest.from_file(APP).run(timeout=20)
    app.radio(key="workspace_page").set_value("股票筛选").run()
    app.toggle(key="demo").set_value(True).run()
    app.checkbox(key="ma_bullish").check().run()
    assert not app.exception
    assert any("历史可计算" in e.label for e in app.expander)
    app.checkbox(key="snakea_cross").check().run()
    assert not app.exception
    from screener.store import Store
    settings = Store(tmp_path / "demo.db").get("settings")
    assert settings["ma_bullish"] and settings["snakea_cross"]


def test_watchlist_jump_keeps_stock_excluded_by_current_filter(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREENER_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(APP).run(timeout=20)
    app.toggle(key="demo").set_value(True).run()
    from screener.store import Store
    Store(tmp_path / "demo.db").set_watchlist(["600005"])
    app.radio(key="workspace_page").set_value("自选跟踪").run()
    app.button(key="watch_open_detail").click().run()
    assert not app.exception
    assert app.radio(key="workspace_page").value == "股票筛选"
    assert app.selectbox(key="detail_stock").value == "600005"

