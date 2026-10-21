"""Read-only watchlist tracking from saved reviews and cached K-lines."""
import pandas as pd
import streamlit as st

from .indicators import add_indicators, make_detail_chart
from .review import ReviewRepository
from .review_compare import comparable_previous, compare_reviews
from .review_metrics import review_metrics
from .service import Service


def build_watch_rows(codes, directory, results, target, changes=None):
    names = {r["code"]:r for r in directory}
    by_code = {r["code"]:r for r in results}
    labels = {}
    for group, label in (("new","新入选"),("continued","持续入选"),
                         ("exited","今日退出"),("uncertain","待确认")):
        for result in (changes or {}).get(group, []):
            labels[result["code"]] = label
    rows = []
    for code in sorted(set(codes)):
        result = by_code.get(code, {})
        stock = names.get(code, {})
        values = review_metrics(result)
        status = {"match":"入选", "no_match":"未入选", "unknown":"无法判定",
                  "error":"请求失败", "excluded":"已排除"}.get(result.get("outcome"), "未覆盖")
        rows.append({"代码":code,"名称":result.get("name") or stock.get("name") or "",
                     "市场":result.get("board") or stock.get("board") or "",
                     "复盘日期":target if result else "", "复盘状态":status,
                     "较上次":labels.get(code, "无可比记录" if result else "未覆盖"),
                     "距SNAKEA %":values["distance_pct"],
                     "SNAKEA日变化 %":values["snakea_change_pct"],
                     "停损下限":values["stop_lower"],"停损显示":values["stop_color"] or "数据不足"})
    return rows


def render_watchlist(store, demo):
    st.subheader("自选股跟踪")
    st.caption("只读取本地自选与复盘记录；打开本页不会刷新行情。")
    codes = store.watchlist()
    if not codes:
        st.info("自选股为空。可在股票筛选的个股详情或每日复盘结果中加入自选。")
        return
    repo = ReviewRepository(store)
    runs = repo.runs()
    latest = runs[0] if runs else None
    results = repo.results(latest["id"], include_history=False) if latest else []
    prior = comparable_previous(runs, latest) if latest else None
    changes = compare_reviews(repo.results(prior["id"], include_history=False), results) if prior else None
    target = (latest.get("target") or latest["config"].get("requested_date")) if latest else None
    if latest:
        st.caption(f"最近复盘：{target} · {latest['status']} · {latest.get('processed',0)} / {latest.get('total') or '待加载'}。未完成时变化仅供暂时查看。")
    else:
        st.info("尚无复盘记录；自选股票仍可查看已有历史K线。")
    rows = build_watch_rows(codes, Service(store).directory(), results, target, changes)
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    choice = st.selectbox("查看自选股票", codes, format_func=lambda c:c+" · "+next(
        (r["名称"] for r in rows if r["代码"] == c), ""), key="watch_detail")
    left, right = st.columns(2)
    if left.button("移出自选", key="watch_remove"):
        store.set_watchlist([c for c in codes if c != choice])
        st.rerun()
    quoted = {r["code"] for r in store.get("quotes", {}).get("rows", [])}
    if right.button("转到个股详情", key="watch_open_detail", disabled=choice not in quoted):
        st.session_state.detail_stock = choice
        st.session_state.requested_page = "股票筛选"
        st.rerun()
    if choice not in quoted:
        st.caption("当前行情缓存尚未包含该股；可在本页查看历史，刷新行情后再转到个股详情。")
    history = store.get("history:"+choice)
    if history and history.get("bars"):
        try:
            st.plotly_chart(make_detail_chart(add_indicators(history["bars"])), use_container_width=True)
            st.caption(f"本地前复权日K · 历史基准日 {history.get('basis_date', '未知')}。本页不会更新数据。")
        except (ValueError, TypeError, KeyError) as exc:
            st.warning(f"历史缓存无法绘图：{exc}")
    else:
        st.info("该股尚无本地历史；可到个股详情手动获取。")
