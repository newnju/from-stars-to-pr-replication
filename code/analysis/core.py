# -*- coding: utf-8 -*-
"""
核心实证分析（干净样本 203 个 Skill 时代仓库）
产出论文所需全部核心数值：
  A. 描述统计 + 采纳空转（fork/star 转化率）
  B. 注意力门槛 θ(L)（star 爆发点回溯）
  C. 贡献门槛 θ(D)（fork 时点累计 star 回溯）
  D. 分离度 Δ = θ(D) - θ(L)
  E. 事件研究（审计冲击对 star/fork 增速）
  F. 高风险技能 vs 低风险技能分层
全部写 JSON 到 data/results/empirical_core.json
"""
import json, os, datetime, statistics
from collections import Counter

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

def load(name):
    return json.load(open(os.path.join(DATA, name), encoding="utf-8"))

def daily_series(hist):
    out = []
    for w in hist:
        base = datetime.datetime.fromtimestamp(w["week"], datetime.timezone.utc)
        for i, c in enumerate(w["days"]):
            d = base + datetime.timedelta(days=i)
            out.append((d.strftime("%Y-%m-%d"), c))
    out.sort()
    return out

def cum_at_date(cum, date_str):
    best = None
    for d, v in cum:
        if d <= date_str:
            best = v
        else:
            break
    return best

def cumulative(hist):
    ds = daily_series(hist)
    cum, run = [], 0
    for d, c in ds:
        run += c
        cum.append((d, run))
    return cum

def q(sorted_vals, p):
    if not sorted_vals:
        return None
    i = min(int(len(sorted_vals) * p), len(sorted_vals) - 1)
    return sorted_vals[i]

