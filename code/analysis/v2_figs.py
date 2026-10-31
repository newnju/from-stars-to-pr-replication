# -*- coding: utf-8 -*-
"""
v2_figs.py —— 修正版统计图（替换旧图 7–10）

产出（data/results/figs/）：
  fig_conversion_ladder.png  注意力—意图转化率随社会证明水平的变化（含聚类 bootstrap 带）
  fig_vis_quartile.png       可见性四分位 × 年龄分层的转化率
  fig_first_fork.png         首次分叉门槛分布（分叉记录完整仓库）与旧口径对照
  fig_flow_stock.png         星标流与分叉流的分月轨迹（无截断子样本 vs 全样本）
  fig_legacy_vs_v2.png       旧口径 38.8 倍与修正口径的对照
"""
import json, os, math, datetime
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

# GBK 控制台防编码崩溃（清单 B 项）
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RES = os.path.join(DATA, "results")
FIGS = os.path.join(RES, "figs")
os.makedirs(FIGS, exist_ok=True)

# 中文字体（Windows 自带）
for f in ("Microsoft YaHei", "SimHei", "DengXian"):
    try:
        font_manager.findfont(f, fallback_to_default=False)
        plt.rcParams["font.sans-serif"] = [f]
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 160
plt.rcParams["savefig.bbox"] = "tight"


def load(n):
    return json.load(open(os.path.join(DATA, n), encoding="utf-8"))


def load_res(n):
    return json.load(open(os.path.join(RES, n), encoding="utf-8"))


def day_of(week_epoch, i):
    return (datetime.datetime.fromtimestamp(week_epoch, datetime.timezone.utc)
            + datetime.timedelta(days=i)).date()


# ---------- 图 1：转化率阶梯 ----------
def fig_conversion_ladder():
    h = load_res("v2_hazard.json")
    c = h["conversion_by_bin"]
    bins = list(range(10))
    y = [c[str(b)]["conv_per_100"] for b in bins]
    lo = [c[str(b)]["conv_lo"] for b in bins]
    hi = [c[str(b)]["conv_hi"] for b in bins]
    x = [c[str(b)]["mean_cum_stars"] for b in bins]
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    ax.fill_between(range(10), lo, hi, color="#9dc3e6", alpha=.45,
                    label="95% 仓库聚类 bootstrap 区间")
    ax.plot(range(10), y, "o-", color="#1f4e79", lw=1.8, ms=5,
            label="每 100 次注意力事件的意图事件数")
    ax.axhline(np.mean(y), ls="--", color="#c00000", lw=1.2,
               label=f"全区间均值 {np.mean(y):.2f}")
    ax.set_xticks(range(10))
    ax.set_xticklabels([f"第{i+1}组\n{x[i]:,.0f}星" for i in range(10)], fontsize=7)
    ax.set_xlabel("社会证明水平（仓库内累计星标十分位；下方为组内平均累计星标）",
                  fontsize=8.5)
    ax.set_ylabel("每 100 次星标事件的\n分叉事件数", fontsize=8.5)
    ax.set_title("图A　注意力—意图转化率在社会证明阶梯上基本持平", fontsize=10)
    ax.tick_params(labelsize=8)
    ax.legend(fontsize=7.5, frameon=False)
    ax.grid(alpha=.25, ls=":")
    fig.savefig(os.path.join(FIGS, "fig_conversion_ladder.png"))
    plt.close(fig)


# ---------- 图 2：可见性四分位 × 年龄分层 ----------
def fig_vis_quartile():
    s = load_res("v2_signal.json")
    cells = s["age_vis_cells"]
    ages = ["≤120日", "121–210日", "211–300日", ">300日"]
    vis = ["V1最低", "V2", "V3", "V4最高"]
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    width = 0.2
    xs = np.arange(len(vis))
    for i, a in enumerate(ages):
        vals = []
        for v in vis:
            k = f"('{a}', '{v}')"
            vals.append(cells.get(k, {}).get("per100", np.nan))
        ax.bar(xs + (i - 1.5) * width, vals, width, label=a)
    ax.set_xticks(xs)
    ax.set_xticklabels(["可见性最低\n(V1)", "V2", "V3", "可见性最高\n(V4)"], fontsize=8.5)
    ax.set_ylabel("每 100 次星标事件的\n分叉事件数", fontsize=8.5)
    ax.set_title("图B　按仓库年龄分层后，可见性越高转化率反而越低", fontsize=10)
    ax.tick_params(labelsize=8)
    ax.legend(fontsize=7.5, frameon=False, ncol=4, title="仓库年龄", title_fontsize=7.5)
    ax.grid(alpha=.25, ls=":", axis="y")
    fig.savefig(os.path.join(FIGS, "fig_vis_quartile.png"))
    plt.close(fig)


