import json
import pytest
import requests
from screener.history import fetch_tencent_history, history_symbol

@pytest.mark.parametrize("stock,board,want", [
    ("600000","沪市主板","sh600000"), ("000001","深市主板","sz000001"),
    ("300058","创业板","sz300058"), ("688001","科创板","sh688001"),
    ("920001","北交所","bj920001"), ("430047","北交所","bj430047")])
def test_market_symbols(stock, board, want):
    assert history_symbol(stock, board) == want

class Session:
    def __init__(self, symbol, volume, error=None):
        self.symbol, self.volume, self.error = symbol, volume, error
        self.calls = []
    def get(self, url, params, timeout):
        self.calls.append(params["param"])
        if self.error:
            raise self.error
        adjust = params["param"].split(",")[-1]
        data = [["2026-03-01","9","10","11","8",self.volume],
                ["2026-10-19","10","11","12","9",self.volume],
                ["2026-10-20","11","12","13","10",self.volume]]
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({"code":0,"data":{self.symbol:{("qfqday" if adjust else "day"):data}}}).encode()
        return response

@pytest.mark.parametrize("symbol,volume,want", [("sz300058", "123",123),("sh688001","12300",123),("bj920001","123",123)])
def test_dates_prices_and_volume_units(symbol, volume, want):
    session = Session(symbol, volume)
    result = fetch_tencent_history(symbol, "2026-10-19", session=session)
    assert [b["date"] for b in result["bars"]] == ["2026-10-19"]
    assert result["bars"][0] == dict(date="2026-10-19", open=10,close=11,high=12,low=9,volume=want)
    assert result["comparable"] and result["basis_date"] == "2026-10-19"
    assert result["source"] == "腾讯历史日线"
    assert len(session.calls) == 2
    assert session.calls[0].endswith(",qfq") and session.calls[1].endswith(",")

def test_proxy_failure_is_explained_without_extra_requests():
    session = Session("sz300058", "123", requests.exceptions.ProxyError("proxy detail"))
    with pytest.raises(RuntimeError, match="代理连接失败"):
        fetch_tencent_history("sz300058", "2026-10-19", session=session)
    assert len(session.calls) == 1

def test_incremental_start_is_sent_and_applied_locally():
    session = Session("sz300058", "123")
    result = fetch_tencent_history("sz300058", "2026-10-20", session=session, start_date="2026-10-20")
    assert [b["date"] for b in result["bars"]] == ["2026-10-20"]
    assert ",2026-10-20,2026-10-20," in session.calls[0]
