# -*- coding: utf-8 -*-
"""
did_final.py — 与论文口径一致的交错 DID + 合成控制（危害导向风险分层）
使用 risk_strata.py 的危害导向分类（DESTRUCTIVE=126 / BENIGN=77），
与 content5.js 第三节风险分层口径完全一致。

A. 交错 DID：处理=含高风险能力文本的仓库(DESTRUCTIVE)，对照=BENIGN
   周度新增星标 log1p，双向固定效应(仓库FE+周FE)+处理×断点后交互，仓库聚类SE
B. 合成控制：处理=anthropics/skills，捐赠池=干净样本其余仓库
   断点=2026-03-24(Silverfort)，报告 pre/post RMSPE 与缺口
"""
import json, os, datetime
import numpy as np

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
SKILLDIR = os.path.join(DATA, "skillmd")

# 危害导向（与 risk_strata.py 完全一致）
HIGH = ["credential", "password", "api_key", "api key", "access token",
        "private key", "reverse shell", "backdoor", "keylogger", "exfiltrat",
        "rm -rf", "drop table", "drop database", "sudo ", "chmod 777",
        "session hijack", "phish", "decrypt", "bypass"]

def load(name):
    return json.load(open(os.path.join(DATA, name), encoding="utf-8"))

def safe_fn(name):
    return name.replace("/", "__").replace("\\", "__") + ".json"

def daily_series(hist):
    out = []
    for w in hist:
        base = datetime.datetime.fromtimestamp(w["week"], datetime.timezone.utc)
        for i, c in enumerate(w["days"]):
            out.append(((base + datetime.timedelta(days=i)).strftime("%Y-%m-%d"), c))
    out.sort()
    return out

def weekly_series(hist, origin="2025-10-01", n_weeks=53):
    daily = dict(daily_series(hist))
    o = datetime.date.fromisoformat(origin)
    out = {}
    for d, c in daily.items():
        dd = datetime.date.fromisoformat(d)
        wi = (dd - o).days // 7
        out[wi] = out.get(wi, 0) + c
    return sorted(out.items())

def repo_risk(k):
    """危害导向：h>=1 → DESTRUCTIVE(1)，否则 BENIGN(0)"""
    fp = os.path.join(SKILLDIR, safe_fn(k))
    h = 0
    if os.path.exists(fp):
        try:
            data = json.load(open(fp, encoding="utf-8"))
        except Exception:
            data = []
        if isinstance(data, dict):
            data = []
        for s in data:
            c = (s.get("content", "") or "").lower()
            h += sum(1 for kw in HIGH if kw in c)
    return 1 if h >= 1 else 0