# ---------- 图 3：首次分叉门槛 ----------
def fig_first_fork():
    panel = load_res("v2_panel.json")["repos"]
    pts = [r["theta_first_fork_point"] for r in panel.values()
           if r.get("theta_first_fork_point") is not None]
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 3.2))
    ax = axes[0]
    ax.hist(pts, bins=np.arange(0, 260, 10), color="#4472c4", edgecolor="white")
    ax.axvline(np.median(pts), color="#c00000", ls="--", lw=1.4,
               label=f"中位数 {np.median(pts):.0f} 星")
    ax.set_xlabel("首次分叉时的累计星标数", fontsize=8.5)
    ax.set_ylabel("仓库数", fontsize=8.5)
    ax.set_title(f"分叉记录完整仓库（n={len(pts)}）", fontsize=9.5)
    ax.legend(fontsize=7.5, frameon=False)
    ax.tick_params(labelsize=8)

    ax = axes[1]
    names = ["旧口径\nθ(D)\n（分叉时点\n累计星标）", "旧口径\nθ(L)\n（增速\n检测点）",
             "修正口径\n首次分叉\n门槛（中位）"]
    vals = [5319, 137, float(np.median(pts))]
    bars = ax.bar(names, vals, color=["#a6a6a6", "#a6a6a6", "#2e75b6"])
    ax.set_yscale("log")
    ax.set_ylabel("累计星标数（对数轴）", fontsize=8.5)
    ax.set_title("旧口径 vs 修正口径", fontsize=9.5)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v * 1.25, f"{v:,.0f}",
                ha="center", fontsize=8)
    ax.tick_params(labelsize=7.5)
    fig.suptitle("图C　意图层门槛的修正估计：首次分叉发生在极低社会证明水平上",
                 fontsize=10, y=1.04)
    fig.savefig(os.path.join(FIGS, "fig_first_fork.png"))
    plt.close(fig)


# ---------- 图 4：流与存量（截断诊断） ----------
def fig_flow_stock():
    d = load_res("v2_dynamics.json")
    allm = {r["ym"]: r for r in d["monthly_ecology_all"]}
    comp = {r["ym"]: r for r in d["monthly_ecology_complete_only"]}
    yms = sorted(set(allm) | set(comp))
    yms = [y for y in yms if y >= "2025-10"]
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.4), sharex=False)
    for ax, src, title in ((axes[0], allm, "全样本（203，含左侧截断）"),
                           (axes[1], comp, "分叉记录完整子样本（95）")):
        yy = [src.get(y, {}).get("fork_per_100_stars", np.nan) for y in yms]
        ax.plot(range(len(yms)), yy, "o-", color="#c00000", lw=1.6, ms=4,
                label="每 100 星标事件的分叉数")
        ax2 = ax.twinx()
        ax2.plot(range(len(yms)),
                 [src.get(y, {}).get("stars_per_day", np.nan) for y in yms],
                 "s--", color="#1f4e79", lw=1.3, ms=3.5, label="星标/日")
        ax2.set_ylabel("星标/日", fontsize=8, color="#1f4e79")
        ax2.tick_params(labelsize=7.5, colors="#1f4e79")
        ax.set_title(title, fontsize=9)
        ax.set_ylabel("每 100 星标事件的分叉数", fontsize=8, color="#c00000")
        ax.tick_params(labelsize=7.5, colors="#c00000")
        ax.set_xticks(range(len(yms)))
        ax.set_xticklabels([y[2:] for y in yms], rotation=60, fontsize=6.5)
        ax.grid(alpha=.2, ls=":")
    fig.suptitle("图D　左：全样本合计的分叉—星标比（受截断抬高）；"
                 "右：无截断子样本呈温和上升后走平", fontsize=9, y=1.06)
    fig.tight_layout(w_pad=2.4)
    fig.savefig(os.path.join(FIGS, "fig_flow_stock.png"))
    plt.close(fig)


