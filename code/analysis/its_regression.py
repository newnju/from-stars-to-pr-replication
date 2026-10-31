# -*- coding: utf-8 -*-
"""
中断时间序列回归（ITS）+ 事件研究图
用 statsmodels OLS 估计 2026 上半年审计冲击对 star/fork 采纳增速的 level & slope 效应
冲击断点：2026-02-03（Koi Security 首披 ClawHavoc）、2026-03-24（Silverfort 排名可操纵）
产出：回归表 + data/results/figs/*.png
"""
import json, os, datetime, statistics
import numpy as np

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

def load(name):
    return json.load(open(os.path.join(DATA, name), encoding="utf-8"))

def daily_series(hist):
    out = []
    for w in hist:
        base = datetime.datetime.fromtimestamp(w["week"], datetime.timezone.utc)
        for i, c in enumerate(w["days"]):
            out.append(((base + datetime.timedelta(days=i)).strftime("%Y-%m-%d"), c))
    out.sort()
    return out

def to_daynum(date_str, origin="2025-10-01"):
    d = datetime.date.fromisoformat(date_str)
    o = datetime.date.fromisoformat(origin)
    return (d - o).days

def build_its(daily, break1="2026-02-03", break2="2026-03-24"):
    """构造 ITS 设计矩阵：time, level1, trend1, level2, trend2"""
    rows = []
    for d, c in daily:
        t = to_daynum(d)
        lvl1 = 1 if d >= break1 else 0
        tr1 = (t - to_daynum(break1)) if d >= break1 else 0
        lvl2 = 1 if d >= break2 else 0
        tr2 = (t - to_daynum(break2)) if d >= break2 else 0
        rows.append((t, c, lvl1, tr1, lvl2, tr2))
    rows.sort(key=lambda r: r[0])
    X = np.array([[1, r[0], r[2], r[3], r[4], r[5]] for r in rows])
    y = np.array([r[1] for r in rows], dtype=float)
    return X, y, [r[0] for r in rows], [r[1] for r in rows]

