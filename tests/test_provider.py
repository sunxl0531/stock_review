from screener.provider import normalize_quotes, normalize_directory, normalize_history, parse_tencent

def test_quote_units_and_missing_data():
    rows = normalize_quotes([{"代码": "000001", "名称": "平安银行", "最新价": "11.2", "涨跌幅": "2", "量比": "-", "成交额": "100000000"}])
    assert rows[0]["code"] == "000001"
    assert rows[0]["amount"] == 100000000
    assert rows[0]["volume_ratio"] is None
    assert rows[0]["quote_date"] is None

def test_bj_new_codes_and_sz_directory():
    rows = normalize_directory([{"证券代码": "920001", "证券简称": "样本", "上市日期": "2020-01-01", "所属行业":"软件服务"}], "北交所")
    assert rows[0]["board"] == "北交所"
    assert rows[0]["industry"] == "软件服务"
    rows = normalize_directory([{"A股代码": "000001", "A股简称": "样本", "A股上市日期": "1991-04-03", "板块": "主板", "所属行业":"银行"}], "深圳")
    assert rows[0]["board"] == "深市主板"
    assert rows[0]["industry"] == "银行"


def test_shanghai_directory_keeps_exchange_industry(monkeypatch):
    from screener.worker import shanghai_directory
    import requests
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {"result":[{"A_STOCK_CODE":"600000", "SEC_NAME_CN":"浦发银行",
                "LIST_DATE":"19991110", "CSRC_CODE_DESC":"银行业"}]}
    monkeypatch.setattr(requests, "get", lambda *a, **k: Response())
    rows = shanghai_directory("沪市主板")
    assert rows == [{"code":"600000", "name":"浦发银行", "listed":"1999-11-10",
                     "board":"沪市主板", "industry":"银行业"}]

def test_history_requires_matching_unadjusted_latest_bar():
    rows = [{"日期": "2026-10-19", "开盘": 10, "最高": 11, "最低": 9, "收盘": 10, "成交量": 100}]
    h = normalize_history(rows, rows)
    assert h["comparable"] and h["basis_date"] == "2026-10-19"
    bad = [rows[0] | {"收盘": 9}]
    assert not normalize_history(rows, bad)["comparable"]


def test_history_compares_raw_bar_on_adjusted_basis_when_raw_feed_is_ahead():
    adjusted = [{"日期":"2026-10-22", "开盘":9.66, "最高":9.73,
                 "最低":9.55, "收盘":9.62, "成交量":100}]
    raw = adjusted + [{"日期":"2026-10-23", "开盘":9.69, "最高":9.73,
                       "最低":9.52, "收盘":9.53, "成交量":110}]
    assert normalize_history(adjusted, raw)["comparable"]

def test_tencent_timestamp_and_amount_units():
    f = [""] * 60
    for i, v in {1:"平安银行", 2:"000001", 3:"11.2", 6:"100", 30:"20261019145959", 32:"2.5", 37:"1234.5", 49:"1.8"}.items():
        f[i] = v
    row = parse_tencent('v_sz000001="' + '~'.join(f) + '";')[0]
    assert row["quote_date"] == "2026-10-19"
    assert row["amount"] == 12345000
    assert row["volume_ratio"] == 1.8

def test_rate_limit_does_not_enter_sdk_retry_loop(monkeypatch):
    import requests
    import pytest
    from akshare.utils.func import fetch_paginated_data
    from screener.worker import install_transport_guard
    retry = fetch_paginated_data.__globals__["request_with_retry"]
    attempts = []
    def limited_send(self, request, **kwargs):
        attempts.append(request.url)
        response = requests.Response()
        response.status_code = 429
        response._content = b'{}'
        response.request = request
        return response
    monkeypatch.setattr(requests.sessions.Session, "send", limited_send)
    install_transport_guard()
    with pytest.raises(RuntimeError, match="429"):
        retry("https://example.invalid/test", params={})
    assert len(attempts) == 1