# ---------- 图 5：旧口径与修正口径对照 ----------
def fig_legacy_vs_v2():
    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    labels = ["旧：θ(D)−θ(L)\n（跨口径比值）", "旧：同口径仓库级中位",
              "修正：转化率随社会证明的\n变化幅度（似然比检验）"]
    note = ["38.8 倍", "24.3 倍", "p=%.3g"]
    h = load_res("v2_hazard.json")
    p = h.get("bin_joint_test", {}).get("p", np.nan)
    vals = [38.8, 24.25, 1.0]
    colors = ["#a6a6a6", "#a6a6a6", "#2e75b6"]
    bars = ax.barh(labels, vals, color=colors)
    ax.set_xscale("log")
    ax.set_xlabel("效应量（对数轴；第三项为相对基准 1.0 的图示占位）", fontsize=8.5)
    ax.set_title("图E　旧「门槛分离度」与修正口径的性质差异", fontsize=10)
    for b, v, n in zip(bars, vals, note):
        ax.text(v * 1.15, b.get_y() + b.get_height() / 2,
                (f"{v:.1f} 倍" if v > 2 else n % p), va="center", fontsize=8)
    ax.tick_params(labelsize=8)
    ax.grid(alpha=.2, ls=":", axis="x")
    fig.savefig(os.path.join(FIGS, "fig_legacy_vs_v2.png"))
    plt.close(fig)


# ---------- 图 6：合成控制（从权威结果复算，保证图文数值一致） ----------
def fig_scm():
    """用与 did_final.py 相同的设定重算合成控制，使图注数值与正文一致。

    处理单元 anthropics/skills，捐赠池为其余干净样本仓库，
    以冲击前（2025-10-01 至 2026-03-23）周度新增星标的拟合误差最小化
    求解非负权重；断点 2026-03-24。
    """
    from scipy.optimize import nnls
    sh = load("star_history.json")
    clean = load(os.path.join("results", "clean_sample.json"))["clean_repos"]
    treated = "anthropics/skills"
    start = datetime.date(2025, 10, 1)
    end = datetime.date(2026, 10, 4)
    brk = datetime.date(2026, 3, 24)

    def weekly(repo):
        wk = {}
        for w in sh.get(repo, []):
            for i, c in enumerate(w["days"]):
                d = day_of(w["week"], i)
                if start <= d <= end:
                    wi = (d - start).days // 7
                    wk[wi] = wk.get(wi, 0) + c
        return wk

    tw = weekly(treated)
    weeks = sorted(tw)
    don = [k for k in clean if k != treated and sh.get(k)]
    D, y = [], []
    for wi in weeks:
        D.append([weekly(k).get(wi, 0) for k in don])
        y.append(tw.get(wi, 0))
    from scipy.optimize import minimize
    D = np.array(D, float).T
    y = np.array(y, float)
    pre_idx = [i for i, wi in enumerate(weeks)
               if start + datetime.timedelta(weeks=wi) < brk]
    post_idx = [i for i, wi in enumerate(weeks)
                if start + datetime.timedelta(weeks=wi) >= brk]
    # 捐赠池筛选与权重约束与 did_synthetic.py 一致：冲击前覆盖过半、sum(w)=1、w>=0
    keep = []
    for j in range(D.shape[0]):
        pre = D[j, pre_idx]
        if len(pre) and (pre == 0).mean() < 0.5:
            keep.append(j)
    D = D[keep]
    T0 = len(pre_idx)
    Ypre = y[pre_idx]
    Dpre = D[:, pre_idx]
    J = D.shape[0]

    def obj(w):
        return float(np.sum((Ypre - Dpre.T @ w) ** 2))

    res = minimize(obj, np.full(J, 1.0 / J), method="SLSQP",
                   bounds=[(0, 1)] * J,
                   constraints=[{"type": "eq", "fun": lambda w: np.sum(w) - 1}])
    w = np.where(res.x < 1e-4, 0, res.x)
    w = w / w.sum() if w.sum() > 0 else res.x
    fit = D.T @ w
    pre_rmse = float(np.sqrt(np.mean((y[pre_idx] - fit[pre_idx]) ** 2)))
    post_rmse = float(np.sqrt(np.mean((y[post_idx] - fit[post_idx]) ** 2)))

    dates = [start + datetime.timedelta(weeks=wi) for wi in weeks]
    fig, axes = plt.subplots(2, 1, figsize=(6.6, 4.4), sharex=True,
                             gridspec_kw={"height_ratios": [2.1, 1]})
    ax = axes[0]
    ax.plot(dates, y, color="#1f4e79", lw=1.7, label="实际 anthropics/skills")
    ax.plot(dates, fit, color="#c00000", lw=1.5, ls="--", label="合成控制（反事实）")
    ax.axvline(brk, color="#7f7f7f", ls=":", lw=1.1)
    ax.annotate("Silverfort\n2026-03-24", xy=(brk, max(y) * .95), fontsize=7.5,
                color="#595959", ha="left", va="top")
    ax.set_ylabel("周度新增星标", fontsize=8.5)
    ax.set_title("图F　合成控制：处理单元为超级节点，冲击前拟合失败", fontsize=10)
    ax.legend(fontsize=8, frameon=False)
    ax.tick_params(labelsize=8)
    ax.grid(alpha=.25, ls=":")
    ax.text(0.98, 0.05,
            f"冲击前 RMSE={pre_rmse:,.0f}　冲击后 RMSE={post_rmse:,.0f}"
            f"　比值={post_rmse/pre_rmse:.2f}",
            transform=ax.transAxes, fontsize=8, color="#404040",
            ha="right", va="bottom",
            bbox=dict(fc="white", ec="none", alpha=.85, pad=2))
    ax2 = axes[1]
    ax2.axhline(0, color="#7f7f7f", lw=.8)
    ax2.fill_between(dates, 0, y - fit, color="#9dc3e6", alpha=.6)
    ax2.axvline(brk, color="#7f7f7f", ls=":", lw=1.1)
    ax2.set_ylabel("实际−合成", fontsize=8.5)
    ax2.set_xlabel("日期", fontsize=8.5)
    ax2.tick_params(labelsize=8)
    ax2.grid(alpha=.25, ls=":")
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "fig_scm.png"))
    plt.close(fig)
    return {"pre_rmse": pre_rmse, "post_rmse": post_rmse,
            "n_donors": int((w > 1e-4).sum()), "n_donors_pool": len(don)}


