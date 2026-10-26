"""Daily review page. Viewing saved results never requests market data."""
from datetime import date
from collections import Counter
import pandas as pd
import streamlit as st

from .core import BOARDS
from .indicators import add_indicators, make_detail_chart
from .review import ReviewRepository, ReviewRunner
from .review_compare import comparable_previous, compare_reviews
from .review_metrics import review_metrics
from .review_export import review_excel
from .store import now

STATUS = {"ready":"待开始", "running":"扫描中", "paused":"已暂停", "done":"扫描完成", "partial":"存在请求失败"}
COLUMNS = {"code":"代码", "name":"名称", "industry":"行业板块",
           "above_days":"连续站上天数", "break_date":"突破日期",
           "close":"日K收盘价", "snakea":"SNAKEA", "snakea_direction":"SNAKEA方向",
           "distance_pct":"距SNAKEA %", "snakea_change_pct":"SNAKEA日变化 %",
           "stop_lower":"停损下限", "stop_color":"停损显示",
           "reason":"入选原因", "verification":"数据依据", "data_fetched_at":"行情获取时间"}


def render_review(store, demo):
    st.subheader("每日复盘 · SNAKEA")
    st.write("站上 1～2 天直接入选；连续站上超过 2 天，仅在 SNAKEA 上行时入选。")
    st.caption("站上=日K收盘价严格大于同日SNAKEA；上行=最新一根SNAKEA高于前一根。按沪深主板、创业板、科创板、北交所分组。")
    st.info("复盘只使用本地日K，不重复请求全市场数据。请先在今日概览更新数据；缺失目标日K会列为无法判定。")
    st.caption(f"本地数据库：{store.path}。迁移电脑时保留整个 data 文件夹即可。")
    if demo:
        st.caption("演示模式不发起复盘扫描。关闭左侧演示模式后可开始真实复盘。")
    review_panel(store, demo)


@st.cache_data(show_spinner=False, max_entries=3)
def cached_review_excel(run, results):
    return review_excel(run, results)


