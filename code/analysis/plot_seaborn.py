# -*- coding: utf-8 -*-
"""
plot_seaborn.py —— seaborn 风格重绘 4 张论文统计图
输出 data/results/figs/seaborn/{star_its,hollowing,theta_D_dist,scm_gap}.png
统一学术风格：去上下脊线、浅灰网格、微软雅黑、克制色板、断点清晰标注。
"""
import os, datetime
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns

from plot_data import prep_data, FIGROOT

# ---- 统一风格 ----
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Noto Sans SC", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
sns.set_theme(style="whitegrid", font=["Microsoft YaHei", "SimHei"], rc={
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.color": "#e6e6e6",
    "grid.linewidth": 0.6,
    "axes.edgecolor": "#333333",
    "figure.dpi": 110,
})

# 学术色板（克制、协调）
C_STAR = "#1b6ca8"     # 深蓝（星标/实际）
C_FORK = "#c0504d"     # 暗红（分叉）
C_SYNTH = "#7f7f7f"    # 灰（反事实/合成）
C_HIST = "#4d8f6f"     # 墨绿（直方图）
C_BREAK = "#b03a2e"    # 断点红

OUT = os.path.join(FIGROOT, "seaborn")
os.makedirs(OUT, exist_ok=True)


def _style_axis(ax, xlabel="日期", ylabel=""):
    ax.set_xlabel(xlabel, fontsize=11)
    ax.set_ylabel(ylabel, fontsize=11)
    ax.tick_params(labelsize=9.5)
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")


def _breakline(ax, date_str, label, ymax, color=C_BREAK, dy=0.92):
    bd = datetime.date.fromisoformat(date_str)
    ax.axvline(bd, color=color, ls="--", lw=1.1, alpha=0.75, zorder=3)
    ax.text(bd, ymax * dy, label, rotation=90, va="top", ha="right",
            fontsize=8.5, color=color)


def fig7_star_its(d):
    fig, ax = plt.subplots(figsize=(10, 4.4))
    ax.plot(d["s_dates"], d["s_ma"], color=C_STAR, lw=1.6,
            label="7 日移动平均 star/天", zorder=4)
    _breakline(ax, "2026-02-03", "冲击簇 (ClawHavoc)", max(d["s_ma"]))
    _breakline(ax, "2026-03-24", "Silverfort", max(d["s_ma"]))
    ax.fill_between(d["s_dates"], 0, d["s_ma"], color=C_STAR, alpha=0.10, zorder=1)
    _style_axis(ax, ylabel="新增 star/天")
    ax.legend(loc="upper left", frameon=True, fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "star_its.png"), dpi=200)
    plt.close(fig)


def fig8_hollowing(d):
    fig, ax = plt.subplots(figsize=(10, 4.4))
    ax.plot(d["s_dates"], d["s_ma"], color=C_STAR, lw=1.6,
            label="star（浅层参与）", zorder=4)
    ax.plot(d["f_dates"], d["f_ma"], color=C_FORK, lw=1.6,
            label="fork（深层贡献）", zorder=4)
    _breakline(ax, "2026-02-03", "冲击簇", max(d["s_ma"]), color="#999999", dy=0.9)
    _style_axis(ax, ylabel="日均新增")
    ax.legend(loc="upper left", frameon=True, fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "hollowing.png"), dpi=200)
    plt.close(fig)


def fig9_theta_dist(d):
    fig, ax = plt.subplots(figsize=(8.5, 4.2))
    logv = np.log10(np.array(d["tvals"]) + 1)
    sns.histplot(logv, bins=40, color=C_HIST, alpha=0.75, ax=ax,
                 edgecolor="white", linewidth=0.4, kde=False)
    med = np.median(d["tvals"])
    ax.axvline(np.log10(med + 1), color="#8a8a8a", ls="--", lw=1.1, zorder=3)
    ax.text(np.log10(med + 1), ax.get_ylim()[1] * 0.92, f" 中位数 θ(D)={med:,.0f}",
            fontsize=8.5, color="#555555", va="top")
    ax.set_xlabel("log10(累计 star + 1)", fontsize=11)
    ax.set_ylabel("fork 事件数", fontsize=11)
    ax.tick_params(labelsize=9.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "theta_D_dist.png"), dpi=200)
    plt.close(fig)


def fig10_scm(d):
    fig, ax = plt.subplots(figsize=(9.5, 4.4))
    ax.plot(d["scm_dates"], d["scm_actual"], color=C_STAR, lw=1.7,
            label="实际 anthropics/skills", zorder=4)
    ax.plot(d["scm_dates"], d["scm_synth"], color=C_SYNTH, lw=1.7, ls="--",
            label="合成控制（反事实）", zorder=4)
    bd = datetime.date.fromisoformat("2026-03-24")
    ax.axvline(bd, color="#999999", ls=":", lw=1.2, alpha=0.9, zorder=3)
    ax.text(bd, max(d["scm_actual"]) * 0.9, "Silverfort (2026-03-24)",
            fontsize=8.5, color="#555555", ha="left")
    _style_axis(ax, ylabel="周度新增 star")
    ax.legend(loc="upper right", frameon=True, fontsize=9)
    # 图内小注：拟合质量
    ax.text(0.02, 0.03,
            f"pre RMSE={d['pre_rmse']:,.0f}  post RMSE={d['post_rmse']:,.0f}  ratio={d['ratio']:.2f}",
            transform=ax.transAxes, fontsize=8, color="#666666")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "scm_gap.png"), dpi=200)
    plt.close(fig)


def main():
    d = prep_data()
    fig7_star_its(d)
    fig8_hollowing(d)
    fig9_theta_dist(d)
    fig10_scm(d)
    print("seaborn 版 4 图已输出到", OUT)


if __name__ == "__main__":
    main()
