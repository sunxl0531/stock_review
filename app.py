from pathlib import Path
import os
import streamlit as st
from screener.store import Store
from screener.demo import seed

st.set_page_config(page_title="工作台", page_icon="📈", layout="wide", initial_sidebar_state="expanded")
st.markdown("""<style>
.block-container{padding-top:2rem;max-width:1600px}
[data-testid=stMetric]{background:#f0f4f8;padding:16px;border-radius:10px}
[data-testid=stMetricValue]{font-size:1.8rem}
[data-testid=stSidebar]{background:#272b35;border-right:1px solid #3a4050}
[data-testid=stSidebar] h1,[data-testid=stSidebar] h3,[data-testid=stSidebar] p{color:#dce4ef}
[data-testid=stSidebar] hr{border-color:#404756}
[data-testid=stSidebarUserContent]{padding-top:0.5rem}
[data-testid=stSidebarCollapseButton]{visibility:visible!important;opacity:1!important}
[data-testid=stSidebarCollapseButton] button{color:#e8f0fa!important;background:#394454;border-radius:6px}
[data-testid=stSidebarCollapseButton] button:hover{background:#4a576c}
[data-testid=stSidebarCollapseButton] [data-testid=stIconMaterial]{color:#e8f0fa!important}
[data-testid=stExpandSidebarButton]{visibility:visible!important;opacity:1!important;color:#176a80!important;background:#e8eef4;border-radius:6px}
[data-testid=collapsedControl]{visibility:visible!important;opacity:1!important;color:#176a80!important}
[data-testid=stSidebar] button[aria-label="Collapse sidebar"]{color:#e8f0fa!important}

[data-testid=stSidebar] [role="radiogroup"]{gap:4px}
[data-testid=stSidebar] label[data-baseweb="radio"]{padding:16px 18px;margin:0;border-radius:6px;width:100%;box-sizing:border-box;cursor:pointer;border-left:3px solid transparent}
[data-testid=stSidebar] label[data-baseweb="radio"]:hover{background:#353b48}
[data-testid=stSidebar] label[data-baseweb="radio"]:has(input:checked){background:#394454;border-left:3px solid #45c3ce}
[data-testid=stSidebar] label[data-baseweb="radio"]:has(input:checked) p{color:#fff;font-weight:700}
[data-testid=stSidebar] label[data-baseweb="radio"]>div:first-child{display:none}
[data-testid=stSidebar] label[data-baseweb="radio"]:focus-within{outline:2px solid #45c3ce}
</style>""", unsafe_allow_html=True)
ROOT = Path(__file__).resolve().parent
data_dir = Path(os.environ.get("SCREENER_DATA_DIR", str(ROOT / "data")))
if st.session_state.get("requested_page"):
    st.session_state.workspace_page = st.session_state.pop("requested_page")
with st.sidebar:
    labels = {"今日概览":"▦  今日概览", "股票筛选":"⌕  个股筛选", "每日复盘":"▤  每日复盘", "自选跟踪":"☆  自选跟踪"}
    page = st.radio("主菜单", list(labels), format_func=labels.get, key="workspace_page", label_visibility="collapsed")
demo = os.environ.get("SCREENER_DEMO") == "1"
store = Store(data_dir / ("demo.db" if demo else "market.db"))
if demo:
    seed(store)
    st.warning("演示模式：合成样例数据，不是真实行情。")
if page == "今日概览":
    from screener.overview_ui import render_overview
    render_overview(store, demo)
elif page == "每日复盘":
    from screener.review_ui import render_review
    render_review(store, demo)
elif page == "自选跟踪":
    from screener.watchlist_ui import render_watchlist
    render_watchlist(store, demo)
else:
    from screener.stock_ui import render_stock
    render_stock(store, demo)
