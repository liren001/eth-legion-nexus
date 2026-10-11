#!/usr/bin/env python3
"""BOUNTY-002 判卷 — 2lll5 (PR #9) 全量盲跑, 2026-10-09巡逻哨执行
====================================================================
口径与 run1(bounty2_judge.py)/run2 完全一致:
- holdout = 行401..3510 (N=3110), 锚点: yuruyang total=4851 lift=1.4294
- LABEL-PERM 10,000次 (seed=20261009), p=(exceed+1)/10001
- 合格线: lift >= 1.15 AND p < 0.001 (预承诺)

2lll5 方法 (PR#9 solution.py 逐字转写):
- 衰减活跃场: state = decay*state + (1-decay)*onehot(y), decay=2^(-1/0.5)=0.25
- 非循环核: scores[i] = 0.25*s[i] + sum_{d=-5..9, valid} s[i-d]
  (offset∈[-7,7], shift=offset+2∈[-5,9]; 自身额外0.25)
- top6, tie->lower (stable argsort on -scores)
三重验证:
  V1: 向量化 vs 其solution.py逐字代码 (公开前缀targets 2..700逐tick对拍)
  V2: yuruyang锚点复现 (4851/1.5593/1.4294)
  V3: 快速置换 A@KK[Q,:] vs 直接置换实现 (3个随机perm全序列对拍)
"""
import json, sys, time
import numpy as np

N_ALPH, K = 33, 6
BASE = K * K / N_ALPH  # 1.0909

rows = json.load(open('/tmp/full_rows.json'))
# 数据一致性断言
full_alt = json.load(open('/home/z/my-project/lottery_research/bounty2_full_N3511.json'))
if isinstance(full_alt, dict):
    full_alt = full_alt.get('data', full_alt.get('history'))
assert len(rows) == len(full_alt) == 3511, f"数据长度异常: {len(rows)} vs {len(full_alt)}"
pub = json.load(open('/home/z/my-project/lottery_research/bounty_dataset_task2_public.json'))
if isinstance(pub, dict):
    pub = pub.get('data', pub.get('history'))
def _norm(rr):
    if isinstance(rr, dict): return list(rr['reds'])
    return list(rr)
assert [_norm(r) for r in rows[:400]] == [_norm(r) for r in pub[:400]], "公开前缀不一致!"
print("数据断言通过: full=3511, full[:400]==published")

Y = np.zeros((len(rows), N_ALPH))
for i, r in enumerate(rows):
    Y[i, np.array(r, dtype=int) - 1] = 1.0
T = len(Y)
H0 = 400
start = H0 + 1  # holdout 起始行(0-based 401)

# ================= V2: yuruyang 锚点复现 =================
DECAY_YY = 2.0 ** (-1.0 / 2.0)
RADIUS_YY, DRIFT_YY = 6, 1
KER_YY = np.zeros((N_ALPH, N_ALPH))
for d in range(-RADIUS_YY, RADIUS_YY + 1):
    w = 1.0 - abs(d) / (RADIUS_YY + 1)
    src = (np.arange(N_ALPH) - (d + DRIFT_YY)) % N_ALPH
    KER_YY[np.arange(N_ALPH), src] += w

def build_states(Ym, decay):
    S = np.zeros_like(Ym)
    cur = np.zeros(N_ALPH)
    for t in range(len(Ym)):
        S[t] = cur
        cur = decay * cur + (1.0 - decay) * Ym[t]
    return S

def hits_from_scores(Ym, scores, start):
    """start=401 -> 目标tick 401..3511(行400..3510, N=3111, 任务规格口径)."""
    order = np.argsort(-scores, axis=1, kind='stable')[:, :K]
    hits = np.take_along_axis(Ym, order, axis=1).sum(axis=1)
    return hits[start - 1:]

