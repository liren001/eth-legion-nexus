#!/usr/bin/env python3
"""每日自主获客引擎 v1 — 自动爬公告→提邮箱→发冷邮件→登记台账
cron: 每日早上7:30自动执行 | 无需人工干预"""
import urllib.request, urllib.parse, re, json, time, smtplib, random, sys, logging
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr
from pathlib import Path

BASE = Path(__file__).parent
SECRETS = {'account_175': 'REDACTED', 'imap_auth_175': 'REDACTED'}  # credentials redacted
LEDGER = BASE / 'ledger.json'
LEADS_ALL = BASE / 'leads_all.json'

# 公告源: 中央+地方(扩量)
SOURCES = [
    'http://www.ccgp.gov.cn/cggg/zygg/gkzb/index.htm',
    'http://www.ccgp.gov.cn/cggg/zygg/gkzb/index_1.htm',
    'http://www.ccgp.gov.cn/cggg/dfgg/gkzb/index.htm',
    'http://www.ccgp.gov.cn/cggg/dfgg/gkzb/index_1.htm',
    'http://www.ccgp.gov.cn/cggg/dfgg/gkzb/index_2.htm',
]

LOG = logging.getLogger(__name__)
ERROR_EXIT = 2

class RunStatus:
    def __init__(self):
        self.errors = 0

    def fail(self, stage, error):
        self.errors += 1
        # Do not include page bodies, mailbox addresses or credentials in logs.
        LOG.error("outreach_error stage=%s type=%s count=%d", stage,
                  type(error).__name__, self.errors)

    @property
    def exit_code(self):
        return ERROR_EXIT if self.errors else 0


def validate_url(url):
    if not isinstance(url, str) or any(c.isspace() for c in url):
        raise ValueError("invalid URL")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("invalid URL")
    if parts.username is not None or parts.password is not None:
        raise ValueError("URL credentials are unsupported")
    parts.port  # Validate malformed/out-of-range ports.
    return url


def detail_url(source, relative):
    validate_url(source)
    if not isinstance(relative, str) or not re.fullmatch(
            r"\./\d{6}/t\d+_\d+\.htm", relative):
        raise ValueError("invalid detail path")
    url = validate_url(urllib.parse.urljoin(source, relative))
    if urllib.parse.urlsplit(url).netloc != urllib.parse.urlsplit(source).netloc:
        raise ValueError("detail host changed")
    return url


def validate_page(page):
    if not isinstance(page, str):
        raise TypeError("fetch must return decoded HTML text")
    return page


def valid_email(email):
    if not isinstance(email, str) or email.count("@") != 1:
        return False
    local, domain = email.split("@")
    if not 1 <= len(local) <= 40 or "%" in local:
        return False
    if not re.fullmatch(r"[A-Za-z0-9._+\-]+", local):
        return False
    if local.startswith(".") or local.endswith(".") or ".." in local:
        return False
    labels = domain.split(".")
    return (len(domain) <= 253 and len(labels) >= 2
            and all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                    for label in labels)
            and re.fullmatch(r"[A-Za-z]{2,63}", labels[-1]) is not None)


def fetch(url, timeout=15):
    return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'}), timeout=timeout).read().decode('utf-8','replace')

def collect(status=None):
    """爬公告详情页, 提机构邮箱, 排除已发"""
    status = status if status is not None else RunStatus()
    sent = set()
    if LEADS_ALL.exists():
        for l in json.load(open(LEADS_ALL)): sent.add(l['email'])
    leads, titles = [], []
    for src in SOURCES:
        try:
            h = validate_page(fetch(validate_url(src)))
            for row in re.findall(r'href="(\./\d{6}/t\d+_\d+\.htm)"[^>]*>([^<]{12,80})</a>', h):
                if not isinstance(row, tuple) or len(row) != 2:
                    raise ValueError('invalid list match shape')
                u, t = row
                titles.append((t.strip(), detail_url(src, u)))
        except Exception as e:
            status.fail('list', e)
        time.sleep(0.3)
    for row in titles:
        if len(leads) >= 40: break  # 每日上限40新邮箱
        try:
            t, u = row
            h = validate_page(fetch(validate_url(u)))
            for e in list(set(re.findall(r'''[^\s<>"'(),;:]+@[^\s<>"'(),;:]+''', h))):
                if valid_email(e) and e not in sent and not re.match(r'^\d+@', e):
                    leads.append({'email': e, 'title': t[:50], 'url': u, 'date': time.strftime('%F')})
                    sent.add(e)
        except Exception as e:
            status.fail('detail', e)
        time.sleep(0.4)
    return leads

def mailto(leads, status=None):
    status = status if status is not None else RunStatus()
    user, pwd = SECRETS['account_175'], SECRETS['imap_auth_175']
    smtp = smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=30)
    smtp.login(user, pwd)
    sent = 0
    for l in leads:
        digest = f"""您好：

我们是一家数据研究院（ETH-LEGION），每日追踪中国政府采购网全量公告并做结构化分析。

今日信号示例：高校设备更新采购密集发布、医疗IT从新建转向升级、流标重招（二次公告）=竞争度骤降的入场窗口。

如需每周一早收到完整版政采机会周报（含行业定制与流标捡漏清单），回复本邮件即可，¥99/月。回复可获当期完整样例。

—— ETH-LEGION研究院"""
        msg = MIMEText(digest, 'plain', 'utf-8')
        msg['Subject'] = Header('政采情报周报: 本日公告结构与赛道信号', 'utf-8')
        msg['From'] = formataddr(('ETH-LEGION研究院', user))
        msg['To'] = l['email']
        try:
            smtp.sendmail(user, [l['email']], msg.as_string())
            l['sent'] = True; sent += 1
        except Exception as e:
            l['sent'] = False; l['err'] = str(e)[:50]
            status.fail('send', e)
        time.sleep(random.uniform(1.5, 3))
    smtp.quit()
    return sent

def main():
    status = RunStatus()
    leads = collect(status)
    print(f'今日新线索: {len(leads)}')
    if not leads:
        print('无新线索, 结束'); return status.exit_code
    sent = mailto(leads, status)
    # 台账
    all_leads = json.load(open(LEADS_ALL)) if LEADS_ALL.exists() else []
    all_leads += leads
    json.dump(all_leads, open(LEADS_ALL, 'w'), ensure_ascii=False, indent=1)
    pool = json.load(open(LEDGER))
    pool.setdefault('outreach', []).append({'date': time.strftime('%F'), 'new_leads': len(leads), 'sent': sent})
    json.dump(pool, open(LEDGER, 'w'), ensure_ascii=False, indent=1)
    print(f'发送: {sent} | 累计线索: {len(all_leads)} | 台账已更新')

    return status.exit_code

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    try:
        sys.exit(main())
    except Exception as error:
        LOG.error('outreach_error stage=main type=%s', type(error).__name__)
        sys.exit(ERROR_EXIT)
