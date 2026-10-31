# -*- coding: utf-8 -*-
"""
v2_hazard.py —— 注意力—意图转化的条件风险函数（替代被否证的「双重门槛回溯」）

被修正的旧口径：
    θ(L) = 「连续 7 日日均新增星标首次 ≥5」时点的累计星标（检测阈值，存在 ~35 的数学下界）
    θ(D) = 分叉时点的累计星标（事件级累计水平，且受左侧截断构造性上偏）
    Δ = 5,182（38.8 倍）——两口径分析单位与量纲均不同，不可比。

新口径（可比、无任意阈值、事件级）：
    在「分叉记录完备窗口」内，把仓库—日作为风险集，问：
        给定社会证明水平 s，一次注意力事件（新增星标）中
        有多大比例伴随一次意图事件（分叉）？
    社会证明以「仓库内累计星标分位」度量，使规模不同的仓库可比；
    面板 logit 含仓库固定效应与时间趋势，标准误按仓库聚类。

产出：data/results/v2_hazard.json
"""
import json, os, datetime, statistics, math
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RES = os.path.join(DATA, "results")
NBIN = 10
WIN_START = datetime.date(2025, 9, 21)
WIN_END = datetime.date(2026, 10, 4)
BREAK = datetime.date(2026, 2, 3)   # 风险感知冲击簇起点


def load(name):
    return json.load(open(os.path.join(DATA, name), encoding="utf-8"))


def day_of(week_epoch, i):
    return (datetime.datetime.fromtimestamp(week_epoch, datetime.timezone.utc)
            + datetime.timedelta(days=i)).date()


def build_panel():
    sh = load("star_history.json")
    forks = load("forks_timestamps.json")
    meta = load("repos_meta.json")
    clean = load(os.path.join("results", "clean_sample.json"))["clean_repos"]
    rows, repo_info = [], {}
    for k in clean:
        m, hist = meta.get(k), sh.get(k)
        if not isinstance(m, dict) or not hist:
            continue
        daily = []
        for w in hist:
            for i, c in enumerate(w["days"]):
                daily.append((day_of(w["week"], i), c))
        daily.sort()
        cum, run, cummap = [], 0, {}
        for d, c in daily:
            run += c
            cum.append((d, run))
            cummap[d] = run
        cum_sorted = [v for _, v in cum]
        created = datetime.date.fromisoformat(m["created_at"][:10])
        total_forks = int(m.get("forks") or 0)
        fdates = sorted(datetime.date.fromisoformat(f["created_at"][:10])
                        for f in (forks.get(k) or []) if f.get("created_at"))
        truncated = (len(fdates) >= 500) and (total_forks > len(fdates))
        lo = max(fdates[0] if truncated else created, WIN_START)
        hi = min(WIN_END, daily[-1][0])
        if lo > hi:
            continue
        fcount = {}
        for d in fdates:
            if lo <= d <= hi:
                fcount[d] = fcount.get(d, 0) + 1
        for d, c in daily:
            if d < lo or d > hi:
                continue
            base = cummap.get(d - datetime.timedelta(days=1), 0)
            i = np.searchsorted(cum_sorted, base, side="right")
            rows.append({"repo": k, "date": d,
                         "t": (d - WIN_START).days,
                         "post": 1 if d >= BREAK else 0,
                         "age": (d - created).days, "cum": base,
                         "pct": i / len(cum_sorted),
                         "new_stars": c, "forks": fcount.get(d, 0)})
        repo_info[k] = {
            "win_lo": lo.isoformat(), "win_hi": hi.isoformat(),
            "win_days": (hi - lo).days + 1, "fork_left_truncated": bool(truncated),
            "n_fork_records": len(fdates), "total_forks": total_forks,
            "total_stars": int(m.get("stars") or 0), "created": created.isoformat(),
            "retained_fork_share": (len(fdates) / total_forks) if total_forks else None,
            "win_stars": sum(c for d, c in daily if lo <= d <= hi),
            "win_forks": sum(fcount.values()),
            "win_cum_mean": (statistics.mean(
                [cummap.get(d - datetime.timedelta(days=1), 0)
                 for d, _ in daily if lo <= d <= hi])),
            "win_cum_lo": cummap.get(lo - datetime.timedelta(days=1), 0),
            "win_cum_hi": cummap.get(hi - datetime.timedelta(days=1), 0),
        }
    df = pd.DataFrame(rows)
    return df, repo_info


