#!/usr/bin/env python3
"""每日自主获客引擎 v1 — 防御性加固版（任务 TASK-001 的交付物）。

与 `tasks/TASK-001/engine_redacted.py` 的关系:
- 不修改原业务逻辑（邮件文案、SMTP 凭据、SOURCES 列表、collect/mailto 流）。
- 在原引擎 *相同* 的三个数据入口（列表页 URL 构造 / 详情页 fetch / 邮箱正则输出）
  之上加一层结构性校验；同时把 `except: pass` 替换成计数器+日志+非静默退出。
- 本文件保留 stdlib-only、无网络依赖；可直接被离线测试 / CI 触发。

退出码约定（与现有 `0=真零线索` 的观察兼容）:
- 0  今日确实 0 新线索（没有失败被吞）
- 2  发现被吞的异常 / 隐性失败（tuple-unpack、honeypot 命中、URL 构造缺陷等）
- 3  守护层自身异常（不应发生）
- 1  未捕获的运行时错误（原行为可能压平到这一步）
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Callable, Iterable, Tuple

# 退出码约定 — 守护层与原引擎共享；常量集中声明避免散落。
EXIT_WITH_SWALLOWED = 2
EXIT_GUARD_FAILURE = 3

# ---------------------------------------------------------------------------
# Constants — keep in sync with engine_redacted.py where relevant.
# ---------------------------------------------------------------------------

BASE = Path(__file__).parent

# 列表页源必须满足的形状（防拼接失败 class）。
_URL_SCHEMES = ("http://", "https://")
_DETAIL_URL_RE = re.compile(r"^https?://[^\s]+/\d{6}/t\d+_\d+\.htm(l)?$")
# 邮箱白名单形状：local@domain.tld；URL-encoded mailbox trap (%xx 编码 local part) 必须被拒。
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}$")
_URL_ENCODED_TRAP_RE = re.compile(r"%[0-9A-Fa-f]{2}")
_GOOD_TLD_RE = re.compile(r"\.[A-Za-z]{2,24}$")
_MAX_LOCAL_PART = 40  # 任务规范：>40 字符的 local part 一律拒
_MAX_EMAIL_LEN = 254


# ---------------------------------------------------------------------------
# Input validation layer.
# ---------------------------------------------------------------------------

class ValidationError(ValueError):
    """任何输入点不满足结构性约束时抛出（替代裸 AssertionError）。"""


def validate_list_url(url: object) -> str:
    """列表页 URL 入口校验：必须是字符串、以 http(s) 开头、可被 urllib 解析。
    设计目标: 暴露历史上 `src.rsplit('/', 1)[0]` 切片失败、
    或凭据混入 `SOURCES` 后被拼接出的非 URL 值。
    """
    if not isinstance(url, str):
        raise ValidationError(f"list-url must be str, got {type(url).__name__}")
    if not url:
        raise ValidationError("list-url empty")
    if not url.startswith(_URL_SCHEMES):
        raise ValidationError(f"list-url scheme invalid: {url[:40]!r}")
    if "\n" in url or "\r" in url:
        raise ValidationError("list-url contains CR/LF (header injection risk)")
    parsed = urllib.parse.urlparse(url)
    if not parsed.netloc or "." not in parsed.netloc:
        raise ValidationError(f"list-url netloc invalid: {url!r}")
    return url


def validate_detail_url(url: object) -> str:
    """详情页 URL 入口校验：与列表页 URL 构造结果一致 + 正则匹配任务原文 spec."""
    base = validate_list_url(url)
    if not _DETAIL_URL_RE.match(base):
        raise ValidationError(f"detail-url shape mismatch: {base!r}")
    return base


def _reject_url_encoded_mailbox(s: str) -> None:
    # 任务原文明确要求：拒绝 %xx 编码的 mailbox trap（如 %E6..@qq.com）。
    if _URL_ENCODED_TRAP_RE.search(s):
        raise ValidationError(f"url-encoded mailbox trap rejected: {s!r}")


def _reject_oversize_local_part(s: str) -> None:
    # 任务原文：>40-char local part 必须拒绝。
    if s.count("@") != 1:
        raise ValidationError(f"email malformed (multiple/missing @): {s!r}")
    local = s.split("@", 1)[0]
    if len(local) > _MAX_LOCAL_PART:
        raise ValidationError(
            f"email local part too long ({len(local)}>{_MAX_LOCAL_PART}): {s!r}"
        )


def _reject_malformed_tld(domain: str) -> None:
    if not _GOOD_TLD_RE.search(domain):
        raise ValidationError(f"email domain malformed TLD: {domain!r}")


def _reject_label_edge_hyphen(domain: str) -> None:
    # 任务语义补充：邮箱域的任一 *label* 不能以连字符开头或结尾
    # （RFC 5891 + 真实世界反垃圾邮件实践 — `bad@-bad-.com` 形态属此类）。
    for label in domain.split("."):
        if label.startswith("-") or label.endswith("-"):
            raise ValidationError(
                f"email domain label has leading/trailing hyphen: {domain!r}"
            )
        if not label:
            raise ValidationError(
                f"email domain has empty label (double-dot / edge dot): {domain!r}"
            )


def validate_email(candidate: object) -> str:
    """邮箱正则输出入口校验：白名单 + 3 个 honeypot 形态必须全拒。"""
    if not isinstance(candidate, str):
        raise ValidationError(f"email must be str, got {type(candidate).__name__}")
    s = candidate.strip()
    if not s:
        raise ValidationError("email empty")
    if len(s) > _MAX_EMAIL_LEN:
        raise ValidationError(f"email too long ({len(s)}>{_MAX_EMAIL_LEN})")
    # 任何 URL-encoded 字符 / 不可见字符必须先拒，避免后续处理把陷阱当合法。
    _reject_url_encoded_mailbox(s)
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in s):
        raise ValidationError("email contains control/space chars")
    # 白名单形状：local@domain.tld
    if not _EMAIL_RE.match(s):
        raise ValidationError(f"email does not match whitelist pattern: {s!r}")
    domain = s.split("@", 1)[1]
    _reject_oversize_local_part(s)
    _reject_label_edge_hyphen(domain)
    _reject_malformed_tld(domain)
    return s


# ---------------------------------------------------------------------------
# Exception-visibility refactor.
# ---------------------------------------------------------------------------

class SwallowedExceptionCounter:
    """守护层核心：每次 `except: pass` 用这里替换，确保状态被计数 + 日志 + 退出码区分。

    用法::

        ctr = SwallowedExceptionCounter()
        ...
        except Exception as e:
            ctr.record("detail-fetch", src=u, exc=e)
            continue   # 业务循环需要 continue；可观测性已记录。

    `finalize()` 结束时如 `records > 0`，进程必须收到一个 *非零* 退出码
    （通过 `sys.exit(SwallowedExceptionCounter.EXIT_WITH_SWALLOWED)` 或
    raise `SystemExit(2)`），从而与「真正 0 线索」的 0 退出码严格区分。
    """

    EXIT_WITH_SWALLOWED = 2
    EXIT_GUARD_FAILURE = 3

    def __init__(self) -> None:
        self.by_origin: Counter[Tuple[str, str]] = Counter()
        self.records: list[dict] = []

    def record(self, origin: str, exc: BaseException | None = None, **ctx) -> None:
        """记录一次被吞掉的异常（origin + 上下文）。

        调用方在 `except` 块内调用此方法并把当前异常 *传进来*。
        这样调用方的 except 块就能继续正常吞异常，守护层也能拿到真实的 exc_type/msg。

        `ctx` 应当只包含 *用户已对外暴露* 的字段——严禁把 SECRET / 邮箱
        完整内容等塞进来，避免日志成为新的敏感面。
        """
        if exc is None:
            # 兜底：调用方忘了传 — 用 RuntimeError 占位，但记录明确告警。
            exc_type = RuntimeError
            exc_msg = "caller did not pass exception"
        else:
            exc_type = type(exc)
            exc_msg = str(exc)
        key = (origin, exc_type.__name__)
        self.by_origin[key] += 1
        self.records.append(
            {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "origin": origin,
                "exc_type": exc_type.__name__,
                "msg": exc_msg[:80],
                "ctx": {k: _sanitize_for_log(v) for k, v in ctx.items()},
            }
        )
        # 结构化日志（单行 JSON），便于机械验证。
        print(json.dumps(self.records[-1], ensure_ascii=False), file=sys.stderr)

    def finalize(self) -> int:
        """返回退出码：被吞异常 >0 时返回 EXIT_WITH_SWALLOWED (=2)，否则 0."""
        if not self.records:
            return 0
        return self.EXIT_WITH_SWALLOWED


def _sanitize_for_log(value: object) -> object:
    """日志安全：截断长字符串，并把任何 email/URL 当字符串处理；不做 PII 推断。"""
    if isinstance(value, str):
        if len(value) > 80:
            return value[:77] + "..."
        return value
    return value


# ---------------------------------------------------------------------------
# Hooked versions of the engine's three entry points.
# ---------------------------------------------------------------------------

def safe_fetch(
    fetch_fn: Callable[[str], str],
    url: str,
    *,
    counter: SwallowedExceptionCounter,
    origin: str,
) -> str | None:
    """取代 `engine_redacted.py` 中 `try: h = fetch(u) except: pass`。

    返回 None 当且仅当守护层成功捕获并记录了一个异常；
    返回 string 当成功 fetch。
    """
    try:
        validate_list_url(url)
        return fetch_fn(url)
    except ValidationError as e:
        counter.record(origin, exc=e, msg=str(e), url_tail=url[-40:])
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        counter.record(origin, exc=e, url_tail=url[-40:])
    except Exception as e:  # 守护层最后兜底；防止安静错误。
        counter.record(origin, exc=e, url_tail=url[-40:])
    return None


def safe_email_iter(
    raw_html: str,
    *,
    counter: SwallowedExceptionCounter,
) -> Iterable[str]:
    """对 `re.findall(...)` 的输出做逐条 validate_email；非法项被拒 + 计数。"""
    try:
        # 原行为：re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', h)
        # 守护层额外捕获：如果 *没有* 任何匹配，就把空集合/空列表也包装到结构里。
        candidates = re.findall(
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", raw_html
        )
    except re.error as e:
        counter.record("regex-mismatch", exc=e)
        return
    for raw in candidates:
        try:
            yield validate_email(raw)
        except ValidationError as e:
            counter.record("email-reject", exc=e, email_head=raw[:20], msg=str(e))


# ---------------------------------------------------------------------------
# Smoke-runner (used by RUN_NOTES.md examples, not by production cron).
# ---------------------------------------------------------------------------

def _stub_fetch(_: str) -> str:
    """离线 smoke fetch：不发网络请求。"""
    raise OSError("smoke: network disabled in test env")


def smoke_run() -> int:
    counter = SwallowedExceptionCounter()
    # 入口 1: 列表页 URL 构造失败 — 验证失败必须被守门抓到。
    try:
        validate_list_url("not-a-url")
    except ValidationError as e:
        counter.record("list-url-preflight", msg=str(e))
    # 入口 2: 详情页 fetch 失败 — 不应再被裸 except: pass 吞下。
    safe_fetch(_stub_fetch, "http://stub.local/t", counter=counter, origin="detail")
    # 入口 3: 邮箱正则输出 — 三个 honeypot 必须全被拒 + 一行结构化日志。
    sample_html = "Contact: %E6..@qq.com <a href=mailto:foo.bar@example.com>x</a>"
    kept = list(safe_email_iter(sample_html, counter=counter))
    print(f"smoke: kept_emails={kept!r} swallowed_records={len(counter.records)}",
          file=sys.stderr)
    return counter.finalize()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(smoke_run())
