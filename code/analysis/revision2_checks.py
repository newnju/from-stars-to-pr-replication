# -*- coding: utf-8 -*-
"""revision2_checks.py — 顶刊外审要求的补充统计（2026-10-30）"""
import json, os, glob, datetime, math
import numpy as np, pandas as pd
from scipy import stats

ROOT = r"E:\Skill扩散论文_可复现项目"
TMP = r"E:\temp\opencode"
COL = os.path.join(ROOT, "external_data", "collected_20261024")
meta = json.load(open(os.path.join(ROOT, "data", "repos_meta.json"), encoding="utf-8"))
final = json.load(open(os.path.join(ROOT, "data", "results", "fork_prs_final_20261026.json"), encoding="utf-8"))
P = pd.DataFrame(final["per_parent"])
P["conv"] = P["returning_forks"] / P["n_forks"]
P["stars"] = P["parent"].map(lambda p: (meta.get(p) or {}).get("stars") or 0)
P["forks"] = P["parent"].map(lambda p: (meta.get(p) or {}).get("forks") or 0)

inst, claw, rel = {}, {}, set()
for fn in ["market_full.jsonl", "market_retry.jsonl", "market_extra.jsonl"]:
    p = os.path.join(COL, fn)
    if not os.path.exists(p): continue
    for line in open(p, encoding="utf-8", errors="replace"):
        try: d = json.loads(line)
        except Exception: continue
        if d.get("type") == "skills_sh" and d.get("repo") and (d.get("total_installs") or 0) > 0:
            inst[d["repo"]] = max(inst.get(d["repo"], 0), d["total_installs"])
        if d.get("type") == "clawhub_search" and d.get("repo"):
            claw[d["repo"]] = d.get("total_downloads") or 0
for line in open(os.path.join(COL, "release_downloads.jsonl"), encoding="utf-8", errors="replace"):
    try: d = json.loads(line)
    except Exception: continue
    if d.get("type") == "repo" and ((d.get("github") or {}).get("downloads") or 0) > 0:
        rel.add(d.get("repo"))
P["visibility"] = P["parent"].map(lambda p: int(p in inst) + int(p in claw) + int(p in rel))

R = {}

# ---------- 1. P1 TOST / 90% CI ----------
D = pd.DataFrame([{"stars": (meta.get(r) or {}).get("stars") or 0, "installs": v}
                  for r, v in inst.items()])
D = D[D.stars > 0]
rho, pv = stats.spearmanr(D.stars, D.installs)
n = len(D)
z = np.arctanh(rho); se = 1 / math.sqrt(n - 3)
ci90 = [float(np.tanh(z - 1.645 * se)), float(np.tanh(z + 1.645 * se))]
# TOST: H0 rho>=0.5 vs rho<0.5, and H0 rho<=-0.5 vs rho>-0.5
z_hi = (np.arctanh(0.5) - z) / se
z_lo = (z - np.arctanh(-0.5)) / se
R["P1_tost"] = {"n": n, "rho": round(float(rho), 3),
                "ci90": [round(x, 3) for x in ci90],
                "p_upper_vs_05": float(1 - stats.norm.cdf(z_hi)),
                "p_lower_vs_m05": float(1 - stats.norm.cdf(z_lo)),
                "tost_p": float(max(1 - stats.norm.cdf(z_hi), 1 - stats.norm.cdf(z_lo)))}

# ---------- 2. NMI bin sensitivity + distance correlation ----------
def entropy(v):
    _, c = np.unique(v, return_counts=True); p = c / c.sum()
    return float(-(p * np.log(p)).sum())

def mi(a, b):
    ct = pd.crosstab(a, b).values.astype(float); n = ct.sum()
    pa = ct.sum(1, keepdims=True) / n; pb = ct.sum(0, keepdims=True) / n
    with np.errstate(divide="ignore", invalid="ignore"):
        t = ct / n * np.log((ct / n) / (pa @ pb))
    return float(np.nansum(t))

vars_ = ["stars", "forks", "conv", "visibility"]
nmi = {}
for k in (3, 4, 5, 6):
    Dq = pd.DataFrame({v: pd.qcut(P[v].rank(method="first"), k, labels=False) for v in vars_})
    nmi[k] = {}
    for a in vars_:
        for b in vars_:
            if a == b: continue
            key = f"{a}|{b}"
            obs = mi(Dq[a], Dq[b]); den = min(entropy(Dq[a]), entropy(Dq[b]))
            nmi[k][key] = round(obs / den, 4) if den else None

def dcor(x, y):
    x = np.asarray(x, float); y = np.asarray(y, float)
    a = np.abs(x[:, None] - x[None, :]); b = np.abs(y[:, None] - y[None, :])
    A = a - a.mean(0) - a.mean(1)[:, None] + a.mean()
    B = b - b.mean(0) - b.mean(1)[:, None] + b.mean()
    dcov2 = (A * B).mean(); dx = (A * A).mean(); dy = (B * B).mean()
    return float(np.sqrt(dcov2 / np.sqrt(dx * dy))) if dx > 0 and dy > 0 else None

