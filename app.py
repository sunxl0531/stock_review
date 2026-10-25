from dataclasses import asdict, replace
from pathlib import Path
import os
import pandas as pd
from screener.indicators import add_indicators, assess_trend, make_detail_chart
import streamlit as st
from screener.core import BOARDS, Filters, LABELS, screen, export_csv
from screener.store import Store
from screener.service import Service
from screener.demo import seed

st.set_page_config(page_title="工作台", page_icon="📈", layout="wide", initial_sidebar_state="expanded")
st.markdown("""<style>
.block-container{padding-top:2rem;max-width:1600px} [data-testid=stMetric]{background:#f0f4f8;padding:16px;border-radius:10px}
[data-testid=stMetricValue]{font-size:1.8rem} h1{letter-spacing:-1px} .stCaption{color:#687385}
.st-key-workspace_page [role="radiogroup"]{gap:6px}
.st-key-workspace_page label[data-baseweb="radio"]{padding:12px 16px;margin:0;border-radius:8px;width:100%;box-sizing:border-box;cursor:pointer}
.st-key-workspace_page label[data-baseweb="radio"]:hover{background:#e8eef3}
.st-key-workspace_page label[data-baseweb="radio"]:has(input:checked){background:#176f83;color:white;font-weight:600}
.st-key-workspace_page label[data-baseweb="radio"]>div:first-child{display:none}
.st-key-workspace_page label[data-baseweb="radio"]:focus-within{outline:2px solid #176f83;outline-offset:2px}
</style>""", unsafe_allow_html=True)
ROOT = Path(__file__).resolve().parent
data_dir = Path(os.environ.get("SCREENER_DATA_DIR", str(ROOT / "data")))

if st.session_state.get("requested_page"):
    st.session_state.workspace_page = st.session_state.pop("requested_page")
with st.sidebar:
    st.title("📈 工作台")
    page = st.radio("主菜单", ["今日概览", "股票筛选", "每日复盘", "自选跟踪"],
                    key="workspace_page", label_visibility="collapsed")
    st.divider()
    st.caption("本地工作台 · 手动刷新 · 可携带")
    demo = st.toggle("演示模式（不联网）", key="demo")

store = Store(data_dir / ("demo.db" if demo else "market.db"))
if demo:
    seed(store)
svc = Service(store)
st.title("工作台")
if page == "今日概览":
    from screener.overview_ui import render_overview
    render_overview(store, demo)
    st.stop()
if page == "每日复盘":
    from screener.review_ui import render_review
    st.session_state.settings_mode = "review"
    render_review(store, demo)
    st.stop()
if page == "自选跟踪":
    from screener.watchlist_ui import render_watchlist
    render_watchlist(store, demo)
    st.stop()
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

with st.sidebar:
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

st.subheader("全市场筛选工作台")
st.caption("沪深主板 · 创业板 · 科创板 · 北交所  /  按你的条件，查看可解释的筛选结果")
if demo:
    st.warning("演示模式：下方是合成样例，用于体验操作，不是真实行情。演示日历也仅为样例。")

def perform(label, fn):
    try:
        with st.spinner(label):
            count = fn()
        st.session_state["flash"] = f"{label}完成：{count} 条。"
        st.rerun()
    except Exception as exc:
        st.error(f"{label}失败，已保留旧缓存。{exc}")

if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))

a, b, c = st.columns([2, 1, 3])
source_name = a.selectbox("行情来源", ["腾讯（含行情时间，需先加载目录）", "东方财富（日期缺失时不判断突破）"], disabled=demo)
source = "tencent" if source_name.startswith("腾讯") else "eastmoney"
b.write("")
b.write("")
if b.button("立即刷新行情", type="primary", disabled=demo, use_container_width=True):
    perform("刷新行情", lambda: svc.refresh_quotes(source))
c.info("手动刷新 · 自动刷新已关闭\n\n公开接口额度未知。一次全市场刷新可能包含多个 HTTP 请求。")
history_options = ["腾讯（默认）", "东方财富（备用）"]
if "history_source" not in st.session_state:
    saved_source = store.get("history_source", history_options[0])
    st.session_state.history_source = saved_source if saved_source in history_options else history_options[0]
history_choice = st.selectbox("历史数据来源", history_options, key="history_source", disabled=demo,
                            help="独立于上方实时行情来源。切换本身不联网；获取按钮使用这里的选择。")
history_source = "tencent" if history_choice.startswith("腾讯") else "eastmoney"
store.put("history_source", history_choice)
st.caption("历史默认使用腾讯，东方财富可手动备用。不会在失败后自动多次换源请求。")

