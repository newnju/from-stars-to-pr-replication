# -*- coding: utf-8 -*-
"""
catalog_robustness.py —— 清单型（awesome/list）仓库稳健性
（《数据来源全清单》第八节第 2 项）

问题：主导发现是否依赖 awesome 类清单仓库？
  (a) 分类：对 203 干净样本按 名称/描述/话题/已知清单 识别 catalog_repo（记录命中规则）；
  (b) 描述：catalog 组与非 catalog 组的体量、窗口事件占比与共现率差异；
  (c) 剔除稳健性：剔除 catalog 后重估四项主导结果——
        ① 首次分叉门槛 θ(I)（完备记录仓库点估计中位数）
        ② 率梯度 β(log_cum)（主规格：仓库 FE Poisson，P1 零梯度）
        ③ 可见性负相关 vis_resid（对齐 v2_robustness.R2 规格）
        ④ 同窗口分叉—星标比（共现率）中位数与总体值
  另附 GitSkills repos.is_fork 口径的分叉属性描述（清单提示的辅助判定）。

前置：run_all.py 第二阶段已产出 v2_panel.json / v2_risk.json
输出：data/results/catalog_robustness.json
"""
import json
import os
import re
import sys
import datetime
import statistics

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import numpy as np
import pandas as pd
from scipy import stats as st

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
RES = os.path.join(DATA, "results")
sys.path.insert(0, HERE)

KNOWN_LISTS = {
    "sindresorhus/awesome",
    "public-apis/public-apis",
    "awesome-selfhosted/awesome-selfhosted",
}
DESC_PAT = re.compile(
    r"curated list|awesome list|a list of|list of (the )?best|collection of (the )?best",
    re.I,
)
TOPIC_HIT = {"awesome", "list", "collection", "directory", "catalog", "index"}


def load(path):
    return json.load(open(path, encoding="utf-8"))


def classify(name, description, topics, gitskills_desc=None):
    """返回 (是否 catalog, 命中规则列表)。parquet 空值会变 NaN，先规整类型。"""
    description = description if isinstance(description, str) else ""
    gitskills_desc = gitskills_desc if isinstance(gitskills_desc, str) else ""
    if not isinstance(topics, (list, tuple)):
        topics = []
    rules = []
    lname = name.lower()
    if name in KNOWN_LISTS:
        rules.append("known_list")
    if "awesome" in lname:
        rules.append("name_awesome")
    for src, d in (("meta", description), ("gitskills", gitskills_desc)):
        if d and DESC_PAT.search(d):
            rules.append(f"desc_{src}")
            break
    for t in topics:
        if isinstance(t, str) and t.lower() in TOPIC_HIT:
            rules.append("topic_list")
            break
    return bool(rules), sorted(set(rules))


def vis_model(dat):
    """对齐 v2_robustness.supernode 的可见性规格：Poisson，offset=log(stars/day)。"""
    import statsmodels.formula.api as smf
    import statsmodels.api as sm

    dat = dat.copy()
    dat["stars_per_day"] = dat["stars_ev"] / dat["win_days"]
    m = smf.glm("forks ~ vis_resid + log_age + text_len", data=dat,
                family=sm.families.Poisson(),
                offset=np.log(dat["stars_per_day"])).fit(cov_type="HC1")
    return {"beta": float(m.params["vis_resid"]), "se": float(m.bse["vis_resid"]),
            "p": float(m.pvalues["vis_resid"]), "n": int(m.nobs)}


