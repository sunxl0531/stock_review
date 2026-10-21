from datetime import date, timedelta
import pytest
from screener.core import Filters, screen, breakout, export_csv

CAL = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(100)]
TODAY = CAL[80]

def stock(**overrides):
    return dict(code="000001", name="平安银行", board="深市主板", price=11,
                change_pct=2, volume_ratio=1.5, amount=100000000,
                listed=CAL[0], suspended=False, status_date=TODAY,
                quote_date=TODAY, **{}) | overrides

def test_range_boundaries_and_missing_ratio():
    rows = [stock(), stock(code="000002", volume_ratio=None), stock(code="000003", change_pct=1.99)]
    result = screen(rows, Filters(change_min=2, change_max=7, ratio_min=1.5), CAL, {}, TODAY)
    assert [x["result"] for x in result] == ["匹配", "无法判定", "未匹配"]

def test_default_exclusions_and_sixty_market_days():
    rows = [stock(name="*ST测试"), stock(suspended=True), stock(listed=CAL[22]),
            stock(listed=CAL[21]), stock(listed=None), stock(suspended=None)]
    assert [x["result"] for x in screen(rows, Filters(), CAL, {}, TODAY)] == [
        "未匹配", "未匹配", "未匹配", "匹配", "无法判定", "无法判定"]

def test_empty_markets_and_stale_status_do_not_match():
    assert screen([stock()], Filters(boards=()), CAL, {}, TODAY)[0]["result"] == "未匹配"
    assert screen([stock(status_date=CAL[79])], Filters(), CAL, {}, TODAY)[0]["result"] == "无法判定"

def test_calendar_must_cover_as_of_date():
    assert screen([stock()], Filters(), CAL[:70], {}, TODAY)[0]["result"] == "无法判定"

def history():
    return {"basis_date": TODAY, "comparable": True,
            "bars": [{"date": d, "high": 10, "close": 9} for d in CAL[60:81]]}

def test_breakout_excludes_today_and_requires_strict_greater():
    h = history()
    h["bars"][-1]["high"] = 99
    assert breakout(stock(), h, 20, CAL, TODAY)[0] is True
    assert breakout(stock(price=10), h, 20, CAL, TODAY)[0] is False

def test_breakout_missing_dates_or_basis_is_unknown():
    h = history()
    h["bars"].pop(0)
    assert breakout(stock(), h, 20, CAL, TODAY)[0] is None
    h = history() | {"basis_date": CAL[79]}
    assert breakout(stock(), h, 20, CAL, TODAY)[0] is None

def test_known_failure_wins_over_missing_data():
    row = stock(change_pct=-10, volume_ratio=None)
    assert screen([row], Filters(change_min=2, ratio_min=2), CAL, {}, TODAY)[0]["result"] == "未匹配"

def test_export_preserves_code_and_prevents_formula_names():
    raw = export_csv([stock(name="=HYPERLINK(1)", result="匹配")]).decode("utf-8-sig")
    assert "000001" in raw and "'=HYPERLINK(1)" in raw

def test_invalid_filter_range_rejected():
    with pytest.raises(ValueError):
        Filters(change_min=7, change_max=2)

def test_older_quote_in_mixed_snapshot_cannot_match():
    row = stock(quote_date=CAL[79])
    assert screen([row], Filters(), CAL, {}, TODAY)[0]["result"] == "无法判定"

def technical_history(prices):
    return {"basis_date": TODAY, "comparable": True, "bars": [
        dict(date=d, open=p, high=p+1, low=p-1, close=p, volume=100)
        for d, p in zip(CAL[81-len(prices):81], prices)]}

def test_ma_alignment_filter_and_strict_equality():
    for prices, expected in [(list(range(10,40)), "匹配"), ([20]*30, "未匹配"),
                             (list(range(40,10,-1)), "未匹配")]:
        result = screen([stock()], Filters(ma_bullish=True), CAL,
                        {"000001": technical_history(prices)}, TODAY)[0]
        assert result["result"] == expected
        assert result["indicator_date"] == TODAY

def test_snakea_cross_is_new_cross_not_already_above():
    for prices, expected in [([20]*29+[30], "匹配"),
                             ([20]*28+[30,31], "未匹配"), ([20]*30, "未匹配")]:
        result = screen([stock()], Filters(snakea_cross=True), CAL,
                        {"000001": technical_history(prices)}, TODAY)[0]
        assert result["result"] == expected

def test_technical_filters_require_valid_current_history():
    good = technical_history(list(range(10,40)))
    missing = technical_history(list(range(10,40)))
    missing["bars"].pop(-2)
    duplicate = technical_history(list(range(10,40)))
    duplicate["bars"].append(duplicate["bars"][-1])
    for h in [None, good | {"basis_date":CAL[79]}, missing, duplicate,
              technical_history([20]*12)]:
        result = screen([stock()], Filters(ma_bullish=True, snakea_cross=True),
                        CAL, {"000001":h} if h else {}, TODAY)[0]
        assert result["result"] == "无法判定"

def test_technical_filter_combination_and_no_future_bars():
    h = technical_history([20]*29+[30])
    result = screen([stock()], Filters(ma_bullish=True, snakea_cross=True),
                    CAL, {"000001":h}, TODAY)[0]
    assert result["result"] == "匹配"
    h["bars"].append(h["bars"][-1] | {"date":CAL[81], "close":1})
    assert screen([stock()], Filters(ma_bullish=True, snakea_cross=True),
                  CAL, {"000001":h}, TODAY)[0]["result"] == "匹配"
