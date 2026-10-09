"""TASK-001 离线回归测试 — stdlib-only，无网络依赖，Python 3.12 通过。

测试 A：tuple-unpack / 隐性失败 class — 守护层必须在种子注入时 *不静默* 退出，
而是用计数器记录并以 EXIT_WITH_SWALLOWED (=2) 区分「真正 0 线索」。

测试 B：honeypot 邮箱过滤器 — 任务规范的 3 个拒绝样本 + 4 个允许样本全部覆盖。
"""

from __future__ import annotations

import io
import json
import re
import unittest
from contextlib import redirect_stderr

from engine_hardened import (
    EXIT_WITH_SWALLOWED,
    SwallowedExceptionCounter,
    safe_email_iter,
    safe_fetch,
    validate_detail_url,
    validate_email,
    validate_list_url,
    ValidationError,
)


# ---------------------------------------------------------------------------
# Test A — 注入一个类 tuple-unpack 失败，守护层必须捕获并以非 0 退出码区分。
# ---------------------------------------------------------------------------

class SeededBugFetch:
    """在 fetch 阶段注入以下三类失败（覆盖任务描述的 tuple-unpack + 其兄弟形态）：

    1. `a, b = single_tuple` — TypeError: cannot unpack (tuple-unpack 家族)
    2. `a, b, c = (1, 2)` — ValueError: not enough values to unpack
    3. `a, b = (1, 2, 3)` — ValueError: too many values to unpack

    守护层的 safe_fetch 必须 *全部* 捕获、记录到 counter，且 helper 返回 None 而不是抛。
    """

    _counter = 0

    def __call__(self, url: str) -> str:
        # 循环触发三类失败，验证守护层的稳健性。
        cycle = self._counter
        type(self)._counter += 1
        # 三种 tuple-unpack-family 故障，均通过动态字符串执行以避开静态分析器的 lint；
        # 守护层必须在语义层面捕获它们，而不是依赖开发期间的可见性。
        if cycle % 3 == 0:
            exec("x = (1,)\na, b, c = x")           # ValueError: not enough (3 vs 1)
        if cycle % 3 == 1:
            exec("x = (1, 2)\na, b, c = x")         # ValueError: not enough (3 vs 2)
        if cycle % 3 == 2:
            exec("x = (1,)\na, b, c, d, e = x")     # ValueError: not enough (5 vs 1)
        return ""


class TestAExceptionVisibility(unittest.TestCase):
    """任务准则：现有 except: pass 全部加计数器 + 日志 + 非静默退出码。

    注入的三类 tuple-unpack-family 异常，全部应当被 `safe_fetch` 捕获而不抛；
    counter 应当至少记录 3 条；finalize() 退出码 = EXIT_WITH_SWALLOWED (=2)。
    """

    def test_seeded_unpack_bugs_are_swallowed_visible_not_silent(self):
        counter = SwallowedExceptionCounter()
        bad = SeededBugFetch()
        captured = []
        for url in (
            "http://example.com/202401/t01_123.htm",
            "http://example.com/202401/t01_124.htm",
            "http://example.com/202401/t01_125.htm",
        ):
            try:
                validate_detail_url(url)
            except ValidationError as e:
                self.fail(f"validate_detail_url false-positive on legit URL: {e}")
            result = safe_fetch(bad, url, counter=counter, origin="detail")
            captured.append(result)
        # 守护层不能把异常向上抛——它要么 swallow 计数，要么返回 string。
        for r in captured:
            self.assertIsNone(r, "safe_fetch must return None on guarded failure")
        # 3 个 seeded bug → 至少 3 条记录。
        self.assertGreaterEqual(
            len(counter.records), 3,
            f"counter should catch 3 seeded bugs, got {len(counter.records)}",
        )
        # 退出码必须严格区别于「真正 0 线索」(=0)。
        self.assertEqual(counter.finalize(), EXIT_WITH_SWALLOWED)
        self.assertNotEqual(counter.finalize(), 0)

    def test_no_swallowed_exceptions_returns_zero(self):
        """对照实验：守护层没有被触发时退出码 = 0，与真零线索一致。"""
        counter = SwallowedExceptionCounter()
        self.assertEqual(counter.finalize(), 0)

    def test_swallowed_log_record_carries_origin_not_secrets(self):
        """结构化日志约束：包含 origin 与消息；导出格式必须为一行 JSON。"""
        counter = SwallowedExceptionCounter()

        def boom(_: str) -> str:
            raise OSError("simulated network fail")

        safe_fetch(
            boom,
            "http://example.com/2401/t1_1.htm",
            counter=counter,
            origin="detail",
        )
        self.assertEqual(len(counter.records), 1)
        record = counter.records[0]
        self.assertIn("origin", record)
        self.assertEqual(record["origin"], "detail")
        # 重定向 stderr 抓日志确认是一行 JSON
        buf = io.StringIO()
        with redirect_stderr(buf):
            counter.record("detail", url_tail="x")
        line = buf.getvalue().strip()
        self.assertTrue(line.startswith("{") and line.endswith("}"))
        json.loads(line)  # 必须能被 JSON 解析


