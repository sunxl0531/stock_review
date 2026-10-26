"""Shared stock analysis panel."""
import pandas as pd
import streamlit as st
from .indicators import add_indicators, assess_trend, make_detail_chart


def render_detail(h, prefix):
    if not h or not h.get("bars"):
        st.info("尚无该股历史缓存，请点击刷新获取行情和日K。")
        return
    try:
        bars = add_indicators(h["bars"])
    except (ValueError, TypeError) as exc:
        st.error(f"历史数据无法计算指标：{exc}")
        return
    state = assess_trend(bars)
    st.subheader(f"走势状态：{state['state']}")
    st.write(state["summary"])
    st.caption(f"分析截至 {state['date']} 的缓存日K。最新一根可能包含盘中数据，并非收盘确认；不将旧日线当作当前实时走势。")
    mcols = st.columns(4)
    for col, name in zip(mcols, ["MA5","MA10","MA20","SNAKEA"]):
        value = bars[name].iloc[-1]
        col.metric(name, f"{value:.2f}" if pd.notna(value) else "数据不足")
    controls = st.columns([2,1,1,1,1])
    period = controls[0].selectbox("显示范围", ["最近120根","最近60根","全部"], key=prefix+"_period")
    show_ma = controls[1].checkbox("显示5/10/20均线", value=True, key=prefix+"_ma")
    show_trend = controls[2].checkbox("显示趋势线", value=True, key=prefix+"_trend")
    show_snakea = controls[3].checkbox("显示SNAKEA", value=True, key=prefix+"_snakea")
    show_stop = controls[4].checkbox("显示停损下限", value=True, key=prefix+"_stop")
    panel = st.radio("副图指标", ["成交量", "MACD"], horizontal=True, key=prefix+"_panel")
    chart = make_detail_chart(bars, {"最近120根":120,"最近60根":60,"全部":None}[period], show_ma, show_trend, show_snakea, show_stop, panel=panel)
    st.plotly_chart(chart, use_container_width=True, key=prefix+"_chart")
    st.caption("SNAKEA（青色）：三重平滑收盘价 B2 最近13根日K（含当根）的最高值。")
    st.caption("停损下限：条件成立时在B2位置绘制红线或绿线；两条线各自独立，不代表自动买卖信号。")
    with st.expander("走势判断依据与计算口径"):
        st.dataframe(pd.DataFrame(state["evidence"]), hide_index=True, use_container_width=True)
        st.write("偏进攻：MA5 > MA10 > MA20，日K收盘价 ≥ MA5，MA20上行且20根拟合斜率为正。偏防守：上述条件反向。其余为震荡观察。")
        st.caption("均线取前复权收盘价的简单平均；不足窗口不补值。趋势线是最近20根有效日K的最小二乘拟合，仅描述该段走势，不向未来延伸。")
        st.code("B2 = SMA(SMA(SMA(C, 2, 1), 2, 1), 2, 1)\nSMA2 = MA(B2, 3)\nSNAKEA = HHV(MA(B2, 1), 13)\n停损下限红 = IF(LLV(MA(B2, 8), 3) >= SMA2, B2, DRAWNULL)\n停损下限绿 = IF(B2 < SMA2, B2, DRAWNULL)", language="text")
        st.caption("C为前复权收盘价。SMA(X,2,1)=本期X×0.5+上期SMA×0.5，各层以缓存首根有效值初始化；连续满13根才绘制SNAKEA。缺失值处断开并重新初始化，切换显示范围不重新计算。缓存起点与其他软件不同可能产生初期差异。走势状态仍按上述均线和趋势条件判断。")
    st.caption(f"来源：{h.get('source', '旧缓存（来源未记录）')} · 前复权日线 · 历史基准日 {h.get('basis_date')} · 与当前价可比性需通过基准验证")
    st.caption("MACD：DIF=EMA(C,12)−EMA(C,26)，DEA=EMA(DIF,9)，柱值=2×(DIF−DEA)。使用完整缓存计算，切换范围不重置；不作为自动买卖信号。")
