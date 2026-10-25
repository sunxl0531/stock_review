from datetime import date, timedelta
import threading
import pytest
from screener.review import review_signal, ReviewRunner, ReviewRepository
from screener.store import Store

CAL = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(100)]
DAY = CAL[-1]

def history(prices):
    return {"basis_date": DAY, "comparable": True, "source":"腾讯历史日线", "bars": [
        dict(date=d, open=p, high=p+1, low=p-1, close=p, volume=100)
        for d,p in zip(CAL[-len(prices):], prices)]}

@pytest.mark.parametrize("prices,days", [
    ([20]*29+[30], 1), ([20]*28+[30,31], 2),
    ([20]*27+[30,31,32], 3), ([20]*30, 0),
    ([20]*28+[30,19], 0),
])
def test_review_recent_cross_or_longer_rising_trend(prices, days):
    result = review_signal(history(prices), CAL, DAY)
    assert result["outcome"] == ("match" if days else "no_match")
    if days:
        assert result["above_days"] == days
        assert result["break_date"] == CAL[-days]

def test_review_rejects_missing_history_and_ignores_future():
    h = history([20]*29+[30])
    h["bars"].append(h["bars"][-1] | {"date":"2030-01-01", "close":1})
    assert review_signal(h, CAL, DAY)["outcome"] == "match"
    h["bars"].pop(-2)
    assert review_signal(h, CAL, DAY)["outcome"] == "unknown"
    assert review_signal(history([20]*14), CAL, DAY)["outcome"] == "unknown"

@pytest.mark.parametrize("prices,days,direction,outcome", [
    ([100]*20+[20]*2+[80]*12, 1, "下行", "match"),
    ([100]*20+[20]*12+[80]*4, 3, "下行", "no_match"),
    ([100]*20+[20]*5+[110], 1, "走平", "match"),
    ([100]*20+[20]*5+[110]*3, 3, "走平", "no_match"),
])
def test_rising_requirement_only_applies_after_two_days(prices, days, direction, outcome):
    result = review_signal(history(prices), CAL, DAY)
    assert result["above_days"] == days
    assert result["snakea_direction"] == direction
    assert result["outcome"] == outcome

def test_long_uptrend_can_match_when_original_cross_precedes_cache():
    result = review_signal(history(list(range(10,40))), CAL, DAY)
    assert result["outcome"] == "match"
    assert result["above_days"] > 2
    assert result["above_days_at_least"]
    assert not result["break_date"]

class FakeService:
    def __init__(self):
        self.calls = []
        self.fail = set()
    def request(self, operation, **kwargs):
        self.calls.append((operation, kwargs))
        if kwargs.get("code") in self.fail:
            raise RuntimeError("network error")
        if operation == "calendar":
            return {"days":CAL}
        if operation == "directory":
            return {"rows":[dict(code="600001", name="测试", board="沪市主板", listed=CAL[0])]}
        if operation == "review_quotes_tencent":
            return {"rows":[]}
        return history([20]*29+[30])

def config():
    return dict(boards=["沪市主板"], source="tencent", exclude_st=True, exclude_new=True,
                requested_date=DAY)

def test_run_snapshots_and_resume_without_refetching_success(tmp_path):
    store = Store(tmp_path/"test.db")
    repo = ReviewRepository(store)
    service = FakeService()
    runner = ReviewRunner(repo, service, delay=0)
    run = runner.create(config())
    runner.run(run["id"])
    assert repo.get(run["id"])["status"] == "done"
    results = repo.results(run["id"])
    assert results[0]["outcome"] == "match"
    assert results[0]["history"]["bars"][-1]["close"] == 30
    store.put("history:600001", history([1]*30))
    assert repo.results(run["id"])[0]["history"]["bars"][-1]["close"] == 30
    calls = len(service.calls)
    runner.run(run["id"])
    assert len(service.calls) == calls

def test_failure_is_not_no_match_and_can_retry(tmp_path):
    repo = ReviewRepository(Store(tmp_path/"test.db"))
    service = FakeService()
    service.fail.add("600001")
    runner = ReviewRunner(repo, service, delay=0)
    run = runner.create(config())
    runner.run(run["id"])
    assert repo.get(run["id"])["status"] == "partial"
    assert repo.results(run["id"])[0]["outcome"] == "error"
    service.fail.clear()
    runner.run(run["id"])
    assert repo.get(run["id"])["status"] == "done"
    assert repo.results(run["id"])[0]["outcome"] == "match"

def test_stop_and_cross_process_lease(tmp_path):
    repo = ReviewRepository(Store(tmp_path/"test.db"))
    runner = ReviewRunner(repo, FakeService(), delay=0)
    run = runner.create(config())
    repo.stop(run["id"])
    runner.run(run["id"])
    assert repo.get(run["id"])["status"] == "paused"
    assert repo.claim("one", "owner1")
    assert not ReviewRepository(repo.store).claim("two", "owner2")
    repo.release("owner1")
    assert repo.claim("two", "owner2")

