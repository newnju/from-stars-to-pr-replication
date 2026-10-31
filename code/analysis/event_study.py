# -*- coding: utf-8 -*-
"""
事件研究 / 中断时间序列（ITS）：2026上半年七项审计冲击对 star 采纳增速的因果效应
数据：star_history.json（每日star） + forks_timestamps.json（每日fork）
冲击点：2026-02-03（Koi Security 首披 ClawHavoc，冲击簇首个事件）
       2026-03-24（Silverfort 排名可操纵性披露，第二断点）
方法：中断时间序列（level + slope change）+ 安慰剂断点检验
"""
import json, os, datetime, statistics

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

def agg_daily(sh):
    """全生态每日 star 总量"""
    byday = {}
    for k, hist in sh.items():
        for d, c in daily_series(hist):
            byday[d] = byday.get(d, 0) + c
    return sorted(byday.items())

def fork_daily(forks):
    """全生态每日 fork 数"""
    byday = {}
    for k, flist in forks.items():
        if not isinstance(flist, list):
            continue
        for f in flist:
            d = f.get("created_at", "")[:10]
            if d:
                byday[d] = byday.get(d, 0) + 1
    return sorted(byday.items())

def seg_mean(daily, start, end):
    """[start, end) 区间日均值"""
    vals = [c for d, c in daily if start <= d < end]
    return statistics.mean(vals) if vals else None

def its(daily, break1="2026-02-03", break2="2026-03-24"):
    """分段日均值（中断时间序列简化版）"""
    out = {}
    # 冲击簇前：2025-10-01 至 2026-02-02
    out["pre_shock"] = seg_mean(daily, "2025-10-01", break1)
    # 冲击簇：2026-02-03 至 2026-03-23
    out["shock_cluster"] = seg_mean(daily, break1, break2)
    # 第二断点后：2026-03-24 至 2026-06-30
    out["post_break2"] = seg_mean(daily, break2, "2026-07-01")
    # 尾部：2026-07-01 至 2026-10-05
    out["tail"] = seg_mean(daily, "2026-07-01", "2026-10-05")
    return out

def placebo(daily, shifts):
    """安慰剂：把 break1 平移到其他日期，看效应是否仅为随机"""
    res = []
    for label, b1 in shifts:
        b2 = None
        # 保持窗口结构（b2 = b1 + 49天）
        d1 = datetime.date.fromisoformat(b1)
        d2 = d1 + datetime.timedelta(days=49)
        b2 = d2.isoformat()
        pre = seg_mean(daily, (d1 - datetime.timedelta(days=125)).isoformat(), b1)
        post = seg_mean(daily, b1, b2)
        if pre and post:
            res.append((label, pre, post, post - pre))
    return res

def main():
    sh = load("star_history.json")
    forks = load("forks_timestamps.json")
    meta = load("repos_meta.json")

    print("=" * 70)
    print("事件研究：2026上半年审计冲击对 star/fork 采纳增速的效应")
    print("=" * 70)

    daily = agg_daily(sh)
    print(f"\n每日 star 序列：{len(daily)} 天，从 {daily[0][0]} 到 {daily[-1][0]}")

    # 官方仓库 vs 全体
    o_hist = sh.get("anthropics/skills", [])
    o_daily = daily_series(o_hist)

    print(f"\n【star 日均新增】")
    print(f"{'区间':<22}{'全生态':>10}{'anthropics/skills':>18}")
    segs = [
        ("冲击前(10-01~02-02)", "2025-10-01", "2026-02-03"),
        ("冲击簇(02-03~03-23)", "2026-02-03", "2026-03-24"),
        ("第二断点后(03-24~06-30)", "2026-03-24", "2026-07-01"),
        ("尾部(07-01~10-05)", "2026-07-01", "2026-10-05"),
    ]
    for name, s, e in segs:
        a = seg_mean(daily, s, e)
        b = seg_mean(o_daily, s, e)
        a_s = f"{a:,.0f}" if a else "n/a"
        b_s = f"{b:,.0f}" if b else "n/a"
        print(f"{name:<22}{a_s:>10}{b_s:>18}")

    # fork 事件研究
    fdaily = fork_daily(forks)
    print(f"\n【fork 日均新增】")
    for name, s, e in segs:
        a = seg_mean(fdaily, s, e)
        a_s = f"{a:,.0f}" if a else "n/a"
        print(f"{name:<22}{a_s:>10}")

    # 冲击效应（ITS）
    print(f"\n【中断时间序列（level change）】")
    its_star = its(daily)
    pre = its_star["pre_shock"] or 0
    cluster = its_star["shock_cluster"] or 0
    post2 = its_star["post_break2"] or 0
    tail = its_star["tail"] or 0
    print(f"  star 冲击前均值: {pre:,.0f}/天")
    print(f"  star 冲击簇均值: {cluster:,.0f}/天  (相对冲击前 {((cluster-pre)/pre)*100:+.1f}%)")
    print(f"  star 第二断点后: {post2:,.0f}/天  (相对冲击前 {((post2-pre)/pre)*100:+.1f}%)")
    print(f"  star 尾部: {tail:,.0f}/天  (相对冲击前 {((tail-pre)/pre)*100:+.1f}%)")

    # 安慰剂检验
    print(f"\n【安慰剂断点检验（star）】")
    shifts = [
        ("伪断点A(2025-11-15)", "2025-11-15"),
        ("伪断点B(2025-12-15)", "2025-12-15"),
        ("伪断点C(2026-01-15)", "2026-01-15"),
        ("真断点(2026-02-03)", "2026-02-03"),
    ]
    for label, pre, post, diff in placebo(daily, shifts):
        print(f"  {label:<24} 前={pre:,.0f} 后={post:,.0f}  Δ={diff:+,.0f}")

    # 保存
    res = {
        "its_star": its_star,
        "its_fork": its(daily=fdaily),
        "placebo_star": placebo(daily, shifts),
    }
    os.makedirs(os.path.join(DATA, "results"), exist_ok=True)
    json.dump(res, open(os.path.join(DATA, "results", "event_study.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"\n  结果已保存 data/results/event_study.json")
    print("=" * 70)

if __name__ == "__main__":
    main()
