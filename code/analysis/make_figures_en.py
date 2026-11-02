# -*- coding: utf-8 -*-
"""make_figures_en.py — 英文投稿版四图（ICA / APA 体例）

与中文期刊版同源同数据，只改标签语言与字体：
  - 字体 Times New Roman（英文期刊正文同族）
  - 标签全英文，符号沿用 |ρ|、ρ、α
  - 灰度安全，与中文版配色一致
输出：paper_figs/en/jfig1_framework.png, jfig2_p1.png, jfig3_p2.png, jfig4_p4.png
运行：python analysis/make_figures_en.py
"""
import json, os
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

plt.rcParams["font.family"] = "serif"
plt.rcParams["font.serif"] = ["Times New Roman", "DejaVu Serif"]
plt.rcParams["mathtext.fontset"] = "stix"
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["font.size"] = 12
plt.rcParams["axes.titlesize"] = 12
plt.rcParams["axes.labelsize"] = 11

ROOT = r"E:\Skill扩散论文_可复现项目"
COL = os.path.join(ROOT, "external_data", "collected_20261024")
OUT = os.path.join(ROOT, "paper_figs", "en")
os.makedirs(OUT, exist_ok=True)

INK, MID, GREY = "#1A1A1A", "#5A5A5A", "#8C8C8C"

# ---------- 图 1 框架 ----------
fig, ax = plt.subplots(figsize=(7.6, 3.6))
ax.set_xlim(0, 100); ax.set_ylim(0, 48); ax.axis("off")

items = [("Attribution", "which segment it records"),
         ("Endpoint", "validity ends there"),
         ("Positionality", "boundaries are uneven")]
BW3, GAP3, X0 = 26.0, 3.0, 8.0
Y3, H3 = 38.0, 6.0
for k, (t1, t2) in enumerate(items):
    x = X0 + k * (BW3 + GAP3)
    ax.add_patch(FancyBboxPatch((x, Y3), BW3, H3, boxstyle="square,pad=0",
                                fc="white", ec=INK, lw=1.0))
    ax.text(x + BW3 / 2, Y3 + H3 * 0.68, t1, ha="center", va="center",
            fontsize=11.0, color=INK)
    ax.text(x + BW3 / 2, Y3 + H3 * 0.27, t2, ha="center", va="center",
            fontsize=9.2, color=MID)

names = ["Attention", "Install", "Copy", "Fork", "PR", "Review"]
BW, GAP = 11.0, 3.5
Y, H = 24.0, 6.0
xs = [X0 + i * (BW + GAP) for i in range(6)]
for name, x in zip(names, xs):
    ax.add_patch(FancyBboxPatch((x, Y), BW, H, boxstyle="square,pad=0",
                                fc="white", ec=INK, lw=1.0))
    ax.text(x + BW / 2, Y + H / 2, name, ha="center", va="center",
            fontsize=9.8, color=INK)
for i in range(5):
    ax.add_patch(FancyArrowPatch((xs[i] + BW, Y + H / 2), (xs[i + 1], Y + H / 2),
                                 arrowstyle="-|>", mutation_scale=8,
                                 color=MID, lw=0.9))

mids = [(xs[i] + BW + xs[i + 1]) / 2 for i in range(5)]
specs = [(mids[0], "solid", 1.9, "P1"),
         (mids[1], "dashed", 1.1, ""),
         (mids[2], "dashdot", 1.4, ""),
         (mids[3], "solid", 1.9, "P2")]
STYLE = {"solid": ("-", INK), "dashed": ((0, (3.2, 2.2)), GREY),
         "dashdot": ((0, (6.0, 2.2, 1.2, 2.2)), INK)}
for x, kind, lw, label in specs:
    ls, color = STYLE[kind]
    ax.plot([x, x], [Y - 5.0, Y + H + 5.0], color=color, lw=lw, ls=ls,
            solid_capstyle="butt")
    if label:
        ax.text(x, Y - 7.2, label, ha="center", va="center",
                fontsize=10.0, color=INK)

