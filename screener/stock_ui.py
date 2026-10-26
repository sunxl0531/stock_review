"""Search the whole local stock directory and refresh only the chosen stock."""
import pandas as pd
import streamlit as st
from .service import Service
from .workspace import search_stocks
from .detail_ui import render_detail
from .store import now


def render_stock(store, demo):
    service = Service(store)
    st.subheader("个股筛选")
    query = st.text_input("搜索全市场代码或名称", placeholder="输入股票代码或名称，例如：002050、三花", key="stock_search")
    rows = service.rows()
    choices = search_stocks(rows, query)
    if not choices:
        st.info("未找到股票。请检查名称／代码；首次使用请先到今日概览获取数据。")
        return
    lookup = {r["code"]:r for r in choices}
    if st.session_state.get("detail_stock") not in lookup:
        st.session_state.detail_stock = next(iter(lookup))
    selected = st.selectbox("选择股票", list(lookup), format_func=lambda c:c+" · "+(lookup[c].get("name") or ""), key="detail_stock")
    left, right = st.columns([1, 3])
    watch = store.watchlist()
    if left.button("移出自选" if selected in watch else "加入自选", key="stock_watch"):
        store.set_watchlist([c for c in watch if c != selected] if selected in watch else watch+[selected])
        st.rerun()
    if right.button("刷新当前股行情与日K", type="primary", disabled=demo, key="stock_refresh"):
        errors = []
        with st.spinner("更新当前股票…"):
            try:
                service.refresh_watchlist_quotes([selected], preserve_other=True)
            except Exception as exc:
                errors.append("行情："+str(exc))
            try:
                days = [d for d in store.get("calendar", {}).get("days", []) if d <= now()[:10]]
                target = max(days) if days else service.as_of()
                source = "eastmoney" if store.get("history_source", "腾讯").startswith("东方财富") else "tencent"
                service.fetch_history(selected, source, target_date=target)
            except Exception as exc:
                errors.append("日K："+str(exc))
        st.session_state.stock_refresh_result = (selected, errors)
        st.rerun()
    result = st.session_state.get("stock_refresh_result")
    if result and result[0] == selected:
        if result[1]:
            for error in result[1]:
                st.warning(error)
        else:
            st.success("当前股行情和日K已更新。")
    row = lookup[selected]
    extra = next((r for r in store.get("watch_quotes", {}).get("rows", []) if r["code"] == selected), {})
    if (extra.get("quote_time") or extra.get("quote_date") or "") >= (row.get("quote_time") or row.get("quote_date") or ""):
        row = row | extra
    st.subheader(f"{selected} · {row.get('name') or ''}")
    st.caption(f"{row.get('board') or '市场未知'} · {row.get('industry') or '行业未提供'} · 行情时间：{row.get('quote_time') or row.get('quote_date') or '未获取'}")
    cols = st.columns(3)
    for col, label, key in zip(cols, ("最新价", "涨跌幅 %", "量比"), ("price", "change_pct", "volume_ratio")):
        col.metric(label, row.get(key) if row.get(key) is not None else "未获取")
    render_detail(store.get("history:"+selected), "stock")

    with st.expander("全市场条件筛选 · 本地计算"):
        from .filter_ui import render_filters
        render_filters(store, demo)
