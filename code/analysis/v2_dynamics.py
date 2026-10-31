# -*- coding: utf-8 -*-
"""
v2_dynamics.py —— 时间维度的脱钩（描述性）与稳健性补充

内容：
  A. 分位组 × 时期 的转化比（用等样本量分位桶，保证每一桶在两期都有观测）
  B. 星标流与分叉流的时间轨迹（分月，生态合计），用于判断"增速脱钩"是否为
     生态世俗成熟过程而非冲击特异响应
  C. 转化强度的规模不变性：分仓库规模四分位、话题类别的转化强度中位数
  D. 窗口长度敏感性：仅用完备窗口 ≥90 天的仓库重估
  E. 与旧口径的差异来源分解：θ(D) 高值中有多少来自「成熟期测量」而非「门槛」

产出：data/results/v2_dynamics.json
"""
import json, os, math, statistics, datetime
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RES = os.path.join(DATA, "results")
BREAK = datetime.date(2026, 2, 3)
BREAK2 = datetime.date(2026, 3, 24)


def load(n):
    return json.load(open(os.path.join(DATA, n), encoding="utf-8"))


def day_of(week_epoch, i):
    return (datetime.datetime.fromtimestamp(week_epoch, datetime.timezone.utc)
            + datetime.timedelta(days=i)).date()


def build_daily_ecology():
    """生态逐日星标流与分叉流（203 干净样本），用于时间描述。"""
    sh = load("star_history.json")
    forks = load("forks_timestamps.json")
    clean = load(os.path.join("results", "clean_sample.json"))["clean_repos"]
    stars, fks = {}, {}
    for k in clean:
        for w in sh.get(k, []):
            for i, c in enumerate(w["days"]):
                d = day_of(w["week"], i)
                stars[d] = stars.get(d, 0) + c
        for f in (forks.get(k) or []):
            d = datetime.date.fromisoformat(f["created_at"][:10])
            fks[d] = fks.get(d, 0) + 1
    days = sorted(set(stars) | set(fks))
    rows = [{"date": d, "stars": stars.get(d, 0), "forks": fks.get(d, 0)} for d in days]
    return pd.DataFrame(rows)


