import pandas as pd
import pytest
from screener.indicators import add_indicators, assess_trend, make_detail_chart

def bars(prices):
    return [dict(date=d.strftime("%Y-%m-%d"), open=p, close=p, high=p+1, low=p-1, volume=100)
            for d,p in zip(pd.bdate_range("2026-01-01", periods=len(prices)), prices)]

def test_ma_warmup_and_values_use_only_past_bars():
    df = add_indicators(bars(list(range(1,31))))
    assert pd.isna(df.MA5.iloc[3])
    assert df.MA5.iloc[4] == 3
    assert df.MA10.iloc[9] == 5.5
    assert df.MA20.iloc[19] == 10.5
    assert add_indicators(bars(list(range(1,31))+[999])).MA20.iloc[19] == 10.5

@pytest.mark.parametrize("prices,state", [(list(range(10,40)),"偏进攻"),
                                          (list(range(40,10,-1)),"偏防守"),
                                          ([20]*30,"震荡观察")])
def test_explainable_trend_states(prices, state):
    result = assess_trend(add_indicators(bars(prices)))
    assert result["state"] == state
    assert len(result["evidence"]) == 4

def test_insufficient_or_bad_close_cannot_be_classified():
    assert assess_trend(add_indicators(bars([20]*20)))["state"] == "数据不足"
    rows = bars(list(range(10,40)))
    rows[-2]["close"] = None
    assert assess_trend(add_indicators(rows))["state"] == "数据不足"

def test_regression_line_is_recent_fit_and_no_future_projection():
    df = add_indicators(bars(list(range(10,40))))
    assert df.trend.dropna().tolist() == pytest.approx(list(range(20,40)))
    assert df.trend.iloc[:10].isna().all()
    assert assess_trend(df)["slope"] == pytest.approx(1)

def test_duplicate_dates_rejected_and_input_not_mutated():
    rows = bars(list(range(10,40)))
    with pytest.raises(ValueError, match="重复"):
        add_indicators(rows+[rows[-1]])
    df = add_indicators(rows)
    assert "MA5" not in rows[0]
    fig = make_detail_chart(df)
    names = {trace.name for trace in fig.data}
    assert {"MA5", "MA10", "MA20", "近20根趋势线", "前复权日K"} <= names

def test_snakea_triple_sma_and_inclusive_13_bar_high():
    df = add_indicators(bars([10,12,14] + [10]*27))
    assert df.B2.iloc[:3].tolist() == pytest.approx([10,10.25,10.875])
    assert df.SNAKEA.iloc[:12].isna().all()
    assert df.SNAKEA.iloc[12] == max(df.B2.iloc[:13])
    assert df.SNAKEA.iloc[15] == max(df.B2.iloc[3:16])
    extended = add_indicators(bars([10,12,14] + [10]*27 + [999]))
    pd.testing.assert_series_equal(df.SNAKEA, extended.SNAKEA.iloc[:30])
    fig = make_detail_chart(df, display_bars=5)
    trace = next(t for t in fig.data if t.name == "SNAKEA")
    assert list(trace.y) == pytest.approx(df.SNAKEA.tail(5).tolist())
    assert "SNAKEA" not in {t.name for t in make_detail_chart(df, show_snakea=False).data}

def test_snakea_does_not_bridge_invalid_close():
    rows = bars([20]*30)
    rows[14]["close"] = None
    df = add_indicators(rows)
    assert pd.isna(df.B2.iloc[14])
    assert df.SNAKEA.iloc[14:27].isna().all()
    assert df.SNAKEA.iloc[27] == 20

def test_stop_lower_formula_and_chart_toggle():
    df = add_indicators(bars([10]*20 + [1]*5))
    assert df.stop_sma2.iloc[19] == pytest.approx(10)
    assert df.stop_floor.iloc[19] == pytest.approx(10)
    assert df.stop_red.iloc[19] == pytest.approx(df.B2.iloc[19])
    assert pd.isna(df.stop_green.iloc[19])
    # The two original predicates are independent and can overlap.
    assert df.stop_red.iloc[-1] == pytest.approx(df.B2.iloc[-1])
    assert df.stop_green.iloc[-1] == pytest.approx(df.B2.iloc[-1])
    assert df.stop_red.iloc[:9].isna().all()
    fig = make_detail_chart(df, show_stop=True)
    assert {"停损下限·红", "停损下限·绿"} <= {trace.name for trace in fig.data}
    hidden = make_detail_chart(df, show_stop=False)
    assert not any(trace.name.startswith("停损下限") for trace in hidden.data)