rng = np.random.default_rng(20261030)
pairs = [("stars", "forks"), ("stars", "conv"), ("stars", "visibility"),
         ("forks", "conv"), ("forks", "visibility"), ("conv", "visibility")]
dc = {}
for a, b in pairs:
    obs = dcor(P[a].values, P[b].values)
    perm = [dcor(P[a].values, rng.permutation(P[b].values)) for _ in range(300)]
    p = (1 + sum(1 for v in perm if v >= obs)) / (1 + len(perm))
    dc[f"{a}|{b}"] = {"dcor": round(obs, 4), "p": round(float(p), 3)}
R["NMI_sensitivity"] = {"n": int(len(P)), "bins": nmi, "distance_correlation": dc}

# ---------- 3. 动态耦合：bootstrap CI + week FE ----------
stars = json.load(open(os.path.join(TMP, "star_history_v2.json"), encoding="utf-8"))
best = {}
for fn in glob.glob(os.path.join(TMP, "fork_prs*.jsonl")):
    for line in open(fn, encoding="utf-8", errors="replace"):
        try: d = json.loads(line)
        except Exception: continue
        if d.get("type") == "parent" and d.get("complete"):
            pp = d["parent"]
            if pp not in best or d.get("n_matched", 0) > best[pp].get("n_matched", 0):
                best[pp] = d
EV = []
for pp, d in best.items():
    for l in d.get("links") or []:
        ts = l.get("created_at")
        if not ts: continue
        try: t = datetime.datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
        except Exception: continue
        wk = t.date() - datetime.timedelta(days=(t.weekday() + 1) % 7)
        EV.append((pp, wk, l.get("number")))
EV = pd.DataFrame(EV, columns=["parent", "week", "number"]).drop_duplicates(subset=["parent", "number"])
S = pd.DataFrame([(r, datetime.date.fromtimestamp(w["week"]), max(0, int(w.get("total") or 0)))
                  for r, ws in stars.items() for w in ws], columns=["parent", "week", "inc"])
S = S[S.parent.isin(set(P.parent))]
ev = EV.groupby(["parent", "week"]).size().rename("pr").reset_index()
M = S.merge(ev, on=["parent", "week"], how="left"); M["pr"] = M["pr"].fillna(0)
M = M.merge(P[["parent", "conv"]], on="parent", how="left")
M["regime"] = np.where(M.conv >= .20, "high", "low")

def boot_median_rho(df, B=1000):
    repos = [g for _, g in df.groupby("parent")]
    vals = []
    for g in repos:
        g = g.sort_values("week"); a, b = g.inc.values, g.pr.values
        if len(a) < 12 or np.std(a) == 0 or np.std(b) == 0: continue
        r, _ = stats.spearmanr(a, b)
        if np.isfinite(r): vals.append(r)
    vals = np.array(vals)
    boots = [np.median(rng.choice(vals, len(vals), replace=True)) for _ in range(B)]
    return {"n_repos": int(len(vals)), "median": round(float(np.median(vals)), 3),
            "ci95": [round(float(np.percentile(boots, 2.5)), 3), round(float(np.percentile(boots, 97.5)), 3)]}

def week_fe_elast(df):
    d = df.copy()
    d["ly"] = np.log1p(d["pr"]); d["lx"] = np.log1p(d["inc"])
    # 双向去均值（repo + week），吸收共同冲击
    d["ly"] = d.ly - d.groupby("parent").ly.transform("mean") - d.groupby("week").ly.transform("mean") + d.ly.mean()
    d["lx"] = d.lx - d.groupby("parent").lx.transform("mean") - d.groupby("week").lx.transform("mean") + d.lx.mean()
    import statsmodels.api as sm
    m = sm.OLS(d.ly, sm.add_constant(d.lx)).fit(cov_type="cluster", cov_kwds={"groups": d.parent})
    return {"beta": round(float(m.params["lx"]), 4), "se": round(float(m.bse["lx"]), 4),
            "p": float(m.pvalues["lx"]), "n": int(len(d))}

R["dynamic_coupling"] = {}
for reg in ("low", "high"):
    sub = M[M.regime == reg]
    R["dynamic_coupling"][reg] = {"rho": boot_median_rho(sub), "week_fe_elasticity": week_fe_elast(sub)}

# ---------- 4. P5 MDE ----------
se_logor = (math.log(1.35) - math.log(0.65)) / (2 * 1.96)
R["P5_mde"] = {"se_logOR": round(se_logor, 3),
               "mde_or_80pct": round(math.exp(2.8 * se_logor), 2),
               "note": "近似最小可检测 OR（双侧 α=.05，功效 .8）"}

print(json.dumps(R, ensure_ascii=False, indent=1))
