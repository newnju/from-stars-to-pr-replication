# -*- coding: utf-8 -*-
"""
plot_plotnine.py —— plotnine（Python 版 ggplot2）风格重绘论文 4 张统计图
输出 data/results/figs/plotnine/{star_its,hollowing,theta_D_dist,scm_gap}.png
风格：theme_minimal + 微软雅黑，接近 R ggplot2 期刊审美。

四张图分别为论文中的 图7 / 图8 / 图9 / 图10：
  图7  全生态每日新增 star（7日移动平均）+ 审计断点
  图8  star 浅层 vs fork 深层 增速脱钩
  图9  贡献门槛 θ(D) 对数分布
  图10 合成控制 实际 vs 反事实（标注处理单元特殊性）

修复记录（相对首版）：
  1) geom_line 缺 group aesthetic 导致单点散点 → 全部加 group
  2) scale_color_manual 用列表会按因子字母序错配 → 改为 dict
  3) 图10 同时 color+linetype 产生 4 条目重复图例 → 改用 linetype 分组而非 aesthetic
  4) 图8（原版）冲击簇基准日虚线缺标签 → 补"冲击簇基准日"
  5) 图10 反事实不可信说明 → 图内显眼标注 + 图说中说明
"""
import os, datetime, sys

# GBK 控制台防编码崩溃（清单 B 项）
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
import numpy as np
import pandas as pd

from plotnine import (
    ggplot, aes, geom_line, geom_vline, geom_histogram,
    labs, theme, theme_minimal, scale_color_manual, scale_linetype_manual,
    scale_x_continuous, scale_y_continuous, scale_x_date,
    element_text, element_line, element_blank,
    annotate, geom_label, geom_hline, geom_rect
)
import matplotlib
matplotlib.use("Agg")

from plot_data import prep_data, FIGROOT

OUT = os.path.join(FIGROOT, "plotnine")
os.makedirs(OUT, exist_ok=True)

# 学术色板（CSSCI 期刊常用克制色）
C_STAR = "#1f4e79"      # 深蓝
C_FORK = "#a52a2a"      # 暗红
C_SYNTH = "#7f7f7f"     # 灰
C_HIST = "#3a7d44"       # 墨绿
C_BREAK = "#c0392b"     # 警示红

# 统一主题（ggplot2 minimal + 中文友好）
thm = (
    theme_minimal(base_family="Microsoft YaHei", base_size=11)
    + theme(
        figure_size=(10, 4.6),
        plot_title=element_text(size=11.5, ha="center", weight="bold", color="#222222", margin={'t': 6, 'b': 6}),
        plot_subtitle=element_text(size=9.5, ha="center", color="#666666", margin={'b': 8}),
        axis_title=element_text(size=10, color="#333333"),
        axis_text=element_text(size=9, color="#444444"),
        axis_text_x=element_text(angle=0, hjust=0.5),
        legend_position="top",
        legend_title=element_blank(),
        legend_key=element_blank(),
        legend_background=element_blank(),
        panel_grid_minor=element_blank(),
        panel_grid_major=element_line(color="#eaeaea", size=0.5),
        panel_border=element_line(color="#cccccc", size=0.6),
        plot_margin=12,
    )
)


def _week_index(d):
    return d.strftime("%Y-%m-%d")


def fig7_star_its(d):
    """全生态每日新增 star（7日移动平均）+ 审计断点"""
    df = pd_for_dates(d["s_dates"], d["s_ma"], "star")
    b1 = datetime.date.fromisoformat("2026-02-03")
    b2 = datetime.date.fromisoformat("2026-03-24")
    ymax = max(d["s_ma"])

    p = (
        ggplot(df, aes("date", "val", group=1))
        + geom_line(color=C_STAR, size=0.9)
        + geom_vline(xintercept=[b1, b2], color=C_BREAK, linetype="dashed", alpha=0.85)
        + annotate("text", x=b1, y=ymax * 0.95, label="ClawHavoc (2026-02-03)",
                   angle=90, ha="right", va="top", size=8, color=C_BREAK)
        + annotate("text", x=b2, y=ymax * 0.95, label="Silverfort (2026-03-24)",
                   angle=90, ha="right", va="top", size=8, color=C_BREAK)
        + scale_x_date(date_labels="%Y-%m", date_breaks="2 months")
        + labs(x="日期", y="新增 star / 天（7 日移动平均）",
               title="图7　全生态每日新增 star 时序与审计冲击断点",
               subtitle="数据：203 个干净样本仓库 stargazers/history 端点回溯")
        + thm
    )
    p.save(os.path.join(OUT, "star_its.png"), dpi=200, verbose=False)