def main():
    clean = load(os.path.join(RES, "clean_sample.json"))["clean_repos"]
    meta = load(os.path.join(DATA, "repos_meta.json"))
    panel = load(os.path.join(RES, "v2_panel.json"))
    risk = load(os.path.join(RES, "v2_risk.json"))["repos"]
    pinfo = panel["repos"]

    # GitSkills 表拿补充描述与 is_fork（152/203 命中，缺则仅用 meta）
    gk = {}
    try:
        import glob
        rp = pd.read_parquet(sorted(glob.glob(os.path.join(
            ROOT, "external_data", "gitskills_parquet", "repos", "*.parquet")))[0],
            columns=["full_name", "description", "is_fork"])
        gk = {r.full_name: r for r in rp.itertuples(index=False)}
    except Exception:
        pass

    # ---------------- (a) 分类 ----------------
    classification = {}
    for k in clean:
        m = meta.get(k) or {}
        g = gk.get(k)
        gdesc = getattr(g, "description", None) if g is not None else None
        is_fork = int(getattr(g, "is_fork", 0)) if g is not None else None
        flag, rules = classify(k, m.get("description"), m.get("topics"), gdesc)
        classification[k] = {"catalog": flag, "rules": rules, "is_fork_gitskills": is_fork}
    cat = sorted(k for k, v in classification.items() if v["catalog"])
    rule_counts = {}
    for v in classification.values():
        for r in v["rules"]:
            rule_counts[r] = rule_counts.get(r, 0) + 1

    # ---------------- (b) 描述 ----------------
    def win(k):
        r = pinfo.get(k) or {}
        return {"win_forks": int(r.get("win_forks") or 0),
                "win_stars": int(r.get("win_stars") or 0),
                "total_stars": int(r.get("total_stars") or 0),
                "complete": not r.get("fork_left_truncated", True)}

    cat_set = set(cat)
    rows = []
    for k in clean:
        if k not in pinfo:
            continue
        w = win(k)
        if w["win_stars"] > 0:
            w["ratio"] = w["win_forks"] / w["win_stars"]
        else:
            w["ratio"] = None
        w["repo"] = k
        w["catalog"] = k in cat_set
        w["stars"] = meta.get(k, {}).get("stars") or 0
        rows.append(w)
    d = pd.DataFrame(rows)

    def grp(mask):
        g = d[mask]
        return {
            "n": int(len(g)),
            "stars_median": float(g["stars"].median()),
            "win_forks_total": int(g["win_forks"].sum()),
            "win_stars_total": int(g["win_stars"].sum()),
            "ratio_median": (float(g["ratio"].median())
                             if g["ratio"].notna().any() else None),
            "ratio_overall": (float(g["win_forks"].sum() / g["win_stars"].sum())
                              if g["win_stars"].sum() else None),
        }

    gc, gn = grp(d["catalog"]), grp(~d["catalog"])
    tot_f, tot_s = int(d["win_forks"].sum()), int(d["win_stars"].sum())
    shares = {
        "catalog_fork_share": (gc["win_forks_total"] / tot_f) if tot_f else None,
        "catalog_star_share": (gc["win_stars_total"] / tot_s) if tot_s else None,
    }
    a = d.loc[d["catalog"], "ratio"].dropna().to_numpy()
    b = d.loc[~d["catalog"], "ratio"].dropna().to_numpy()
    mwu = (float(st.mannwhitneyu(a, b, alternative="two-sided").pvalue)
           if len(a) >= 5 and len(b) >= 5 else None)

    # ---------------- (c1) θ(I) 首次分叉门槛 ----------------
    def theta(block=None):
        pts = [r["theta_first_fork_point"] for k, r in pinfo.items()
               if r.get("theta_first_fork_point") is not None
               and not r.get("fork_left_truncated")
               and (block is None or k in block)]
        return {"n": len(pts),
                "median": float(np.median(pts)) if pts else None,
                "mean": float(np.mean(pts)) if pts else None,
                "share_le_10": (float(np.mean(np.array(pts) <= 10)) if pts else None)}

    th_full = theta()
    th_excl = theta(set(clean) - cat_set)

    # ---------------- (c2) 率梯度 β(log_cum) ----------------
    from v2_hazard import build_panel, add_bins, rate_model, rate_by_bin
    df, _ = build_panel()
    df = add_bins(df)
    grad = {}
    m_full, d_full = rate_model(df, repo_fe=True)
    df_ex = df[~df["repo"].isin(cat_set)]
    m_ex, d_ex = rate_model(df_ex, repo_fe=True)
    for tag, m, dd in (("full", m_full, d_full), ("excl_catalog", m_ex, d_ex)):
        g = rate_by_bin(dd)
        grad[tag] = {
            "beta_log_cum": float(m.params["log_cum"]),
            "se": float(m.bse["log_cum"]),
            "p": float(m.pvalues["log_cum"]),
            "factor_per_10x": float(10 ** m.params["log_cum"]),
            "nobs": int(m.nobs),
            "n_repos": int(dd["repo"].nunique()),
            "naive_per100_min": float(g["per100"].min()),
            "naive_per100_max": float(g["per100"].max()),
            "naive_max_min_ratio": float(g["per100"].max() / g["per100"].min()),
        }

    # ---------------- (c3) 可见性 vis_resid ----------------
    CUT = datetime.date(2026, 1, 1)
    base = {k: int(v.get("stars") or 0) for k, v in meta.items()
            if datetime.date.fromisoformat(v["created_at"][:10]) < CUT}
    bench = statistics.median(base.values())
    vrows = []
    for k, r in pinfo.items():
        rr = risk.get(k, {})
        if not r["win_stars"]:
            continue
        vrows.append({
            "repo": k, "forks": r["win_forks"], "stars_ev": r["win_stars"],
            "vis_resid": float(np.log10(int(r["total_stars"]) + 10) -
                               np.log10(bench + 10)),
            "age": (datetime.date(2026, 10, 4) -
                    datetime.date.fromisoformat(r["created"])).days,
            "win_days": r["win_days"],
            "text_len": float(np.log10((rr.get("text_len") or 0) + 10)),
            "catalog": k in cat_set,
        })
    vd = pd.DataFrame(vrows)
    vd["log_age"] = np.log10(vd["age"] + 10)
    vis = {
        "full": vis_model(vd),
        "excl_catalog": vis_model(vd[~vd["catalog"]]),
    }

    # ---------------- 输出 ----------------
    out = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "classification": {
            "n_clean": len(clean), "n_catalog": len(cat),
            "share": len(cat) / len(clean),
            "rule_counts": rule_counts,
            "catalog_repos": {k: classification[k] for k in cat},
            "n_is_fork_gitskills": int(sum(
                1 for v in classification.values() if v["is_fork_gitskills"] == 1)),
        },
        "descriptive": {"catalog": gc, "non_catalog": gn, **shares,
                        "ratio_mwu_p": mwu},
        "theta_first_fork": {"full": th_full, "excl_catalog": th_excl},
        "rate_gradient": grad,
        "visibility": vis,
        "note": "catalog 判定为多规则并集（known/名称 awesome/描述 list/话题 list），"
                "规则明细见 classification.catalog_repos；剔除组的模型规格与正文一致，"
                "仅改变样本构成。",
    }
    with open(os.path.join(RES, "catalog_robustness.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=float)

    # ---------------- 摘要 ----------------
    print("=" * 78)
    print("清单型（awesome/list）仓库稳健性")
    print("=" * 78)
    print(f"  分类: {len(cat)}/{len(clean)} catalog  规则命中 {rule_counts}")
    print(f"  体量: catalog 组星标中位 {gc['stars_median']:,.0f} vs "
          f"非 catalog {gn['stars_median']:,.0f}")
    print(f"  窗口事件占比: 分叉 {shares['catalog_fork_share']*100:.1f}%  "
          f"星标 {shares['catalog_star_share']*100:.1f}%")
    print(f"  共现率(分叉/星标): catalog {gc['ratio_overall']*100:.2f}% vs "
          f"非 catalog {gn['ratio_overall']*100:.2f}%  MWU p={mwu}")
    print(f"\n  ① θ(I) 完备记录: 全样本中位 {th_full['median']:,.0f} (n={th_full['n']}) → "
          f"剔除后 {th_excl['median']:,.0f} (n={th_excl['n']})")
    gf, ge = grad["full"], grad["excl_catalog"]
    print(f"  ② 率梯度 β(log_cum): 全样本 {gf['beta_log_cum']:+.4f} "
          f"(SE={gf['se']:.4f}, p={gf['p']:.4f}) → "
          f"剔除后 {ge['beta_log_cum']:+.4f} (SE={ge['se']:.4f}, p={ge['p']:.4f})")
    print(f"  ③ 可见性 vis_resid: 全样本 {vis['full']['beta']:+.3f} "
          f"(p={vis['full']['p']:.4f}) → "
          f"剔除后 {vis['excl_catalog']['beta']:+.3f} (p={vis['excl_catalog']['p']:.4f})")
    print(f"  ④ 共现率总体: catalog {gc['ratio_overall']*100:.2f}% → "
          f"剔除后 {gn['ratio_overall']*100:.2f}%（即全样本 → 非 catalog）")
    print(f"\n  产出: data/results/catalog_robustness.json")
    print("=" * 78)


if __name__ == "__main__":
    main()
