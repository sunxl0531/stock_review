"""Read-only watchlist tracking from saved reviews and cached K-lines."""
import pandas as pd
import streamlit as st

from .indicators import add_indicators, make_detail_chart
from .review import ReviewRepository
from .review_compare import comparable_previous, compare_reviews
from .review_metrics import review_metrics
from .service import Service
from .store import now


def latest_history_metrics(history):
    if not history or not history.get("bars"):
        return None
    try:
        bars = [r for r in history["bars"] if r["date"] <= history["basis_date"]]
        df = add_indicators(bars)
        if len(df) < 2:
            return None
        last, previous = df.iloc[-1], df.iloc[-2]
        return review_metrics({"close":last.close, "snakea":last.SNAKEA,
                               "snakea_previous":previous.SNAKEA,
                               "indicator_date":last.date, "history":history}) | {"indicator_date":last.date}
    except (ValueError, TypeError, KeyError):
        return None


def build_watch_rows(codes, directory, results, target, changes=None, quotes=None, histories=None):
    names = {r["code"]:r for r in directory}
    by_code = {r["code"]:r for r in results}
    by_quote = {r["code"]:r for r in (quotes or [])}
    labels = {}
    for group, label in (("new","新入选"),("continued","持续入选"),
                         ("exited","今日退出"),("uncertain","待确认")):
        for result in (changes or {}).get(group, []):
            labels[result["code"]] = label
    rows = []
    for code in sorted(set(codes)):
        result = by_code.get(code, {})
        stock = names.get(code, {})
        quote = by_quote.get(code, {})
        current_values = latest_history_metrics((histories or {}).get(code))
        values = current_values or review_metrics(result)
        status = {"match":"入选", "no_match":"未入选", "unknown":"无法判定",
                  "error":"请求失败", "excluded":"已排除"}.get(result.get("outcome"), "未覆盖")
        rows.append({"代码":code,"名称":result.get("name") or stock.get("name") or quote.get("name") or "",
                     "市场":result.get("board") or stock.get("board") or "",
                     "最新价":quote.get("price"),"涨跌幅 %":quote.get("change_pct"),
                     "量比":quote.get("volume_ratio"),"成交额（元）":quote.get("amount"),
                     "行情时间":quote.get("quote_time") or quote.get("quote_date") or "未刷新",
                     "复盘日期":target if result else "", "复盘状态":status,
                     "较上次":labels.get(code, "无可比记录" if result else "未覆盖"),
                     "距SNAKEA %":values["distance_pct"],
                     "SNAKEA日变化 %":values["snakea_change_pct"],
                     "指标日线日期":values.get("indicator_date") or result.get("indicator_date") or "数据不足",
                     "停损下限":values["stop_lower"],"停损显示":values["stop_color"] or "数据不足"})
    return rows


def render_watchlist(store, demo):
    st.subheader("自选股跟踪")
    st.caption("打开本页只读本地数据；点击刷新按钮后才请求自选股行情和日K。")
    codes = store.watchlist()
    if not codes:
        st.info("自选股为空。可在股票筛选的个股详情或每日复盘结果中加入自选。")
        return
    update_daily = st.checkbox("同时更新所有自选股日K", value=True, key="watch_update_daily",
                               help="每只股票通常至少2次历史接口请求；关闭后只批量刷新最新报价。")
    st.caption(f"本次将批量请求 {len(codes)} 只自选股报价" + (f"，并逐只更新日K（通常至少{2*len(codes)}次历史请求）" if update_daily else ""))
    if st.button("刷新全部自选股行情", type="primary", disabled=demo, key="watch_refresh_all"):
        service = Service(store)
        try:
            quote_count = service.refresh_watchlist_quotes(codes)
        except Exception as exc:
            st.error(f"自选股行情刷新失败，旧缓存已保留：{exc}")
        else:
            updated, errors = 0, []
            if update_daily:
                watch_quotes = {r["code"]:r for r in store.get("watch_quotes", {}).get("rows", [])}
                days = [d for d in store.get("calendar", {}).get("days", []) if d <= now()[:10]]
                fallback_date = days[-1] if days else service.as_of()
                history_choice = store.get("history_source", "腾讯（默认）")
                source = "eastmoney" if history_choice.startswith("东方财富") else "tencent"
                progress = st.progress(0, text="开始更新自选股日K")
                for index, stock_code in enumerate(codes):
                    try:
                        target = max(watch_quotes.get(stock_code, {}).get("quote_date") or fallback_date, fallback_date)
                        service.fetch_history(stock_code, source, target_date=target)
                        updated += 1
                    except Exception as exc:
                        errors.append(f"{stock_code}：{exc}")
                        if any(token in str(exc).lower() for token in ("429", "403", "限流", "quota")):
                            progress.progress((index+1)/len(codes), text="接口限流，已停止后续请求")
                            break
                    progress.progress((index+1)/len(codes), text=f"已处理 {index+1}/{len(codes)} 只 · {stock_code}")
            st.session_state.watch_refresh_summary = (f"已刷新 {quote_count}/{len(codes)} 只自选股报价；"
                f"日K成功 {updated}/{len(codes)} 只。" if update_daily else f"已刷新 {quote_count}/{len(codes)} 只自选股报价。")
            st.session_state.watch_refresh_errors = errors
            st.rerun()
    if st.session_state.get("watch_refresh_summary"):
        st.success(st.session_state.watch_refresh_summary)
        for error in st.session_state.get("watch_refresh_errors", [])[:5]:
            st.warning(error)
        if len(st.session_state.get("watch_refresh_errors", [])) > 5:
            st.caption(f"另有 {len(st.session_state.watch_refresh_errors)-5} 只更新失败，可查看请求记录。")
    watch_snapshot = store.get("watch_quotes", {})
    if watch_snapshot:
        st.caption(f"自选报价最近手动获取：{watch_snapshot.get('fetched_at', '未知')}；每只股票实际行情时间见表格。")
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
    histories = {code:store.get("history:"+code) for code in codes}
    rows = build_watch_rows(codes, Service(store).directory(), results, target, changes,
                            quotes=watch_snapshot.get("rows", []), histories=histories)
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