with st.expander("基础资料与数据管理 · 首次使用从这里开始", expanded=not svc.directory()):
    st.write("① 更新目录和日历 → ② 刷新行情 → ③ 更新停牌状态。历史数据只在你点击获取时下载。")
    options = {"沪市主板":"沪市主板", "科创板":"科创板", "深市主板和创业板":"深圳", "北交所":"北交所", "交易日历":None}
    chosen = st.multiselect("本次更新项目", list(options), default=list(options), key="basic_selection", disabled=demo)
    st.caption(f"预计 {len(chosen)} 次 SDK 调用，内部可能分页；实际 HTTP 次数未知。仅点击按钮后请求。")
    if st.button("更新所选基础资料", disabled=demo or not chosen):
        status = st.empty()
        errors = []
        for label in chosen:
            status.info("正在获取：" + label)
            try:
                svc.refresh_basic("directory" if options[label] else "calendar", options[label])
            except Exception as exc:
                errors.append(f"{label}：{exc}")
                if any(s in str(exc).lower() for s in ["429", "403", "限流", "quota"]):
                    break
        status.empty()
        if errors:
            for error in errors:
                st.error(error)
        else:
            st.success("基础资料已更新，可刷新行情。")
    if st.button("更新停牌状态", disabled=demo or not store.get("quotes")):
        perform("更新停牌状态", svc.refresh_suspensions)
    st.caption("停牌资料独立获取，行情刷新不会附带请求。状态缺失时，默认筛选会把相关股票列为无法判定。")
    directory = svc.directory()
    snapshot = store.get("quotes", {})
    quoted = {r["code"] for r in snapshot.get("rows", [])}
    coverage = [{"市场": board, "目录股票数": sum(r.get("board")==board for r in directory),
                 "有行情": sum(r.get("board")==board and r["code"] in quoted for r in directory)} for board in BOARDS]
    st.dataframe(pd.DataFrame(coverage), hide_index=True, use_container_width=True)
    calendar_data = store.get("calendar", {})
    st.caption(f"日历覆盖至：{max(calendar_data.get('days', []), default='未加载')} ｜ 本地数据目录：{data_dir}")

snapshot = store.get("quotes", {})
rows = svc.rows()
calendar = store.get("calendar", {}).get("days", [])
as_of = svc.as_of()
st.caption(f"行情来源：{snapshot.get('source', '未加载')} ｜ 最近获取：{snapshot.get('fetched_at', '未刷新')} ｜ 数据交易日：{as_of if snapshot else '未知'}")
if snapshot and not demo:
    st.info("当前显示的是缓存快照。获取时间不代表行情时间；需要新行情时请点“立即刷新行情”。")
if not snapshot:
    st.info("暂无行情。请先更新基础资料，再点击“立即刷新行情”；也可以打开左侧演示模式体验。")
    st.stop()

try:
    filters = Filters(tuple(boards), exclude_st, exclude_suspended, exclude_new,
                      change_min if use_change else None, change_max if use_change else None,
                      ratio_min if use_ratio else None, amount_min * 1e8 if use_amount else None,
                      breakout_days if use_breakout else None, ma_bullish=ma_bullish, snakea_cross=snakea_cross)
except ValueError as exc:
    st.error(str(exc))
    st.stop()
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

if needs_history:
    candidates = [r for r in screen(rows, replace(filters, breakout_days=None, ma_bullish=False, snakea_cross=False), calendar, {}, as_of) if r["result"] == "匹配"]
    by_code = {r["code"]:r for r in results}
    pending = [r["code"] for r in candidates if any(by_code[r["code"]].get(k) == "待判定"
               for k in ("breakout", "ma_state", "snakea_state"))]
    with st.expander(f"筛选历史准备：{len(candidates)-len(pending)} / {len(candidates)} 只候选历史可计算", expanded=bool(pending)):
        st.caption("每只股票通常需至少2次历史接口调用。按你选择的批次获取，不会省略剩余候选。")
        selected = st.multiselect("本次补齐股票", pending, default=pending[:5], disabled=demo)
        st.caption("候选为通过非历史条件的股票。历史不足、日期过期或基准异常均列入待补齐；未获取的股票不会自动算作符合。")
        if st.button(f"获取所选历史（{len(selected)}只）", disabled=demo or not selected):
            progress = st.progress(0)
            for i, stock_code in enumerate(selected):
                try:
                    svc.fetch_history(stock_code, history_source)
                except Exception as exc:
                    st.error(f"{stock_code} 获取失败，任务已停止：{exc}")
                    break
                progress.progress((i+1)/len(selected), text=stock_code)
            else:
                st.rerun()
        refresh_codes = st.multiselect("重新更新已有历史（用于盘中更新日K）",
                                      [r["code"] for r in candidates if r["code"] not in pending],
                                      disabled=demo)
        if st.button(f"更新所选已有历史（{len(refresh_codes)}只，至少{len(refresh_codes)*2}次调用）", disabled=demo or not refresh_codes):
            for stock_code in refresh_codes:
                try:
                    svc.fetch_history(stock_code, history_source)
                except Exception as exc:
                    st.error(f"{stock_code} 获取失败，任务已停止：{exc}")
                    break
            else:
                st.rerun()

