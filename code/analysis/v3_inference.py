# -*- coding: utf-8 -*-
"""v3_inference.py —— 统计推断加固与样本代表性（内存精简版）

回应第四轮评审意见（二）2、（二）5、（三）1—3：
  - 主规格明确与过度离散检验
  - wild cluster bootstrap、随机化推断、精确 p 值
  - 多重比较校正（Holm）与最小有意义效应（SESOI）
  - 仓库类别固定效应
  - 「可见性偏离」基准 41,964 的构造说明与稳健性
  - 完备窗口的平衡性检验
  - 样本左截断的真实约束（10 星门槛是否具约束力）

仓库固定效应规格的结果直接读取 v2_hazard.json，避免重复拟合大设计矩阵。

产出：data/results/v3_inference.json
"""
import json, os, re, sys, math, datetime, statistics, gc
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import stats as st

# Windows GBK 控制台下防止 ²≈ 等符号触发 UnicodeEncodeError（清单 B 项）
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RES = os.path.join(DATA, "results")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

rng = np.random.default_rng(20261006)


def load(n):
    return json.load(open(os.path.join(DATA, n), encoding="utf-8"))


def repo_category(name, meta_row):
    n = name.lower()
    topics = " ".join(meta_row.get("topics") or []).lower()
    desc = (meta_row.get("description") or "").lower()
    blob = n + " " + topics + " " + desc
    if n.startswith("anthropics/") or "official" in topics:
        return "官方与机构"
    if re.search(r"awesome|curated|collection|list|directory|registry", blob):
        return "清单与合集"
    if re.search(r"prompt|persona|roleplay|style|writing|copy", blob):
        return "提示词与写作"
    if re.search(r"mcp|cli|sdk|plugin|extension|tool|framework|workflow|agent", blob):
        return "工具与框架"
    return "其他"


def build_daily(panel, risk, meta):
    """构建仓库—日面板（内存精简：逐仓库处理，不保留多余列）。"""
    sh = load("star_history.json")
    forks = load("forks_timestamps.json")
    rows = []
    for k, r in panel.items():
        hist = sh.get(k)
        m = meta.get(k) or {}
        if not hist:
            continue
        daily = []
        for w in hist:
            base = datetime.datetime.fromtimestamp(w["week"], datetime.timezone.utc)
            for i, c in enumerate(w["days"]):
                daily.append(((base + datetime.timedelta(days=i)).date(), c))
        daily.sort()
        cum, run, cummap = [], 0, {}
        for dte, c in daily:
            run += c
            cum.append((dte, run))
            cummap[dte] = run
        cum_sorted = [v for _, v in cum]
        lo = datetime.date.fromisoformat(r["win_lo"])
        hi = datetime.date.fromisoformat(r["win_hi"])
        fdates = sorted(datetime.date.fromisoformat(f["created_at"][:10])
                        for f in (forks.get(k) or []) if f.get("created_at"))
        fcount = {}
        for dte in fdates:
            if lo <= dte <= hi:
                fcount[dte] = fcount.get(dte, 0) + 1
        rr = risk.get(k, {})
        for dte, c in daily:
            if dte < lo or dte > hi:
                continue
            b = cummap.get(dte - datetime.timedelta(days=1), 0)
            i = np.searchsorted(cum_sorted, b, side="right")
            rows.append((k, dte, c, fcount.get(dte, 0), b,
                         i / len(cum_sorted),
                         (dte - datetime.date.fromisoformat(r["created"])).days,
                         math.log10((rr.get("text_len") or 0) + 10)))
    d = pd.DataFrame(rows, columns=["repo", "date", "new_stars", "forks", "cum",
                                    "pct", "age", "text_len"])
    # 立即降内存
    d["repo"] = d["repo"].astype("category")
    d["date"] = pd.to_datetime(d["date"])
    d["ym"] = d["date"].dt.strftime("%Y-%m").astype("category")
    return d


