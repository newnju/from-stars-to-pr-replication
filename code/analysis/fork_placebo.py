# -*- coding: utf-8 -*-
"""
fork_placebo.py — 对 fork（贡献行为）增速做与 star 相同的置换安慰剂检验，
判断贡献行为加速是否真断点特异，而非世俗增长。
"""
import json, os, datetime, random, statistics
import numpy as np

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
RESULTS = os.path.join(DATA, "results")

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
    return X, y

def main():
    forks = load("forks_timestamps.json")
    clean = load(os.path.join(RESULTS, "clean_sample.json"))
    clean_repos = set(clean["clean_repos"])

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

    fdaily = fork_daily(clean_repos)
    print(f"fork 每日序列: {len(fdaily)} 天，{fdaily[0][0]} 到 {fdaily[-1][0]}")

    def its_trend2(daily, b1, b2):
        X, y = build_its(daily, b1, b2)
        import statsmodels.api as sm
        m = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 7})
        return float(m.params[5]), float(m.pvalues[5])

    true_t2, true_p = its_trend2(fdaily, "2026-02-03", "2026-03-24")
    print(f"真实断点 fork trend2 = {true_t2:.3f}  (p={true_p:.3e})")

    rng = random.Random(42)
    d0 = datetime.date(2026, 1, 1)   # fork 数据最早 2026-09-14 之前？实际 fork 最早 2026-09-14 不对——用较早窗口
    # 注意：fork 事件最早出现在 2025 年末，数据窗口有限，伪断点范围设 2025-12-01 ~ 2026-08-01
    d0 = datetime.date(2025, 12, 1)
    d1 = datetime.date(2026, 8, 1)
    span = (d1 - d0).days
    placebo = []
    n_placebo = 200
    for _ in range(n_placebo):
        b1 = d0 + datetime.timedelta(days=rng.randint(0, span))
        b2 = b1 + datetime.timedelta(days=49)
        t2, p2 = its_trend2(fdaily, b1.isoformat(), b2.isoformat())
        placebo.append(t2)
    placebo = np.array(placebo)
    # fork trend2 为正（加速），p = P(placebo >= true) 单侧
    p_perm = float(np.mean(placebo >= true_t2))
    print(f"安慰剂 fork trend2: mean={placebo.mean():.3f}  sd={placebo.std():.3f}  min={placebo.min():.3f}  max={placebo.max():.3f}")
    print(f"置换 p 值（单侧，placebo >= true）: {p_perm:.3f}")
    print(f"真实 trend2 在安慰剂分布中的分位: {float(np.mean(placebo < true_t2))*100:.1f}%")

    out = {
        "true_fork_trend2": true_t2, "true_p": true_p,
        "n_placebo": n_placebo,
        "placebo_mean": float(placebo.mean()), "placebo_sd": float(placebo.std()),
        "placebo_min": float(placebo.min()), "placebo_max": float(placebo.max()),
        "perm_p": p_perm, "true_percentile": float(np.mean(placebo < true_t2)),
    }
    os.makedirs(RESULTS, exist_ok=True)
    json.dump(out, open(os.path.join(RESULTS, "fork_placebo.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("  结果已保存 data/results/fork_placebo.json")

if __name__ == "__main__":
    main()
