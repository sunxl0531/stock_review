"""Optional offline screening using the original saved conditions."""
from dataclasses import replace
import pandas as pd
import streamlit as st
from .core import BOARDS, Filters, LABELS, screen, export_csv
from .service import Service


def render_filters(store, demo):
    svc = Service(store)
    rows = svc.rows()
    calendar = store.get("calendar", {}).get("days", [])
    as_of = svc.as_of()
    # Restore independently saved settings when switching data modes.
    mode = "demo" if demo else "live"
    if st.session_state.get("settings_mode") != mode:
        defaults = dict(boards=list(BOARDS), exclude_st=True, exclude_suspended=True, exclude_new=True,
                        use_change=False, change_min=2.0, change_max=7.0, use_ratio=False, ratio_min=1.5,
                        use_amount=False, amount_min=1.0, use_breakout=False, breakout_days=20,
                        ma_bullish=False, snakea_cross=False)
        defaults.update(store.get("settings", {}))
        for key, value in defaults.items():
            st.session_state[key] = value
        st.session_state.settings_mode = mode

    with st.expander("筛选条件", expanded=False):
        st.subheader("筛选条件")
        boards = st.multiselect("市场范围", BOARDS, key="boards")
        exclude_st = st.checkbox("排除 ST / *ST", key="exclude_st")
        exclude_suspended = st.checkbox("排除停牌", key="exclude_suspended")
        exclude_new = st.checkbox("排除上市不足60个交易日", key="exclude_new")
        st.divider()
        use_change = st.checkbox("涨跌幅区间", key="use_change")
        left, right = st.columns(2)
        change_min = left.number_input("最低 %", step=0.5, key="change_min", disabled=not use_change)
        change_max = right.number_input("最高 %", step=0.5, key="change_max", disabled=not use_change)
        use_ratio = st.checkbox("放量：量比下限", key="use_ratio")
        ratio_min = st.number_input("最低量比", min_value=0.0, step=0.1, key="ratio_min", disabled=not use_ratio)
        use_amount = st.checkbox("成交额下限", key="use_amount")
        amount_min = st.number_input("最低成交额（亿元）", min_value=0.0, step=0.5, key="amount_min", disabled=not use_amount)
        use_breakout = st.checkbox("突破历史高点", key="use_breakout")
        breakout_days = st.selectbox("此前交易日数", [20, 60], key="breakout_days", disabled=not use_breakout)
        ma_bullish = st.checkbox("均线多头：MA5 > MA10 > MA20", key="ma_bullish")
        snakea_cross = st.checkbox("日K收盘价上穿 SNAKEA", key="snakea_cross")
        if ma_bullish or snakea_cross:
            st.caption("使用缓存前复权日线。上穿：上一根收盘价≤当根SNAKEA，本根收盘价>当根SNAKEA。盘中日K未收盘，信号可能变化；刷新行情不会更新日线。")
        st.caption("启用的条件需同时满足。切换条件不会请求接口。")
        settings = {key: st.session_state[key] for key in ["boards", "exclude_st", "exclude_suspended", "exclude_new",
            "use_change", "change_min", "change_max", "use_ratio", "ratio_min", "use_amount", "amount_min", "use_breakout", "breakout_days",
            "ma_bullish", "snakea_cross"]}
        store.put("settings", settings)

    try:
        filters = Filters(tuple(boards), exclude_st, exclude_suspended, exclude_new,
                          change_min if use_change else None, change_max if use_change else None,
                          ratio_min if use_ratio else None, amount_min * 1e8 if use_amount else None,
                          breakout_days if use_breakout else None, ma_bullish=ma_bullish, snakea_cross=snakea_cross)
    except ValueError as exc:
        st.error(str(exc))
        return
    needs_history = use_breakout or ma_bullish or snakea_cross
    histories = svc.histories([r["code"] for r in rows]) if needs_history else {}
    results = screen(rows, filters, calendar, histories, as_of)
    matched = [r for r in results if r["result"] == "匹配"]
    unknown = [r for r in results if r["result"] == "无法判定"]
    cols = st.columns(4)
    for col, label, count in zip(cols, ["缓存股票", "符合条件", "无法判定", "已排除"], [len(rows), len(matched), len(unknown), len(results)-len(matched)-len(unknown)]):
        col.metric(label, f"{count:,}")
    if unknown:
        st.warning(f"{len(unknown)} 只股票因资料或历史不足无法判定；当前结果不代表全部股票均已完成筛选。")

    tab = st.radio("查看", ["匹配结果", "无法判定", "全部股票", "我的自选"], horizontal=True)
    display = matched if tab == "匹配结果" else unknown if tab == "无法判定" else results
    if tab == "我的自选":
        display = [r for r in results if r["code"] in store.watchlist()]
    search = st.text_input("搜索代码或名称", placeholder="例如：000001 或 平安")
    display = [r for r in display if not search or search in r["code"] or search in (r.get("name") or "")]
    if display:
        frame = pd.DataFrame(display).reindex(columns=list(LABELS)).rename(columns=LABELS)
        st.dataframe(frame, hide_index=True, use_container_width=True, height=420)
        st.download_button("导出当前结果 CSV", export_csv(display), "筛选结果.csv", "text/csv")
    else:
        st.info("当前视图没有股票。可调整条件，或查看“无法判定”中的原因。")