class ConcurrentService(FakeService):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()
        self.lock = threading.Lock()
        self.active = 0
        self.peak = 0

    def request(self, operation, **kwargs):
        if operation == "directory":
            return {"rows":[dict(code=f"60000{i}", name=f"测试{i}", board="沪市主板", listed=CAL[0])
                            for i in (1, 2, 3)]}
        if operation == "history":
            with self.lock:
                self.calls.append((operation, kwargs))
                self.active += 1
                self.peak = max(self.peak, self.active)
                if self.active == 2:
                    self.started.set()
            try:
                assert self.release.wait(5), "requests were not released"
                return history([20]*29+[30])
            finally:
                with self.lock:
                    self.active -= 1
        return super().request(operation, **kwargs)

def test_two_history_workers_overlap_and_stop_saves_inflight(tmp_path):
    repo = ReviewRepository(Store(tmp_path/"test.db"))
    service = ConcurrentService()
    runner = ReviewRunner(repo, service, delay=0)
    run = runner.create(config() | {"workers":2})
    thread = threading.Thread(target=runner.run, args=(run["id"],))
    thread.start()
    try:
        assert service.started.wait(5), "two requests did not overlap"
        repo.stop(run["id"])
    finally:
        service.release.set()
        thread.join(10)
    assert not thread.is_alive()
    assert service.peak == 2
    assert repo.get(run["id"])["status"] == "paused"
    assert {r["code"] for r in repo.results(run["id"])} == {"600001", "600002"}
    runner.run(run["id"])
    assert repo.get(run["id"])["status"] == "paused"  # direct run keeps a requested stop
    repo.store.put("review:stop:"+run["id"], False)
    runner.run(run["id"])
    assert repo.get(run["id"])["status"] == "done"
    assert len([c for op, args in service.calls if op == "history" for c in [args["code"]] if c == "600001"]) == 1

def test_invalid_worker_count_is_rejected(tmp_path):
    repo = ReviewRepository(Store(tmp_path/"test.db"))
    with pytest.raises(ValueError, match="并发"):
        ReviewRunner(repo).create(config() | {"workers":20})


@pytest.mark.parametrize("workers", [5, 10])
def test_requested_workers_really_run_concurrently(tmp_path, workers):
    barrier = threading.Barrier(workers)
    class ManyStocks(FakeService):
        def request(self, operation, **kwargs):
            if operation == "directory":
                return {"rows":[dict(code=f"600{i:03d}", name="测试", board="沪市主板",
                                     listed=CAL[0]) for i in range(workers)]}
            if operation == "history":
                barrier.wait(timeout=10)
                return history([20]*29+[30])
            return super().request(operation, **kwargs)
    repo = ReviewRepository(Store(tmp_path/"test.db"))
    runner = ReviewRunner(repo, ManyStocks(), delay=0)
    run = runner.create(config() | {"workers":workers})
    runner.run(run["id"])
    assert repo.get(run["id"])["status"] == "done"
    assert len(repo.results(run["id"])) == workers
    assert all(r["outcome"] == "match" for r in repo.results(run["id"]))

def test_review_page_start_saved_chart_and_offline_navigation(tmp_path, monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from screener.provider import Provider
    monkeypatch.setenv("SCREENER_DATA_DIR", str(tmp_path))
    def forbidden(*args, **kwargs):
        raise AssertionError("普通复盘浏览不能联网")
    monkeypatch.setattr(Provider, "call", forbidden)
    service = FakeService()
    def synchronous_start(self, run_id):
        self.service = service
        self.delay = 0
        self.run(run_id)
    monkeypatch.setattr(ReviewRunner, "start", synchronous_start)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/"app.py")).run(timeout=20)
    app.radio(key="workspace_page").set_value("每日复盘").run()
    assert not app.exception
    assert not service.calls
    app.multiselect(key="review_boards").set_value(["沪市主板"])
    app.date_input(key="review_date").set_value(date.fromisoformat(DAY))
    app.button(key="review_start").click().run(timeout=20)
    assert not app.exception
    assert any(op == "history" for op, _ in service.calls)
    run_id = app.selectbox(key="review_run").value
    app.session_state["review_selected:"+run_id] = "600001"
    calls = len(service.calls)
    app.run()
    assert not app.exception
    assert len(app.get("plotly_chart")) == 1
    assert len(service.calls) == calls
    app.radio(key="workspace_page").set_value("股票筛选").run()
    assert not app.exception
    assert app.checkbox(key="exclude_st").value
    assert app.checkbox(key="exclude_new").value