st.subheader("个股详情")
choices = display or results
if st.session_state.get("detail_stock") and st.session_state.detail_stock not in {r["code"] for r in choices}:
    requested = next((r for r in results if r["code"] == st.session_state.detail_stock), None)
    if requested:
        choices = choices + [requested]
if choices:
    lookup = {r["code"]: r for r in choices}
    if st.session_state.get("detail_stock") not in lookup:
        st.session_state.detail_stock = next(iter(lookup))
    selected = st.selectbox("选择股票", list(lookup), format_func=lambda k: k + " · " + (lookup[k].get("name") or ""), key="detail_stock")
    row = lookup[selected]
    left, right = st.columns([1, 3])
    watch = store.watchlist()
    if left.button("移出自选" if selected in watch else "加入自选"):
        store.set_watchlist([c for c in watch if c != selected] if selected in watch else watch + [selected])
        st.rerun()
    if right.button("获取／更新该股历史（至少2次调用）", disabled=demo):
        perform("更新历史", lambda: svc.fetch_history(selected, history_source))
    h = store.get("history:" + selected)
    if h and h.get("bars"):
        try:
            bars = add_indicators(h["bars"])
        except (ValueError, TypeError) as exc:
            st.error(f"历史数据无法计算指标：{exc}")
            st.stop()
        state = assess_trend(bars)
        st.subheader(f"走势状态：{state['state']}")
        st.write(state["summary"])
        st.caption(f"分析截至 {state['date']} 的缓存日K。最新一根可能包含盘中数据，并非收盘确认；不将旧日线当作当前实时走势。")
        mcols = st.columns(4)
        for col, name in zip(mcols, ["MA5","MA10","MA20","SNAKEA"]):
            value = bars[name].iloc[-1]
            col.metric(name, f"{value:.2f}" if pd.notna(value) else "数据不足")
        controls = st.columns([2,1,1,1,1])
        period = controls[0].selectbox("显示范围", ["最近120根","最近60根","全部"], key="chart_period")
        show_ma = controls[1].checkbox("显示5/10/20均线", value=True, key="chart_ma")
        show_trend = controls[2].checkbox("显示趋势线", value=True, key="chart_trend")
        show_snakea = controls[3].checkbox("显示SNAKEA", value=True, key="chart_snakea")
        show_stop = controls[4].checkbox("显示停损下限", value=True, key="chart_stop")
        chart = make_detail_chart(bars, {"最近120根":120,"最近60根":60,"全部":None}[period], show_ma, show_trend, show_snakea, show_stop)
        st.plotly_chart(chart, use_container_width=True)
        st.caption("SNAKEA（青色）：三重平滑收盘价 B2 最近13根日K（含当根）的最高值。")
        st.caption("停损下限：条件成立时在B2位置绘制红线或绿线；两条线各自独立，不代表自动买卖信号。")
        with st.expander("走势判断依据与计算口径"):
            st.dataframe(pd.DataFrame(state["evidence"]), hide_index=True, use_container_width=True)
            st.write("偏进攻：MA5 > MA10 > MA20，日K收盘价 ≥ MA5，MA20上行且20根拟合斜率为正。偏防守：上述条件反向。其余为震荡观察。")
            st.caption("均线取前复权收盘价的简单平均；不足窗口不补值。趋势线是最近20根有效日K的最小二乘拟合，仅描述该段走势，不向未来延伸。")
            st.code("B2 = SMA(SMA(SMA(C, 2, 1), 2, 1), 2, 1)\nSMA2 = MA(B2, 3)\nSNAKEA = HHV(MA(B2, 1), 13)\n停损下限红 = IF(LLV(MA(B2, 8), 3) >= SMA2, B2, DRAWNULL)\n停损下限绿 = IF(B2 < SMA2, B2, DRAWNULL)", language="text")
            st.caption("C为前复权收盘价。SMA(X,2,1)=本期X×0.5+上期SMA×0.5，各层以缓存首根有效值初始化；连续满13根才绘制SNAKEA。缺失值处断开并重新初始化，切换显示范围不重新计算。缓存起点与其他软件不同可能产生初期差异。走势状态仍按上述均线和趋势条件判断。")
        st.caption(f"来源：{h.get('source', '旧缓存（来源未记录）')} · 前复权日线 · 历史基准日 {h.get('basis_date')} · 与当前价可比性需通过基准验证")
    else:
        st.info("尚无该股历史缓存。选择股票不会自动联网，点击上方按钮后获取。")

with st.expander("请求记录与使用说明"):
    st.caption("记录为任务／SDK调用日志；除明确列出的HTTP次数外，不等同于服务商额度扣减次数。")
    st.dataframe(pd.DataFrame(store.logs()), hide_index=True, use_container_width=True)
    st.write("迁移到其他 Windows 64 位电脑：复制整个便携文件夹，包括 data 目录，再双击 start.bat。")
