# TASK-001 — 本地验证说明（待客户 fixtures）

在此目录运行 `python3 -m unittest -v test_engine.py`。只用 stdlib，mock 网络/SMTP/休眠；不执行真实采集或发信。

预期：2 tests / OK。覆盖错误 tuple 形状、详情 fetch 非文本、注入 unpack 异常、真正空运行、URL 校验、邮箱过滤及采集边界。错误输出包含 stage/type/count，退出码 2；真正空运行退出码 0。错误日志不包含邮箱、页面或凭证。其余主程序异常也退出 2。

客户提供的两个 fixture 文件各只有一个换行；当前邮箱测试明确使用合成样例，不能证明客户七个样例验收通过。客户补齐 JSON 字符串数组后运行 `TASK001_CLIENT_FIXTURES=1 python3 -m unittest -v test_engine.py`；文件为空或数量不对时此模式明确失败，不伪造通过。

本地已验证 Python 3.12.15 和 3.14.4，两项测试均通过。没有上线、发送邮件或最终交付。包含一次范围内修订。
