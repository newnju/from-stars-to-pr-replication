# -*- coding: utf-8 -*-
"""make_journal_figures.py — 期刊版 4 图（2026-10-30）"""
import json, os
import numpy as np, pandas as pd
from scipy import stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

plt.rcParams["font.sans-serif"] = ["SimHei"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["font.size"] = 12
plt.rcParams["axes.titlesize"] = 12
plt.rcParams["axes.labelsize"] = 11

ROOT = r"E:\Skill扩散论文_可复现项目"
COL = os.path.join(ROOT, "external_data", "collected_20261024")
OUT = r"C:\Users\diamond\AppData\Local\Temp\skillfigs"
os.makedirs(OUT, exist_ok=True)

# ---------- 数据 ----------
p1 = json.load(open(os.path.join(ROOT, "data", "results", "fig_input_p1_p2.json"), encoding="utf-8"))
hz = json.load(open(os.path.join(ROOT, "data", "results", "fig_input_fork_hazard.json"), encoding="utf-8"))
meta = json.load(open(os.path.join(ROOT, "data", "repos_meta.json"), encoding="utf-8"))
inst = {}
for fn in ["market_full.jsonl", "market_retry.jsonl", "market_extra.jsonl"]:
    p = os.path.join(COL, fn)
    if not os.path.exists(p): continue
    for line in open(p, encoding="utf-8", errors="replace"):
        try: d = json.loads(line)
        except Exception: continue
        if d.get("type") == "skills_sh" and d.get("repo") and (d.get("total_installs") or 0) > 0:
            inst[d["repo"]] = max(inst.get(d["repo"], 0), d["total_installs"])
D = pd.DataFrame([{"repo": r, "stars": (meta.get(r) or {}).get("stars") or 0, "installs": v}
                  for r, v in inst.items()])
D = D[D.stars > 0]

# ---------- 图 1 已迁出 ----------
# 图 1（效度边界的三要件与检验覆盖）改由 analysis/make_fig1_framework.py 生成，
# 输出 paper_figs/jfig1_framework.png。此处的旧版链式图代码已停用，避免覆盖新版。
# 旧代码共 47 行，见 git 历史或 2026-10-30 备份。

# ---------- 图 2 P1 ----------
fig, axes = plt.subplots(1, 2, figsize=(7.8, 3.5), gridspec_kw={"width_ratios": [1.05, 1]})
ax = axes[0]
ax.scatter(D.stars, D.installs, s=10, alpha=.55, color="#1A1A1A", edgecolor="none")
ax.set_xscale("log"); ax.set_yscale("log")
ax.set_xlabel("星标（+1，对数）"); ax.set_ylabel("安装（+1，对数）")
ax.set_title("(a) 星标—安装：ρ=0.204")
ax.text(.04, .94, "95%CI [0.056, 0.343]\n等价界 ρ=0.5 可排除", transform=ax.transAxes,
        fontsize=9.5, va="top", color="#333333")

ax = axes[1]
rows = [("总体", p1["overall"])] + [("星标 Q%d" % q["stratum"], q) for q in p1["star_quartiles"]] + \
       [("年龄 T%d" % t["stratum"], t) for t in p1["age_tertiles"]]
ys = np.arange(len(rows))[::-1]
for y, (lab, r) in zip(ys, rows):
    ax.plot([r["ci"][0], r["ci"][1]], [y, y], color="#1A1A1A", lw=1.6)
    ax.plot(r["rho"], y, "o", color="#1A1A1A", ms=5)
    ax.text(-0.58, y, lab, ha="left", va="center", fontsize=10)
ax.axvline(0, color="#B0B0B0", lw=.8, ls=":")
ax.axvline(0.5, color="#8C8C8C", lw=1, ls="--")
# 等价界标签已移入图注，图内不再标注
ax.set_xlim(-0.6, 0.75); ax.set_ylim(-0.7, len(rows) - 0.3)
ax.set_yticks([]); ax.set_xlabel("Spearman ρ（95%CI）")
ax.set_title("(b) 分层敏感性：层内 ρ 0.12–0.37")
fig.subplots_adjust(wspace=0.55)
fig.savefig(os.path.join(OUT, "jfig2_p1.png"), dpi=300, bbox_inches="tight")
plt.close(fig)

# ---------- 图 3 P2 全量 fork 风险 ----------
fig, axes = plt.subplots(1, 2, figsize=(7.8, 3.5))
ax = axes[0]
for key, lab, color in [("overall", "全部 fork", "#1A1A1A"),
                        ("list", "清单仓", "#6E6E6E"),
                        ("non_list", "非清单仓", "#B8B8B8")]:
    c = hz[key]["curve"]
    ax.plot(c["times_h"], c["cum_pct"], lw=1.8, label=f"{lab}（n={hz[key]['n_forks']:,}）", color=color)
for t, lab in [(1, "1h"), (24, "24h"), (168, "7d"), (720, "30d")]:
    ax.axvline(t, color="#CCCCCC", lw=.6, ls=":")
    ax.text(t, 9.4, lab, ha="center", fontsize=9, color="#666666")
ax.set_xscale("log")
ax.set_xlim(0.1, 8760); ax.set_ylim(0, 10)
ax.set_xlabel("fork 后时间（小时，对数）"); ax.set_ylabel("首次回流累计发生率（%）")
ax.set_title("(a) 全量 fork 的累计回流风险")
ax.legend(frameon=False, fontsize=9, loc="lower right")

ax = axes[1]
b = hz["overall"]["hazard_bins"]
labels = [x["bin"] for x in b]
vals = [x["hazard_pct"] for x in b]
ax.bar(range(len(vals)), vals, color="#1A1A1A", width=.62)
for i, v in enumerate(vals):
    ax.text(i, v * 1.12, f"{v:.2f}", ha="center", fontsize=9)
ax.set_yscale("log"); ax.set_ylim(0.05, 10)
disp = {"90–365d": "90d–1y", ">365d": ">1y"}
ax.set_xticks(range(len(labels)))
ax.set_xticklabels([disp.get(x, x) for x in labels], fontsize=8.5, rotation=30, ha="right")
ax.set_ylabel("区间风险率（%，对数）")
ax.set_title("(b) 分区间风险：首小时 4.82%")
fig.tight_layout()
fig.savefig(os.path.join(OUT, "jfig3_p2.png"), dpi=300, bbox_inches="tight")
plt.close(fig)

# ---------- 图 4 P4 ----------
fig, axes = plt.subplots(1, 2, figsize=(7.8, 3.4), gridspec_kw={"width_ratios": [1.05, 1]})
ax = axes[0]
labels = ["<50", "50–199", "200–999", "≥1,000"]
vals = [5.8, 11.2, 16.0, 26.2]
bars = ax.bar(labels, vals, color=["#DCDCDC", "#B0B0B0", "#7A7A7A", "#1A1A1A"], width=.6)
for b, v in zip(bars, vals):
    ax.text(b.get_x() + b.get_width() / 2, v + .6, f"{v:.1f}%", ha="center", fontsize=9.5)
ax.axhline(30, color="#8C8C8C", ls="--", lw=1)
ax.text(3.35, 30.8, "三成", color="#8C8C8C", fontsize=9, ha="right")
ax.set_ylim(0, 34)
ax.set_xlabel("仓库 PR 量"); ax.set_ylabel("正式审查覆盖率（%）")
ax.set_title("(a) 审查覆盖随规模上升但恒低于三成")

ax = axes[1]
auc, lo, hi = .595, .545, .644
ax.errorbar([1], [auc], yerr=[[auc - lo], [hi - auc]], fmt="o", color="#1A1A1A",
            capsize=6, ms=7, lw=1.6)
ax.axhline(.5, color="#B0B0B0", ls="--", lw=1)
ax.text(1.03, .503, "随机基线 0.5", fontsize=8.5, va="bottom", color="#666666")
ax.set_xlim(.7, 1.45); ax.set_ylim(.48, .68)
ax.set_xticks([1]); ax.set_xticklabels(["合并结果"])
ax.set_ylabel("AUC（五折仓库分组）")
ax.set_title("(b) 合并弱可预测：0.595 [0.545, 0.644]")
fig.tight_layout()
fig.savefig(os.path.join(OUT, "jfig4_p4.png"), dpi=300, bbox_inches="tight")
plt.close(fig)

print("OK journal figs")