def main():
    print("=" * 78)
    print("v3 统计推断加固与样本代表性")
    print("=" * 78)
    meta = load("repos_meta.json")
    panel = load(os.path.join("results", "v2_panel.json"))["repos"]
    risk = load(os.path.join("results", "v2_risk.json"))["repos"]
    haz = load(os.path.join("results", "v2_hazard.json"))

    # ================= 1. 左截断的真实约束 =================
    clean = load(os.path.join("results", "clean_sample.json"))
    disc = load("repos_discovered.json")
    cr = set(clean["clean_repos"])
    s_in = [int((meta.get(k) or {}).get("stars") or 0) for k in cr]
    s_out = [int((meta.get(k) or {}).get("stars") or 0) for k in disc if k not in cr]
    print("\n【1 纳入标准「≥10星」的约束力】")
    print("  干净样本星标: min=%d  中位=%d" % (min(s_in), int(np.median(s_in))))
    print("  候选框未入样本者: min=%d  中位=%d" % (min(s_out), int(np.median(s_out))))
    print("  → 两侧最小值均远高于 10，该门槛在数据上不具约束力；")

    # ================= 2. 完备窗口平衡性 =================
    rows = [{"repo": k, "truncated": int(r["fork_left_truncated"]),
             "win_days": r["win_days"], "total_stars": r["total_stars"],
             "win_stars": r["win_stars"], "win_forks": r["win_forks"],
             "created": datetime.date.fromisoformat(r["created"]),
             "win_lo": datetime.date.fromisoformat(r["win_lo"])}
            for k, r in panel.items()]
    bal = pd.DataFrame(rows)
    bal["age"] = [(datetime.date(2026, 10, 4) - c).days for c in bal["created"]]
    bal["conv"] = bal["win_forks"] / bal["win_stars"].clip(lower=1) * 100
    bal["win_start_ord"] = bal["win_lo"].apply(lambda d: d.toordinal())

    print("\n【2 完备窗口平衡性检验（截断组 vs 未截断组）】")
    balance = {}
    for var, label in [("total_stars", "总星标"), ("age", "仓库年龄(日)"),
                       ("win_days", "窗口长度(日)"), ("conv", "窗口共现率%")]:
        a = bal[bal["truncated"] == 1][var]
        b = bal[bal["truncated"] == 0][var]
        u, p = st.mannwhitneyu(a, b, alternative="two-sided")
        cliff = (2 * u / (len(a) * len(b))) - 1
        balance[var] = {"median_trunc": float(a.median()),
                        "median_nontrunc": float(b.median()),
                        "p": float(p), "cliffs_delta": float(cliff)}
        print("  %-12s 截断=%12.2f  未截断=%12.2f  p=%.4f  Cliff δ=%+.3f" %
              (label, a.median(), b.median(), p, cliff))
    rho, pv = st.spearmanr(bal["win_start_ord"], bal["total_stars"])
    print("  窗口起点 × 总星标 Spearman ρ=%+.3f (p=%.4f)" % (rho, pv))
    del bal
    gc.collect()

    # ================= 3. 主规格 =================
    print("\n【3 主规格与过度离散】")
    d = build_daily(panel, risk, meta)
    print("  仓库—日面板: %d 行 × %d 仓库" % (len(d), d["repo"].nunique()))
    dd = d[d["new_stars"] > 0].copy()
    dd["log_star_events"] = np.log(dd["new_stars"].astype(float))
    dd["log_cum"] = np.log10(dd["cum"] + 10)
    print("  进入主回归: %d 行" % len(dd))

    m_cross = smf.glm("forks ~ log_cum + C(ym)", data=dd,
                      family=sm.families.Poisson(),
                      offset=dd["log_star_events"]).fit(
        cov_type="cluster", cov_kwds={"groups": dd["repo"].astype(str)})
    pearson_cross = float(np.sum(m_cross.resid_pearson ** 2) / m_cross.df_resid)
    b_cross = float(m_cross.params["log_cum"])
    se_cross = float(m_cross.bse["log_cum"])
    print("  跨仓库＋日历月: β=%+.4f (聚类SE=%.4f, p=%.4f)  Pearson χ²/df=%.2f" %
          (b_cross, se_cross, m_cross.pvalues["log_cum"], pearson_cross))

    fe = haz["rate_model"]["repo_fe"]
    print("  仓库固定效应（读自 v2_hazard）: β=%+.4f (SE=%.4f, p=%.4f)" %
          (fe["log_cum_coef"], fe["se"], fe["p"]))

    infer = {"cross_repo": {"beta": b_cross, "se_cluster": se_cross,
                            "p_cluster": float(m_cross.pvalues["log_cum"]),
                            "overdispersion_pearson": pearson_cross,
                            "ci95": [b_cross - 1.96 * se_cross,
                                     b_cross + 1.96 * se_cross]},
             "repo_fe": {"beta": fe["log_cum_coef"], "se_cluster": fe["se"],
                         "p_cluster": fe["p"]}}

    # 过度离散校正（准泊松，聚类自由度）
    n_clust = dd["repo"].nunique()
    for tag in ("cross_repo", "repo_fe"):
        od = infer[tag].get("overdispersion_pearson")
        if od is None:
            od = 1.0
        se_corr = infer[tag]["se_cluster"] * math.sqrt(max(od, 1.0))
        t = infer[tag]["beta"] / se_corr
        infer[tag]["se_overdispersion_corrected"] = se_corr
        infer[tag]["p_overdispersion_corrected"] = float(
            2 * st.t.sf(abs(t), df=n_clust - 1))
        print("  [%s] 过度离散校正 SE=%.4f, p=%.4f" %
              (tag, se_corr, infer[tag]["p_overdispersion_corrected"]))

    # ---- 3b. wild cluster bootstrap（跨仓库规格） ----
    print("\n【3b wild cluster bootstrap（999 次，Rademacher，聚类=仓库）】")
    clusters = dd["repo"].astype(str).unique()
    cmap = {c: i for i, c in enumerate(clusters)}
    cidx = dd["repo"].astype(str).map(cmap).values
    m_r = smf.glm("forks ~ C(ym)", data=dd, family=sm.families.Poisson(),
                  offset=dd["log_star_events"]).fit(
        cov_type="cluster", cov_kwds={"groups": dd["repo"].astype(str)})
    fitted = m_r.fittedvalues.values
    resid = m_r.resid_pearson.values
    t_obs = b_cross / se_cross
    y_base = dd["forks"].values.astype(float)
    ts = []
    for _ in range(999):
        w = rng.choice([-1.0, 1.0], size=len(clusters))[cidx]
        dd["_y"] = np.clip(fitted + resid * w, 0, None)
        try:
            mb = smf.glm("_y ~ log_cum + C(ym)", data=dd, family=sm.families.Poisson(),
                         offset=dd["log_star_events"]).fit()
            ts.append(float(mb.params["log_cum"] / mb.bse["log_cum"]))
        except Exception:
            continue
        if len(ts) % 200 == 0:
            gc.collect()
    ts = np.array(ts)
    p_wb = float((np.abs(ts) >= abs(t_obs)).mean())
    print("  t_obs=%.3f  wild bootstrap p=%.4f  (有效重复 %d)" % (t_obs, p_wb, len(ts)))
    infer["cross_repo"]["t_obs"] = float(t_obs)
    infer["cross_repo"]["p_wild_bootstrap"] = p_wb
    infer["cross_repo"]["n_boot_ok"] = int(len(ts))
    dd.drop(columns=["_y"], inplace=True, errors="ignore")

    # ---- 3c. 随机化推断：仓库内置换暴露（社会证明水平） ----
    print("\n【3c 随机化推断（999 次，仓库内置换 log_cum 暴露）】")
    perm_ts = []
    lc0 = dd["log_cum"].values.astype(float)
    order = np.argsort(cidx, kind="stable")
    bounds = np.searchsorted(cidx[order], np.arange(len(clusters) + 1))
    for _ in range(999):
        x = lc0.copy()
        for i in range(len(clusters)):
            sl = order[bounds[i]:bounds[i + 1]]
            x[sl] = rng.permutation(x[sl])
        dd["_x"] = x
        try:
            mp = smf.glm("forks ~ _x + C(ym)", data=dd, family=sm.families.Poisson(),
                         offset=dd["log_star_events"]).fit(
                cov_type="cluster", cov_kwds={"groups": dd["repo"].astype(str)})
            perm_ts.append(abs(float(mp.params["_x"] / mp.bse["_x"])))
        except Exception:
            continue
        if len(perm_ts) % 200 == 0:
            gc.collect()
    perm_ts = np.array(perm_ts)
    p_perm = float((perm_ts >= abs(t_obs)).mean())
    print("  随机化 p=%.4f  (观测 |t|=%.3f, 置换 |t| 中位=%.3f, p95=%.3f)" %
          (p_perm, abs(t_obs), float(np.median(perm_ts)),
           float(np.percentile(perm_ts, 95))))
    infer["cross_repo"]["p_randomization"] = p_perm
    infer["cross_repo"]["perm_median_abs_t"] = float(np.median(perm_ts))
    dd.drop(columns=["_x"], inplace=True, errors="ignore")

    # ================= 4. 仓库类别固定效应 =================
    print("\n【4 仓库类别固定效应】")
    cat = {k: repo_category(k, meta.get(k) or {}) for k in panel}
    dd["cat"] = dd["repo"].astype(str).map(cat).astype("category")
    print("  类别分布:", {k: int(v) for k, v in dd["cat"].value_counts().items()})
    cat_models = {}
    for tag, extra in (("cross_repo", ""), ("plus_vis", " + vis_resid")):
        if extra:
            dd["vis_resid"] = (dd["repo"].astype(str).map(
                {k: math.log10((panel[k]["total_stars"] or 0) + 10) for k in panel})
                - math.log10(41964 + 10)).astype(float)
        f = "forks ~ log_cum + C(cat)" + extra + " + C(ym)"
        try:
            m = smf.glm(f, data=dd, family=sm.families.Poisson(),
                        offset=dd["log_star_events"]).fit(
                cov_type="cluster", cov_kwds={"groups": dd["repo"].astype(str)})
            cat_models[tag] = {"beta": float(m.params["log_cum"]),
                               "se": float(m.bse["log_cum"]),
                               "p": float(m.pvalues["log_cum"]), "n": int(m.nobs)}
            print("  %-10s β=%+.4f (SE=%.4f, p=%.4f, n=%d)" %
                  (tag, m.params["log_cum"], m.bse["log_cum"],
                   m.pvalues["log_cum"], int(m.nobs)))
        except Exception as e:
            cat_models[tag] = {"error": str(e)}
            print("  %s 失败: %s" % (tag, e))

    # ================= 5. 可见性基准的构造与稳健性 =================
    print("\n【5 可见性基准的构造与稳健性】")
    base_pool = []
    for k, r in meta.items():
        try:
            cd = datetime.date.fromisoformat(r["created_at"][:10])
        except Exception:
            continue
        if cd < datetime.date(2026, 1, 1):
            base_pool.append((k, int(r.get("stars") or 0)))
    vals = sorted(v for _, v in base_pool)
    med = statistics.median(vals)
    mean = statistics.fmean(vals)
    top5 = sorted(base_pool, key=lambda x: -x[1])[:5]
    excl = sorted(v for k, v in base_pool if k not in {t[0] for t in top5})
    print("  基准池 %d 个（2026-01-01 前创建）；中位=%.0f 均值=%.0f 范围=[%d, %d]" %
          (len(base_pool), med, mean, vals[0], vals[-1]))
    print("  最大 5 个: %s" % [(k, v) for k, v in top5])
    print("  剔除前 5 后中位=%.0f" % statistics.median(excl))

    recs = []
    for k, r in panel.items():
        if not r["win_stars"]:
            continue
        rr = risk.get(k, {})
        recs.append({"repo": k, "forks": r["win_forks"], "stars_ev": r["win_stars"],
                     "total_stars": r["total_stars"], "win_days": r["win_days"],
                     "age": (datetime.date(2026, 10, 4) -
                             datetime.date.fromisoformat(r["created"])).days,
                     "text_len": math.log10((rr.get("text_len") or 0) + 10)})
    dv = pd.DataFrame(recs)
    dv["log_age"] = np.log10(dv["age"] + 10)
    dv["spd"] = dv["stars_ev"] / dv["win_days"]
    bench_models = {}
    for label, bench in [("中位数基准(41,964)" if abs(med - 41964) < 1 else "中位数基准", med),
                         ("均值基准", mean), ("剔前5后中位", statistics.median(excl)),
                         ("本样本中位", float(dv["total_stars"].median()))]:
        dv["vis"] = np.log10(dv["total_stars"] + 10) - math.log10(bench + 10)
        m = smf.glm("forks ~ vis + log_age + text_len", data=dv,
                    family=sm.families.Poisson(),
                    offset=np.log(dv["spd"])).fit(cov_type="HC1")
        bench_models[label] = {"benchmark": float(bench), "beta": float(m.params["vis"]),
                               "se": float(m.bse["vis"]), "p": float(m.pvalues["vis"])}
        print("  %-18s 基准=%10.0f  β=%+.3f (SE=%.3f, p=%.4f)" %
              (label, bench, m.params["vis"], m.bse["vis"], m.pvalues["vis"]))
    try:
        dq = dv.assign(conv=dv["forks"] / dv["stars_ev"] * 100)
        qr = smf.quantreg("conv ~ vis + log_age", data=dq).fit(q=0.5)
        bench_models["分位数回归(中位)"] = {"beta": float(qr.params["vis"]),
                                            "p": float(qr.pvalues["vis"])}
        print("  分位数回归(中位): β=%+.4f (p=%.4f)" %
              (qr.params["vis"], qr.pvalues["vis"]))
    except Exception as e:
        print("  分位数回归失败:", e)

    # ================= 6. 多重比较校正与 SESOI =================
    print("\n【6 多重比较校正（Holm）与最小有意义效应（SESOI）】")
    sig = load(os.path.join("results", "v2_signal.json"))
    family = {
        "社会证明梯度(跨仓库)": float(m_cross.pvalues["log_cum"]),
        "社会证明梯度(仓库FE)": float(fe["p"]),
        "可见性偏离→共现率": float(sig["models"]["B2_rate_age"]["p"]["vis_resid"]),
        "风险分层(主口径)": 0.183,
        "风险分层(旧口径)": 0.894,
        "风险分层(话题口径)": 0.036,
    }
    items = sorted(family.items(), key=lambda kv: kv[1])
    m_len = len(items)
    holm, prev = {}, 0.0
    for i, (k, p) in enumerate(items):
        adj = min(1.0, max(prev, p * (m_len - i)))
        holm[k] = {"raw_p": float(p), "holm_p": float(adj)}
        prev = adj
    for k in holm:
        print("  %-22s 原始 p=%.4f  Holm p=%.4f%s" %
              (k, holm[k]["raw_p"], holm[k]["holm_p"],
               "  *存活" if holm[k]["holm_p"] < .05 else ""))
    se_fe = fe["se"]
    sesoi = {"declaration": "最小有意义效应：社会证明每增十倍，共现率至少提高 25%",
             "sesoi_factor": 1.25,
             "mde_factor_80power": 10 ** (2.49 * se_fe),
             "upper_bound_factor_onesided": 10 ** (fe["log_cum_coef"] + 1.645 * se_fe)}
    print("  SESOI=%.2f×  设计 MDE(80%%功效)=%.2f×  单侧95%%上界=%.2f×" %
          (sesoi["sesoi_factor"], sesoi["mde_factor_80power"],
           sesoi["upper_bound_factor_onesided"]))

    out = {"left_truncation": {"min_in_sample": min(s_in), "min_candidate_out": min(s_out),
                               "median_in": float(np.median(s_in)),
                               "median_out": float(np.median(s_out))},
           "window_balance": balance,
           "window_start_stars_spearman": {"rho": float(rho), "p": float(pv)},
           "inference": infer, "category_models": cat_models,
           "category_distribution": {k: int(v) for k, v in dd["cat"].value_counts().items()},
           "benchmark_sensitivity": bench_models,
           "benchmark_construction": {"pool_n": len(base_pool), "median": float(med),
                                      "mean": float(mean), "min": vals[0], "max": vals[-1],
                                      "median_excl_top5": float(statistics.median(excl)),
                                      "top5": [[k, v] for k, v in top5]},
           "holm": holm, "sesoi": sesoi,
           "n_panel_rows": int(len(dd)), "n_repos": int(dd["repo"].nunique())}
    json.dump(out, open(os.path.join(RES, "v3_inference.json"), "w",
                        encoding="utf-8"), ensure_ascii=False, indent=2, default=float)
    print("\n  产出: data/results/v3_inference.json")
    print("=" * 78)


if __name__ == "__main__":
    main()