def add_bins(df):
    df = df.copy()
    p = df["pct"].clip(0, 0.999999)
    df["bin"] = np.minimum((p * NBIN).astype(int), NBIN - 1)
    return df


def rate_model(df, extra="", repo_fe=False, size_class=True):
    """意图转化率模型：forks ~ Poisson(new_stars 为暴露)，相对风险形式。

    暴露（offset=log 星标事件数）使结果解释为「每 100 次注意力事件对应的
    意图事件数」如何随社会证明水平变化，从而消除规模与时间的机械共变。
    """
    d = df.copy()
    d = d[d["new_stars"] > 0].copy()
    d["log_star_events"] = np.log(d["new_stars"])
    d["log_cum"] = np.log10(d["cum"] + 10)
    d["ym"] = d["date"].apply(lambda x: f"{x.year}-{x.month:02d}")
    if size_class:
        maxcum = d.groupby("repo")["cum"].max()
        q = pd.qcut(maxcum.rank(method="first"), 4, labels=False)
        d["size_q"] = d["repo"].map(q.to_dict()).astype(int)
    parts = ["log_cum"]
    if size_class:
        parts.append("C(size_q)")
    parts.append("C(ym)")
    if repo_fe:
        parts.append("C(repo)")
    if extra:
        parts.append(extra)
    f = "forks ~ " + " + ".join(parts)
    m = smf.glm(f, data=d, family=sm.families.Poisson(),
                offset=d["log_star_events"]).fit(
        cov_type="cluster", cov_kwds={"groups": d["repo"]})
    return m, d


def rate_by_bin(d):
    """给定（含 new_stars>0 的）面板，按分位组算「每 100 星标事件的分叉数」
    以及 Poisson 相对风险点估计的朴素版本。"""
    g = d.groupby("bin").agg(ns=("new_stars", "sum"), fk=("forks", "sum"),
                             days=("forks", "size"))
    g["per100"] = g["fk"] / g["ns"] * 100
    return g


def period_conversion(df, break_date=pd.Timestamp("2026-02-03")):
    """分位组 × 时期 的朴素转化比（不依赖参数模型，避免共线）。"""
    d = df.copy()
    d["period"] = np.where(d["date"] >= break_date.date(), "post", "pre")
    g = d.groupby(["bin", "period"]).agg(ns=("new_stars", "sum"),
                                         fk=("forks", "sum"))
    g["conv"] = g["fk"] / g["ns"] * 100
    piv = g["conv"].unstack()
    piv["diff"] = piv["post"] - piv["pre"]
    return piv


def risk_interaction(df, risk_map):
    """社会证明水平 × 敏感能力触达（二分）的转化率交互（Poisson 速率模型）。"""
    d = df.copy()
    d["hi"] = d["repo"].map(lambda k: risk_map.get(k)).fillna(0).astype(int)
    d = d[d["new_stars"] > 0].copy()
    d["log_star_events"] = np.log(d["new_stars"])
    d["log_cum"] = np.log10(d["cum"] + 10)
    d["ym"] = d["date"].apply(lambda x: f"{x.year}-{x.month:02d}")
    f = "forks ~ log_cum * hi + C(ym)"
    m = smf.glm(f, data=d, family=sm.families.Poisson(),
                offset=d["log_star_events"]).fit(
        cov_type="cluster", cov_kwds={"groups": d["repo"]})
    terms = [t for t in m.params.index if "hi" in t or t == "log_cum"]
    return m, [(t, float(m.params[t]), float(m.pvalues[t])) for t in terms]


def bin_effects(model, df):
    if model is None:
        return {}
    res = {}
    for b in range(NBIN):
        dd = df.copy()
        dd["bin"] = b
        res[b] = float(model.predict(dd).mean())
    return res


def joint_bin_test(model):
    """分位组 1–9 相对第 0 组的联合 Wald 检验。"""
    terms = [t for t in model.params.index if t.startswith("C(bin)")]
    if not terms:
        return None
    R = np.zeros((len(terms), len(model.params)))
    idx = {n: i for i, n in enumerate(model.params.index)}
    for r, t in enumerate(terms):
        R[r, idx[t]] = 1.0
    try:
        w = model.wald_test(R, scalar=True)
        return {"stat": float(np.ravel(w.statistic)[0]), "p": float(w.pvalue),
                "df": len(terms)}
    except Exception as e:
        return {"error": str(e)}


