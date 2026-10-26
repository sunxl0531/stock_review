"""Deterministic chart indicators and rule-based descriptions of cached bars."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

def triple_sma(close):
    """Three recursive SMA(X,2,1) passes, seeded at each valid segment's start."""
    values = []
    previous = None
    for value in close:
        if pd.isna(value):
            previous = None
            values.append(np.nan)
            continue
        if previous is None:
            previous = [value, value, value]
        else:
            for i in range(3):
                value = (value + previous[i]) / 2
                previous[i] = value
        values.append(previous[2])
    return pd.Series(values, index=close.index, dtype=float)

def add_indicators(records):
    df = pd.DataFrame(records).copy()
    required = {"date", "open", "high", "low", "close", "volume"}
    if not required <= set(df):
        raise ValueError("日K字段不足，无法计算指标")
    df["date"] = pd.to_datetime(df["date"], errors="raise").dt.strftime("%Y-%m-%d")
    if df.date.duplicated().any():
        raise ValueError("日K日期重复，请重新获取历史")
    df = df.sort_values("date").reset_index(drop=True)
    for column in required - {"date"}:
        df[column] = pd.to_numeric(df[column], errors="coerce").replace([np.inf,-np.inf], np.nan)
    df.loc[df.close <= 0, "close"] = np.nan
    for period in (5, 10, 20):
        df[f"MA{period}"] = df.close.rolling(period, min_periods=period).mean()
    # Restart recursive MACD at gaps; calculate before cropping the chart.
    df["DIF"] = np.nan
    df["DEA"] = np.nan
    for _, segment in df.groupby(df.close.isna().cumsum()):
        valid = segment.close.dropna()
        dif = valid.ewm(span=12, adjust=False).mean() - valid.ewm(span=26, adjust=False).mean()
        df.loc[valid.index, "DIF"] = dif
        df.loc[valid.index, "DEA"] = dif.ewm(span=9, adjust=False).mean()
    df["MACD"] = 2 * (df.DIF - df.DEA)
    df["B2"] = triple_sma(df.close)
    df["SNAKEA"] = df.B2.rolling(13, min_periods=13).max()
    df["stop_sma2"] = df.B2.rolling(3, min_periods=3).mean()
    df["stop_floor"] = df.B2.rolling(8, min_periods=8).mean().rolling(3, min_periods=3).min()
    df["stop_red"] = df.B2.where(df.stop_floor >= df.stop_sma2)
    df["stop_green"] = df.B2.where(df.B2 < df.stop_sma2)
    df["trend"] = np.nan
    slope = None
    if len(df) >= 20 and df.close.tail(20).notna().all():
        values = df.close.tail(20).to_numpy()
        x = np.arange(20, dtype=float)
        slope = float(np.dot(x-x.mean(), values-values.mean()) / np.dot(x-x.mean(), x-x.mean()))
        df.loc[df.index[-20:], "trend"] = values.mean() + slope*(x-x.mean())
    df.attrs["slope"] = slope
    return df

def assess_trend(df):
    result = {"state":"数据不足", "date": df.date.iloc[-1] if len(df) else None,
              "evidence":[], "slope":df.attrs.get("slope"), "summary":"至少需要连续21根有效收盘价，才能比较MA20方向。"}
    if len(df) < 21 or df.close.tail(21).isna().any() or result["slope"] is None:
        return result
    last, previous = df.iloc[-1], df.iloc[-2]
    slope = result["slope"]
    bullish = [last.MA5 > last.MA10 > last.MA20, last.close >= last.MA5,
               last.MA20 > previous.MA20, slope > 0]
    bearish = [last.MA5 < last.MA10 < last.MA20, last.close <= last.MA5,
               last.MA20 < previous.MA20, slope < 0]
    state = "偏进攻" if all(bullish) else "偏防守" if all(bearish) else "震荡观察"
    direction = lambda value: "上行" if value > 1e-10 else "下行" if value < -1e-10 else "走平"
    evidence = [
        {"项目":"均线排列", "现状": "多头：MA5 > MA10 > MA20" if bullish[0] else "空头：MA5 < MA10 < MA20" if bearish[0] else "交织或走平"},
        {"项目":"价格位置", "现状":f"日K收盘价 {last.close:.2f}，MA5 {last.MA5:.2f}，MA20 {last.MA20:.2f}"},
        {"项目":"MA20方向", "现状":f"{direction(last.MA20-previous.MA20)}，较上一根 {last.MA20-previous.MA20:+.3f}"},
        {"项目":"20根趋势", "现状":f"{direction(slope)}，拟合斜率 {slope:+.3f} 元／根"},
    ]
    return result | {"state":state, "evidence":evidence,
        "summary": {"偏进攻":"多头排列、价格位于MA5之上，MA20与近期趋势同向上行。",
                    "偏防守":"空头排列、价格位于MA5之下，MA20与近期趋势同向下行。",
                    "震荡观察":"多空条件尚未一致，暂不归入进攻或防守状态。"}[state]}

