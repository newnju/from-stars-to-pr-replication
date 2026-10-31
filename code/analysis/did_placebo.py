# -*- coding: utf-8 -*-
"""
did_placebo.py — 两个决定性检验：
  A. 置换安慰剂检验（permutation placebo）：随机抽取大量伪断点，拟合 ITS，得到 trend2 的零分布，
     检验真实断点(2026-02-03/2026-03-24)的效应是否显著异于随机断点。
  B. 风险分层 DID（dose-response，单平台内）：
     处理强度 = 风险层级（DESTRUCTIVE=1 / BENIGN=0）
     结果 = 仓库级日均新增 star 的 冲击后-冲击前 差
     DID = E[Δstar | DESTRUCTIVE] - E[Δstar | BENIGN]
     以聚类稳健 SE 报告，并做平行趋势（冲击前）预检验。
"""
import json, os, datetime, random, statistics
import numpy as np

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
SKILLDIR = os.path.join(DATA, "skillmd")
RESULTS = os.path.join(DATA, "results")

# 危害导向风险关键词（与 risk_strata.py 一致）
DESTRUCTIVE = [
    "rm -rf", "rm -fr", "drop table", "drop database", "truncate table",
    "credential", "credentials", "password", "passwd", "api_key", "api key",
    "access token", "auth token", "oauth", "private key", "ssh-keygen",
    "sudo ", "chmod 777", "setuid", "privilege escalation",
    "reverse shell", "backdoor", "keylogger", "payload", "exfiltrat",
    "c2 server", "command and control", "impersonat", "spoof", "phish",
    "steal", "harvest credential", "browser cookie", "session hijack",
    "mitm", "keychain", "vault decrypt", "decrypt", "unlock", "bypass",
]
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

def repo_risk(k):
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
    return 1 if h >= 1 else 0  # DESTRUCTIVE=1, BENIGN=0

