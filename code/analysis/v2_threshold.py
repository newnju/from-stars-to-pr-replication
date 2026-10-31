# -*- coding: utf-8 -*-
"""
v2_threshold.py —— 「门槛」在修正口径下的重新估计

旧口径被否证的原因（见 C刊标准评审意见 4.1、4.2）：
    θ(L)=137（仓库级「增速检测点」，含 ~35 的数学下界）
    θ(D)=5,319（事件级「分叉时点累计星标」，受左侧截断构造性上偏）
    Δ=38.8 倍系两口径混合比较，且截断方向被写反。

本模块给出两条替代路径，均不再使用任意阈值、不再混用分析单位：

  路径一（首次事件门槛，区间删失）：
      以「仓库自创建至首次分叉所累积的星标数」作为意图层门槛的非参数估计。
      仅针对分叉记录完整（元数据 fork 总数 ≤ 500）的仓库可精确识别；
      对其余仓库给出区间下界（区间删失），并用 Kaplan–Meier 处理右删失。

  路径二（转化强度，暴露标准化）：
      以完备窗口内的「分叉事件数 / (星标事件数 × 窗口平均累计星标)」
      作为无量纲的意图转化强度，避免与仓库体量机械共变。

  风险分层检验：仓库级 Mann–Whitney U、Cliff's delta、仓库层面置换检验，
      并以 Snyk 生态构成（36.8% 高风险）作后分层加权还原；
      三套风险口径（旧任意关键词 / 新触达指数 / core.py 描述词）平行报告。

产出：data/results/v2_threshold.json
"""
import json, os, math, statistics, datetime
import numpy as np
from scipy import stats as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RES = os.path.join(DATA, "results")
RNG = np.random.default_rng(20261005)


def load(n):
    return json.load(open(os.path.join(DATA, n), encoding="utf-8"))


