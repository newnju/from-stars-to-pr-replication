# -*- coding: utf-8 -*-
"""
v2_robustness.py —— 应对第二轮评审的补充稳健性证据

回应四项质疑：
  R1（等价性）「零梯度」是否只是功效不足？ —— TOST 等价检验 + 最小可检测效应（MDE）
  R2（超级节点）可见性负相关是否由 anthropics/skills 等超级节点驱动？
      —— 剔除官方仓库与星标前 1% 后重估
  R3（风险口径）三套口径究竟差在哪？ —— 指定主口径 + 2×2 混淆矩阵
  R4（窗口代表性）完备窗口起点中位 2026-07，是否具生态代表性？
      —— 窗口起点与仓库规模、年龄、时期的关系

产出：data/results/v2_robustness.json
"""
import json, os, math, datetime, statistics
import numpy as np
import pandas as pd
from scipy import stats as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RES = os.path.join(DATA, "results")

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from v2_hazard import build_panel, add_bins, rate_model  # 复用面板构造


def load(n):
    return json.load(open(os.path.join(DATA, n), encoding="utf-8"))


# ----------------------------------------------------------------------
# R1: 等价检验与功效分析
# ----------------------------------------------------------------------
def equivalence():
    df, _ = build_panel()
    df = add_bins(df)
    m2, _ = rate_model(df, repo_fe=True)     # 主规格：仓库固定效应
    m1, _ = rate_model(df, repo_fe=False)    # 对照：跨仓库

    res = {}
    for tag, m in (("repo_fe", m2), ("cross_repo", m1)):
        b = float(m.params["log_cum"])
        se = float(m.bse["log_cum"])
        # TOST：单侧检验，H1: β < δ
        margins = {"1.25x/decade": math.log10(1.25),
                   "1.5x/decade": math.log10(1.5),
                   "2.0x/decade": math.log10(2.0),
                   "3.0x/decade": math.log10(3.0)}
        tost = {}
        for name, d in margins.items():
            z = (d - b) / se
            tost[name] = {
                "delta_log10": d,
                "z": z,
                "p_upper": float(st.norm.sf(z)),
            }
        # 单侧 95% 上界
        ub = b + 1.645 * se
        # MDE（80% 功效、单侧 5%）：≈2.49×SE
        mde = 2.49 * se
        res[tag] = {
            "beta": b, "se": se, "p": float(m.pvalues["log_cum"]),
            "factor_per_10x": 10 ** b,
            "ci95_upper_one_sided": ub,
            "ci95_upper_factor": 10 ** ub,
            "ci95_lower_factor": 10 ** (b - 1.96 * se),
            "mde_80power_factor": 10 ** mde,
            "tost": tost,
        }
        print(f"  [{tag}] β={b:+.3f} (SE={se:.3f})  每10倍×{10**b:.2f}")
        print(f"    单侧95%上界: ×{10**ub:.2f}/10倍  MDE(80%功效): ×{10**mde:.2f}/10倍")
        for name in margins:
            mark = "  → 等价" if tost[name]["p_upper"] < .05 else ""
            print(f"    TOST[{name:<13}] p={tost[name]['p_upper']:.4f}{mark}")

    # 朴素曲线的 max/min 比（无模型假设，聚类 bootstrap）
    conv = df.groupby("bin").agg(ns=("new_stars", "sum"), fk=("forks", "sum"))
    conv["c"] = conv["fk"] / conv["ns"] * 100
    rng = np.random.default_rng(20261005)
    repos = df["repo"].unique()
    idx = {r: g.index.values for r, g in df.groupby("repo")}
    ratios = []
    for _ in range(2000):
        pick = rng.choice(repos, size=len(repos), replace=True)
        s = pd.concat([df.loc[idx[r]] for r in pick])
        g = s.groupby("bin").agg(ns=("new_stars", "sum"), fk=("forks", "sum"))
        c = (g["fk"] / g["ns"] * 100)
        ratios.append(c.max() / c.min())
    obs = conv["c"].max() / conv["c"].min()
    lo, hi = np.nanpercentile(ratios, 2.5), np.nanpercentile(ratios, 97.5)
    res["naive_curve"] = {
        "max_min_ratio": float(obs), "max_min_ratio_ci": [float(lo), float(hi)],
        "min_bin_per100": float(conv["c"].min()), "max_bin_per100": float(conv["c"].max())}
    print(f"  朴素曲线 max/min = {obs:.3f}  [bootstrap 95% CI: {lo:.3f}, {hi:.3f}]")
    return res