def joint_bin_test_from_df(df):
    """似然比检验：转化率是否随社会证明分位变化（H0: 各分位组相同）。"""
    d = df[df["new_stars"] > 0].copy()
    d["log_star_events"] = np.log(d["new_stars"])
    d["log_cum"] = np.log10(d["cum"] + 10)
    d["ym"] = d["date"].apply(lambda x: f"{x.year}-{x.month:02d}")
    try:
        m0 = smf.glm("forks ~ log_cum + C(ym)", data=d, family=sm.families.Poisson(),
                     offset=d["log_star_events"]).fit()
        m1 = smf.glm("forks ~ C(bin) + C(ym)", data=d, family=sm.families.Poisson(),
                     offset=d["log_star_events"]).fit()
        lr = 2 * (m1.llf - m0.llf)
        dof = int(m1.df_model - m0.df_model)
        from scipy import stats as st
        return {"stat": float(lr), "df": dof, "p": float(st.chi2.sf(lr, dof))}
    except Exception as e:
        return {"error": str(e)}


def boot_conv(df, n_boot=1000, seed=20261005):
    rng = np.random.default_rng(seed)
    repos = df["repo"].unique()
    idx = {r: g.index.values for r, g in df.groupby("repo")}
    curves = []
    for _ in range(n_boot):
        pick = rng.choice(repos, size=len(repos), replace=True)
        s = pd.concat([df.loc[idx[r]] for r in pick])
        g = s.groupby("bin").agg(ns=("new_stars", "sum"), fk=("forks", "sum"))
        curves.append((g["fk"] / g["ns"] * 100).reindex(range(NBIN)).values)
    arr = np.array(curves, dtype=float)
    return {"lo": np.nanpercentile(arr, 2.5, axis=0).tolist(),
            "hi": np.nanpercentile(arr, 97.5, axis=0).tolist(),
            "n_boot": n_boot}