# ---------- 图 7：交错DID与合成控制的识别边界 ----------
def fig_did_scm():
    """DID：按风险分组的周度星标轨迹；SCM：实际vs反事实轨迹与缺口。"""
    sh = load("star_history.json")
    risk = load_res("v2_risk.json")["repos"]
    clean = load(os.path.join("results", "clean_sample.json"))["clean_repos"]
    start = datetime.date(2025, 9, 28)
    end = datetime.date(2026, 10, 4)
    brk = datetime.date(2026, 2, 3)

    def weekly(repo):
        wk = {}
        for w in sh.get(repo, []):
            for i, c in enumerate(w["days"]):
                d = day_of(w["week"], i)
                if start <= d <= end:
                    wi = (d - start).days // 7
                    wk[wi] = wk.get(wi, 0) + c
        return wk

    weeks = sorted({wi for k in clean for wi in weekly(k)})
    wdates = [start + datetime.timedelta(weeks=wi) for wi in weeks]
    hi, lo = [], []
    for k in clean:
        wk = weekly(k)
        v = [wk.get(wi, 0) for wi in weeks]
        (hi if (risk.get(k) or {}).get("reach_binary") else lo).append(v)
    mhi = np.mean(np.array(hi, float), axis=0)
    mlo = np.mean(np.array(lo, float), axis=0)

    # SCM（与 did_synthetic.py 相同设定）
    treated = "anthropics/skills"
    tw = weekly(treated)
    don = [k for k in clean if k != treated and sh.get(k)]
    Dm = np.array([[weekly(k).get(wi, 0) for wi in weeks] for k in don], float)
    yv = np.array([tw.get(wi, 0) for wi in weeks], float)
    pre = [i for i, d in enumerate(wdates) if d < brk]
    keep = [j for j in range(Dm.shape[0]) if (Dm[j, pre] == 0).mean() < 0.5]
    Dm = Dm[keep]
    J = Dm.shape[0]
    from scipy.optimize import minimize
    res = minimize(lambda w: float(np.sum((yv[pre] - Dm[:, pre].T @ w) ** 2)),
                   np.full(J, 1.0 / J), method="SLSQP", bounds=[(0, 1)] * J,
                   constraints=[{"type": "eq", "fun": lambda w: np.sum(w) - 1}])
    w = np.where(res.x < 1e-4, 0, res.x)
    w = w / w.sum() if w.sum() > 0 else res.x
    fit = Dm.T @ w
    post = [i for i, d in enumerate(wdates) if d >= brk]
    pre_rmse = float(np.sqrt(np.mean((yv[pre] - fit[pre]) ** 2)))
    post_rmse = float(np.sqrt(np.mean((yv[post] - fit[post]) ** 2)))

    fig, axes = plt.subplots(1, 2, figsize=(7.6, 3.4),
                             gridspec_kw={"width_ratios": [1, 1]})
    ax = axes[0]
    ax.plot(wdates, mhi, color="#c00000", lw=1.7, label="处理组：敏感能力触达≥2族")
    ax.plot(wdates, mlo, color="#1f4e79", lw=1.7, ls="--", label="对照组：其余仓库")
    ax.axvline(brk, color="#7f7f7f", ls=":", lw=1.1)
    ax.annotate("2026-02-03", xy=(brk, max(mhi) * .98), fontsize=7.5,
                color="#595959", ha="left", va="top")
    ax.set_ylabel("周度新增星标（组均值）", fontsize=8.5)
    ax.set_title("左：交错双重差分（交互项+0.531，p=0.295）", fontsize=9)
    ax.legend(fontsize=7.5, frameon=False, loc="upper right")
    ax.tick_params(labelsize=7.5)
    ax.grid(alpha=.25, ls=":")
    ax.text(0.02, 0.05,
            "注：冲击前两组已存在水平差距，\n平行趋势假定本身不成立",
            transform=ax.transAxes, fontsize=7.5, color="#404040",
            ha="left", va="bottom",
            bbox=dict(fc="white", ec="none", alpha=.85, pad=2))

    ax2 = axes[1]
    ax2.plot(wdates, yv, color="#1f4e79", lw=1.7, label="实际 anthropics/skills")
    ax2.plot(wdates, fit, color="#c00000", lw=1.5, ls="--", label="合成控制（反事实）")
    ax2.axvline(brk, color="#7f7f7f", ls=":", lw=1.1)
    ax2.set_ylabel("周度新增星标", fontsize=8.5)
    ax2.set_title("右：合成控制（冲击前拟合失败）", fontsize=9)
    ax2.legend(fontsize=7.5, frameon=False, loc="upper right")
    ax2.tick_params(labelsize=7.5)
    ax2.grid(alpha=.25, ls=":")
    ax2.text(0.98, 0.05,
             f"冲击前 RMSE={pre_rmse:,.0f}\n冲击后 RMSE={post_rmse:,.0f}",
             transform=ax2.transAxes, fontsize=7.5, color="#404040",
             ha="right", va="bottom",
             bbox=dict(fc="white", ec="none", alpha=.85, pad=2))
    fig.suptitle("图H　两项差分识别检验均未支持因果解读", fontsize=10, y=1.05)
    fig.tight_layout(w_pad=2.0)
    fig.savefig(os.path.join(FIGS, "fig_did_scm.png"))
    plt.close(fig)
    return {"did_hi_mean": float(np.mean(mhi)), "did_lo_mean": float(np.mean(mlo)),
            "pre_rmse": pre_rmse, "post_rmse": post_rmse, "n_donors": int((w > 1e-4).sum())}


if __name__ == "__main__":
    fig_conversion_ladder()
    fig_vis_quartile()
    fig_first_fork()
    fig_flow_stock()
    fig_legacy_vs_v2()
    scm = fig_scm()
    did = fig_did_scm()
    legacy = load_res("v2_threshold.json")["legacy_reproduction"]
    print("图已生成：")
    for f in sorted(os.listdir(FIGS)):
        if f.startswith("fig_"):
            print("  ", f, os.path.getsize(os.path.join(FIGS, f)), "bytes")
    print("旧口径同口径重算比值:", round(legacy["like_for_like_ratio"], 2))
    print("SCM（复算）:", {k: (round(v, 1) if isinstance(v, float) else v)
                          for k, v in scm.items()})
    print("DID/SCM（复算）:", {k: (round(v, 1) if isinstance(v, float) else v)
                              for k, v in did.items()})
    json.dump({"scm": scm, "did_scm": did},
              open(os.path.join(RES, "v2_scm_refit.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