ax.add_patch(FancyBboxPatch((X0, 3.6), 34, 5.6, boxstyle="square,pad=0",
                            fc="white", ec=GREY, lw=1.0, ls=(0, (4, 3))))
ax.text(X0 + 17, 6.4, "P5 out-of-chain check", ha="center", va="center",
        fontsize=9.6, color=MID)
ax.add_patch(FancyArrowPatch((xs[0] + 3.0, Y - 0.2), (X0 + 9.0, 9.4),
                             arrowstyle="-|>", mutation_scale=8,
                             color=GREY, lw=1.0, ls=(0, (3, 2))))

fig.savefig(os.path.join(OUT, "jfig1_framework.png"), dpi=300,
            bbox_inches="tight", pad_inches=0.04)
plt.close(fig)

# ---------- 数据 ----------
p1 = json.load(open(os.path.join(ROOT, "data", "results", "fig_input_p1_p2.json"), encoding="utf-8"))
hz = json.load(open(os.path.join(ROOT, "data", "results", "fig_input_fork_hazard.json"), encoding="utf-8"))
meta = json.load(open(os.path.join(ROOT, "data", "repos_meta.json"), encoding="utf-8"))
inst = {}
for fn in ["market_full.jsonl", "market_retry.jsonl", "market_extra.jsonl"]:
    p = os.path.join(COL, fn)
    if not os.path.exists(p):
        continue
    for line in open(p, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("type") == "skills_sh" and d.get("repo") and (d.get("total_installs") or 0) > 0:
            inst[d["repo"]] = max(inst.get(d["repo"], 0), d["total_installs"])
D = pd.DataFrame([{"repo": r, "stars": (meta.get(r) or {}).get("stars") or 0, "installs": v}
                  for r, v in inst.items()])
D = D[D.stars > 0]

# ---------- 图 2 P1 ----------
fig, axes = plt.subplots(1, 2, figsize=(7.8, 3.5), gridspec_kw={"width_ratios": [1.05, 1]})
ax = axes[0]
ax.scatter(D.stars, D.installs, s=10, alpha=.55, color=INK, edgecolor="none")
ax.set_xscale("log"); ax.set_yscale("log")
ax.set_xlabel("Stars (+1, log scale)"); ax.set_ylabel("Installs (+1, log scale)")
ax.set_title("(a) Stars–installs: ρ = .204")
ax.text(.04, .94, "95% CI [.056, .343]\n|ρ| ≥ .50 excluded", transform=ax.transAxes,
        fontsize=9.5, va="top", color="#333333")

ax = axes[1]
rows = [("Overall", p1["overall"])] + [("Stars Q%d" % q["stratum"], q) for q in p1["star_quartiles"]] + \
       [("Age T%d" % t["stratum"], t) for t in p1["age_tertiles"]]
ys = np.arange(len(rows))[::-1]
for y, (lab, r) in zip(ys, rows):
    ax.plot([r["ci"][0], r["ci"][1]], [y, y], color=INK, lw=1.6)
    ax.plot(r["rho"], y, "o", color=INK, ms=5)
    ax.text(-0.58, y, lab, ha="left", va="center", fontsize=10)
ax.axvline(0, color="#B0B0B0", lw=.8, ls=":")
ax.axvline(0.5, color=GREY, lw=1, ls="--")
ax.set_xlim(-0.6, 0.75); ax.set_ylim(-0.7, len(rows) - 0.3)
ax.set_yticks([]); ax.set_xlabel("Spearman ρ (95% CI)")
ax.set_title("(b) Stratified: ρ = .12–.37", fontsize=11.2)
fig.subplots_adjust(wspace=0.55)
fig.savefig(os.path.join(OUT, "jfig2_p1.png"), dpi=300, bbox_inches="tight")
plt.close(fig)

# ---------- 图 3 P2 ----------
fig, axes = plt.subplots(1, 2, figsize=(7.8, 3.5))
ax = axes[0]
for key, lab, color in [("overall", "All forks", INK),
                        ("list", "Curated", "#6E6E6E"),
                        ("non_list", "Non-curated", "#B8B8B8")]:
    c = hz[key]["curve"]
    ax.plot(c["times_h"], c["cum_pct"], lw=1.8,
            label="%s (n=%s)" % (lab, format(hz[key]["n_forks"], ",")), color=color)
for t, lab in [(1, "1h"), (24, "24h"), (168, "7d"), (720, "30d")]:
    ax.axvline(t, color="#CCCCCC", lw=.6, ls=":")
    ax.text(t, 9.4, lab, ha="center", fontsize=9, color="#666666")
ax.set_xscale("log")
ax.set_xlim(0.1, 8760); ax.set_ylim(0, 10)
ax.set_xlabel("Hours since fork (log scale)")
ax.set_ylabel("Cumulative first-return incidence (%)")
ax.set_title("(a) Cumulative first-return risk, all forks")
ax.legend(frameon=False, fontsize=9, loc="lower right")

ax = axes[1]
b = hz["overall"]["hazard_bins"]
labels = [x["bin"] for x in b]
vals = [x["hazard_pct"] for x in b]
ax.bar(range(len(vals)), vals, color=INK, width=.62)
for i, v in enumerate(vals):
    ax.text(i, v * 1.12, f"{v:.2f}", ha="center", fontsize=9)
ax.set_yscale("log"); ax.set_ylim(0.05, 10)
disp = {"90–365d": "90d–1y", ">365d": ">1y"}
ax.set_xticks(range(len(labels)))
ax.set_xticklabels([disp.get(x, x) for x in labels], fontsize=8.5, rotation=30, ha="right")
ax.set_ylabel("Interval hazard rate (%, log scale)")
ax.set_title("(b) Interval hazards: 4.82% in first hour")
fig.tight_layout()
fig.savefig(os.path.join(OUT, "jfig3_p2.png"), dpi=300, bbox_inches="tight")
plt.close(fig)

# ---------- 图 4 P4 ----------
fig, axes = plt.subplots(1, 2, figsize=(7.8, 3.4), gridspec_kw={"width_ratios": [1.05, 1]})
ax = axes[0]
labels = ["<50", "50–199", "200–999", "≥1,000"]
vals = [5.8, 11.2, 16.0, 26.2]
bars = ax.bar(labels, vals, color=["#DCDCDC", "#B0B0B0", "#7A7A7A", INK], width=.6)
for bb, v in zip(bars, vals):
    ax.text(bb.get_x() + bb.get_width() / 2, v + .6, f"{v:.1f}%", ha="center", fontsize=9.5)
ax.axhline(30, color=GREY, ls="--", lw=1)
ax.text(3.35, 30.8, "30%", color=GREY, fontsize=9, ha="right")
ax.set_ylim(0, 34)
ax.set_xlabel("Repository PR volume")
ax.set_ylabel("Formal review decision coverage (%)")
ax.set_title("(a) Coverage rises with volume, below 30%")

ax = axes[1]
auc, lo, hi = .595, .545, .644
ax.errorbar([1], [auc], yerr=[[auc - lo], [hi - auc]], fmt="o", color=INK,
            capsize=6, ms=7, lw=1.6)
ax.axhline(.5, color="#B0B0B0", ls="--", lw=1)
ax.text(1.03, .503, "Chance (.50)", fontsize=8.5, va="bottom", color="#666666")
ax.set_xlim(.7, 1.45); ax.set_ylim(.48, .68)
ax.set_xticks([1]); ax.set_xticklabels(["Merge outcome"])
ax.set_ylabel("AUC (five-fold, repo-grouped)")
ax.set_title("(b) Weak predictability: .595 [.545, .644]")
fig.tight_layout()
fig.savefig(os.path.join(OUT, "jfig4_p4.png"), dpi=300, bbox_inches="tight")
plt.close(fig)

print("OK", OUT)
