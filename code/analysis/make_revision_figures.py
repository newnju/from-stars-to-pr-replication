# -*- coding: utf-8 -*-
"""make_revision_figures.py — 为大修稿 6 生成 4 张新图（2026-10-30）"""
import json, os, glob, datetime
import numpy as np
import pandas as pd
from scipy import stats
from scipy.stats import gaussian_kde
from sklearn.mixture import GaussianMixture
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["SimHei"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["font.size"] = 11.5
plt.rcParams["axes.titlesize"] = 12
plt.rcParams["axes.labelsize"] = 11

ROOT = r"E:\Skill扩散论文_可复现项目"
TMP = r"E:\temp\opencode"
OUTDIR = r"C:\Users\diamond\AppData\Local\Temp\skillfigs"
os.makedirs(OUTDIR, exist_ok=True)
COL = os.path.join(ROOT, "external_data", "collected_20261024")

# ---------- 载入 ----------
final = json.load(open(os.path.join(ROOT, "data", "results", "fork_prs_final_20261026.json"), encoding="utf-8"))
P = pd.DataFrame(final["per_parent"])
P["conv"] = P["returning_forks"] / P["n_forks"]
deep = json.load(open(os.path.join(ROOT, "data", "results", "deep_what_data_shows_20261030.json"), encoding="utf-8"))

best = {}
for fn in glob.glob(os.path.join(TMP, "fork_prs*.jsonl")):
    for line in open(fn, encoding="utf-8", errors="replace"):
        try: d = json.loads(line)
        except Exception: continue
        if d.get("type") == "parent" and d.get("complete"):
            p = d["parent"]
            if p not in best or d.get("n_matched", 0) > best[p].get("n_matched", 0):
                best[p] = d

EV = []
for p, d in best.items():
    for l in d.get("links") or []:
        EV.append((p, l.get("author") or "?", l.get("number"), l.get("created_at")))
EV = pd.DataFrame(EV, columns=["parent", "author", "number", "created_at"]).drop_duplicates(
    subset=["parent", "number"])
auth = EV.groupby("author").size().sort_values(ascending=False)

# ---------- 图 11：P2 生成结构 ----------
fig = plt.figure(figsize=(10, 6.4))
gs = fig.add_gridspec(2, 2, height_ratios=[1.1, 1])
ax = fig.add_subplot(gs[0, :])
conv = P["conv"].values
eps = 1e-4
logit = np.log((conv + eps) / (1 - conv + eps))
z = ((logit - logit.mean()) / logit.std()).reshape(-1, 1)
gm = GaussianMixture(1, covariance_type="full", random_state=20261030, n_init=8).fit(z)
ax.hist(logit, bins=24, density=True, color="#90cdf4", edgecolor="white", alpha=.9, label="仓库（n=225）")
grid = np.linspace(logit.min(), logit.max(), 400)
ax.plot(grid, gaussian_kde(logit, bw_method=.35)(grid), color="#2b6cb0", lw=2, label="KDE")
ax.axvline(np.log(0.20 / 0.80), color="#dd6b20", ls="--", lw=1)
ax.text(np.log(0.20 / 0.80) + .1, ax.get_ylim()[1] * .55, "20%", color="#dd6b20", fontsize=9)
ax.set_xlabel("logit(转化率)")
ax.set_ylabel("密度")
ax.set_title("(a) 单峰重尾：GMM BIC 选 k=1")
ax.legend(frameon=False, fontsize=8, loc="upper left")

# (b) 基线
ax = fig.add_subplot(gs[1, 0])
labels = ["全样本", "剔除高转化仓", "剔除 top5 事件仓"]
vals = [6.67, 4.90, 4.74]
meds = [3.95, 3.25, 3.48]
bars = ax.bar(labels, vals, color=["#2b6cb0", "#4a90c2", "#90cdf4"], width=.6)
for b, v, m in zip(bars, vals, meds):
    ax.text(b.get_x() + b.get_width() / 2, v + .12, f"{v:.1f}%", ha="center", fontsize=10)
    ax.text(b.get_x() + b.get_width() / 2, .35, f"中位 {m:.2f}%", ha="center", fontsize=8, color="white")
ax.set_ylim(0, 8)
ax.set_ylabel("fork 加权转化率（%）")
ax.set_title("(b) 头部剔除后的基线")

# (c) 集中度
ax = fig.add_subplot(gs[1, 1])
items = ["top5 父仓\n事件份额", "483 名作者\n事件份额", "其余 99,315 名\n作者事件份额"]
shares = [46.8, 38.9, 61.1]
bars = ax.barh(items[::-1], shares[::-1], color=["#cbd5e0", "#4a90c2", "#2b6cb0"], height=.55)
for b, v in zip(bars, shares[::-1]):
    ax.text(v + 1, b.get_y() + b.get_height() / 2, f"{v:.1f}%", va="center", fontsize=10)
ax.set_xlim(0, 75)
ax.set_xlabel("占全部回流 PR 事件（%）")
ax.set_title("(c) 事件集中度")

plt.tight_layout()
fig.savefig(os.path.join(OUTDIR, "fig11_p2_structure.png"), dpi=300, bbox_inches="tight")
plt.close(fig)

# ---------- 图 12：两个尺度 ----------
fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.2), gridspec_kw={"width_ratios": [1, 1.15]})