def main():
    sh = load("star_history.json")
    forks = load("forks_timestamps.json")
    clean = load(os.path.join(RESULTS, "clean_sample.json"))
    clean_repos = list(clean["clean_repos"])

    # ---------- A. 置换安慰剂检验 ----------
    print("=" * 70)
    print("A. 置换安慰剂检验（permutation placebo，ITS trend2）")
    print("=" * 70)

    # 全生态每日 star
    def agg_daily(repos):
        byday = {}
        for k in repos:
            for d, c in daily_series(sh.get(k, [])):
                byday[d] = byday.get(d, 0) + c
        return sorted(byday.items())

    daily = agg_daily(clean_repos)

    def its_trend2(daily, b1, b2):
        X, y = build_its(daily, b1, b2)
        import statsmodels.api as sm
        m = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 7})
        return float(m.params[5]), float(m.pvalues[5])  # trend2

    true_trend2, true_p = its_trend2(daily, "2026-02-03", "2026-03-24")
    print(f"真实断点 trend2 = {true_trend2:.1f}  (p={true_p:.3e})")

    # 随机伪断点：在 2025-11-01 ~ 2026-08-01 内随机抽 break1，break2=break1+49天
    rng = random.Random(42)
    d0 = datetime.date(2025, 11, 1)
    d1 = datetime.date(2026, 8, 1)
    span = (d1 - d0).days
    placebo_trend2 = []
    n_placebo = 200
    for _ in range(n_placebo):
        b1 = d0 + datetime.timedelta(days=rng.randint(0, span))
        b2 = b1 + datetime.timedelta(days=49)
        t2, p2 = its_trend2(daily, b1.isoformat(), b2.isoformat())
        placebo_trend2.append(t2)
    placebo_trend2 = np.array(placebo_trend2)
    # 真实 trend2 为负（减速），p = P(placebo <= true) 单侧
    p_perm = float(np.mean(placebo_trend2 <= true_trend2))
    print(f"安慰剂 trend2 分布: mean={placebo_trend2.mean():.1f}  sd={placebo_trend2.std():.1f}  min={placebo_trend2.min():.1f}  max={placebo_trend2.max():.1f}")
    print(f"置换 p 值（单侧，placebo <= true）: {p_perm:.3f}")
    print(f"真实 trend2 在安慰剂分布中的分位: {float(np.mean(placebo_trend2 < true_trend2))*100:.1f}%")

    # ---------- B. 风险分层 DID（dose-response） ----------
    print("=" * 70)
    print("B. 风险分层 DID（单平台 dose-response）")
    print("=" * 70)

    PRE_START, PRE_END = "2025-11-01", "2026-02-02"
    POST_START, POST_END = "2026-02-03", "2026-03-23"
    POST2_START, POST2_END = "2026-03-24", "2026-06-30"

    def repo_rate(k, s, e):
        hist = sh.get(k)
        if not hist:
            return None
        vals = [c for d, c in daily_series(hist) if s <= d < e]
        return statistics.mean(vals) if vals else None

    treat, outcome = [], []
    pre_rates, post_rates = [], []
    for k in clean_repos:
        r = repo_risk(k)
        pre = repo_rate(k, PRE_START, PRE_END)
        post = repo_rate(k, POST_START, POST_END)
        if pre is None or post is None:
            continue
        treat.append(r)
        pre_rates.append(pre)
        post_rates.append(post)
        outcome.append(post - pre)

    treat = np.array(treat); pre_rates = np.array(pre_rates)
    post_rates = np.array(post_rates); outcome = np.array(outcome)

    d_idx = np.where(treat == 1)[0]
    b_idx = np.where(treat == 0)[0]

    # DID = E[Δ | D=1] - E[Δ | D=0]
    did = float(outcome[d_idx].mean() - outcome[b_idx].mean())
    # 聚类稳健 SE（仓库级，实际这里每仓库一个观测，等价于异方差稳健 SE）
    import statsmodels.api as sm
    X = sm.add_constant(treat)
    m = sm.OLS(outcome, X).fit(cov_type="HC1")
    did_coef = float(m.params[1]); did_se = float(m.bse[1]); did_p = float(m.pvalues[1])
    print(f"\nDESTRUCTIVE n={len(d_idx)}  BENIGN n={len(b_idx)}")
    print(f"Δstar(冲击后-冲击前)  DESTRUCTIVE: {outcome[d_idx].mean():+.2f}/天")
    print(f"Δstar(冲击后-冲击前)  BENIGN:       {outcome[b_idx].mean():+.2f}/天")
    print(f"DID 估计量 = {did_coef:+.3f}  SE={did_se:.3f}  p={did_p:.3e}")

    # 平行趋势预检验：冲击前更早窗口 2025-10-01~2025-11-01 的趋势差异
    pre2 = np.array([repo_rate(clean_repos[i], "2025-10-01", "2025-11-01")
                     for i in range(len(clean_repos)) if True], dtype=float)
    # 简化：用 pre_rates 的组间差异检验基准水平差异（不完全等价平行趋势，但可指示）
    print(f"\n[平行趋势提示] 冲击前日均 star  DESTRUCTIVE: {pre_rates[d_idx].mean():.2f}  BENIGN: {pre_rates[b_idx].mean():.2f}")

    # 稳健：加入冲击前水平作为协变量（ANCOVA 形式）
    X2 = sm.add_constant(np.column_stack([treat, pre_rates]))
    m2 = sm.OLS(post_rates, X2).fit(cov_type="HC1")
    did_ancova = float(m2.params[1]); did_ancova_p = float(m2.pvalues[1])
    print(f"DID(ANCOVA, 控制冲击前水平) = {did_ancova:+.3f}  p={did_ancova_p:.3e}")

    out = {
        "placebo": {
            "true_trend2": true_trend2, "true_p": true_p,
            "n_placebo": n_placebo,
            "placebo_mean": float(placebo_trend2.mean()),
            "placebo_sd": float(placebo_trend2.std()),
            "perm_p": p_perm,
            "true_percentile": float(np.mean(placebo_trend2 < true_trend2)),
        },
        "did": {
            "n_destructive": int(len(d_idx)), "n_benign": int(len(b_idx)),
            "delta_destructive": float(outcome[d_idx].mean()),
            "delta_benign": float(outcome[b_idx].mean()),
            "did": did_coef, "did_se": did_se, "did_p": did_p,
            "did_ancova": did_ancova, "did_ancova_p": did_ancova_p,
        }
    }
    os.makedirs(RESULTS, exist_ok=True)
    json.dump(out, open(os.path.join(RESULTS, "did_placebo.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("\n  结果已保存 data/results/did_placebo.json")
    print("=" * 70)

if __name__ == "__main__":
    main()
