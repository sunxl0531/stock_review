from screener.store import Store
from screener.service import Service
import pytest

class Provider:
    def __init__(self, payload=None, error=None):
        self.payload, self.error = payload, error
    def call(self, operation, **kwargs):
        if self.error:
            raise RuntimeError(self.error)
        return self.payload

def test_persistent_store_and_failure_preserve_snapshot(tmp_path):
    s = Store(tmp_path / "test.db")
    old = {"rows": [{"code": "000001", "price": 10}], "fetched_at": "old"}
    s.put("quotes", old)
    with pytest.raises(RuntimeError):
        Service(s, Provider(error="限流")).refresh_quotes()
    assert Store(tmp_path / "test.db").get("quotes") == old
    assert s.logs()[0]["ok"] == 0

@pytest.mark.parametrize("rows", [[], [{"code": "000001"}, {"code": "000001"}]])
def test_invalid_snapshot_not_committed(tmp_path, rows):
    s = Store(tmp_path / "test.db")
    s.put("quotes", {"rows": [{"code": "000001", "price": 8}]})
    with pytest.raises(ValueError):
        Service(s, Provider({"rows": rows})).refresh_quotes()
    assert s.get("quotes")["rows"][0]["price"] == 8

def test_service_construction_and_local_reads_do_not_request(tmp_path):
    svc = Service(Store(tmp_path / "test.db"), Provider(error="不应联网"))
    assert svc.rows() == []

def test_watchlist_persists(tmp_path):
    s = Store(tmp_path / "test.db")
    s.set_watchlist(["000001", "000001", "920001"])
    assert Store(tmp_path / "test.db").watchlist() == ["000001", "920001"]

def test_busy_guard_releases_after_failure(tmp_path):
    s = Store(tmp_path / "test.db")
    with s.task_lock():
        with pytest.raises(RuntimeError, match="进行"):
            with s.task_lock():
                pass
    with s.task_lock():
        pass

@pytest.mark.parametrize("payload", [{}, {"date": "2026-10-19"}, {"date": "2026-10-19", "records": [{}]}])
def test_malformed_suspensions_preserve_valid_cache(tmp_path, payload):
    s = Store(tmp_path / "test.db")
    old = {"date": "2026-10-19", "records": []}
    s.put("suspensions", old)
    with pytest.raises(ValueError):
        Service(s, Provider(payload)).refresh_suspensions()
    assert s.get("suspensions") == old

def test_bad_quote_types_and_directory_schema_preserve_cache(tmp_path):
    s = Store(tmp_path / "test.db")
    old = {"rows": [{"code": "000001", "price": 8}]}
    s.put("quotes", old)
    with pytest.raises(ValueError):
        Service(s, Provider({"rows": [{"code": "000001", "price": "bad"}]})).refresh_quotes()
    assert s.get("quotes") == old
    s.put("directory:北交所", old)
    with pytest.raises(ValueError):
        Service(s, Provider({"rows": [{"code": "920001"}]})).refresh_basic("directory", "北交所")
    assert s.get("directory:北交所") == old

def test_malformed_history_preserves_cached_bars(tmp_path):
    s = Store(tmp_path / "test.db")
    old = {"bars": [{"date": "2026-10-19", "high": 10}]}
    s.put("history:000001", old)
    with pytest.raises(ValueError):
        Service(s, Provider({"bars": []})).fetch_history("000001")
    assert s.get("history:000001") == old

def test_expected_resumption_is_not_confirmation(tmp_path):
    s = Store(tmp_path / "test.db")
    s.put("quotes", {"rows": [{"code":"000001", "price":10, "quote_date":"2026-10-19"}]})
    s.put("suspensions", {"date":"2026-10-19", "records":[{"代码":"000001", "停牌时间":"2026-10-16", "预计复牌时间":"2026-10-19", "停牌截止时间":"2026-10-16"}]})
    assert Service(s).rows()[0]["suspended"] is None