# ----------------------------------------------------------------------
# R2: 超级节点剔除
# ----------------------------------------------------------------------
def supernode():
    import statsmodels.formula.api as smf
    import statsmodels.api as sm

    panel = load(os.path.join("results", "v2_panel.json"))["repos"]
    risk = load(os.path.join("results", "v2_risk.json"))["repos"]
    meta = load("repos_meta.json")

    CUT = datetime.date(2026, 1, 1)
    base = {}
    for k, r in meta.items():
        if datetime.date.fromisoformat(r["created_at"][:10]) < CUT:
            base[k] = int(r.get("stars") or 0)
    bench = statistics.median(base.values())

    rows = []
    for k, r in panel.items():
        rr = risk.get(k, {})
        if not r["win_stars"]:
            continue
        rows.append({
            "repo": k, "forks": r["win_forks"], "stars_ev": r["win_stars"],
            "vis_resid": math.log10(int(r["total_stars"]) + 10) - math.log10(bench + 10),
            "total_stars": int(r["total_stars"]),
            "age": (datetime.date(2026, 10, 4) -
                    datetime.date.fromisoformat(r["created"])).days,
            "win_days": r["win_days"],
            "text_len": math.log10((rr.get("text_len") or 0) + 10),
        })
    d = pd.DataFrame(rows)
    d["log_age"] = np.log10(d["age"] + 10)
    d["stars_per_day"] = d["stars_ev"] / d["win_days"]

    def vis_model(dat):
        dat = dat.copy()
        dat["stars_per_day"] = dat["stars_ev"] / dat["win_days"]
        m = smf.glm("forks ~ vis_resid + log_age + text_len", data=dat,
                    family=sm.families.Poisson(),
                    offset=np.log(dat["stars_per_day"])).fit(cov_type="HC1")
        return (float(m.params["vis_resid"]), float(m.bse["vis_resid"]),
                float(m.pvalues["vis_resid"]), int(m.nobs))

    b, se, p, n = vis_model(d)
    print(f"  全样本 (n={n}):        vis_resid β={b:+.3f} (SE={se:.3f}, p={p:.4f})")
    out = {"full": {"beta": b, "se": se, "p": p, "n": n}}

    d1 = d[d["repo"] != "anthropics/skills"].copy()
    b1, se1, p1, n1 = vis_model(d1)
    out["excl_official"] = {"beta": b1, "se": se1, "p": p1, "n": n1}
    print(f"  剔除官方仓库 (n={n1}):  vis_resid β={b1:+.3f} (SE={se1:.3f}, p={p1:.4f})")

    cutoff = float(d["total_stars"].quantile(0.99))
    top1 = d[d["total_stars"] >= cutoff]["repo"].tolist()
    d2 = d[d["total_stars"] < cutoff].copy()
    b2, se2, p2, n2 = vis_model(d2)
    out["excl_top1pct"] = {
        "beta": b2, "se": se2, "p": p2, "n": n2,
        "removed": top1, "cutoff": cutoff}
    print(f"  剔除前1% (n={n2}):    vis_resid β={b2:+.3f} (SE={se2:.3f}, p={p2:.4f})"
          f"  [移除: {', '.join(top1)}]")

    d3 = d[(d["repo"] != "anthropics/skills") &
           (d["total_stars"] < cutoff)].copy()
    b3, se3, p3, n3 = vis_model(d3)
    out["excl_both"] = {"beta": b3, "se": se3, "p": p3, "n": n3}
    print(f"  双剔除 (n={n3}):      vis_resid β={b3:+.3f} (SE={se3:.3f}, p={p3:.4f})")

    tot_forks, tot_stars = d["forks"].sum(), d["stars_ev"].sum()
    out["node_shares"] = {}
    for r in ["anthropics/skills"] + top1:
        s = d[d["repo"] == r]
        if len(s):
            share_f = float(s["forks"].sum() / tot_forks)
            share_s = float(s["stars_ev"].sum() / tot_stars)
            out["node_shares"][r] = {"fork_share": share_f, "star_share": share_s}
            print(f"    {r}: 占窗口分叉 {share_f*100:.1f}% / 星标 {share_s*100:.1f}%")
    return out