@st.fragment(run_every=3)
def review_panel(store, demo):
    repo = ReviewRepository(store)
    runner = ReviewRunner(repo)
    active = repo.active()
    with st.expander("本次复盘设置", expanded=not repo.runs()):
        boards = st.multiselect("复盘市场", BOARDS, default=list(BOARDS), key="review_boards", disabled=bool(active))
        source_name = st.selectbox("复盘历史来源", ["腾讯", "东方财富"], key="review_source", disabled=bool(active))
        selected_date = st.date_input("复盘日期", value=date.fromisoformat(now()[:10]),
                                      max_value=date.fromisoformat(now()[:10]), key="review_date", disabled=bool(active))
        st.caption("非交易日取此前最近交易日。当前目录用于扫描，不构成历史时点完整上市名单。")
        a,b = st.columns(2)
        exclude_st = a.checkbox("复盘排除 ST / *ST", value=True, key="review_exclude_st", disabled=bool(active))
        exclude_new = b.checkbox("复盘排除上市不足60个交易日", value=True, key="review_exclude_new", disabled=bool(active))
        force_refresh = False
        fast_batch = False
        workers = 5
        st.caption("开始后按本地日K计算，行业信息来自本地目录。数据不足请到今日概览获取。")
    if st.button("开始复盘", type="primary", disabled=demo or bool(active) or not boards, key="review_start"):
        try:
            run = runner.create(dict(boards=boards, source="tencent" if source_name == "腾讯" else "eastmoney",
                                     requested_date=selected_date.isoformat(), exclude_st=exclude_st, exclude_new=exclude_new,
                                     force_refresh=force_refresh, workers=workers, local_only=True,
                                     fast_batch=fast_batch and source_name == "腾讯" and not force_refresh))
            runner.start(run["id"])
            st.session_state.review_run = run["id"]
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    runs = repo.runs()
    if not runs:
        st.info("还没有保存的复盘。每次新复盘单独保存，结果不会覆盖之前的记录。")
        return
    lookup = {r["id"]:r for r in runs}
    if st.session_state.get("review_run") not in lookup:
        st.session_state.review_run = runs[0]["id"]
    run_id = st.selectbox("查看已保存复盘", list(lookup), key="review_run",
        format_func=lambda k:f"{lookup[k].get('target') or lookup[k]['config']['requested_date']} · {lookup[k]['created_at'][11:19]} · {STATUS[lookup[k]['status']]}")
    run = repo.get(run_id)
    results = repo.results(run_id, include_history=False)
    prior = comparable_previous(runs, run)
    previous_results = repo.results(prior["id"], include_history=False) if prior else []
    changes = compare_reviews(previous_results, results) if prior else None
    counts = Counter(r["outcome"] for r in results)
    total = run["total"]
    st.write(f"**{STATUS[run['status']]}** · 复盘交易日：{run.get('target') or '待获取'}")
    if active and active != run_id:
        st.info("另一次复盘正在后台运行，可在上方选择该记录查看或停止。")
    st.progress(min(len(results)/total,1.0) if total else 0.0,
                text=f"已处理 {len(results)} / {total or '待加载'} · {run.get('current','')}")
    columns = st.columns(5)
    for col, label, value in zip(columns, ["符合","未符合","已排除","无法判定","请求失败"],
                                 [counts[k] for k in ("match","no_match","excluded","unknown","error")]):
        col.metric(label, value)
    cache_counts = Counter(r.get("cache_mode") for r in results)
    st.caption(f"历史读取：批量初筛 {cache_counts['batch']} · 收盘行情补日K {cache_counts['spot_close']} · 本地复用 {cache_counts['local']} · 增量更新 {cache_counts['incremental']} · 首次/换源获取 {cache_counts['full']} · 价格基准变化后重取 {cache_counts['rebase']}")
    if cache_counts["batch"]:
        st.warning(f"{cache_counts['batch']} 只未入选股票由批量当日行情和本地历史初筛，未逐只校验当天前复权价格；除权等情况可能使筛选结果变化。需要严格核验时，重新开始复盘并关闭“快速复盘”。")
    st.caption(f"开始：{run['created_at']} · 最近更新：{run['updated_at']}。每只股票独立请求，非同一时刻快照；收盘前日K可能变化。")
    saved = run["config"]
    st.caption("本记录使用本地缓存计算" if saved.get("local_only") else "旧版联网复盘记录")
    st.caption(f"本记录来源：{'腾讯' if saved['source']=='tencent' else '东方财富'} · 排除ST：{'是' if saved.get('exclude_st') else '否'} · 排除上市不足60个交易日：{'是' if saved.get('exclude_new') else '否'}")
    if counts["unknown"] or counts["error"] or len(results) < total or not total:
        st.warning("本次仍有未处理、失败或无法判定的股票，当前符合列表不是完整市场结论。")
    if run['status'] in ('done', 'partial') and active != run_id:
        st.download_button('导出个股明细 Excel', data=cached_review_excel(run, results),
            file_name=f"每日复盘_{run.get('target') or saved['requested_date']}_{run_id[:8]}.xlsx",
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            key='review_export:'+run_id, on_click='ignore')
        st.caption('导出所选复盘记录：复盘概要、符合个股、全部明细（含未符合及无法判定原因）。')
    if changes:
        st.caption(f"与 {prior['target']} 复盘比较；两次均有明确结果才判定变化。扫描未完成时仅为暂时结果。")
        change_cols = st.columns(4)
        for col, label, key in zip(change_cols, ("新入选", "持续入选", "今日退出", "待确认"),
                                   ("new", "continued", "exited", "uncertain")):
            col.metric(label, len(changes[key]))
    if run.get("error"):
        st.error(run["error"])
    if active == run_id:
        if st.button("停止复盘", key="review_stop"):
            repo.stop(run_id)
            st.info("已请求停止，当前接口请求结束后停止（单次任务最长约90秒）。")
    elif run["status"] != "done":
        if st.button("继续复盘／重试失败项", disabled=demo or bool(active), key="review_resume"):
            try:
                # Speed controls may be changed when continuing an existing scan.
                # Keep its date, source and screening exclusions frozen.
                run["config"]["local_only"] = True
                run["config"]["workers"] = workers
                run["config"]["fast_batch"] = fast_batch and run["config"]["source"] == "tencent" and not run["config"].get("force_refresh", False)
                repo.save(run)
                runner.start(run_id)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        if run["status"] == "running":
            st.caption("上次进程可能已退出。任务占用到期后可继续，已成功处理的股票不会重复请求。")
    view = st.radio("结果视图", ["全部入选", "新入选", "持续入选", "今日退出", "待确认"],
                    horizontal=True, key="review_change_view") if changes else "全部入选"
    view_key = "review_active_view:"+run_id
    if st.session_state.get(view_key) != view:
        st.session_state.pop("review_selected:"+run_id, None)
        st.session_state[view_key] = view
    key_by_view = {"新入选":"new", "持续入选":"continued", "今日退出":"exited", "待确认":"uncertain"}
    matches = ([r for r in results if r["outcome"] == "match"] if view == "全部入选"
               else changes[key_by_view[view]])
    if not matches:
        st.info("当前视图暂无股票。")
    selected_code = st.session_state.get("review_selected:"+run_id)
    industry_by_code = {row["code"]:row.get("industry") for source_board in
        ("沪市主板", "科创板", "深圳", "北交所")
        for row in store.get("directory:"+source_board, {}).get("rows", [])}
    for board in run["config"]["boards"]:
        group = sorted([r for r in matches if r.get("board") == board],
                       key=lambda r:(r.get("above_days", 0),r["code"]))
        with st.expander(f"{board} · {len(group)} 只", expanded=bool(group)):
            if not group:
                st.caption("当前暂无符合股票")
                continue
            st.caption("点击表格行，在下方查看该股K线。")
            displayed = []
            for r in group:
                source_row = (repo.result(run_id, r["code"]) or (repo.result(prior["id"], r["code"]) if prior else None)) if r.get("outcome") == "match" and r.get("stop_lower") is None else r
                displayed.append(r | review_metrics(source_row or r) | {
                    "industry":r.get("industry") or industry_by_code.get(r["code"]) or "未提供",
                    "verification":r.get("verification") or "历史日K",
                    "above_days":f"≥{r.get('above_days','')}" if r.get("above_days_at_least") else str(r.get("above_days", "")),
                    "break_date":r.get("break_date") or "早于可确认区间"})
            event = st.dataframe(pd.DataFrame(displayed).reindex(columns=list(COLUMNS)).rename(columns=COLUMNS),
                                hide_index=True, use_container_width=True, on_select="rerun",
                                selection_mode="single-row", key=f"review_table:{run_id}:{view}:{board}:{len(group)}",
                                column_config={"距SNAKEA %":st.column_config.NumberColumn(format="%.2f%%"),
                                               "SNAKEA日变化 %":st.column_config.NumberColumn(format="%.2f%%"),
                                               "停损下限":st.column_config.NumberColumn(format="%.2f")})
            # Each market's table can retain a selection; only a changed selection takes focus.
            chosen = list(event.selection.rows)
            selection_key = f"review_selection:{run_id}:{board}"
            signature = group[chosen[0]]["code"] if chosen and chosen[0] < len(group) else None
            if signature and signature != st.session_state.get(selection_key):
                selected_code = signature
                st.session_state["review_selected:"+run_id] = signature
            st.session_state[selection_key] = signature
    if selected_code:
        watch = store.watchlist()
        if st.button("移出自选" if selected_code in watch else "加入自选", key=f"review_watch:{run_id}:{selected_code}"):
            store.set_watchlist([c for c in watch if c != selected_code] if selected_code in watch else watch+[selected_code])
            st.rerun()
        result = repo.result(run_id, selected_code)
        chart_target = run["target"]
        if (not result or not result.get("history")) and prior:
            prior_result = repo.result(prior["id"], selected_code)
            if prior_result and prior_result.get("history"):
                result = prior_result
                chart_target = prior["target"]
                st.caption("本次没有保存该股K线，下面展示上次复盘的历史快照。")
        if result and result.get("history"):
            st.subheader(f"{selected_code} · {result.get('name','')} · 复盘K线")
            duration = ("至少" if result.get("above_days_at_least") else "") + str(result["above_days"])
            st.caption(f"连续站上 {duration} 天 · 突破日期 {result['break_date'] or '早于可确认区间'} · SNAKEA {result['snakea_direction']} · 日线截至 {chart_target}")
            bars = [b for b in result["history"]["bars"] if b["date"] <= chart_target]
            from .detail_ui import render_detail
            render_detail(result["history"] | {"bars":bars}, f"review_detail:{run_id}:{selected_code}")

    with st.expander("无法判定、失败及排除原因"):
        other = [r for r in results if r["outcome"] in ("unknown","error","excluded")]
        st.dataframe(pd.DataFrame(other).reindex(columns=["code","name","board","reason"]).rename(
            columns={"code":"代码","name":"名称","board":"市场","reason":"原因"}), hide_index=True, use_container_width=True)