def fig8_hollowing(d):
    """star 浅层 vs fork 深层 增速脱钩"""
    dfa = pd_for_dates(d["s_dates"], d["s_ma"], "series", "star（浅层参与）")
    dfb = pd_for_dates(d["f_dates"], d["f_ma"], "series", "fork（深层贡献）")
    df = pd.concat([dfa, dfb], ignore_index=True)
    b1 = datetime.date.fromisoformat("2026-02-03")
    b2 = datetime.date.fromisoformat("2026-03-24")
    ymax = max(np.max(d["s_ma"]), np.max(d["f_ma"]))

    p = (
        ggplot(df, aes("date", "val", color="series", group="series"))
        + geom_line(size=0.9)
        + geom_vline(xintercept=[b1, b2], color="#999999", linetype="dotted", alpha=0.7)
        + annotate("text", x=b1, y=ymax * 0.95, label="ClawHavoc",
                   angle=90, ha="right", va="top", size=8, color="#666666")
        + annotate("text", x=b2, y=ymax * 0.95, label="Silverfort",
                   angle=90, ha="right", va="top", size=8, color="#666666")
        + scale_color_manual(values={
            "star（浅层参与）": C_STAR, "fork（深层贡献）": C_FORK})
        + scale_x_date(date_labels="%Y-%m", date_breaks="2 months")
        + labs(x="日期", y="日均新增（7 日移动平均）",
               title="图8　采纳空转：star（浅层）与 fork（深层）增速的脱钩",
               subtitle="全生态合计；star 二季度见顶后回落，fork 持续攀升")
        + thm
    )
    p.save(os.path.join(OUT, "hollowing.png"), dpi=200, verbose=False)


def fig9_theta_dist(d):
    """贡献门槛 θ(D) 对数分布"""
    med = float(np.median(d["tvals"]))
    arr = np.log10(np.array(d["tvals"]) + 1)
    df = pd.DataFrame({"logv": arr})
    xmed = np.log10(med + 1)

    p = (
        ggplot(df, aes("logv"))
        + geom_histogram(bins=42, fill=C_HIST, color="white", size=0.4, alpha=0.88)
        + geom_vline(xintercept=[xmed], color="#444444", linetype="dashed")
        + annotate("label", x=xmed, y=7600,
                   label=f"中位数 θ(D) = {med:,.0f}",
                   ha="left", va="top", size=8.5, color="#222222",
                   fill="#f6f6f6")
        + scale_x_continuous(breaks=np.arange(0, 6.1, 1).tolist())
        + labs(
            x="log₁₀（分叉时点累计 star + 1）",
            y="分叉事件频次",
            title="图9　贡献门槛 θ(D) 的分布（对数轴）",
            subtitle=f"78,586 个分叉事件，中位数 5,319；分布右偏，近似长尾")
        + thm
    )
    p.save(os.path.join(OUT, "theta_D_dist.png"), dpi=200, verbose=False)


def fig10_scm(d):
    """合成控制 实际 vs 反事实（含处理单元特殊性免责标注）"""
    dfa = pd_for_dates(d["scm_dates"], d["scm_actual"], "series", "实际 anthropics/skills")
    dfb = pd_for_dates(d["scm_dates"], d["scm_synth"], "series", "合成控制（反事实）")
    df = pd.concat([dfa, dfb], ignore_index=True)
    bd = datetime.date.fromisoformat("2026-03-24")
    ymax = max(max(d["scm_actual"]), max(d["scm_synth"]))

    p = (
        ggplot(df, aes("date", "val", group="series"))
        + geom_line(aes(linetype="series", color="series"), size=0.95)
        + scale_linetype_manual(values={
            "实际 anthropics/skills": "solid",
            "合成控制（反事实）": "dashed"})
        + scale_color_manual(values={
            "实际 anthropics/skills": C_STAR,
            "合成控制（反事实）": C_SYNTH})
        + geom_vline(xintercept=[bd], color="#999999", linetype="dotted")
        + annotate("text", x=bd, y=ymax * 0.92, label="2026-03-24",
                   ha="left", va="top", size=8, color="#666666")
        + annotate("label",
                   x=dfa["date"].iloc[len(dfa)//2], y=max(d["scm_actual"]) * 0.05,
                   label=f"pre RMSE = {d['pre_rmse']:,.0f}\npost RMSE = {d['post_rmse']:,.0f}\nratio = {d['ratio']:.2f}",
                   ha="center", va="bottom", size=8, fill="#f6f6f6", color="#444444")
        + scale_x_date(date_labels="%Y-%m", date_breaks="2 months")
        + labs(x="日期", y="周度新增 star",
               title="图10　合成控制：anthropics/skills 周度新增（实际 vs 反事实）",
               subtitle="处理单元为生态超级节点，pre RMSE 远大于 post，反事实不可信，仅作方法说明")
        + thm
    )
    p.save(os.path.join(OUT, "scm_gap.png"), dpi=200, verbose=False)


def pd_for_dates(dates, vals, col, name=""):
    import pandas as pd
    if name:
        return pd.DataFrame({"date": dates, "val": vals, col: name})
    return pd.DataFrame({"date": dates, "val": vals})


def main():
    d = prep_data()
    fig7_star_its(d)
    fig8_hollowing(d)
    fig9_theta_dist(d)
    fig10_scm(d)
    print("plotnine 版 4 图已输出到", OUT)


if __name__ == "__main__":
    main()