def main():
    sh = load("star_history.json")
    clean = load(os.path.join(DATA, "results", "clean_sample.json"))
    clean_repos = list(clean["clean_repos"])

    treated = [k for k in clean_repos if repo_risk(k) == 1]
    control = [k for k in clean_repos if repo_risk(k) == 0]
    print(f"DESTRUCTIVE(处理) n={len(treated)}  BENIGN(对照) n={len(control)}")

    BREAK_WEEK = (datetime.date.fromisoformat("2026-02-03") - datetime.date.fromisoformat("2025-10-01")).days // 7

    panel = []
    repo_id = {}
    for k in treated + control:
        ws = weekly_series(sh.get(k, []))
        if not ws:
            continue
        rid = len(repo_id)
        repo_id[k] = rid
        treat = 1 if k in treated else 0
        for wi, v in ws:
            post = 1 if wi >= BREAK_WEEK else 0
            panel.append((rid, wi, treat, post, np.log1p(v)))

    panel = np.array(panel, dtype=float)
    n_obs = panel.shape[0]
    n_repo = len(repo_id)
    weeks = sorted(set(int(w) for w in panel[:, 1]))
    n_week = len(weeks)

    n_cols = 1 + (n_repo - 1) + (n_week - 1) + 1
    X = np.zeros((n_obs, n_cols))
    y = panel[:, 4]
    X[:, 0] = 1.0
    col = 1
    for r in range(1, n_repo):
        X[:, col] = (panel[:, 0] == r).astype(float); col += 1
    for i, w in enumerate(weeks[1:]):
        X[:, col] = (panel[:, 1] == w).astype(float); col += 1
    X[:, col] = (panel[:, 2] * panel[:, 3])

    import statsmodels.api as sm
    model = sm.OLS(y, X).fit(cov_type="cluster", cov_kwds={"groups": panel[:, 0].astype(int)})
    did_coef = float(model.params[col])
    did_se = float(model.bse[col])
    did_p = float(model.pvalues[col])

    treat_pre = np.mean(panel[(panel[:, 2] == 1) & (panel[:, 3] == 0), 4])
    treat_post = np.mean(panel[(panel[:, 2] == 1) & (panel[:, 3] == 1), 4])
    ctrl_pre = np.mean(panel[(panel[:, 2] == 0) & (panel[:, 3] == 0), 4])
    ctrl_post = np.mean(panel[(panel[:, 2] == 0) & (panel[:, 3] == 1), 4])
    did_means = float((treat_post - treat_pre) - (ctrl_post - ctrl_pre))

    print(f"n_repo={n_repo} n_obs={n_obs} n_week={n_week} break_week={BREAK_WEEK}")
    print(f"treat×post coef={did_coef:+.4f} SE={did_se:.4f} p={did_p:.3e}")
    print(f"DID in means={did_means:+.4f}")
    print(f"处理 pre={treat_pre:.3f} post={treat_post:.3f} | 对照 pre={ctrl_pre:.3f} post={ctrl_post:.3f}")

    # 合成控制
    treated_repo = "anthropics/skills"
    pre_start_wi = 0
    pre_end_wi = (datetime.date.fromisoformat("2026-03-24") - datetime.date.fromisoformat("2025-10-01")).days // 7 - 1
    post_end_wi = (datetime.date.fromisoformat("2026-10-05") - datetime.date.fromisoformat("2025-10-01")).days // 7

    def repo_weekly(k):
        return dict(weekly_series(sh.get(k, [])))

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

    post = [yt.get(wi, 0.0) for wi in range(pre_start_wi, post_end_wi + 1)]
    synth = [synth_at(wi) for wi in range(pre_start_wi, post_end_wi + 1)]
    pre_rmse = np.sqrt(np.mean((Y_pre_treat - D_pre.T @ w) ** 2))
    post_gap = np.array(post[T0 + 1:]) - np.array(synth[T0 + 1:])
    post_rmse = np.sqrt(np.mean(post_gap ** 2))
    ratio = post_rmse / pre_rmse if pre_rmse > 0 else None

    print(f"\nSCM: donors={J} positive_weights={int(np.sum(w>1e-4))}")
    print(f"pre_rmse={pre_rmse:.2f} post_rmse={post_rmse:.2f} ratio={ratio:.2f}")
    print(f"mean_gap_post={np.mean(post_gap):+.2f} total_gap={np.sum(post_gap):+.0f}")

    out = {
        "A_did": {
            "risk_classification": "harm-oriented (DESTRUCTIVE/BENIGN)",
            "n_destructive": len(treated), "n_benign": len(control),
            "n_repo": n_repo, "n_obs": int(n_obs), "n_week": n_week,
            "break_week": BREAK_WEEK, "break_date": "2026-02-03",
            "outcome": "log1p(weekly_new_stars)",
            "treat_x_post_coef": did_coef, "treat_x_post_se": did_se, "treat_x_post_p": did_p,
            "r2": float(model.rsquared),
            "did_in_means": did_means,
            "treat_pre_mean": treat_pre, "treat_post_mean": treat_post,
            "ctrl_pre_mean": ctrl_pre, "ctrl_post_mean": ctrl_post,
        },
        "B_scm": {
            "treated": treated_repo, "n_donors": J,
            "n_positive_weights": int(np.sum(w > 1e-4)),
            "pre_period": ["2025-10-01", "2026-03-23"],
            "post_period": ["2026-03-24", "2026-10-04"],
            "pre_rmse": float(pre_rmse), "post_rmse": float(post_rmse),
            "rmspe_ratio": float(ratio) if ratio is not None else None,
            "mean_gap_post": float(np.mean(post_gap)),
            "total_gap_post": float(np.sum(post_gap)),
            "top_weights": [[donors[j], round(float(w[j]), 4)] for j in np.argsort(-w)[:10] if w[j] > 1e-4],
        }
    }
    os.makedirs(os.path.join(DATA, "results"), exist_ok=True)
    json.dump(out, open(os.path.join(DATA, "results", "did_final.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("\n  结果已保存 data/results/did_final.json")

if __name__ == "__main__":
    main()