def main():
    panel = load(os.path.join("results", "v2_panel.json"))
    risk = load(os.path.join("results", "v2_risk.json"))["repos"]
    meta = load("repos_meta.json")
    repos = panel["repos"]

    # ---------- 0. 截断的时间诊断：完备窗口覆盖了仓库生命史的哪一段 ----------
    diag = []
    for k, r in repos.items():
        tot_age = (datetime.date(2026, 10, 4) - datetime.date.fromisoformat(r["created"])).days + 1
        diag.append({
            "repo": k,
            "truncated": r["fork_left_truncated"],
            "age_days": tot_age,
            "win_days": r["win_days"],
            "win_share_of_life": r["win_days"] / tot_age,
            "fork_share_retained": r["retained_fork_share"],
            "win_lo": r["win_lo"],
            "win_hi": r["win_hi"],
        })
    dg = pd.DataFrame(diag)
    print("=" * 78)
    print("v2 时间维度与截断诊断")
    print("=" * 78)
    tr = dg[dg["truncated"]]
    print(f"  左侧截断仓库 {len(tr)}/{len(dg)}")
    print(f"    完备窗口占其生命史比例：中位数 {tr['win_share_of_life'].median():.2f}，"
          f"最小 {tr['win_share_of_life'].min():.2f}，最大 {tr['win_share_of_life'].max():.2f}")
    print(f"    分叉记录保留份额：中位数 {tr['fork_share_retained'].median():.3f}")
    print(f"    窗口起点：中位数 {sorted(tr['win_lo'])[len(tr)//2]}；"
          f"最晚 {max(tr['win_lo'])}；最早 {min(tr['win_lo'])}")
    print("  说明：截断仓库只保留了最近一次分叉之前的记录，凡以「分叉事件」为观测单位的")
    print("        生态合计时序，其早期月份必然被系统性少计 → 增速结论不成立。")

    # ---------- A/B. 生态时间轨迹 ----------
    # (a) 全样本合计（受截断影响，仅供对照）
    eco = build_daily_ecology()
    eco["ym"] = eco["date"].apply(lambda d: f"{d.year}-{d.month:02d}")
    monthly = eco.groupby("ym").agg(stars=("stars", "sum"), forks=("forks", "sum"),
                                    days=("stars", "size"))
    monthly["stars_per_day"] = monthly["stars"] / monthly["days"]
    monthly["forks_per_day"] = monthly["forks"] / monthly["days"]
    monthly["fork_per_100_stars"] = monthly["forks"] / monthly["stars"] * 100
    print("\n【分月：全样本合计（分叉列受截断影响，仅供对照）】")
    print(monthly.to_string(float_format=lambda x: f"{x:,.2f}"))

    # (b) 仅分叉记录完整仓库：无截断的月份对照
    complete_repos = [k for k, r in repos.items() if not r["fork_left_truncated"]]
    sh2 = load("star_history.json")
    fk2 = load("fork_timestamps.json") if os.path.exists(
        os.path.join(DATA, "fork_timestamps.json")) else load("forks_timestamps.json")
    stars2, fks2 = {}, {}
    for k in complete_repos:
        for w in sh2.get(k, []):
            for i, c in enumerate(w["days"]):
                d = day_of(w["week"], i)
                stars2[d] = stars2.get(d, 0) + c
        for f in (fk2.get(k) or []):
            d = datetime.date.fromisoformat(f["created_at"][:10])
            fks2[d] = fks2.get(d, 0) + 1
    days2 = sorted(set(stars2) | set(fks2))
    eco2 = pd.DataFrame([{"date": d, "stars": stars2.get(d, 0),
                          "forks": fks2.get(d, 0)} for d in days2])
    eco2["ym"] = eco2["date"].apply(lambda d: f"{d.year}-{d.month:02d}")
    monthly2 = eco2.groupby("ym").agg(stars=("stars", "sum"), forks=("forks", "sum"),
                                      days=("stars", "size"))
    monthly2["stars_per_day"] = monthly2["stars"] / monthly2["days"]
    monthly2["forks_per_day"] = monthly2["forks"] / monthly2["days"]
    monthly2["fork_per_100_stars"] = monthly2["forks"] / monthly2["stars"] * 100
    print(f"\n【分月：仅分叉记录完整仓库 n={len(complete_repos)}（无左侧截断）】")
    print(monthly2.to_string(float_format=lambda x: f"{x:,.2f}"))

    # 三段对照（以两个冲击日为界）
    def seg(d0, d1):
        s = eco[(eco["date"] >= d0) & (eco["date"] < d1)]
        return {"days": len(s), "stars_per_day": s["stars"].mean(),
                "forks_per_day": s["forks"].mean(),
                "fork_per_100_stars": s["forks"].sum() / s["stars"].sum() * 100}
    segs = {
        "pre_2025-09-21_2026-02-02": seg(datetime.date(2025, 9, 21), BREAK),
        "cluster_2026-02-03_2026-03-23": seg(BREAK, BREAK2),
        "post_2026-03-24_2026-10-04": seg(BREAK2, datetime.date(2026, 10, 5)),
    }
    print("\n【三段对照】")
    for k, v in segs.items():
        print(f"  {k:<32} 星标/日 {v['stars_per_day']:>9,.0f}  "
              f"分叉/日 {v['forks_per_day']:>8,.1f}  "
              f"每100星标分叉 {v['fork_per_100_stars']:>6.2f}")

    # ---------- C. 规模与类别的转化强度 ----------
    rows = []
    for k, r in repos.items():
        rr = risk.get(k, {})
        if not r["win_stars"] or not r["win_cum_mean"]:
            continue
        rows.append({
            "repo": k, "stars": r["win_stars"], "forks": r["win_forks"],
            "conv": r["win_forks"] / r["win_stars"] * 100,
            "total_stars": r["total_stars"], "win_days": r["win_days"],
            "reach2": rr.get("reach_binary") or 0,
            "reach": rr.get("reach_index") or 0.0,
            "old_kw": rr.get("any_old_kw") or 0,
            "age": (datetime.date(2026, 10, 4) - datetime.date.fromisoformat(r["created"])).days,
        })
    d = pd.DataFrame(rows)
    d["size_q"] = pd.qcut(d["total_stars"].rank(method="first"), 4,
                          labels=["Q1最小", "Q2", "Q3", "Q4最大"])
    print("\n【按仓库体量四分位的转化比（每 100 星标事件的分叉数）】")
    print(d.groupby("size_q", observed=True).apply(
        lambda s: pd.Series({"n": len(s), "median_total_stars": s["total_stars"].median(),
                             "forks_per_100": s["forks"].sum() / s["stars"].sum() * 100,
                             "median_conv": s["conv"].median()}),
        include_groups=False).to_string(float_format=lambda x: f"{x:,.2f}"))

    # 规模弹性
    m = smf.glm("forks ~ log10_total + log_age", data=d.assign(
        log10_total=np.log10(d["total_stars"] + 10), log_age=np.log10(d["age"] + 10)),
        family=sm.families.Poisson(), offset=np.log(d["stars"])).fit(cov_type="HC1")
    size_elast = {"coef": float(m.params["log10_total"]), "se": float(m.bse["log10_total"]),
                  "p": float(m.pvalues["log10_total"]),
                  "irr_per_10x": float(np.exp(m.params["log10_total"]))}
    print(f"\n  体量弹性：仓库总星标每增 10 倍，分叉/星标比 ×{size_elast['irr_per_10x']:.3f}"
          f" (p={size_elast['p']:.3f})")

    # ---------- D. 窗口长度敏感性 ----------
    sub = d[d["win_days"] >= 90]
    m2 = smf.glm("forks ~ reach2 + np.log10(total_stars+10) + np.log10(age+10)",
                 data=sub, family=sm.families.Poisson(),
                 offset=np.log(sub["stars"])).fit(cov_type="HC1")
    win_sens = {"n": int(len(sub)), "reach2_coef": float(m2.params["reach2"]),
                "reach2_p": float(m2.pvalues["reach2"]),
                "irr": float(np.exp(m2.params["reach2"]))}
    print(f"\n【窗口≥90 天的子样本（n={win_sens['n']}）】风险代理 IRR="
          f"{win_sens['irr']:.3f} (p={win_sens['reach2_p']:.3f})")

    # ---------- A（分位组 × 时期，等样本量分位桶） ----------
    sh = load("star_history.json")
    forks = load("forks_timestamps.json")
    clean = load(os.path.join("results", "clean_sample.json"))["clean_repos"]
    day_rows = []
    for k in clean:
        r = repos.get(k)
        if r is None or not r["win_lo"]:
            continue
        lo = datetime.date.fromisoformat(r["win_lo"])
        hi = datetime.date.fromisoformat(r["win_hi"])
        daily = []
        for w in sh.get(k, []):
            for i, c in enumerate(w["days"]):
                dd = day_of(w["week"], i)
                if lo <= dd <= hi:
                    daily.append((dd, c))
        daily.sort()
        cummap = {}
        for s in sh.get(k, []):
            pass
        # 重建累计（自序列起点）
        allc, run = {}, 0
        tmp = []
        for w in sh.get(k, []):
            for i, c in enumerate(w["days"]):
                tmp.append((day_of(w["week"], i), c))
        tmp.sort()
        for dd, c in tmp:
            run += c
            allc[dd] = run
        fdates = sorted(datetime.date.fromisoformat(f["created_at"][:10])
                        for f in (forks.get(k) or []))
        fcnt = {}
        for dd in fdates:
            if lo <= dd <= hi:
                fcnt[dd] = fcnt.get(dd, 0) + 1
        # 以窗口内累计星标分位分桶（等样本量）
        cums = [allc.get(dd - datetime.timedelta(days=1), 0) for dd, _ in daily]
        order = np.argsort(np.argsort(cums))
        for j, (dd, c) in enumerate(daily):
            day_rows.append({"repo": k, "date": dd,
                             "q": order[j] / max(len(daily) - 1, 1),
                             "new_stars": c, "forks": fcnt.get(dd, 0),
                             "period": "post" if dd >= BREAK else "pre"})
    dp = pd.DataFrame(day_rows)
    dp["qbin"] = np.minimum((dp["q"] * 5).astype(int), 4)
    gg = dp.groupby(["qbin", "period"]).agg(ns=("new_stars", "sum"),
                                            fk=("forks", "sum"))
    gg["conv"] = gg["fk"] / gg["ns"] * 100
    piv = gg["conv"].unstack()
    piv["n_pre"] = gg["ns"].unstack()["pre"]
    piv["n_post"] = gg["ns"].unstack()["post"]
    print("\n【五分位桶 × 时期 的转化比（等样本量桶，两期均有观测）】")
    print(piv.to_string(float_format=lambda x: f"{x:,.2f}"))

    out = {
        "truncation_diagnostics": {
            "n_truncated": int(len(tr)), "n_total": int(len(dg)),
            "median_win_share_of_life_truncated": float(tr["win_share_of_life"].median()),
            "min_win_share_of_life_truncated": float(tr["win_share_of_life"].min()),
            "median_fork_share_retained_truncated": float(tr["fork_share_retained"].median()),
            "median_win_lo_truncated": sorted(tr["win_lo"])[len(tr) // 2],
            "note": "凡以分叉事件为观测单位的生态合计时序，其早期月份被系统性少计，"
                    "故分叉『增速加速』不可作为结论。",
        },
        "monthly_ecology_all": monthly.reset_index().to_dict("records"),
        "monthly_ecology_complete_only": monthly2.reset_index().to_dict("records"),
        "n_complete_repos": len(complete_repos),
        "segments": segs,
        "by_size_quartile": json.loads(d.groupby("size_q", observed=True).apply(
            lambda s: pd.Series({"n": len(s), "median_total_stars": s["total_stars"].median(),
                                 "forks_per_100": s["forks"].sum() / s["stars"].sum() * 100,
                                 "median_conv": s["conv"].median()}),
            include_groups=False).to_json(orient="index")),
        "size_elasticity": size_elast,
        "window_sensitivity": win_sens,
        "quintile_by_period": {str(i): {c: (None if pd.isna(piv.loc[i, c]) else float(piv.loc[i, c]))
                                        for c in piv.columns} for i in piv.index},
    }
    json.dump(out, open(os.path.join(RES, "v2_dynamics.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2, default=float)
    print("\n  产出: data/results/v2_dynamics.json")
    print("=" * 78)


if __name__ == "__main__":
    main()