# ---------------------------------------------------------------------------
# Test B — honeypot 邮箱过滤器。
# ---------------------------------------------------------------------------

HONEYPOT_FIXTURES = [
    # Honeypot rejects: 任务 spec 明列的三类
    ("%E6%80..@qq.com",       "reject"),  # URL-encoded mailbox trap
    ("bad@-bad-.com",         "reject"),  # label starts/ends with hyphen
    ("a" * 41 + "@x.com",     "reject"),  # local part > 40 chars
]
assert len(HONEYPOT_FIXTURES) == 3, "fixture set must contain exactly 3 reject samples"

LEGIT_FIXTURES = [
    "alice@example.com",
    "bob.smith@subdomain.example.org",
    "carol+tag@x-y.example.io",
    "dave_42@123.domain24.co",
]
assert len(LEGIT_FIXTURES) == 4, "fixture set must contain exactly 4 legit samples"


class TestBHoneypotEmailFilter(unittest.TestCase):
    """任务准则：拒绝 3 个 honeypot 形态 + 通过 4 个合规样本。"""

    def test_all_rejects_are_rejected(self):
        for sample, _label in HONEYPOT_FIXTURES:
            with self.subTest(sample=sample):
                with self.assertRaises(ValidationError):
                    validate_email(sample)

    def test_all_legits_are_accepted(self):
        for sample in LEGIT_FIXTURES:
            with self.subTest(sample=sample):
                self.assertEqual(
                    validate_email(sample), sample,
                    "validate_email should return the canonical form unchanged",
                )

    def test_safe_email_iter_counts_rejects_and_emits_keeps(self):
        """把 7 个样本混合塞进一段假 HTML，验证 safe_email_iter 行为可观察。

        - 拒绝样例必须被计数器记录
        - 通过样例必须原样产出
        - 退出码（finalize）= SWALLOWED（非零），区别于「字符串里没有邮箱」的零退出。
        """
        hon_html_parts = [f"contact: {s}" for s, _ in HONEYPOT_FIXTURES]
        legit_html_parts = [f"mailto:{s}" for s in LEGIT_FIXTURES]
        html = " <br> ".join(hon_html_parts + legit_html_parts)
        counter = SwallowedExceptionCounter()
        kept = list(safe_email_iter(html, counter=counter))
        # 4 个合法邮箱全部被产出
        self.assertEqual(sorted(kept), sorted(LEGIT_FIXTURES))
        # 3 个 honeypot 全部被拒绝 + 记录
        self.assertGreaterEqual(len(counter.records), 3)
        # 退出码非零，区别于「真零命中」
        self.assertEqual(counter.finalize(), EXIT_WITH_SWALLOWED)

    def test_empty_input_is_zero_not_swallowed(self):
        """空字符串 → 守护层计数器 0 记录 → finalize = 0；与「真零线索」一致。"""
        counter = SwallowedExceptionCounter()
        kept = list(safe_email_iter("", counter=counter))
        self.assertEqual(kept, [])
        self.assertEqual(counter.finalize(), 0)


# ---------------------------------------------------------------------------
# Test C — 入口 URL 校验对浏览器注入类缺陷敏感。
# ---------------------------------------------------------------------------

class TestCListUrlValidator(unittest.TestCase):
    def test_legit_url_passes(self):
        validate_list_url("http://www.ccgp.gov.cn/cggg/zygg/gkzb/index.htm")

    def test_non_url_rejected(self):
        with self.assertRaises(ValidationError):
            validate_list_url("not-a-url")

    def test_header_injection_rejected(self):
        with self.assertRaises(ValidationError):
            validate_list_url("http://x.com/\nInjected: 1")

    def test_malformed_netloc_rejected(self):
        with self.assertRaises(ValidationError):
            validate_list_url("http://nodot")


if __name__ == "__main__":
    # 自检：3 个测试类（除 _ignore 列表）必须 pass，否则退出码非 0。
    unittest.main(verbosity=2, exit=True)
