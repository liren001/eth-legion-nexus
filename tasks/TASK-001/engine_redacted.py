#!/usr/bin/env python3
"""每日自主获客引擎 v1 — 自动爬公告→提邮箱→发冷邮件→登记台账
cron: 每日早上7:30自动执行 | 无需人工干预"""
import urllib.request, re, json, time, smtplib, random
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

def fetch(url, timeout=15):
    return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'}), timeout=timeout).read().decode('utf-8','replace')

def collect():
    """爬公告详情页, 提机构邮箱, 排除已发"""
    sent = set()
    if LEADS_ALL.exists():
        for l in json.load(open(LEADS_ALL)): sent.add(l['email'])
    leads, titles = [], []
    for src in SOURCES:
        try:
            h = fetch(src)
            base = src.rsplit('/', 1)[0] + '/'
            titles += [(t.strip(), base + u.lstrip('./')) for u,t in re.findall(r'href="(\./\d{6}/t\d+_\d+\.htm)"[^>]*>([^<]{12,80})</a>', h)]
        except Exception as e:
            print('src ERR', src[-25:], str(e)[:40])
        time.sleep(0.3)
    for t, u in titles:
        if len(leads) >= 40: break  # 每日上限40新邮箱
        try:
            h = fetch(u)
            for e in list(set(re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', h))):
                if e not in sent and not re.match(r'^\d+@', e) and '%' not in e and len(e) < 40:
                    leads.append({'email': e, 'title': t[:50], 'url': u, 'date': time.strftime('%F')})
                    sent.add(e)
        except: pass
        time.sleep(0.4)
    return leads

def mailto(leads):
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
        time.sleep(random.uniform(1.5, 3))
    smtp.quit()
    return sent

def main():
    leads = collect()
    print(f'今日新线索: {len(leads)}')
    if not leads:
        print('无新线索, 结束'); return
    sent = mailto(leads)
    # 台账
    all_leads = json.load(open(LEADS_ALL)) if LEADS_ALL.exists() else []
    all_leads += leads
    json.dump(all_leads, open(LEADS_ALL, 'w'), ensure_ascii=False, indent=1)
    pool = json.load(open(LEDGER))
    pool.setdefault('outreach', []).append({'date': time.strftime('%F'), 'new_leads': len(leads), 'sent': sent})
    json.dump(pool, open(LEDGER, 'w'), ensure_ascii=False, indent=1)
    print(f'发送: {sent} | 累计线索: {len(all_leads)} | 台账已更新')

if __name__ == '__main__':
    main()