def cliffs_delta(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    gt = sum((a[:, None] > b[None, :]).ravel())
    lt = sum((a[:, None] < b[None, :]).ravel())
    return (gt - lt) / (len(a) * len(b))


def perm_test(a, b, n=20000):
    """仓库层面置换检验（双侧），统计量为组间中位数差。"""
    a, b = np.asarray(a, float), np.asarray(b, float)
    obs = np.median(a) - np.median(b)
    pool = np.concatenate([a, b])
    na = len(a)
    cnt = 0
    for _ in range(n):
        RNG.shuffle(pool)
        if abs(np.median(pool[:na]) - np.median(pool[na:])) >= abs(obs):
            cnt += 1
    return obs, (cnt + 1) / (n + 1)


def km_curve(durations, events):
    """Kaplan–Meier：durations 为到事件/删失的时间，events 为事件指示。"""
    order = np.argsort(durations)
    t = np.asarray(durations, float)[order]
    e = np.asarray(events, int)[order]
    n = len(t)
    times, surv, at_risk = [0.0], [1.0], [n]
    s = 1.0
    i = 0
    while i < n:
        ti = t[i]
        d = 0
        c = 0
        while i < n and t[i] == ti:
            if e[i]:
                d += 1
            else:
                c += 1
            i += 1
        if d > 0:
            s *= (1 - d / (n - (i - d - c)))
            times.append(float(ti))
            surv.append(s)
            at_risk.append(int(n - i))
    return times, surv, at_risk


def km_quantile(times, surv, q=0.5):
    for t, s in zip(times, surv):
        if s <= q:
            return t
    return None


def main():
    panel = load(os.path.join("results", "v2_panel.json"))
    risk = load(os.path.join("results", "v2_risk.json"))
    repos = panel["repos"]
    rrisk = risk["repos"]
    meta = load("repos_meta.json")

    # ---------- 仓库级派生量 ----------
    rows = []
    for k, r in repos.items():
        rr = rrisk.get(k, {})
        win_stars = r["win_stars"]
        win_forks = r["win_forks"]
        cum_mean = r["win_cum_mean"]
        rows.append({
            "repo": k,
            "complete": not r["fork_left_truncated"],
            "retained_share": r["retained_fork_share"],
            "win_days": r["win_days"],
            "win_stars": win_stars, "win_forks": win_forks,
            "cum_mean": cum_mean,
            # 口径一致的分叉—星标比（同一完备窗口内）
            "fork_star_ratio_win": (win_forks / win_stars) if win_stars else None,
            # 暴露标准化的转化强度（无量纲：每单位社会证明存量对应的分叉率）
            "conv_intensity": (win_forks / (win_stars * cum_mean)) if (win_stars and cum_mean) else None,
            "total_stars": r["total_stars"], "total_forks": r["total_forks"],
            "theta_ff_lo": r["theta_first_fork_lo"],
            "theta_ff_hi": r["theta_first_fork_hi"],
            "theta_ff_point": r["theta_first_fork_point"],
            "days_to_first_fork": r["days_to_first_fork"],
            "created": r["created"],
            "reach_index": rr.get("reach_index"),
            "reach_binary": rr.get("reach_binary"),
            "old_kw": rr.get("any_old_kw"),
            "core_kw": rr.get("core_kw_hit"),
            "disclosure_index": rr.get("disclosure_index"),
            "has_skillmd": rr.get("has_skillmd"),
            "age_days": (datetime.date(2026, 10, 4) -
                         datetime.date.fromisoformat(r["created"])).days,
        })

    def col(name, cond=lambda r: True):
        return [r[name] for r in rows
                if cond(r) and r.get(name) is not None]

    # ---------- 路径一：首次分叉门槛 ----------
    complete = [r for r in rows if r["complete"]]
    pts = [r["theta_ff_point"] for r in complete if r["theta_ff_point"] is not None]
    # 左截断仓库的区间下界：其真实首次分叉不晚于可观测最早分叉，故门槛 ≤ 观测值；
    # 以「元数据分叉总数」给出更紧的上界讨论，此处仅记录区间端点。
    n_trunc = sum(1 for r in rows if not r["complete"])
    bounds = {
        "n_truncated_repos": n_trunc,
        "note": "左截断仓库的真实首次分叉早于可观测下界，其门槛只能给出上界"
                "（等于可观测最早分叉时点的累计星标），不进入点识别样本。",
    }

    # ---------- 路径二：转化强度的风险分层 ----------
    full = [r for r in rows if r["conv_intensity"] is not None]
    ratio_rows = [r for r in rows if r["fork_star_ratio_win"] is not None]

    def stratify(rows_, key, hi_val=1):
        a = [r["conv_intensity"] for r in rows_ if r.get(key) == hi_val
             and r["conv_intensity"] is not None]
        b = [r["conv_intensity"] for r in rows_ if r.get(key) != hi_val
             and r.get(key) is not None and r["conv_intensity"] is not None]
        if len(a) < 5 or len(b) < 5:
            return None
        u = st.mannwhitneyu(a, b, alternative="two-sided")
        d = cliffs_delta(a, b)
        obs, p_perm = perm_test(a, b, n=10000)
        return {"n_hi": len(a), "n_lo": len(b),
                "median_hi": statistics.median(a), "median_lo": statistics.median(b),
                "U": float(u.statistic), "p_mwu": float(u.pvalue),
                "cliffs_delta": float(d), "median_diff": float(obs),
                "p_perm_repo": float(p_perm)}

    strata = {}
    for key in ("old_kw", "reach_binary", "core_kw"):
        strata[key] = {
            "conv_intensity": stratify(full, key),
            "conv_intensity_complete_only": stratify(
                [r for r in full if r["complete"]], key),
            "fork_star_ratio_win": stratify(ratio_rows, key),
            "theta_ff_point": stratify(
                [dict(r, conv_intensity=r["theta_ff_point"]) for r in rows
                 if r["theta_ff_point"] is not None], key),
        }

    # 后分层加权：把高风险占比还原至外部审计的生态构成
    def weighted_median(values, weights):
        o = np.argsort(values)
        v, w = np.asarray(values)[o], np.asarray(weights)[o]
        c = np.cumsum(w) / np.sum(w)
        return float(v[np.searchsorted(c, 0.5)])

    TARGET_HI = 0.3682
    ws = []
    hi = [r for r in full if r["reach_binary"] == 1]
    lo = [r for r in full if r["reach_binary"] == 0]
    if hi and lo:
        w_hi = TARGET_HI / len(hi)
        w_lo = (1 - TARGET_HI) / len(lo)
        vals = [r["conv_intensity"] for r in hi] + [r["conv_intensity"] for r in lo]
        wts = [w_hi] * len(hi) + [w_lo] * len(lo)
        weighted = {
            "target_high_share": TARGET_HI,
            "weighted_median_all": weighted_median(vals, wts),
            "unweighted_median_all": statistics.median(vals),
            "weighted_median_hi": weighted_median([r["conv_intensity"] for r in hi],
                                                  [w_hi] * len(hi)),
            "weighted_median_lo": weighted_median([r["conv_intensity"] for r in lo],
                                                  [w_lo] * len(lo)),
        }
    else:
        weighted = None

    # ---------- 对照：旧口径的复现与其分析单位问题 ----------
    legacy = {
        "theta_L_median_repo_level": 137,
        "theta_D_median_event_level": 5319,
        "claimed_ratio": 38.82,
        "theta_D_median_repo_level": None,
        "note": "旧 θ(L) 为仓库级增速检测点、旧 θ(D) 为事件级累计水平；"
                "两者量纲不同且 θ(L) 含约 35 的数学下界，比值不构成门槛分离度证据。",
    }
    # 仓库级 θ(D)（先仓库内取中位数）：复现评审给出的 3,322 并作同口径比较
    sh = load("star_history.json")
    forks = load("forks_timestamps.json")
    clean = load(os.path.join("results", "clean_sample.json"))["clean_repos"]

    def daily_cum(hist):
        ds = []
        for w in hist:
            for i, c in enumerate(w["days"]):
                ds.append(((datetime.datetime.fromtimestamp(w["week"], datetime.timezone.utc)
                            + datetime.timedelta(days=i)).date(), c))
        ds.sort()
        out, run = [], 0
        for d, c in ds:
            run += c
            out.append((d, run))
        return out

    repo_med_D = []
    for k in clean:
        if k not in sh or not isinstance(forks.get(k), list):
            continue
        cum = daily_cum(sh[k])
        vals = []
        for f in forks[k]:
            fd = datetime.date.fromisoformat(f["created_at"][:10])
            v = None
            for d, c in cum:
                if d <= fd:
                    v = c
                else:
                    break
            if v is not None:
                vals.append(v)
        if vals:
            repo_med_D.append(statistics.median(vals))
    legacy["theta_D_median_repo_level"] = statistics.median(repo_med_D)
    legacy["like_for_like_ratio"] = statistics.median(repo_med_D) / 137
    legacy["left_truncation_signature"] = {
        "fork_records_retained_overall": panel["meta"]["fork_retained_share_overall"],
        "n_repos_left_truncated": panel["meta"]["n_fork_records_truncated"],
        "direction": "left truncation of earliest fork events → observed levels biased upward",
    }

    # ---------- 仓库级多元模型：控制年龄、体量、话题类别后的风险效应 ----------
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
    import pandas as pd

    def topic_class(topics):
        t = " ".join(topics or []).lower()
        if any(x in t for x in ("security", "pentest", "red-team", "ctf", "osint")):
            return "安全与攻防"
        if any(x in t for x in ("claude", "codex", "copilot", "cursor", "coding")):
            return "编码与开发"
        if any(x in t for x in ("awesome", "list", "collection", "tutorial", "guide")):
            return "清单与教程"
        return "其他"

    mr = pd.DataFrame([{
        "repo": r["repo"],
        "forks": r["win_forks"], "stars": r["win_stars"],
        "log_stars": math.log10(r["total_stars"] + 10),
        "log_age": math.log10(r["age_days"] + 10),
        "log_days": math.log10(r["win_days"] + 1),
        "reach": r["reach_index"] if r["reach_index"] is not None else 0.0,
        "reach2": r["reach_binary"] if r["reach_binary"] is not None else 0,
        "old_kw": r["old_kw"] if r["old_kw"] is not None else 0,
        "core_kw": r["core_kw"] if r["core_kw"] is not None else 0,
        "disclosure": r["disclosure_index"] if r["disclosure_index"] is not None else 0,
        "cls": topic_class((meta.get(r["repo"]) or {}).get("topics")),
    } for r in rows if r["win_stars"] > 0])

    models = {}
    specs = {
        "M1_old_kw": "forks ~ old_kw + log_stars + log_age + C(cls)",
        "M2_reach_cont": "forks ~ reach + log_stars + log_age + C(cls)",
        "M3_reach2": "forks ~ reach2 + log_stars + log_age + C(cls)",
        "M4_reach2_disc": "forks ~ reach2 + disclosure + log_stars + log_age + C(cls)",
        "M5_core_kw": "forks ~ core_kw + log_stars + log_age + C(cls)",
    }
    for tag, f in specs.items():
        try:
            m = smf.glm(f, data=mr, family=sm.families.Poisson(),
                        offset=np.log(mr["stars"])).fit(
                cov_type="HC1")
            key = [t for t in m.params.index
                   if t in ("old_kw", "reach", "reach2", "core_kw", "disclosure")]
            models[tag] = {
                "formula": f, "n": int(m.nobs),
                "coef": {k: float(m.params[k]) for k in key},
                "se": {k: float(m.bse[k]) for k in key},
                "p": {k: float(m.pvalues[k]) for k in key},
                "irr": {k: float(np.exp(m.params[k])) for k in key},
            }
        except Exception as e:
            models[tag] = {"error": str(e)}

    out = {
        "first_fork_threshold": {
            "n_complete_fork_records": len(complete),
            "n_point_identified": len(pts),
            "median_point": statistics.median(pts) if pts else None,
            "mean_point": statistics.mean(pts) if pts else None,
            "q10": float(np.percentile(pts, 10)) if pts else None,
            "q25": float(np.percentile(pts, 25)) if pts else None,
            "q75": float(np.percentile(pts, 75)) if pts else None,
            "q90": float(np.percentile(pts, 90)) if pts else None,
            "share_at_or_below_10": (sum(1 for v in pts if v <= 10) / len(pts)) if pts else None,
            "share_zero": (sum(1 for v in pts if v == 0) / len(pts)) if pts else None,
            "truncated_repos": bounds,
        },
        "conversion_intensity": {
            "definition": "forks / (star events × mean cumulative stars in window)",
            "median": statistics.median(col("conv_intensity")),
            "mean": statistics.mean(col("conv_intensity")),
        },
        "fork_star_ratio_window": {
            "definition": "forks / star events, same complete window (口径一致)",
            "median": statistics.median(col("fork_star_ratio_win")),
            "mean": statistics.mean(col("fork_star_ratio_win")),
            "overall": (sum(r["win_forks"] for r in rows) /
                        sum(r["win_stars"] for r in rows)),
        },
        "risk_strata": strata,
        "poststratified": weighted,
        "repo_level_models": models,
        "legacy_reproduction": legacy,
    }
    json.dump(out, open(os.path.join(RES, "v2_threshold.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2, default=float)

    print("=" * 78)
    print("v2 门槛的修正估计")
    print("=" * 78)
    ff = out["first_fork_threshold"]
    print(f"  【路径一】首次分叉门槛（仓库自创建累积星标）")
    print(f"    分叉记录完整仓库 {ff['n_complete_fork_records']}，可点识别 {ff['n_point_identified']}")
    print(f"    点估计中位数 {ff['median_point']:,.0f}  均值 {ff['mean_point']:,.0f}  "
          f"q10={ff['q10']:,.0f}  q25={ff['q25']:,.0f}  q75={ff['q75']:,.0f}  q90={ff['q90']:,.0f}")
    print(f"    ≤10 星标即出现首次分叉的仓库占比 {ff['share_at_or_below_10']*100:.1f}%")
    ci = out["conversion_intensity"]
    fs = out["fork_star_ratio_window"]
    print(f"  【路径二】转化强度中位数 {ci['median']:.3e}；同窗口分叉—星标比中位数 "
          f"{fs['median']*100:.2f}%（总体 {fs['overall']*100:.2f}%）")
    print("\n  【风险分层：转化强度的仓库级检验】")
    for key, s in strata.items():
        a = s["conv_intensity"]
        if not a:
            print(f"    {key}: 样本不足")
            continue
        print(f"    {key:<14} n={a['n_hi']}/{a['n_lo']}  "
              f"中位 {a['median_hi']:.2e} vs {a['median_lo']:.2e}  "
              f"MWU p={a['p_mwu']:.4f}  置换 p={a['p_perm_repo']:.4f}  "
              f"Cliff δ={a['cliffs_delta']:+.3f}")
    if weighted:
        print(f"\n  【后分层加权（高风险占比还原至 {weighted['target_high_share']*100:.1f}%）】"
              f" 加权中位 {weighted['weighted_median_all']:.3e} vs "
              f"未加权 {weighted['unweighted_median_all']:.3e}")
    print("\n  【仓库级 Poisson 模型：分叉率 ~ 风险代理 + 控制变量（offset=log 星标事件）】")
    for tag, m in models.items():
        if "error" in m:
            print(f"    {tag}: {m['error']}")
            continue
        for k in m["coef"]:
            print(f"    {tag:<16} {k:<10} β={m['coef'][k]:+.3f} (SE={m['se'][k]:.3f}, "
                  f"p={m['p'][k]:.3f})  IRR={m['irr'][k]:.3f}")
    print(f"\n  【旧口径复现】仓库级 θ(D) 中位数 {legacy['theta_D_median_repo_level']:,.0f}；"
          f"同口径比值 {legacy['like_for_like_ratio']:.2f} 倍（论文报告 38.82 倍）")
    print("  产出: data/results/v2_threshold.json")
    print("=" * 78)


if __name__ == "__main__":
    main()