# (a) NMI 热图
ax = axes[0]
cols = ["注意力", "采纳", "贡献率", "可见性"]
keys = ["attention", "adoption", "contribution_rate", "visibility"]
nmi = deep["D3_mutual_information"]["normalized_mi"]
M = np.array([[nmi[f"{a}|{b}"] for b in keys] for a in keys], float)
im = ax.imshow(M, cmap="Blues", vmin=0, vmax=1)
ax.set_xticks(range(4)); ax.set_yticks(range(4))
ax.set_xticklabels(cols); ax.set_yticklabels(cols)
for i in range(4):
    for j in range(4):
        v = M[i, j]
        ax.text(j, i, f"{v:.2f}", ha="center", va="center",
                color="white" if v > .55 else "#1a202c", fontsize=9)
ax.set_title("(a) 水平解耦：四层 NMI")
fig.colorbar(im, ax=ax, fraction=.046, pad=.04)

# (b) 仓内周相关分布
ax = axes[1]
stars = json.load(open(os.path.join(TMP, "star_history_v2.json"), encoding="utf-8"))
S = []
for repo, weeks in stars.items():
    for w in weeks:
        S.append((repo, datetime.date.fromtimestamp(w["week"]), max(0, int(w.get("total") or 0))))
S = pd.DataFrame(S, columns=["parent", "week", "inc"])
S = S[S["parent"].isin(set(P["parent"]))]
EVw = EV.copy()
EVw["week"] = pd.to_datetime(EVw["created_at"].str[:10], errors="coerce").dt.date
EVw = EVw.dropna(subset=["week"])
EVw["week"] = EVw["week"].map(lambda d: d - datetime.timedelta(days=(d.weekday() + 1) % 7))
agg = EVw.groupby(["parent", "week"]).size().rename("pr").reset_index()
M2 = S.merge(agg, on=["parent", "week"], how="left")
M2["pr"] = M2["pr"].fillna(0)
M2 = M2.merge(P[["parent", "conv"]], on="parent", how="left")
M2["regime"] = np.where(M2["conv"] >= .20, "高转化制（≥20%）", "低转化制（<20%）")

def rhos(df):
    out = []
    for p, g in df.groupby("parent"):
        g = g.sort_values("week")
        a, b = g["inc"].values, g["pr"].values
        if len(a) < 12 or np.std(a) == 0 or np.std(b) == 0: continue
        r, _ = stats.spearmanr(a, b)
        if np.isfinite(r): out.append(r)
    return np.array(out)

r_lo, r_hi = rhos(M2[M2.regime.str.startswith("低")]), rhos(M2[M2.regime.str.startswith("高")])
parts = ax.violinplot([r_lo, r_hi], positions=[1, 2], showmedians=True, widths=.7)
for pc, c in zip(parts["bodies"], ["#90cdf4", "#f6ad55"]):
    pc.set_facecolor(c); pc.set_alpha(.85); pc.set_edgecolor("none")
for key in ("cbars", "cmins", "cmaxes", "cmedians"):
    parts[key].set_color("#4a5568")
