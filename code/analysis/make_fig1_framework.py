# -*- coding: utf-8 -*-
"""make_fig1_framework.py — 期刊版图 1：效度边界的三要件与链条位置

构图约定（2026-10-31 第二版）：
  - 全黑白灰，适配《新闻与传播研究》内页黑白印刷；
  - 三要件（上排）与链条（下排）左右对齐 8—92，链条铺满版心；
  - 图内不写“已测 / 未检验 / 补充已测”等过程性文字，只保留命题编号 P1、P2；
    检验状态由线型承担：实线＝已检验，虚线＝未检验，图注说明；
  - P5 置于链条下方左侧，虚线箭头自“注意”引出，表示不属于链条相邻环节。

输出：paper_figs/jfig1_framework.png（300 dpi，灰度安全）
运行：python analysis/make_fig1_framework.py
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

plt.rcParams["font.sans-serif"] = ["SimHei"]
plt.rcParams["axes.unicode_minus"] = False

INK = "#1A1A1A"      # 主墨色
MID = "#5A5A5A"      # 次级文字
GREY = "#8C8C8C"     # 未检验
LIGHT = "#D0D0D0"    # 辅助线

fig, ax = plt.subplots(figsize=(7.6, 3.6))
ax.set_xlim(0, 100)
ax.set_ylim(0, 48)
ax.axis("off")

# ---------- 三要件 ----------
items = [("归属", "指标属于哪一环节"), ("止点", "跨环即失效"), ("位置性", "边界落在具体环节")]
BW3, GAP3, X0 = 26.0, 3.0, 8.0
Y3, H3 = 38.0, 6.0
for k, (t1, t2) in enumerate(items):
    x = X0 + k * (BW3 + GAP3)
    ax.add_patch(FancyBboxPatch((x, Y3), BW3, H3, boxstyle="square,pad=0",
                                fc="white", ec=INK, lw=1.0))
    ax.text(x + BW3 / 2, Y3 + H3 * 0.66, t1, ha="center", va="center",
            fontsize=11.0, color=INK)
    ax.text(x + BW3 / 2, Y3 + H3 * 0.27, t2, ha="center", va="center",
            fontsize=9.4, color=MID)

# ---------- 链条 ----------
names = ["注意", "安装", "复制", "fork", "PR", "审查"]
BW, GAP = 11.0, 3.5
Y, H = 24.0, 6.0
xs = [X0 + i * (BW + GAP) for i in range(6)]
for name, x in zip(names, xs):
    ax.add_patch(FancyBboxPatch((x, Y), BW, H, boxstyle="square,pad=0",
                                fc="white", ec=INK, lw=1.0))
    ax.text(x + BW / 2, Y + H / 2, name, ha="center", va="center",
            fontsize=10.6, color=INK)
for i in range(5):
    ax.add_patch(FancyArrowPatch((xs[i] + BW, Y + H / 2), (xs[i + 1], Y + H / 2),
                                 arrowstyle="-|>", mutation_scale=8,
                                 color=MID, lw=0.9))

# ---------- 边界：实线＝已检验，虚线＝未检验 ----------
mids = [(xs[i] + BW + xs[i + 1]) / 2 for i in range(5)]
# (x, 是否已检验, 线宽, 标签)
specs = [(mids[0], True, 1.9, "P1"),
         (mids[1], False, 1.1, ""),
         (mids[2], True, 1.4, ""),
         (mids[3], True, 1.9, "P2")]
for x, tested, lw, label in specs:
    ax.plot([x, x], [Y - 5.0, Y + H + 5.0],
            color=INK if tested else GREY, lw=lw,
            ls="-" if tested else (0, (3.2, 2.2)), solid_capstyle="butt")
    if label:
        ax.text(x, Y - 7.2, label, ha="center", va="center",
                fontsize=10.0, color=INK)

# ---------- P5：链外检验 ----------
ax.add_patch(FancyBboxPatch((X0, 3.6), 30, 5.6, boxstyle="square,pad=0",
                            fc="white", ec=GREY, lw=1.0, ls=(0, (4, 3))))
ax.text(X0 + 15, 6.4, "P5 链外检验", ha="center", va="center",
        fontsize=9.8, color=MID)
ax.add_patch(FancyArrowPatch((xs[0] + 3.0, Y - 0.2), (X0 + 8.0, 9.4),
                             arrowstyle="-|>", mutation_scale=8,
                             color=GREY, lw=1.0, ls=(0, (3, 2))))

out = r"C:\Users\diamond\AppData\Local\Temp\jfig1_framework.png"
fig.savefig(out, dpi=300, bbox_inches="tight", pad_inches=0.04)
plt.close(fig)
print("WROTE", out)