def make_detail_chart(df, display_bars=120, show_ma=True, show_trend=True, show_snakea=True, show_stop=True, panel="成交量"):
    shown = df.tail(display_bars) if display_bars else df
    chart = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=.07, row_heights=[.77,.23])
    chart.add_trace(go.Candlestick(x=shown.date, open=shown.open, high=shown.high, low=shown.low, close=shown.close,
                    increasing_line_color="#df4949", decreasing_line_color="#14856a", name="前复权日K"), row=1,col=1)
    if show_ma:
        for name,color in [("MA5","#e9a320"),("MA10","#5274db"),("MA20","#ab52b5")]:
            chart.add_trace(go.Scatter(x=shown.date,y=shown[name],mode="lines",name=name,
                            line=dict(color=color,width=1.6),connectgaps=False,
                            hovertemplate=f"{name} %{{y:.2f}}<extra></extra>"),row=1,col=1)
    if show_snakea:
        chart.add_trace(go.Scatter(x=shown.date,y=shown.SNAKEA,mode="lines",name="SNAKEA",
                        line=dict(color="#009da6",width=2.3),connectgaps=False,
                        hovertemplate="SNAKEA %{y:.2f}<extra></extra>"),row=1,col=1)
    if show_stop:
        for column, name, color in (("stop_red", "停损下限·红", "#df4949"),
                                    ("stop_green", "停损下限·绿", "#14856a")):
            chart.add_trace(go.Scatter(x=shown.date,y=shown[column],mode="lines",name=name,
                            line=dict(color=color,width=3),connectgaps=False,
                            hovertemplate=f"{name} %{{y:.2f}}<extra></extra>"),row=1,col=1)
    if show_trend:
        chart.add_trace(go.Scatter(x=shown.date,y=shown.trend,mode="lines",name="近20根趋势线",
                        line=dict(color="#202c3f",width=2,dash="dash"),connectgaps=False,
                        hovertemplate="拟合趋势 %{y:.2f}<extra></extra>"),row=1,col=1)
    if panel == "MACD":
        chart.add_trace(go.Bar(x=shown.date, y=shown.MACD, name="MACD",
            marker_color=["#df4949" if v >= 0 else "#14856a" for v in shown.MACD]), row=2, col=1)
        for name, color in (("DIF", "#e9a320"), ("DEA", "#5274db")):
            chart.add_trace(go.Scatter(x=shown.date, y=shown[name], name=name,
                mode="lines", connectgaps=False, line=dict(color=color, width=1.6)), row=2, col=1)
        chart.add_hline(y=0, line_width=1, line_color="#b0bac8", row=2, col=1)
    elif panel == "成交量":
        chart.add_trace(go.Bar(x=shown.date,y=shown.volume,name="成交量（手）",showlegend=False,
            marker_color=["#e1a1a1" if c>=o else "#82b9ac" for c,o in zip(shown.close,shown.open)]),row=2,col=1)
    else:
        raise ValueError("未知副图")
    chart.update_layout(height=560,margin=dict(l=10,r=10,t=45,b=10),xaxis_rangeslider_visible=False,
                        hovermode="x unified",legend=dict(orientation="h",y=1.07,x=0))
    chart.update_xaxes(type="category",categoryorder="array",categoryarray=shown.date.tolist(),nticks=10)
    chart.update_yaxes(title_text="价格（元）",row=1,col=1)
    chart.update_yaxes(title_text="MACD (12,26,9)" if panel == "MACD" else "成交量（手）",row=2,col=1)
    return chart