ax.set_xticks([1, 2])
ax.set_xticklabels([f"低转化制\n(n={len(r_lo)})", f"高转化制\n(n={len(r_hi)})"])
ax.axhline(0, color="#a0aec0", lw=.8, ls=":")
ax.set_ylabel("仓内 Spearman ρ（周星标增量 × 周 PR）")
ax.set_title("(b) 动态同向：中位 0.374 / 0.169")
ax.text(.02, .95, "弹性 0.319 / 0.604", transform=ax.transAxes, fontsize=9, color="#4a5568")

plt.tight_layout()
fig.savefig(os.path.join(OUTDIR, "fig12_coupling_scales.png"), dpi=300, bbox_inches="tight")
plt.close(fig)

# ---------- 图 13：双群体 ----------
fig, axes = plt.subplots(1, 2, figsize=(11, 4.1))
ax = axes[0]
counts = auth.values
xs = np.sort(counts)[::-1]
ccdf = np.arange(1, len(xs) + 1) / len(xs)
ax.loglog(xs, ccdf, color="#2b6cb0", lw=1.8)
ax.set_xlabel("作者的回流 PR 数")
ax.set_ylabel("P(X ≥ x)")
ax.set_title("(a) 作者事件数 CCDF（双对数）")
ax.grid(alpha=.25, which="both", ls=":")

ax = axes[1]
c = np.sort(counts)
cum = np.cumsum(c) / c.sum()
x = np.arange(1, len(c) + 1) / len(c)
ax.plot(x, cum, color="#2b6cb0", lw=2, label="作者—事件洛伦兹")
ax.plot([0, 1], [0, 1], color="#a0aec0", ls="--", lw=1, label="完全均等")
ax.axvline(0.624, color="#dd6b20", ls=":", lw=1.2)
ax.axhline(0.139, color="#dd6b20", ls=":", lw=1.2)
ax.text(.30, .24, "62.4% 作者\n仅占 13.9% 事件", fontsize=9.5, color="#dd6b20")
ax.set_xlabel("作者累计份额")
ax.set_ylabel("事件累计份额")
ax.set_title("(b) 双群体：一次性大众 + 极少数常客")
ax.legend(frameon=False, loc="upper left", fontsize=9)

plt.tight_layout()
fig.savefig(os.path.join(OUTDIR, "fig13_dual_population.png"), dpi=300, bbox_inches="tight")
plt.close(fig)

# ---------- 图 14：爆发风险 ----------
hz = deep["D4_burst_hazard"]
fig, axes = plt.subplots(1, 2, figsize=(11, 4.0))
ax = axes[0]
names = {"log_mean4": "近 4 周均值", "age_idx": "仓龄", "log_forks": "fork 规模",
         "log_last": "上周增量", "log_cum": "累计星标"}
items = [(names[k], v) for k, v in hz["coef_standardized"].items() if k in names]
items = sorted(items, key=lambda kv: kv[1])
vals = [v for _, v in items]
ax.barh([k for k, _ in items], vals,
        color=["#e53e3e" if v < 0 else "#2b6cb0" for v in vals], height=.55)
for i, v in enumerate(vals):
    ax.text(v + (.04 if v >= 0 else -.04), i, f"{v:+.2f}", va="center",
            ha="left" if v >= 0 else "right", fontsize=9)
ax.axvline(0, color="#4a5568", lw=.8)
ax.set_xlim(-1.45, 1.30)
ax.set_xlabel("标准化系数")
ax.set_title("(a) 爆发由动量与生命周期驱动")

ax = axes[1]
folds = hz["auc_folds"]
ax.bar([f"折{i+1}" for i in range(len(folds))], folds, color="#90cdf4", width=.55)
ax.axhline(.5, color="#a0aec0", ls="--", lw=1)
ax.axhline(np.mean(folds), color="#dd6b20", ls="-", lw=1.5)
ax.text(len(folds) - .5, np.mean(folds) + .012, f"均值 {np.mean(folds):.3f}", ha="right", fontsize=9, color="#dd6b20")
ax.set_ylim(.45, .75)
ax.set_ylabel("AUC")
ax.set_title("(b) 按仓分组五折验证")

plt.tight_layout()
fig.savefig(os.path.join(OUTDIR, "fig14_burst_hazard.png"), dpi=300, bbox_inches="tight")
plt.close(fig)

print("OK: fig11-14 written")
