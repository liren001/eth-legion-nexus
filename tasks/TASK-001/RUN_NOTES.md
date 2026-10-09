# TASK-001 — 验证说明

在此目录运行 `TASK001_CLIENT_FIXTURES=1 python3 -m unittest -v test_engine.py`。只用 stdlib，mock 网络/SMTP/休眠；不执行真实采集或发信。

预期：2 tests / OK。覆盖错误 tuple 形状、详情 fetch 非文本、注入 unpack 异常、真正空运行、URL 校验、客户提供的3个拒绝/4个通过邮箱及采集边界。错误输出包含 stage/type/count，退出码2；真正空运行退出码0。错误日志不含邮箱、页面或凭证；未处理的主程序异常也退出2。

客户于2026-10-09补齐官方 fixtures；已使用这两份JSON字符串数组验证。此模式拒绝无效JSON或错误样例数量。未设置环境变量时使用标明为合成的独立回归样例。

Python3.12.15通过。没有上线或发送邮件。源码、两项测试、官方fixtures与本说明为完整技术交付；付款及最终验收仍需客户确认，包含一次范围内修订。