def main():
    sh = load("star_history.json")
    forks = load("forks_timestamps.json")
    meta = load("repos_meta.json")
    clean = load("results/clean_sample.json")
    clean_repos = set(clean["clean_repos"])

    R = {}  # 结果容器

    # ---------- A. 描述统计 ----------
    cm = {k: meta[k] for k in clean_repos if k in meta}
    stars = [m["stars"] for m in cm.values() if isinstance(m, dict) and "stars" in m]
    fks = [m["forks"] for m in cm.values() if isinstance(m, dict) and "forks" in m]
    tot_s, tot_f = sum(stars), sum(fks)
    R["A"] = {
        "n": len(cm),
        "total_stars": tot_s, "total_forks": tot_f,
        "median_stars": statistics.median(stars), "mean_stars": statistics.mean(stars),
        "median_forks": statistics.median(fks), "mean_forks": statistics.mean(fks),
        "overall_ratio": tot_f / tot_s if tot_s else None,
        "median_ratio": statistics.median(m["forks"]/m["stars"] if m.get("stars") else 0 for m in cm.values()),
    }

    # ---------- B. 注意力门槛 θ(L)：star 爆发点 ----------
    ignitions = []
    for k in clean_repos:
        hist = sh.get(k)
        if not hist:
            continue
        ds = daily_series(hist)
        if len(ds) < 14:
            continue
        for i in range(6, len(ds)):
            avg = sum(c for _, c in ds[i-6:i+1]) / 7
            if avg >= 5:
                ignitions.append((k, ds[i][0], sum(c for _, c in ds[:i+1])))
                break
        else:
            ignitions.append((k, ds[-1][0], sum(c for _, c in ds)))
    ig_stars = sorted(t[2] for t in ignitions)
    R["B_theta_L"] = {
        "n": len(ignitions),
        "median_ignition_stars": statistics.median(ig_stars) if ig_stars else None,
        "mean_ignition_stars": statistics.mean(ig_stars) if ig_stars else None,
        "pct_le_50": sum(1 for v in ig_stars if v <= 50)/len(ig_stars)*100 if ig_stars else None,
        "pct_le_10": sum(1 for v in ig_stars if v <= 10)/len(ig_stars)*100 if ig_stars else None,
        "q10": q(ig_stars, 0.1), "q25": q(ig_stars, 0.25), "q50": q(ig_stars, 0.5),
        "q75": q(ig_stars, 0.75), "q90": q(ig_stars, 0.9),
    }

    # ---------- C. 贡献门槛 θ(D)：fork 时点累计 star ----------
    thresholds = []
    for k in clean_repos:
        flist = forks.get(k)
        if not isinstance(flist, list) or k not in sh:
            continue
        cum = cumulative(sh[k])
        if not cum:
            continue
        for f in flist:
            fd = f.get("created_at", "")[:10]
            v = cum_at_date(cum, fd)
            if v is not None:
                thresholds.append((k, fd, v))
    tvals = sorted(t[2] for t in thresholds)
    R["C_theta_D"] = {
        "n_events": len(thresholds),
        "median": statistics.median(tvals) if tvals else None,
        "mean": statistics.mean(tvals) if tvals else None,
        "q10": q(tvals, 0.1), "q25": q(tvals, 0.25), "q50": q(tvals, 0.5),
        "q75": q(tvals, 0.75), "q90": q(tvals, 0.9),
        "pct_le_10": sum(1 for v in tvals if v <= 10)/len(tvals)*100 if tvals else None,
    }

    # ---------- D. 分离度 Δ ----------
    # Δ = θ(D)中位数 - θ(L)中位数（注意力门槛近零）
    tl_med = R["B_theta_L"]["median_ignition_stars"]
    td_med = R["C_theta_D"]["median"]
    R["D_separation"] = {
        "theta_L_median": tl_med,
        "theta_D_median": td_med,
        "delta": (td_med - tl_med) if (tl_med is not None and td_med is not None) else None,
        "delta_ratio": (td_med / tl_med) if (tl_med and td_med) else None,
    }

    # ---------- E. 事件研究（干净样本聚合） ----------
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

    def seg_mean(daily, s, e):
        vals = [c for d, c in daily if s <= d < e]
        return statistics.mean(vals) if vals else None

    sdaily = agg_daily(clean_repos)
    fddaily = fork_daily(clean_repos)
    segs = [
        ("pre", "2025-10-01", "2026-02-03"),
        ("cluster", "2026-02-03", "2026-03-24"),
        ("post2", "2026-03-24", "2026-07-01"),
        ("tail", "2026-07-01", "2026-10-05"),
    ]
    R["E_event_study"] = {
        "star": {name: seg_mean(sdaily, s, e) for name, s, e in segs},
        "fork": {name: seg_mean(fddaily, s, e) for name, s, e in segs},
    }
    # 官方仓库单独
    o_hist = sh.get("anthropics/skills", [])
    o_daily = daily_series(o_hist)
    R["E_official"] = {
        "star": {name: seg_mean(o_daily, s, e) for name, s, e in segs},
    }

    # ---------- F. 高风险技能分层 ----------
    # 用安全相关 topic / 描述关键词做粗略风险分层（代理）
    risk_kw = ["security", "pen-test", "pentest", "exploit", "recon", "payload",
               "malware", "hack", "offensive", "vuln", "cve", "osint", "credential",
               "admin", "sudo", "shell", "network"]
    high_risk, low_risk = [], []
    for k in clean_repos:
        m = cm.get(k, {})
        topics = " ".join(m.get("topics", []) or []).lower()
        desc = (m.get("description") or "").lower()
        txt = topics + " " + desc
        if any(kw in txt for kw in risk_kw):
            high_risk.append(k)
        else:
            low_risk.append(k)
    def ratio_stats(repos):
        if not repos:
            return None
        rs = []
        for k in repos:
            m = cm.get(k, {})
            if isinstance(m, dict) and m.get("stars"):
                rs.append(m["forks"]/m["stars"])
        return {
            "n": len(repos),
            "median_ratio": statistics.median(rs) if rs else None,
            "mean_ratio": statistics.mean(rs) if rs else None,
        }
    R["F_risk_strata"] = {
        "high_risk": ratio_stats(high_risk),
        "low_risk": ratio_stats(low_risk),
        "n_high_risk": len(high_risk), "n_low_risk": len(low_risk),
    }

    os.makedirs(os.path.join(DATA, "results"), exist_ok=True)
    json.dump(R, open(os.path.join(DATA, "results", "empirical_core.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    # 打印摘要
    print("=" * 70)
    print("核心实证分析结果（干净样本 203 仓库）")
    print("=" * 70)
    print(f"A 描述: n={R['A']['n']}, star总={tot_s:,}, fork总={tot_f:,}, 转化率={R['A']['overall_ratio']*100:.2f}%")
    print(f"B θ(L): 爆发点累计star中位数={R['B_theta_L']['median_ignition_stars']:.0f}, ≤10占比={R['B_theta_L']['pct_le_10']:.1f}%")
    print(f"C θ(D): fork时点累计star中位数={R['C_theta_D']['median']:.0f}, ≤10占比={R['C_theta_D']['pct_le_10']:.1f}%")
    print(f"D 分离度 Δ={R['D_separation']['delta']:.0f} (θD={td_med:.0f}, θL={tl_med:.0f})")
    print(f"E 事件研究 star: { {k: round(v) if v else None for k,v in R['E_event_study']['star'].items()} }")
    print(f"E 事件研究 fork: { {k: round(v) if v else None for k,v in R['E_event_study']['fork'].items()} }")
    print(f"F 风险分层: 高={R['F_risk_strata']['n_high_risk']}仓库(转化率{R['F_risk_strata']['high_risk']['median_ratio']*100:.2f}%) vs 低={R['F_risk_strata']['n_low_risk']}仓库(转化率{R['F_risk_strata']['low_risk']['median_ratio']*100:.2f}%)")
    print("  结果已保存 data/results/empirical_core.json")
    print("=" * 70)

if __name__ == "__main__":
    main()
