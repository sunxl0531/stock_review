"""Compact landing page for an explicit, local daily-review workflow."""
from datetime import date
import streamlit as st

from .core import BOARDS
from .review import ReviewRepository, ReviewRunner
from .store import now

STATUS = {"ready":"待开始", "running":"扫描中", "paused":"已暂停",
          "done":"扫描完成", "partial":"存在请求失败"}


@st.fragment(run_every=3)
def render_overview(store, demo):
    repo = ReviewRepository(store)
    runs = repo.runs()
    active = repo.active()
    st.subheader("今日概览")
    st.caption("查看本地复盘状态；只有点击开始或继续才请求行情接口。")
    latest = runs[0] if runs else None
    if latest:
        target = latest.get("target") or latest["config"].get("requested_date")
        st.write(f"**最近复盘：{target} · {STATUS.get(latest['status'], latest['status'])}**")
        st.write(f"已处理 {latest.get('processed', 0)} / {latest.get('total') or '待加载'}")
        st.caption(f"最后更新：{latest.get('updated_at', '未知')} · 开始时间：{latest.get('created_at', '未知')}")
        started = latest.get("created_at", "")
        if target == started[:10]:
            st.caption("收盘后发起" if started[11:16] >= "15:30" else "盘中发起；信号可能变化")
        else:
            st.caption("历史日期复盘；以该记录保存的日线为准")
        st.progress(min(latest.get("processed",0)/latest["total"],1.0) if latest.get("total") else 0.0)
        if latest.get("error"):
            st.warning(latest["error"])
    else:
        st.info("尚无复盘记录。可点击下方按钮开始，或进入每日复盘调整设置。")

    cfg = latest["config"] if latest else {}
    workers = st.selectbox("并发请求线程数", list(range(1, 11)), index=4,
                           key="overview_workers", disabled=bool(active),
                           help="默认5个，最多10个。停止任务后可调整线程数再继续，保留已有进度。")
    settings = dict(boards=cfg.get("boards", list(BOARDS)), source=cfg.get("source", "tencent"),
                    requested_date=date.fromisoformat(now()[:10]).isoformat(),
                    exclude_st=cfg.get("exclude_st", True), exclude_new=cfg.get("exclude_new", True),
                    force_refresh=False, workers=workers,
                    fast_batch=cfg.get("fast_batch", True) and cfg.get("source", "tencent") == "tencent")
    st.caption(f"开始新复盘将使用：{'、'.join(settings['boards'])} · {'腾讯' if settings['source']=='tencent' else '东方财富'} · 排除ST：{'是' if settings['exclude_st'] else '否'} · 排除新股：{'是' if settings['exclude_new'] else '否'}。可到每日复盘修改。")
    left, right = st.columns(2)
    with left:
        if st.button("开始今日复盘", type="primary", disabled=demo or bool(active)):
            try:
                run = ReviewRunner(repo).create(settings)
                ReviewRunner(repo).start(run["id"])
                st.session_state.review_run = run["id"]
                st.session_state.requested_page = "每日复盘"
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    with right:
        can_resume = latest and latest["status"] != "done" and not active
        if st.button("继续上次复盘", disabled=demo or bool(active) or not can_resume, key="overview_resume"):
            try:
                latest["config"]["workers"] = workers
                repo.save(latest)
                ReviewRunner(repo).start(latest["id"])
                st.session_state.review_run = latest["id"]
                st.session_state.requested_page = "每日复盘"
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    if st.button("查看完整复盘与设置", key="overview_view_review"):
        st.session_state.requested_page = "每日复盘"
        st.rerun()
