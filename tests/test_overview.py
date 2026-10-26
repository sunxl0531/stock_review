from pathlib import Path
from streamlit.testing.v1 import AppTest
from screener.provider import Provider
from screener.store import Store
from screener.review import ReviewRepository

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_empty_overview_is_local_and_links_to_review(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREENER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(Provider, "call", lambda *a, **k: (_ for _ in ()).throw(AssertionError("联网")))
    app = AppTest.from_file(APP).run(timeout=20)
    assert not app.exception
    assert app.radio(key="workspace_page").value == "今日概览"
    assert any("暂无本地数据" in item.value for item in app.info)
    app.button(key="overview_view_review").click().run()
    assert not app.exception
    assert app.radio(key="workspace_page").value == "每日复盘"


def test_overview_shows_saved_progress_without_network(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREENER_DATA_DIR", str(tmp_path))
    store = Store(tmp_path / "market.db")
    store.put("review:run:test", {"id":"test","target":"2026-10-19","status":"paused",
        "stage":5,"created_at":"2026-10-19T15:50:00+08:00","updated_at":"2026-10-19T16:00:00+08:00",
        "total":100,"processed":25,"current":"","error":"",
        "config":{"boards":["沪市主板"],"source":"tencent","requested_date":"2026-10-19",
                  "exclude_st":True,"exclude_new":True}})
    monkeypatch.setattr(Provider, "call", lambda *a, **k: (_ for _ in ()).throw(AssertionError("联网")))
    app = AppTest.from_file(APP).run(timeout=20)
    assert not app.exception
    app.button(key="overview_view_review").click().run()
    assert any("0 / 100" in item.proto.text for item in app.get("progress"))
    assert any("仍有未处理" in item.value for item in app.warning)


def test_stale_running_review_can_resume(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREENER_DATA_DIR", str(tmp_path))
    store = Store(tmp_path / "market.db")
    store.put("review:run:test", {"id":"test","target":"2026-10-19","status":"running",
        "stage":5,"created_at":"2026-10-19T15:50:00+08:00","updated_at":"2026-10-19T16:00:00+08:00",
        "total":100,"processed":25,"current":"","error":"",
        "config":{"boards":["沪市主板"],"source":"tencent","requested_date":"2026-10-19",
                  "exclude_st":True,"exclude_new":True}})
    app = AppTest.from_file(APP).run(timeout=20)
    assert not app.exception
    app.button(key="overview_view_review").click().run()
    assert not app.button(key="review_resume").disabled


def test_saved_review_and_watchlist_navigation_stay_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREENER_DATA_DIR", str(tmp_path))
    store = Store(tmp_path / "market.db")
    repo = ReviewRepository(store)
    for day, status in (("2026-10-18","done"),("2026-10-19","done")):
        repo.save({"id":day,"target":day,"status":status,"stage":5,
                   "created_at":day+"T16:00:00+08:00","updated_at":day+"T16:01:00+08:00",
                   "total":1,"processed":1,"current":"","error":"",
                   "config":{"boards":["沪市主板"],"source":"tencent","requested_date":day,
                             "exclude_st":True,"exclude_new":True}})
    repo.put_result("2026-10-18", {"code":"600001","name":"甲","board":"沪市主板","outcome":"match",
                                    "above_days":1,"break_date":"2026-10-18","snakea_direction":"上行"})
    repo.put_result("2026-10-19", {"code":"600001","name":"甲","board":"沪市主板","outcome":"no_match",
                                    "above_days":0,"reason":"未站上"})
    store.set_watchlist(["600001"])
    monkeypatch.setattr(Provider, "call", lambda *a, **k: (_ for _ in ()).throw(AssertionError("联网")))
    app = AppTest.from_file(APP).run(timeout=20)
    app.radio(key="workspace_page").set_value("每日复盘").run()
    assert not app.exception
    assert any(m.label == "今日退出" and m.value == "1" for m in app.metric)
    app.radio(key="review_change_view").set_value("今日退出").run()
    assert not app.exception
    app.radio(key="workspace_page").set_value("自选跟踪").run()
    assert not app.exception
    assert app.selectbox(key="watch_detail").value == "600001"
    assert not any("自选股跟踪" in h.value for h in app.subheader)
