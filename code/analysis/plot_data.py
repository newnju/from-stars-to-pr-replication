# -*- coding: utf-8 -*-
"""
plot_compare.py —— 用 seaborn 与 plotnine 两种风格重画论文 4 张统计图
输出到 data/results/figs/seaborn/ 与 data/results/figs/plotnine/，供人工对比。
数据口径与 its_regression.py / did_synthetic.py 完全一致，仅重绘。

四张图：
  fig_seaborn / fig_plotnine 目录下：
    star_its.png        图7 全生态每日新增 star（7日移动平均）+ 审计断点
    hollowing.png       图8 star 浅层 vs fork 深层 增速脱钩
    theta_D_dist.png    图9 贡献门槛 θ(D) 对数分布
    scm_gap.png         图10 合成控制 实际 vs 反事实
"""
import json, os, datetime
import numpy as np

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
FIGROOT = os.path.join(DATA, "results", "figs")


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


def prep_data():
    """返回所有绘图所需数据。"""
    sh = load("star_history.json")
    forks = load("forks_timestamps.json")
    clean = load(os.path.join(DATA, "results", "clean_sample.json"))
    clean_repos = set(clean["clean_repos"])

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

    sdaily = agg_daily(clean_repos)          # star 每日总量
    fddaily = fork_daily(clean_repos)        # fork 每日总量
    o_daily = daily_series(sh.get("anthropics/skills", []))  # 官方仓库

    # 7日移动平均
    def ma7(pairs):
        dates = [datetime.date.fromisoformat(d) for d, c in pairs]
        vals = [c for d, c in pairs]
        m = np.convolve(vals, np.ones(7) / 7, mode="valid")
        return dates[6:], m

    s_dates, s_ma = ma7(sdaily)
    f_dates, f_ma = ma7(fddaily)

    # θ(D) 贡献门槛
    def theta_D_all():
        vals = []
        for k in clean_repos:
            hist = sh.get(k)
            if not hist or k not in forks or not isinstance(forks[k], list):
                continue
            ds = daily_series(hist)
            cum, run = [], 0
            for d, c in ds:
                run += c
                cum.append((d, run))
            for f in forks[k]:
                fd = f.get("created_at", "")[:10]
                best = None
                for d, v in cum:
                    if d <= fd:
                        best = v
                    else:
                        break
                if best is not None:
                    vals.append(best)
        return vals

    tvals = theta_D_all()

    # SCM（复刻 did_synthetic.py 的合成控制轨迹）
    def weekly_series(hist, origin="2025-10-01"):
        daily = dict(daily_series(hist))
        o = datetime.date.fromisoformat(origin)
        out = {}
        for d, c in daily.items():
            dd = datetime.date.fromisoformat(d)
            wi = (dd - o).days // 7
            out[wi] = out.get(wi, 0) + c
        return out

    treated_repo = "anthropics/skills"
    pre_start_wi = 0
    pre_end_wi = (datetime.date.fromisoformat("2026-03-24") - datetime.date.fromisoformat("2025-10-01")).days // 7 - 1
    post_end_wi = (datetime.date.fromisoformat("2026-10-05") - datetime.date.fromisoformat("2025-10-01")).days // 7

    def repo_weekly(k):
        return weekly_series(sh.get(k, []))

    yt = repo_weekly(treated_repo)
    donors = []
    for k in clean_repos:
        if k == treated_repo:
            continue
        wk = repo_weekly(k)
        pre = [wk.get(wi, 0.0) for wi in range(pre_start_wi, pre_end_wi + 1)]
        if len(pre) > 0 and sum(1 for v in pre if v == 0) / len(pre) < 0.5:
            donors.append(k)
    donors = donors[:120]
    J = len(donors)
    T0 = pre_end_wi - pre_start_wi + 1
    Y_pre_treat = np.array([yt.get(wi, 0.0) for wi in range(pre_start_wi, pre_end_wi + 1)])
    D_pre = np.array([[repo_weekly(k).get(wi, 0.0) for wi in range(pre_start_wi, pre_end_wi + 1)] for k in donors])

    from scipy.optimize import minimize
    def obj(w):
        return np.sum((Y_pre_treat - D_pre.T @ w) ** 2)
    cons = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
    bounds = [(0, 1)] * J
    w0 = np.full(J, 1.0 / J)
    res = minimize(obj, w0, method="SLSQP", bounds=bounds, constraints=cons)
    w = res.x
    w = np.where(w < 1e-4, 0, w)
    w = w / w.sum() if w.sum() > 0 else w

    def synth_at(wi):
        return sum(w[j] * repo_weekly(donors[j]).get(wi, 0.0) for j in range(J))

    weeks_idx = list(range(pre_start_wi, post_end_wi + 1))
    scm_dates = [datetime.date.fromisoformat("2025-10-01") + datetime.timedelta(weeks=wi) for wi in weeks_idx]
    scm_actual = [yt.get(wi, 0.0) for wi in weeks_idx]
    scm_synth = [synth_at(wi) for wi in weeks_idx]
    pre_rmse = float(np.sqrt(np.mean((Y_pre_treat - D_pre.T @ w) ** 2)))
    post_gap = np.array(scm_actual[T0 + 1:]) - np.array(scm_synth[T0 + 1:])
    post_rmse = float(np.sqrt(np.mean(post_gap ** 2)))
    ratio = post_rmse / pre_rmse if pre_rmse > 0 else None

    return {
        "s_dates": s_dates, "s_ma": s_ma,
        "f_dates": f_dates, "f_ma": f_ma,
        "o_daily": o_daily,
        "tvals": tvals,
        "scm_dates": scm_dates, "scm_actual": scm_actual, "scm_synth": scm_synth,
        "pre_rmse": pre_rmse, "post_rmse": post_rmse, "ratio": ratio,
    }