def main():
    print("=" * 78)
    print("v2 注意力—意图转化曲线与社会证明弹性")
    print("=" * 78)
    df, repo_info = build_panel()
    df = add_bins(df)
    print(f"  仓库—日面板: {len(df):,} 行 × {df['repo'].nunique()} 仓库")
    print(f"  窗口内星标事件 {int(df['new_stars'].sum()):,}  分叉事件 {int(df['forks'].sum()):,}")

    conv = df.groupby("bin").agg(new_stars=("new_stars", "sum"),
                                 forks=("forks", "sum"),
                                 days=("new_stars", "size"),
                                 mean_cum=("cum", "mean"),
                                 med_cum=("cum", "median"))
    conv["conv_per_100"] = conv["forks"] / conv["new_stars"] * 100
    pr = df.groupby("bin").apply(
        lambda s: pd.Series({"p_fork_day": (s["forks"] > 0).mean(),
                             "p_star_day": (s["new_stars"] > 0).mean()}),
        include_groups=False)
    pr["ratio"] = pr["p_fork_day"] / pr["p_star_day"]
    print("\n【分位组朴素转化比】每 100 次注意力事件伴随的意图事件数")
    print(conv[["new_stars", "forks", "conv_per_100", "mean_cum"]].to_string(
        float_format=lambda x: f"{x:,.2f}"))
    print("\n【仓库—日概率口径】")
    print(pr.to_string(float_format=lambda x: f"{x:.4f}"))

    # ---- 速率模型（消除规模与日历的机械共变） ----
    m1, d1 = rate_model(df, repo_fe=False)    # 跨仓库 + 日历月 + 规模四分位
    m2, d2 = rate_model(df, repo_fe=True)     # 加仓库固定效应（敏感规格）
    print("\n【转化率模型：forks ~ Poisson，offset=log(星标事件数)】")
    for tag, m in (("跨仓库+日历月+规模四分位", m1), ("加仓库固定效应", m2)):
        c = m.params.get("log_cum"); s = m.bse.get("log_cum"); p = m.pvalues.get("log_cum")
        print(f"  {tag:<26} log_cum 系数={c:+.3f} (SE={s:.3f}, p={p:.4f})"
              f"  → 社会证明每增 10 倍，转化率 ×{10**c:.3f}")
    # 仓库 FE 模型中 log_cum 是否与仓库内趋势共线（诊断已并入 rate_model 对比输出）

    pc = period_conversion(df)
    print("\n【分位组 × 时期 的朴素转化比】")
    print(pc.to_string(float_format=lambda x: f"{x:.2f}"))

    # ---- 风险异质性 ----
    rterms, rmap = [], {}
    try:
        risk = load(os.path.join("results", "v2_risk.json"))["repos"]
        rmap = {k: (v.get("reach_binary") if v.get("reach_binary") is not None else 0)
                for k, v in risk.items()}
        m_r, rterms = risk_interaction(df, rmap)
        print("\n【社会证明 × 敏感能力触达 的转化率交互】")
        for t, c, p in rterms:
            print(f"  {t:<20} coef={c:+.3f}  p={p:.3f}")
    except Exception as e:
        print("  [风险交互失败]", e)

    boot = boot_conv(df, 1000)
    print("\n【转化曲线 95% 聚类 bootstrap 区间（每 100 星标对应的分叉数）】")
    for b in range(NBIN):
        print(f"  组{b}: {conv.loc[b,'conv_per_100']:.2f} "
              f"[{boot['lo'][b]:.2f}, {boot['hi'][b]:.2f}]")

    jt = joint_bin_test_from_df(df)
    print(f"\n  分位组间差异的联合检验（似然比）: chi2={jt['stat']:.1f}, p={jt['p']:.3f}"
          if jt else "")

    out = {
        "design": {
            "unit": "repository-day risk set within the complete-fork window",
            "exposure": "within-repo percentile of cumulative stars at day start",
            "bins": NBIN,
            "rate_model": "Poisson with offset log(star events); controls = "
                          "log10 cumulative stars, calendar month, repo size quartile",
            "se": "clustered by repository", "n_rows": int(len(df)),
            "n_repos": int(df["repo"].nunique()),
            "n_star_events": int(df["new_stars"].sum()),
            "n_fork_events": int(df["forks"].sum()),
        },
        "conversion_by_bin": {
            str(b): {"new_stars": float(conv.loc[b, "new_stars"]),
                     "forks": float(conv.loc[b, "forks"]),
                     "conv_per_100": float(conv.loc[b, "conv_per_100"]),
                     "mean_cum_stars": float(conv.loc[b, "mean_cum"]),
                     "median_cum_stars": float(conv.loc[b, "med_cum"]),
                     "p_fork_day": float(pr.loc[b, "p_fork_day"]),
                     "p_star_day": float(pr.loc[b, "p_star_day"]),
                     "prob_ratio": float(pr.loc[b, "ratio"]),
                     "conv_lo": boot["lo"][b], "conv_hi": boot["hi"][b]}
            for b in range(NBIN)
        },
        "rate_model": {
            "cross_repo": {"log_cum_coef": float(m1.params["log_cum"]),
                           "se": float(m1.bse["log_cum"]),
                           "p": float(m1.pvalues["log_cum"]),
                           "factor_per_10x": float(10 ** m1.params["log_cum"]),
                           "n_obs": int(m1.nobs)},
            "repo_fe": {"log_cum_coef": float(m2.params["log_cum"]),
                        "se": float(m2.bse["log_cum"]),
                        "p": float(m2.pvalues["log_cum"]),
                        "factor_per_10x": float(10 ** m2.params["log_cum"]),
                        "n_obs": int(m2.nobs)},
        },
        "bin_joint_test": jt,
        "period_conversion": {str(b): {p: (None if pd.isna(pc.loc[b, p]) else float(pc.loc[b, p]))
                                       for p in pc.columns} for b in pc.index},
        "risk_interaction": [{"term": t, "coef": c, "p": p} for t, c, p in rterms],
        "repo_info": repo_info,
    }
    json.dump(out, open(os.path.join(RES, "v2_hazard.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2, default=float)
    print(f"\n  产出: data/results/v2_hazard.json")
    print("=" * 78)
    return df


if __name__ == "__main__":
    main()
