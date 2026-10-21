# 第一版交付验证

- 本地完整测试：29 passed；Python 语法编译检查通过。
- 真实接口：五板块目录与腾讯快照均为5575只，逐市场数量见README。本次不是交易所独立完整性审计。
- 独立审阅：限流重试、异常缓存覆盖和混合日期行情三个重要问题均已修复，回归测试先失败后通过。
- 便携包：`dist/A-share-screener-Windows-x64.zip`，126179501字节。
- SHA256：`d3d3fd731f40cf7cdf259a6764c11226e82de2cb9263bba991b015244fc21318`。
- 解压至带中文及空格的另一路径，移除PYTHONHOME/PYTHONPATH/VIRTUAL_ENV，并将PATH限制为Windows系统目录后，独立Python导入、空白页面、演示交互、HTTP健康检查均通过。
- 发行压缩包不包含个人行情缓存或自选。源工作目录的data包含此次测试获取的真实数据。
- 未在另一台实体Windows电脑、macOS、Linux或Windows ARM上实测。
- 浏览器自动化工具因其Windows沙箱初始化失败无法使用；界面验证使用Streamlit AppTest完成，不能声称进行了浏览器截图审阅。

复现：`tools/verify_portable.py`，结构化结果见 `dist/verification.json`。