def main():
    sh = load("star_history.json")
    forks = load("forks_timestamps.json")
    clean = json.load(open(os.path.join(DATA, "results", "clean_sample.json"), encoding="utf-8"))
    clean_repos = set(clean["clean_repos"])

    def agg_daily(repos):
        byday = {}
        for k in repos:
            for d, c in daily_series(sh.get(k, [])):
                byday[d] = byday.get(d, 0) + c
        return sorted(byday.items())

    def fork_daily(repos):
        byday = {}
        for k in repos:
            flist = forks.get(k)
            if not isinstance(flist, list):
                continue
            for f in flist:
                d = f.get("created_at", "")[:10]
                if d:
                    byday[d] = byday.get(d, 0) + 1
        return sorted(byday.items())

    sdaily = agg_daily(clean_repos)
    fddaily = fork_daily(clean_repos)

    # 官方仓库
    o_daily = daily_series(sh.get("anthropics/skills", []))

    try:
        import statsmodels.api as sm
    except ImportError:
        print("statsmodels 不可用")
        return

    results = {}
    for label, daily in [("star_生态", sdaily), ("fork_生态", fddaily)]:
        X, y, tdays, yvals = build_its(daily)
        model = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 7})
        results[label] = {
            "coef": {n: float(model.params[i]) for i, n in enumerate(
                ["intercept", "time", "level1", "trend1", "level2", "trend2"])},
            "se": {n: float(model.bse[i]) for i, n in enumerate(
                ["intercept", "time", "level1", "trend1", "level2", "trend2"])},
            "p": {n: float(model.pvalues[i]) for i, n in enumerate(
                ["intercept", "time", "level1", "trend1", "level2", "trend2"])},
            "r2": float(model.rsquared), "n": int(model.nobs),
        }
        print(f"\n=== ITS 回归：{label} ===")
        print(f"  n={model.nobs}  R2={model.rsquared:.3f}")
        for n in ["intercept", "time", "level1", "trend1", "level2", "trend2"]:
            c = model.params[["intercept","time","level1","trend1","level2","trend2"].index(n)]
            p = model.pvalues[["intercept","time","level1","trend1","level2","trend2"].index(n)]
            star = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
            print(f"    {n:>10}: coef={c:>12.1f}  p={p:.3e} {star}")

    # 官方仓库 ITS
    X, y, _, _ = build_its(o_daily)
    om = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 7})
    results["star_官方"] = {
        "coef": {n: float(om.params[i]) for i, n in enumerate(
            ["intercept", "time", "level1", "trend1", "level2", "trend2"])},
        "p": {n: float(om.pvalues[i]) for i, n in enumerate(
            ["intercept", "time", "level1", "trend1", "level2", "trend2"])},
        "r2": float(om.rsquared), "n": int(om.nobs),
    }
    print(f"\n=== ITS 回归：star_官方(anthropics/skills) ===")
    print(f"  n={om.nobs}  R2={om.rsquared:.3f}")
    for n in ["intercept", "time", "level1", "trend1", "level2", "trend2"]:
        c = om.params[["intercept","time","level1","trend1","level2","trend2"].index(n)]
        p = om.pvalues[["intercept","time","level1","trend1","level2","trend2"].index(n)]
        star = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
        print(f"    {n:>10}: coef={c:>12.1f}  p={p:.3e} {star}")

    os.makedirs(os.path.join(DATA, "results"), exist_ok=True)
    json.dump(results, open(os.path.join(DATA, "results", "its_regression.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    # ---------- 图：每日 star 增速 + 断点 ----------
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
    for fp in ["Microsoft YaHei", "SimHei", "Noto Sans SC", "SimSun"]:
        try:
            fm.fontManager.addfont(fp)
        except Exception:
            pass
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Noto Sans SC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    figdir = os.path.join(DATA, "results", "figs")
    os.makedirs(figdir, exist_ok=True)

    # 图1：全生态每日 star（7日移动平均）+ 断点
    plt.figure(figsize=(10, 4.5))
    dates = [datetime.date.fromisoformat(d) for d, c in sdaily]
    vals = [c for d, c in sdaily]
    # 7日移动平均
    ma = np.convolve(vals, np.ones(7)/7, mode="valid")
    ma_dates = dates[6:]
    plt.plot(ma_dates, ma, color="#1f77b4", lw=1.4, label="7日移动平均 star/天")
    for b, name in [("2026-02-03", "冲击簇(ClawHavoc)"), ("2026-03-24", "Silverfort")]:
        bd = datetime.date.fromisoformat(b)
        plt.axvline(bd, color="red", ls="--", lw=1, alpha=0.7)
        plt.text(bd, max(ma)*0.95, name, rotation=90, va="top", fontsize=8, color="red")
    plt.title("全生态每日新增 star（7日移动平均）与审计冲击断点")
    plt.xlabel("日期"); plt.ylabel("新增 star/天")
    plt.grid(alpha=0.3); plt.tight_layout()
    plt.savefig(os.path.join(figdir, "star_its.png"), dpi=150)
    plt.close()

    # 图2：star vs fork 增速对比（采纳空转）
    plt.figure(figsize=(10, 4.5))
    fdates = [datetime.date.fromisoformat(d) for d, c in fddaily]
    fvals = [c for d, c in fddaily]
    fma = np.convolve(fvals, np.ones(7)/7, mode="valid")
    fma_dates = fdates[6:]
    sma = np.convolve(vals, np.ones(7)/7, mode="valid")
    sma_dates = dates[6:]
    plt.plot(sma_dates, sma, color="#1f77b4", lw=1.4, label="star（浅层参与）")
    plt.plot(fma_dates, fma, color="#d62728", lw=1.4, label="fork（深层贡献）")
    plt.axvline(datetime.date.fromisoformat("2026-02-03"), color="gray", ls="--", lw=1, alpha=0.6)
    plt.title("采纳空转：star（浅层）与 fork（深层）增速的脱钩")
    plt.xlabel("日期"); plt.ylabel("日均新增")
    plt.legend(); plt.grid(alpha=0.3); plt.tight_layout()
    plt.savefig(os.path.join(figdir, "hollowing.png"), dpi=150)
    plt.close()

    # 图3：θ(D) 贡献门槛分布（对数）
    def theta_D_all():
        vals = []
        for k in clean_repos:
            hist = sh.get(k)
            if not hist or k not in forks:
                continue
            ds = daily_series(hist)
            cum, run = [], 0
            for d, c in ds:
                run += c; cum.append((d, run))
            def cum_at(cum, ds):
                best = None
                for d, v in cum:
                    if d <= ds: best = v
                    else: break
                return best
            for f in forks[k] if isinstance(forks[k], list) else []:
                fd = f.get("created_at", "")[:10]
                v = cum_at(cum, fd)
                if v is not None:
                    vals.append(v)
        return vals
    tvals = theta_D_all()
    plt.figure(figsize=(8, 4))
    plt.hist(np.log10(np.array(tvals)+1), bins=40, color="#2ca02c", alpha=0.8)
    plt.title("贡献门槛 θ(D) 分布（fork 时点累计 star，对数轴）")
    plt.xlabel("log10(累计 star + 1)"); plt.ylabel("fork 事件数")
    plt.grid(alpha=0.3); plt.tight_layout()
    plt.savefig(os.path.join(figdir, "theta_D_dist.png"), dpi=150)
    plt.close()

    print(f"\n  回归结果已保存 data/results/its_regression.json")
    print(f"  图已保存 data/results/figs/")
    print("=" * 70)

if __name__ == "__main__":
    main()