S_yy = build_states(Y, DECAY_YY)
h_yy_all = np.take_along_axis(Y, np.argsort(-(S_yy @ KER_YY), axis=1, kind='stable')[:, :K], axis=1).sum(axis=1)
h_yy = h_yy_all[start - 1:]
# 任务规格口径: 目标t=401..3511(行400..3510, N=3111); run1 yuruyang即此口径
assert int(h_yy.sum()) == 4851 and abs(h_yy.mean()/BASE - 1.429363548698168) < 1e-9, "锚点未复现!"
print(f"[V2锚点] yuruyang: {int(h_yy.sum())}/{len(h_yy)} lift={h_yy.mean()/BASE:.10f}")
print("[V2] 锚点精确复现 ✓ (4851/3111/1.429363548698168, 任务规格口径)")

# ================= 2lll5 向量化实现 =================
DECAY_2L = 2.0 ** (-1.0 / 0.5)   # 0.25
# KK[j, i] = 状态j对号i的贡献 = 0.25*δ(i,j) + 1{i-j ∈ [-5,9]} (非循环)
KK = np.zeros((N_ALPH, N_ALPH))
for j in range(N_ALPH):
    for i in range(N_ALPH):
        if -5 <= i - j <= 9:
            KK[j, i] += 1.0
KK += 0.25 * np.eye(N_ALPH)

S_2l = build_states(Y, DECAY_2L)
scores_2l = S_2l @ KK
h_2l = hits_from_scores(Y, scores_2l, start)

# ================= V1: 与其solution.py逐字对拍 =================
sys.path.insert(0, '/home/z/my-project/lottery_research')
import importlib.util
spec = importlib.util.spec_from_file_location("sol_2lll5", '/home/z/my-project/lottery_research/bounty2_2lll5_solution.py')
sol = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sol)

V1_END = 700  # targets 2..700 (1-based), 即行1..699
exact_hits = []
for tg in range(1, V1_END):  # 0-based target rows 1..699
    pred = set(sol.predict_next(rows[:tg]))
    exact_hits.append(len(pred.intersection(rows[tg])))
vec_hits_prefix = np.take_along_axis(Y, np.argsort(-scores_2l, axis=1, kind='stable')[:, :K], axis=1).sum(axis=1)
mism = int((np.array(exact_hits) != vec_hits_prefix[1:V1_END]).sum())
print(f"[V1对拍] targets 2..{V1_END}: mismatch={mism}/{V1_END-1}")
assert mism == 0, "逐字对拍失败!"
print("[V1] 向量化==逐字代码 ✓")

print(f"\n=== 2lll5 holdout (目标tick 401..3511, 行{start-1}..{T-1}, N={T-start+1}) ===")
print(f"  {int(h_2l.sum())} hits / {len(h_2l)} ticks = {h_2l.mean():.4f}/tick")
print(f"  lift vs uniform: {h_2l.mean()/BASE:.4f}  {'✓' if h_2l.mean()/BASE>=1.15 else '✗'} (线1.15)")

# ================= V3: 快速置换通道验证 =================
# A = L@Y: A[r] = 状态(行r之前), 线性滤波固定, 与perm无关
pow_dec = DECAY_2L ** np.arange(T + 1)
A = np.zeros_like(Y)
for r in range(1, T):
    # S[r] = 0.75 * sum_{k<r} 0.25^{r-1-k} Y[k]
    w = 0.75 * pow_dec[np.arange(r - 1, -1, -1)]
    A[r] = w @ Y[:r]
assert np.allclose(A, S_2l, atol=1e-12), "A != S_2l"
S_2l = None

rng_chk = np.random.default_rng(777)
for trial in range(3):
    P = rng_chk.permutation(N_ALPH)
    Q = np.argsort(P)
    Yp = Y[:, P]
    Sp = build_states(Yp, DECAY_2L)
    direct = hits_from_scores(Yp, Sp @ KK, start)
    fast = hits_from_scores(Y[:, P], A @ KK[Q, :], start)  # hits必须对Yp(与run1 label_perm_p语义一致)
    assert int(direct.sum()) == int(fast.sum()) and (direct == fast).all(), f"V3 perm{trial} 失败"