# ----------------------------------------------------------------------
# R3: 三套风险口径的 2×2 混淆矩阵
# ----------------------------------------------------------------------
def risk_confusion():
    risk = load(os.path.join("results", "v2_risk.json"))["repos"]
    schemes = {"old_kw": {}, "reach": {}, "core_topic": {}}
    for k, v in risk.items():
        schemes["old_kw"][k] = int(v.get("any_old_kw") or 0)
        schemes["reach"][k] = int(v.get("reach_binary") or 0)
        schemes["core_topic"][k] = int(v.get("core_kw_hit") or 0)

    def matrix(a, b):
        ks = sorted(set(a) & set(b))
        if not ks:
            return None
        av = np.array([a[k] for k in ks])
        bv = np.array([b[k] for k in ks])
        n11 = int(((av == 1) & (bv == 1)).sum())
        n10 = int(((av == 1) & (bv == 0)).sum())
        n01 = int(((av == 0) & (bv == 1)).sum())
        n00 = int(((av == 0) & (bv == 0)).sum())
        po = (n11 + n00) / len(ks)
        pe = ((n11 + n10) * (n11 + n01) + (n01 + n00) * (n10 + n00)) / len(ks) ** 2
        return {"n": len(ks), "both_high": n11, "a_only": n10, "b_only": n01,
                "both_low": n00, "raw_agreement": float(po),
                "kappa": float((po - pe) / (1 - pe)) if pe < 1 else None,
                "jaccard": float(n11 / (n11 + n10 + n01)) if (n11 + n10 + n01) else None}

    out = {"pairs": {}, "prevalence": {}}
    for name, s in schemes.items():
        out["prevalence"][name] = float(np.mean(list(s.values())))
    for (na, a), (nb, b) in [(("old_kw", schemes["old_kw"]), ("reach", schemes["reach"])),
                             (("old_kw", schemes["old_kw"]), ("core_topic", schemes["core_topic"])),
                             (("reach", schemes["reach"]), ("core_topic", schemes["core_topic"]))]:
        m = matrix(a, b)
        if m:
            out["pairs"][f"{na}_vs_{nb}"] = m
            print(f"  {na} vs {nb}: 双高{m['both_high']} 仅{na}高{m['a_only']} "
                  f"仅{nb}高{m['b_only']} 双低{m['both_low']} "
                  f"κ={m['kappa']:.3f} J={m['jaccard']:.3f}")
    print(f"  高风险占比: old_kw={out['prevalence']['old_kw']*100:.1f}% "
          f"reach={out['prevalence']['reach']*100:.1f}% "
          f"core_topic={out['prevalence']['core_topic']*100:.1f}%")
    return out


# ----------------------------------------------------------------------
# R4: 完备窗口的代表性
# ----------------------------------------------------------------------
def window_representativeness():
    panel = load(os.path.join("results", "v2_panel.json"))["repos"]
    d = pd.DataFrame([
        {"repo": k, "truncated": int(r["fork_left_truncated"]),
         "win_days": r["win_days"], "total_stars": r["total_stars"],
         "total_forks": r["n_fork_records"],
         "created": datetime.date.fromisoformat(r["created"]),
         "win_lo": datetime.date.fromisoformat(r["win_lo"]),
         "retained": r["retained_fork_share"] or 0}
        for k, r in panel.items()])

    d["age_at_lo"] = d.apply(lambda x: (x["win_lo"] - x["created"]).days, axis=1)
    tr = d[d["truncated"] == 1]
    nt = d[d["truncated"] == 0]

    med = lambda x: float(np.median(x)) if len(x) else None
    print(f"  截断仓库 n={len(tr)}: 窗长中位 {med(tr['win_days']):.0f} 日, "
          f"总星标中位 {med(tr['total_stars']):,.0f}")
    print(f"  未截断仓库 n={len(nt)}: 窗长中位 {med(nt['win_days']):.0f} 日, "
          f"总星标中位 {med(nt['total_stars']):,.0f}")
    print(f"  截断组窗口起点中位: {sorted(tr['win_lo'])[len(tr)//2]}")

    from scipy.stats import spearmanr
    rho, pv = spearmanr(tr["win_lo"].apply(lambda x: x.toordinal()),
                        tr["total_stars"])
    print(f"  [截断组] 窗口起点 × 总星标 Spearman ρ={rho:.3f} (p={pv:.4f})")

    row_share = float(tr["win_days"].sum() / d["win_days"].sum())
    fork_share = float(tr["total_forks"].sum() / d["total_forks"].sum())
    print(f"  截断仓库贡献的面板行占比: {row_share*100:.1f}%  分叉记录占比: {fork_share*100:.1f}%")

    out = {
        "n_truncated": int(len(tr)), "n_not_truncated": int(len(nt)),
        "trunc_win_days_median": med(tr["win_days"]),
        "notrunc_win_days_median": med(nt["win_days"]),
        "trunc_stars_median": med(tr["total_stars"]),
        "notrunc_stars_median": med(nt["total_stars"]),
        "trunc_win_lo_median": sorted(tr["win_lo"])[len(tr) // 2].isoformat(),
        "panel_row_share_truncated": row_share,
        "fork_record_share_truncated": fork_share,
        "spearman_winlo_stars": {"rho": float(rho), "p": float(pv)},
    }
    return out


def main():
    print("=" * 78)
    print("R1 祖率梯度的等价检验（TOST）与功效")
    print("=" * 78)
    eq = equivalence()
    print()
    print("=" * 78)
    print("R2 超级节点剔除")
    print("=" * 78)
    sn = supernode()
    print()
    print("=" * 78)
    print("R3 三套风险口径的混淆矩阵")
    print("=" * 78)
    rc = risk_confusion()
    print()
    print("=" * 78)
    print("R4 完备窗口的代表性")
    print("=" * 78)
    wr = window_representativeness()

    out = {"equivalence": eq, "supernode": sn,
           "risk_confusion": rc, "window": wr}
    json.dump(out, open(os.path.join(RES, "v2_robustness.json"), "w",
                        encoding="utf-8"), ensure_ascii=False, indent=2, default=float)
    print(f"\n  产出: data/results/v2_robustness.json")
    print("=" * 78)


if __name__ == "__main__":
    main()
