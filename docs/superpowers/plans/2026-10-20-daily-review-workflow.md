# 每日复盘工作台优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成今日概览、跨日变化、自选跟踪和复盘关键数值展示。

**Architecture:** 把跨日比较和指标摘要写为纯计算模块，现有 SQLite 复盘仓库提供轻量读取。首页、复盘页和自选页消费同一份摘要，不增加自动联网行为。

**Tech Stack:** Python 3.12、Streamlit、pandas、Plotly、SQLite、pytest。

**Spec:** `docs/superpowers/specs/2026-10-20-daily-review-workflow-design.md`

## Global Constraints

- 页面切换、排序、比较和查看自选只读取本地数据库。
- 不修改已有筛选与复盘规则；保留旧复盘快照兼容。
- 不打包压缩文件；部署时保留便携目录的 `data` 数据库。
- 变化分类只根据同一股票在两个可比交易日的明确结果；未核验、未覆盖或失败显示待确认。

## Review Focus

- 上次或本次扫描未完成：不把缺席股票归为退出；Task 1 测试。
- 同日多次扫描：不互相充当跨日对比；Task 1 测试。
- 快速初筛未核验 `no_match`：不作为退出依据；Task 1 测试。
- 旧复盘记录缺少新字段或历史快照：显示数据不足；Task 2 测试。
- 空数据库、空自选和无网络：页面仍可操作；Task 3、Task 4 测试。

---

### Task 1: 跨日复盘比较

**Files:** Create `screener/review_compare.py`; Test `tests/test_review_compare.py`.

**Interfaces:** `comparable_previous(runs: list[dict], current: dict) -> dict | None` 返回目标日更早、市场及排除设置相同的最近记录；`compare_reviews(previous_results: list[dict], current_results: list[dict]) -> dict[str,list[dict]]` 返回 `new`, `continued`, `exited`, `uncertain`，只将双方明确且已核验的 `match/no_match` 用于前三类。

- [ ] 写测试：前后明确结果、缺失、失败、`excluded` 和 `cache_mode=batch` 的分类。
- [ ] 运行 `python -m pytest tests/test_review_compare.py -q`，确认失败来自未实现的模块。
- [ ] 实现纯计算函数，按股票代码合并，保留本次结果供页面显示。
- [ ] 运行目标测试，确认通过。
- [ ] 写测试并验证同日多次、不同排除条件、部分扫描的上一记录选择。

### Task 2: 复盘关键数值

**Files:** Modify `screener/review.py`, `screener/review_ui.py`; Create `screener/review_metrics.py`; Test `tests/test_review_metrics.py`.

**Interfaces:** `review_metrics(result: dict) -> dict` 返回 `distance_pct`, `snakea_change_pct`, `stop_lower`, `stop_color`；无足够快照或无效分母时对应值为 `None`。新复盘的入选结果在保存前填充指标；旧记录在显示时本地计算可得字段。

- [ ] 写测试：距离与方向百分比、红绿重叠、无快照及零分母。
- [ ] 运行目标测试确认失败。
- [ ] 用已有 `add_indicators` 计算停损线，以保存的前复权日 K 为准；不额外联网。
- [ ] 运行目标测试确认通过。
- [ ] 复盘表增加新列和排序，旧记录缺项显示数据不足；运行相关页面与复盘测试。

### Task 3: 今日概览和一键入口

**Files:** Modify `app.py`; Create `screener/overview_ui.py`; Test `tests/test_overview.py`.

**Interfaces:** `render_overview(store: Store, demo: bool) -> None` 读取最新记录，显示日期、完成数、数据时效与配置；开始按钮按 spec 复用最近配置或默认配置，继续按钮复用记录 ID。成功操作后 `st.session_state.workspace_page = '每日复盘'`。

- [ ] 写测试：空库、已有完成记录、暂停记录；普通打开和切页绝不调用 Provider。
- [ ] 运行目标测试确认失败。
- [ ] 实现概览 UI 与复盘入口；已有活跃任务时禁用重复启动。
- [ ] 运行目标测试与全套 UI 测试确认通过。

### Task 4: 自选股跟踪

**Files:** Create `screener/watchlist_ui.py`; Modify `app.py`, `screener/review_ui.py`; Test `tests/test_watchlist.py`.

**Interfaces:** `render_watchlist(store: Store, demo: bool) -> None` 从 `watchlist`、本地目录、最近两次可比复盘和已缓存历史构造跟踪表；表格行可打开已缓存的个股 K 线；自选增删沿用 `Store.set_watchlist`。

- [ ] 写测试：空自选、无复盘结果、旧结果缺字段、点击只读浏览；确认失败。
- [ ] 实现自选页面和从复盘页加入/移出自选。
- [ ] 运行目标测试确认通过。
- [ ] 更新 `README.md`；运行全套 `python -m pytest -q`，再同步修改的源码到便携目录，运行编译与两个原端口的健康检查，确认数据库完整。