print("[V3] 快速置换==直接置换 ✓ (3 perms 全序列)")
# 额外: 快速通道 vs 其逐字代码 (1个perm, 前300 tick)
P0 = np.random.default_rng(999).permutation(N_ALPH)
Q0m = np.argsort(P0)  # 旧符号x(1-based)的新标签 = Q0m[x-1]+1, 使Yp0=Y[:,P0]精确成立
rows_perm = [sorted(int(Q0m[x - 1]) + 1 for x in r) for r in rows[:300]]
Yp0 = np.zeros((300, N_ALPH))
for i, r in enumerate(rows_perm):
    Yp0[i, np.array(r, dtype=int) - 1] = 1.0
# 注意: 逐字代码的tie-break在置换后按新标签序; 快速通道同样
ex300 = []
for tg in range(1, 300):
    pred = set(sol.predict_next(rows_perm[:tg]))
    ex300.append(len(pred.intersection(rows_perm[tg])))
sc_perm300 = A[:300] @ KK[np.argsort(P0), :]
hv = np.take_along_axis(Yp0, np.argsort(-sc_perm300, axis=1, kind='stable')[:, :K], axis=1).sum(axis=1)
mism2 = int((np.array(ex300) != hv[1:300]).sum())
print(f"[V3b] 逐字perm对拍 mismatch={mism2}/299")
assert mism2 == 0
print("[V3b] 快速置换==逐字代码(置换数据) ✓")

# ================= FREQ-CTRL (对照) =================
def run_freq(Ym, start):
    c = Ym[:start - 1].sum(axis=0)
    hits = np.zeros(len(Ym) - 1, dtype=int)
    for t in range(start, len(Ym) + 1):
        order = np.argsort(-c, kind='stable')[:K]
        hits[t - 2] = int(Ym[t - 1, order].sum())
        c = c + Ym[t - 1]
    return hits[start - 2:]

h_freq = run_freq(Y, start)
print(f"\n[FREQ-CTRL] {int(h_freq.sum())} hits = {h_freq.mean():.4f}/tick lift={h_freq.mean()/BASE:.4f}")

# ================= LABEL-PERM 10,000次 =================
reps, seed, batch = 10000, 20261009, 64
rng = np.random.default_rng(seed)
obs_total = int(h_2l.sum())
exceed, done = 0, 0
null_sums = np.zeros(reps)
t0 = time.time()
while done < reps:
    b = min(batch, reps - done)
    for bi in range(b):
        P = rng.permutation(N_ALPH)
        Q = np.argsort(P)
        sc = A @ KK[Q, :]
        order = np.argsort(-sc, axis=1, kind='stable')[:, :K]
        Yp = Y[:, P]
        hp = np.take_along_axis(Yp, order, axis=1).sum(axis=1)
        null_sums[done + bi] = hp[start - 1:].sum()
    exceed = int((null_sums[:done + b] >= obs_total).sum())
    done += b
p = (exceed + 1) / (reps + 1)
null_mean = null_sums.mean() / (T - start + 1) / BASE

print(f"\n=== LABEL-PERM ({reps}次, seed={seed}) ===")
print(f"  观测total={obs_total}, null mean={null_sums.mean():.1f} (null lift基线={null_mean:.4f})")
print(f"  p = {p:.5f}  {'✓' if p < 0.001 else '✗'} (线0.001)")

lift = h_2l.mean() / BASE
qualified = lift >= 1.15 and p < 0.001
print(f"\nVERDICT: {'QUALIFIED' if qualified else 'NOT QUALIFIED'}")

json.dump({
  "submitter": "2lll5", "pr": 9,
  "total": int(h_2l.sum()), "n": int(T - start + 1), "mean": float(h_2l.mean()),
  "lift": float(lift), "p": float(p), "null_mean_lift": float(null_mean),
  "freq_ctrl_lift": float(h_freq.mean() / BASE),
  "qualified": bool(qualified),
  "protocol": "holdout target ticks 401..3511 (rows 400..3510, N=3111, task-spec; anchor yuruyang 4851/1.4293635 reproduced); label-perm 10000 reps seed=20261009; thresholds lift>=1.15 & p<0.001 (pre-committed v3.6)"
}, open('/home/z/my-project/lottery_research/bounty2_verdict_2lll5.json', 'w'), indent=1)
print("saved -> bounty2_verdict_2lll5.json")
