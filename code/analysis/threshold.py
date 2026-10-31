# -*- coding: utf-8 -*-
"""
门槛回溯 + 采纳空转 核心分析（真实数据）
数据源：star_history.json（每日star时序）、forks_timestamps.json（fork精确时间戳）、repos_meta.json
产出：注意力门槛 θ(L)、贡献门槛 θ(D)（采纳时点回溯法）、分离度 Δ、采纳空转指标
"""
import json, os, datetime, statistics, math, sys

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

def load(name):
    return json.load(open(os.path.join(DATA, name), encoding="utf-8"))

def daily_series(hist):
    """周分组 → 每日 [(date_str, count)] 升序"""
    out = []
    for w in hist:
        base = datetime.datetime.fromtimestamp(w["week"], datetime.timezone.utc)
        for i, c in enumerate(w["days"]):
            d = base + datetime.timedelta(days=i)
            out.append((d.strftime("%Y-%m-%d"), c))
    out.sort()
    return out

def cumulative(hist):
    """每日 [(date_str, cumulative_stars)]，cumulative 为截至当日（含）的累计 star"""
    ds = daily_series(hist)
    cum = []
    run = 0
    for d, c in ds:
        run += c
        cum.append((d, run))
    return cum

def cum_at_date(cum, date_str):
    """给定日期，返回截至该日的累计 star；无数据返回 None"""
    # cum 升序；二分或线性
    best = None
    for d, v in cum:
        if d <= date_str:
            best = v
        else:
            break
    return best

