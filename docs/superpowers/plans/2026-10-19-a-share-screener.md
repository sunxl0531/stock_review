# A 股筛选器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 交付 Windows 本地可启动的手动刷新 A 股筛选器。
**Architecture:** Streamlit UI 调用独立服务层；SQLite 存储标准化数据，纯筛选函数不联网。外部调用在有超时的子进程中执行，失败不覆盖缓存。
**Tech Stack:** Python 3.12、Streamlit、pandas、Plotly、AKShare、SQLite、pytest。
**Spec:** ../specs/2026-10-19-a-share-screener-design.md

## Global Constraints
- 五个市场；默认排除 ST、停牌、上市不足 60 个交易日。
- 默认手动刷新；额度未知不允许自动刷新；界面操作不隐式联网。
- 缺失字段返回无法判定；历史突破须验证价格基准。
- 数据和样例隔离；失败保留原快照。

## Review Focus
- 缺失证券元数据不应悄悄通过默认排除规则（Task 1）。
- 空响应、重复代码或坏数据不能覆盖缓存（Task 2）。
- 北交所新旧代码均须保留市场归属（Task 3）。
- 上游接口阻塞或报限流时应停止而非自动重复（Task 3）。
- 初次启动、筛选、导出不应触发请求（Task 4）。

### Task 1: 筛选计算
Files: screener/core.py, tests/test_core.py
Interfaces: screen(rows, filters, calendar, histories, as_of) -> list[dict]; breakout(row, history, periods, calendar, as_of) -> (bool|None, str).
- [ ] 先写边界、缺失、五板块、上市天数和价格基准测试；pytest 验证失败。
- [ ] 实现纯计算、三态判断和导出；pytest 验证通过。

### Task 2: 缓存与任务服务
Files: screener/store.py, screener/service.py, tests/test_service.py
Interfaces: Store.get/put(key, payload); Service.refresh_quotes/provider_call, refresh_basics, fetch_histories。
- [ ] 写缓存持久化、失败保留旧快照、同一任务互斥测试；先失败后实现。
- [ ] 保存请求日志、自选及筛选设置；对空响应拒绝覆盖。

### Task 3: 数据源适配
Files: screener/provider.py, screener/worker.py, tests/test_provider.py
Interfaces: Provider.call(operation, **kwargs) -> JSON-compatible payload。
- [ ] 写代码规范化、单位、元数据、未知状态、日线基准测试。
- [ ] 接入 AKShare 的快照、交易所目录、日历、停复牌和历史接口，子进程超时及错误提示。
- [ ] 小量真实请求验证；有阻塞时尝试一个合理的公开备用快照源，并保留来源差异说明。

### Task 4: 页面与启动
Files: app.py, screener/demo.py, start.bat, setup.bat, requirements.txt, README.md, tests/test_app.py
- [ ] 写 AppTest：无网络空态、筛选及缓存样例渲染。
- [ ] 实现手动行情/基础资料/历史补齐按钮、三态结果、K线、自选、导出和数据状态。
- [ ] 显式演示开关使用独立数据库；不把样例当真实行情。
- [ ] 提供一次安装和日常启动入口，适配当前 Python 3.12。

### Task 5: 验证和交付
- [ ] 全量 pytest；真实数据小样本；本地服务器健康检查和页面检查。
- [ ] 按 executing-plans 技能进行一次独立最终代码审阅，修复重要问题。
- [ ] README 记录真实连接结果和限制，向用户提供启动入口。

## 执行记录
- 用户要求“开始做吧，后期一点一点完善”，本轮直接实施，默认由当前助手完成。
- 当前空目录且命令环境无 Git；不创建不必要的 worktree，不声称已提交。记录保留在此文件。
- 自动刷新暂保持不可用：候选公开源没有已验证的额度保障，手动模式满足用户最新要求。
- 用户补充便于迁移到其他电脑：增加 Windows x64 便携压缩包，包含独立 Python 3.12 运行时和依赖，双击启动；开发源码保留。构建后从解压目录验证，不依赖开发环境绝对路径。
- Task 1–4 complete: 29 tests passed after initial missing-module/UI failures and the review regression red→green cycle.
- Final review: independent reviewer found SDK rate-limit retries, malformed payload cache replacement, and mixed-date quotes passing ordinary filters. Fixed each; regression tests prove one HTTP attempt, retained cache and timestamp, and unknown mixed-date rows. Also treat expected resumption as unconfirmed.
- Ruling: review's clean Windows PC validation cannot be performed here; verify relocated extracted runtime with isolated Python paths, document actual cross-machine testing as unperformed.
- Ruling: public-feed completeness is checked against loaded exchange directories (all 5575 returned), not claimed as independent exchange reconciliation.
- Live check 2026-10-20: SH main1700/STAR618/SZ2906/BJ351, all5575 Tencent quotes dated2026-10-19, calendar through2026-12-31, suspension15 rows, 000001 history146 bars.
- Browser automation kernel failed due Windows sandbox initialization; UI interaction validated using Streamlit AppTest; local server started successfully.
