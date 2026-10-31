# -*- coding: utf-8 -*-
"""
v2_signal.py —— 信号竞争：可见性信号压过安全信号的检验

理论对应：五维信号中可见性信号（星标）在渐进式披露的 Level 1 被呈现，
而安全信号（权限声明、审计与沙箱）的完整信息位于 Level 2—3，
用户作出采纳决策时不可见。若该结构成立，则可检验的推论有二：

  T1（可见性超配）：在控制规模与年龄后，获得高于同期同话题基准的可见性
      并不提高（或降低）意图转化率——即可见性信号不含关于"是否值得深入参与"
      的增量信息。
  T2（披露不足）：声明工具权限的技能占比极低，构成安全信号的供给缺口。

两者共同指向「信号竞争」而非「门槛分化」：浅层与深层的分离不由社会证明
阈值造成，而由平台在决策时点呈现哪一类信号造成。

产出：data/results/v2_signal.json
"""
import json, os, math, datetime, statistics
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RES = os.path.join(DATA, "results")


def load(n):
    return json.load(open(os.path.join(DATA, n), encoding="utf-8"))


def main():
    panel = load(os.path.join("results", "v2_panel.json"))["repos"]
    risk = load(os.path.join("results", "v2_risk.json"))["repos"]
    meta = load("repos_meta.json")

    CUT = datetime.date(2026, 1, 1)   # 早期队列基准
    base = {}
    for k, r in meta.items():
        d = datetime.date.fromisoformat(r["created_at"][:10])
        if d < CUT:
            base[k] = int(r.get("stars") or 0)
    bench = statistics.median(base.values()) if base else 1

    rows = []
    for k, r in panel.items():
        rr = risk.get(k, {})
        if not r["win_stars"]:
            continue
        stars_now = int(r["total_stars"])
        resid = math.log10(stars_now + 10) - math.log10(bench + 10)
        rows.append({
            "repo": k,
            "forks": r["win_forks"], "stars_ev": r["win_stars"],
            "vis_resid": resid,                       # 可见性相对同期基准的标准化偏离
            "reach": rr.get("reach_index") if rr.get("reach_index") is not None else 0.0,
            "reach2": rr.get("reach_binary") or 0,
            "old_kw": rr.get("any_old_kw") or 0,
            "disclosure": rr.get("disclosure_index") or 0,
            "allowed_tools": (rr.get("disclosure") or {}).get("allowed_tools") or 0,
            "text_len": math.log10((rr.get("text_len") or 0) + 10),
            "total_stars": stars_now,
            "age": (datetime.date(2026, 10, 4) -
                    datetime.date.fromisoformat(r["created"])).days,
            "win_days": r["win_days"],
            "has_md": bool(rr.get("has_skillmd")),
        })
    d = pd.DataFrame(rows)
    d["log_age"] = np.log10(d["age"] + 10)
    d["log_stars"] = np.log10(d["total_stars"] + 10)
    d["log_text"] = d["text_len"]

    print("=" * 78)
    print("v2 信号竞争检验")
    print("=" * 78)
    print(f"  同期基准（2026-01-01 前创建仓库的星标中位数）: {bench:,.0f}")
    print(f"  可见性偏离: 中位数 {d['vis_resid'].median():+.2f}  "
          f"p10 {d['vis_resid'].quantile(.1):+.2f}  p90 {d['vis_resid'].quantile(.9):+.2f}")

    models = {}
    # 说明：vis_resid 与 log_stars 同为规模的单调变换（纯截面变异），不可同时入模，
    # 故规模只由 vis_resid 承载；窗长与结果机械相关，故主规格改用「日均」暴露。
    d["stars_per_day"] = d["stars_ev"] / d["win_days"]
    # (a) 以窗口内星标事件总数为暴露：回答「同样多注意力事件带来多少意图事件」
    # (b) 以日均星标事件为暴露：剔除窗长与结果之间的机械相关
    specs = {
        "A1_level_base": ("forks ~ vis_resid", np.log(d["stars_ev"])),
        "A2_level_age": ("forks ~ vis_resid + log_age", np.log(d["stars_ev"])),
        "A3_level_full": ("forks ~ vis_resid + log_age + log_text", np.log(d["stars_ev"])),
        "B1_rate_base": ("forks ~ vis_resid", np.log(d["stars_per_day"])),
        "B2_rate_age": ("forks ~ vis_resid + log_age", np.log(d["stars_per_day"])),
        "B3_rate_full": ("forks ~ vis_resid + log_age + log_text", np.log(d["stars_per_day"])),
        "B4_rate_plus_reach": ("forks ~ vis_resid + log_age + log_text + reach2",
                               np.log(d["stars_per_day"])),
        "B5_rate_plus_disc": ("forks ~ vis_resid + log_age + log_text + disclosure",
                              np.log(d["stars_per_day"])),
    }
    for tag, (f, off) in specs.items():
        try:
            m = smf.glm(f, data=d, family=sm.families.Poisson(),
                        offset=off).fit(cov_type="HC1")
            key = [t for t in m.params.index if t in
                   ("vis_resid", "reach2", "disclosure")]
            models[tag] = {"n": int(m.nobs),
                           "coef": {k: float(m.params[k]) for k in key},
                           "se": {k: float(m.bse[k]) for k in key},
                           "p": {k: float(m.pvalues[k]) for k in key},
                           "irr": {k: float(np.exp(m.params[k])) for k in key}}
            print(f"\n  {tag} (n={int(m.nobs)})")
            for k in key:
                print(f"    {k:<12} β={m.params[k]:+.4f} (SE={m.bse[k]:.4f}, "
                      f"p={m.pvalues[k]:.4f})  IRR={np.exp(m.params[k]):.4f}")
        except Exception as e:
            models[tag] = {"error": str(e)}
            print(f"  {tag}: {e}")

    # 稳健性：极端值裁剪与四分位指示变量（判断系数是否由尾部驱动）
    d["vis_q"] = pd.qcut(d["vis_resid"].rank(method="first"), 4,
                         labels=["V1最低", "V2", "V3", "V4最高"])
    lo, hi = d["vis_resid"].quantile(.05), d["vis_resid"].quantile(.95)
    d["vis_win"] = d["vis_resid"].clip(lo, hi)
    # 年龄分箱固定效应：消除「可见性与仓库成熟度」的混淆（评审意见 5.3）
    d["age_bin"] = pd.cut(d["age"], bins=[0, 120, 210, 300, 10000],
                          labels=["≤120日", "121–210日", "211–300日", ">300日"])
    extra = {}
    for tag, f in (("C1_winsor", "forks ~ vis_win + log_age + log_text"),
                   ("C2_quartile", "forks ~ C(vis_q) + log_age + log_text"),
                   ("C3_agebin_vis", "forks ~ vis_resid + C(age_bin) + log_text"),
                   ("C4_agebin_visq", "forks ~ C(vis_q) + C(age_bin) + log_text")):
        try:
            m = smf.glm(f, data=d, family=sm.families.Poisson(),
                        offset=np.log(d["stars_per_day"])).fit(cov_type="HC1")
            key = [t for t in m.params.index if t.startswith("vis_") or "vis_q" in t]
            extra[tag] = {"n": int(m.nobs),
                          "coef": {k: float(m.params[k]) for k in key},
                          "p": {k: float(m.pvalues[k]) for k in key},
                          "irr": {k: float(np.exp(m.params[k])) for k in key}}
            print(f"\n  {tag} (n={int(m.nobs)})")
            for k in key:
                print(f"    {k:<22} β={m.params[k]:+.4f}  p={m.pvalues[k]:.4f}  "
                      f"IRR={np.exp(m.params[k]):.4f}")
        except Exception as e:
            extra[tag] = {"error": str(e)}
            print(f"  {tag}: {e}")

    # 年龄分箱 × 可见性四分位 的原始转化比（无模型假设）
    cell = d.groupby(["age_bin", "vis_q"], observed=True).agg(
        n=("repo", "size"), forks=("forks", "sum"), stars_ev=("stars_ev", "sum"))
    cell["per100"] = cell["forks"] / cell["stars_ev"] * 100
    print("\n【年龄分箱 × 可见性四分位 的原始转化比（每 100 星标事件的分叉数）】")
    print(cell.reset_index().pivot(index="age_bin", columns="vis_q",
                                   values="per100").to_string(
        float_format=lambda x: f"{x:,.2f}"))

    # 披露供给缺口
    by_item = load(os.path.join("results", "v2_risk.json"))["disclosure_desc"]["by_item"]
    with_md = [k for k, r in risk.items() if r.get("has_skillmd")]
    supply = {
        "n_with_skillmd": len(with_md),
        "allowed_tools_declared": by_item["allowed_tools"],
        "permission_mentioned": by_item["permission_scope"],
        "sandbox_mentioned": by_item["sandbox"],
        "audit_mentioned": by_item["audit_badge"],
        "all_five": load(os.path.join("results", "v2_risk.json"))["disclosure_desc"]["share_all5"],
    }
    print("\n【T2 安全信号的供给缺口】")
    for k, v in supply.items():
        if isinstance(v, float):
            print(f"    {k:<26} {v*100:.1f}%")

    # 可见性×披露 的联合分布（是否高可见性技能反而更不披露）
    d["vis_q4"] = pd.qcut(d["vis_resid"].rank(method="first"), 4,
                          labels=["可见性最低", "Q2", "Q3", "可见性最高"])
    tab = d.groupby("vis_q4", observed=True).agg(
        n=("repo", "size"),
        median_disclosure=("disclosure", "median"),
        allowed_tools_share=("allowed_tools", "mean"),
        forks=("forks", "sum"), stars_ev=("stars_ev", "sum"))
    tab["forks_per_100"] = tab["forks"] / tab["stars_ev"] * 100
    print("\n【可见性四分位 × 披露水平 × 转化比】")
    print(tab.to_string(float_format=lambda x: f"{x:,.3f}"))

    out = {"benchmark_median_stars": bench, "models": models, "robustness": extra,
           "supply": supply,
           "age_vis_cells": json.loads(cell.to_json(orient="index")),
           "vis_quartile_table": json.loads(tab.to_json(orient="index"))}
    json.dump(out, open(os.path.join(RES, "v2_signal.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2, default=float)
    print("\n  产出: data/results/v2_signal.json")
    print("=" * 78)


if __name__ == "__main__":
    main()