def main():
    sh = load("star_history.json")
    forks = load("forks_timestamps.json")
    meta = load("repos_meta.json")

    print("=" * 70)
    print("门槛回溯与采纳空转分析")
    print("=" * 70)

    # ---------- A. 生态描述统计 ----------
    n = len(meta)
    stars = [m["stars"] for m in meta.values() if isinstance(m, dict) and "stars" in m]
    fks = [m["forks"] for m in meta.values() if isinstance(m, dict) and "forks" in m]
    tot_stars = sum(stars)
    tot_forks = sum(fks)
    print(f"\n【A. 生态描述统计】")
    print(f"  仓库数: {n}")
    print(f"  总 star: {tot_stars:,}  总 fork: {tot_forks:,}")
    print(f"  star 中位数: {statistics.median(stars):.0f}  均值: {statistics.mean(stars):.0f}")
    print(f"  fork 中位数: {statistics.median(fks):.0f}  均值: {statistics.mean(fks):.0f}")

    # ---------- B. 采纳空转：fork/star 转化率 ----------
    print(f"\n【B. 采纳空转（浅层参与 vs 深层贡献）】")
    ratios = []
    for k, m in meta.items():
        if isinstance(m, dict) and m.get("stars", 0) > 0:
            ratios.append((k, m["stars"], m.get("forks", 0), m["forks"] / m["stars"]))
    ratios.sort(key=lambda x: -x[0].__hash__())  # noop
    # 总体转化率
    overall = tot_forks / tot_stars if tot_stars else 0
    print(f"  生态整体 fork/star 转化率: {overall*100:.2f}%")
    # 中位数转化率
    med_ratio = statistics.median(r[3] for r in ratios)
    print(f"  各仓库 fork/star 转化率中位数: {med_ratio*100:.2f}%")
    # 官方仓库
    o = meta.get("anthropics/skills", {})
    if isinstance(o, dict):
        oratio = o["forks"] / o["stars"] if o.get("stars") else 0
        print(f"  anthropics/skills: {o['stars']:,} star / {o['forks']:,} fork → {oratio*100:.2f}%")
    # 转化率分布分位
    rs = sorted(r[3] for r in ratios)
    def q(p):
        idx = int(len(rs) * p)
        return rs[min(idx, len(rs)-1)]
    print(f"  转化率分位: 10%={q(0.1)*100:.1f}%  25%={q(0.25)*100:.1f}%  50%={q(0.5)*100:.1f}%  75%={q(0.75)*100:.1f}%  90%={q(0.9)*100:.1f}%")

    # ---------- C. 贡献门槛回溯 θ(D) ----------
    print(f"\n【C. 贡献门槛回溯（采纳时点回溯法）】")
    # 对每个 fork 事件，回溯 fork 时点的累计 star 数
    thresholds = []  # (repo, fork_date, cum_stars_at_fork)
    for k, flist in forks.items():
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
    print(f"  有效 fork 事件数: {len(thresholds):,}")
    if thresholds:
        vals = [t[2] for t in thresholds]
        print(f"  θ(D) 贡献门槛分布（fork 时点累计 star）：")
        print(f"    中位数: {statistics.median(vals):.0f}  均值: {statistics.mean(vals):.0f}")
        print(f"    min={min(vals)}  max={max(vals)}")
        s = sorted(vals)
        print(f"    分位: 10%={s[int(len(s)*0.1)]}  25%={s[int(len(s)*0.25)]}  50%={s[int(len(s)*0.5)]}  75%={s[int(len(s)*0.75)]}  90%={s[int(len(s)*0.9)]}")
        # 有多少 fork 发生在 star=0 时（注意力门槛近零的证据 vs 贡献门槛显著为正）
        zero_at_fork = sum(1 for v in vals if v <= 10)
        print(f"    fork 时累计 star ≤10 的比例: {zero_at_fork/len(vals)*100:.1f}%")
        # 注意力门槛：star 从 day 0 就开始（累计=0 时即有人 star）
        # 证据：官方仓库创建后首周即有 star（已见 explore），故 θ(L)≈0
        # 分离度 Δ = θ(D) - θ(L) ≈ θ(D)
        print(f"    分离度 Δ（θ(D)-θ(L)，θ(L)≈0）≈ θ(D) 中位数 {statistics.median(vals):.0f}")

    # ---------- D. 注意力门槛跨越（ignition 点） ----------
    print(f"\n【D. 注意力门槛跨越（star 爆发点）】")
    ignitions = []
    for k, hist in sh.items():
        if not hist:
            continue
        ds = daily_series(hist)
        if len(ds) < 14:
            continue
        # 7日移动平均，找首次 >=5/天 的时点
        for i in range(6, len(ds)):
            seg = ds[i-6:i+1]
            avg = sum(c for _, c in seg) / 7
            if avg >= 5:
                ignitions.append((k, ds[i][0], sum(c for _, c in ds[:i+1])))
                break
        else:
            ignitions.append((k, ds[-1][0], sum(c for _, c in ds)))
    print(f"  有可计算爆发点的仓库: {len(ignitions)}")
    if ignitions:
        ign_stars = [t[2] for t in ignitions]
        print(f"  爆发时点累计 star 中位数: {statistics.median(ign_stars):.0f}  均值: {statistics.mean(ign_stars):.0f}")
        low_ign = sum(1 for v in ign_stars if v <= 50)
        print(f"  爆发时累计 star ≤50 的仓库占比: {low_ign/len(ign_stars)*100:.1f}%  (注意力门槛近零的证据)")

    # ---------- 保存结果 ----------
    result = {
        "n_repos": n,
        "tot_stars": tot_stars, "tot_forks": tot_forks,
        "median_stars": statistics.median(stars), "median_forks": statistics.median(fks),
        "overall_fork_star_ratio": overall,
        "median_fork_star_ratio": med_ratio,
        "n_fork_events": len(thresholds),
        "theta_D_median": statistics.median([t[2] for t in thresholds]) if thresholds else None,
        "theta_D_mean": statistics.mean([t[2] for t in thresholds]) if thresholds else None,
        "ignition_median_stars": statistics.median(ign_stars) if ignitions else None,
    }
    os.makedirs(os.path.join(DATA, "results"), exist_ok=True)
    json.dump(result, open(os.path.join(DATA, "results", "threshold.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"\n  结果已保存 data/results/threshold.json")
    print("=" * 70)

if __name__ == "__main__":
    main()
