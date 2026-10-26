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
    assert any("未找到股票" in i.value for i in app.info)
    assert not app.exception

def test_demo_is_explicit_and_filterable(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREENER_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(APP).run(timeout=20)
    app.radio(key="workspace_page").set_value("股票筛选").run()
    monkeypatch.setenv("SCREENER_DEMO", "1")
    app.run()
    assert not app.exception
    assert any("演示" in w.value for w in app.warning)
    assert len(app.dataframe) > 0
    app.checkbox(key="use_change").check().run()
    assert not app.exception
    assert {"MA5","MA10","MA20","SNAKEA"} <= {metric.label for metric in app.metric}
    app.checkbox(key="stock_ma").uncheck().run()
    assert not app.exception
    app.checkbox(key="stock_snakea").uncheck().run()
    assert not app.exception

def test_indicator_filters_are_offline_and_persist(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREENER_DATA_DIR", str(tmp_path))
    def forbidden(*args, **kwargs):
        raise AssertionError("切换指标筛选不能联网")
    monkeypatch.setattr(Provider, "call", forbidden)
    app = AppTest.from_file(APP).run(timeout=20)
    app.radio(key="workspace_page").set_value("股票筛选").run()
    monkeypatch.setenv("SCREENER_DEMO", "1")
    app.run()
    app.checkbox(key="ma_bullish").check().run()
    assert not app.exception
    assert any("本地计算" in e.label for e in app.expander)
    app.checkbox(key="snakea_cross").check().run()
    assert not app.exception
    from screener.store import Store
    settings = Store(tmp_path / "demo.db").get("settings")
    assert settings["ma_bullish"] and settings["snakea_cross"]


def test_watchlist_shows_full_analysis_without_jump(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREENER_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(APP).run(timeout=20)
    monkeypatch.setenv("SCREENER_DEMO", "1")
    app.run()
    from screener.store import Store
    Store(tmp_path / "demo.db").set_watchlist(["600005"])
    app.radio(key="workspace_page").set_value("自选跟踪").run()
    assert not app.exception
    assert not any(b.key == "watch_open_detail" for b in app.button)
    assert app.selectbox(key="watch_detail").value == "600005"
    assert {"MA5", "MA10", "MA20", "SNAKEA"} <= {m.label for m in app.metric}
    app.radio(key="watch_panel").set_value("MACD").run()
    assert not app.exception
    assert len(app.get("plotly_chart")) == 1


def test_sidebar_contains_only_navigation(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREENER_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SCREENER_DEMO", raising=False)
    monkeypatch.setattr(Provider, "call", lambda *a, **k: (_ for _ in ()).throw(AssertionError("unexpected network")))
    app = AppTest.from_file(APP).run(timeout=20)
    assert not app.exception
    assert not app.sidebar.title
    assert not app.sidebar.caption
    assert not app.sidebar.toggle
    assert len(app.sidebar.radio) == 1
    assert len(app.sidebar.radio[0].options) == 4
    app.sidebar.radio[0].set_value("自选跟踪").run()
    assert not app.exception
    assert app.radio(key="workspace_page").value == "自选跟踪"
