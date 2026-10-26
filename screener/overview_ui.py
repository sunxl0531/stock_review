"""Whole-market data entry and local market breadth dashboard."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from .service import Service
from .workspace import market_statistics
from .data_refresh import MarketRefresh
from .review import ReviewRepository


def render_overview(store, demo):
    st.subheader("今日概览")
    st.caption("先获取数据，再查看市场统计、筛选股票和本地复盘。切换页面不会联网。")
    data_panel(store, demo)


@st.fragment(run_every=3)
def data_panel(store, demo):
    svc = Service(store)
    repo = ReviewRepository(store)
    active = repo.active()
    with st.expander("数据来源与获取设置", expanded=not svc.directory()):
        quote_source = st.selectbox("行情来源", ["腾讯", "东方财富"], key="market_source", disabled=bool(active))
        history_options = ["腾讯（默认）", "东方财富（备用）"]
        choice = st.selectbox("历史数据来源", history_options,
            index=history_options.index(store.get("history_source")) if store.get("history_source") in history_options else 0,
            key="market_history_source", disabled=bool(active))
        store.put("history_source", choice)
        workers = st.selectbox("并发请求线程数", list(range(1,11)), index=4, key="overview_workers", disabled=bool(active))
        st.caption("一次获取包含：目录、行业、交易日历、全市场报价、停牌资料和日K。已有收盘日K复用，其他增量更新。首次获取较慢；接口限流会暂停并保留缓存。")
    if st.button("获取／更新所有数据", type="primary", disabled=demo or bool(active), key="market_refresh"):
        try:
            MarketRefresh(store).start(workers, "tencent" if quote_source == "腾讯" else "eastmoney",
                "tencent" if choice.startswith("腾讯") else "eastmoney")
            st.rerun(scope="fragment")
        except Exception as exc:
            st.error(str(exc))
    state = store.get("market:refresh", {})
    if state:
        status = state.get("status")
        if status == "running" and active != "market-data":
            st.warning("上次获取进程已退出，可以重新点击获取；本地缓存会被复用。")
        st.caption(f"{state.get('current', '')} · 最后更新 {state.get('updated_at','')} · 目标交易日 {state.get('target','待确定')}")
        st.progress(min(state.get("processed",0)/state["total"],1.0) if state.get("total") else 0,
            text=f"日K已处理 {state.get('processed',0)} / {state.get('total',0)} · 成功 {state.get('success',0)} · 目标日未返回 {state.get('missing',0)}")
        if active == "market-data" and st.button("停止获取", key="market_stop"):
            store.put("market:stop", True)
            st.info("已请求停止，等待当前请求结束。")
        if state.get("errors"):
            with st.expander(f"获取异常 · {len(state['errors'])} 项"):
                for error in state["errors"][:30]:
                    st.write(error)
    snapshot = store.get("quotes", {})
    rows = svc.rows()
    target = svc.as_of()
    st.caption(f"数据交易日：{target if snapshot else '未获取'} · 行情获取时间：{snapshot.get('fetched_at','未获取')} · {snapshot.get('source','')}。不同日期或缺失报价列为未知。")
    if not rows:
        st.info("暂无本地数据，点击上方获取按钮开始。")
    else:
        stats = market_statistics(rows, "board", target)
        cols = st.columns(5)
        for col, label in zip(cols, ("股票数", "上涨", "下跌", "平盘", "未知")):
            col.metric(label, sum(r[label] for r in stats))
        st.subheader("各市场涨跌分布")
        st.dataframe(pd.DataFrame(stats).rename(columns={"分组":"市场"}), hide_index=True, use_container_width=True)
        st.subheader("行业板块")
        st.caption("按交易所提供的行业分类统计；未提供行业单列。点击表头可排序。")
        order = st.selectbox("板块排序", ["上涨占比 %", "上涨", "下跌", "股票数"], key="sector_sort")
        sectors = pd.DataFrame(market_statistics(rows, "industry", target)).sort_values(order, ascending=False, na_position="last")
        limit = st.selectbox("图表显示", [10,20,50,"全部"], key="sector_limit")
        shown = sectors if limit == "全部" else sectors.head(limit)
        fig = go.Figure()
        for name,color in (("上涨","#df4949"),("下跌","#14856a"),("平盘","#94a3b8"),("未知","#d8dde5")):
            fig.add_trace(go.Bar(name=name, x=shown[name], y=shown["分组"], orientation="h", marker_color=color))
        fig.update_layout(barmode="stack", height=max(320, 28*len(shown)+80), margin=dict(l=0,r=10,t=10,b=10),
            yaxis=dict(autorange="reversed"), legend=dict(orientation="h"), xaxis_title="股票数量")
        st.plotly_chart(fig, use_container_width=True, key="sector_chart")
        st.dataframe(sectors.rename(columns={"分组":"行业板块"}), hide_index=True, use_container_width=True)
    if st.button("查看完整复盘与设置", key="overview_view_review"):
        st.session_state.requested_page = "每日复盘"
        st.rerun()
    with st.expander("基础资料覆盖与请求记录"):
        st.caption(f"本地数据目录：{store.path.parent}")
        st.dataframe(pd.DataFrame(store.logs()), hide_index=True, use_container_width=True)
