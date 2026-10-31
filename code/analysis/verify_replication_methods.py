# -*- coding: utf-8 -*-
"""verify_replication_methods.py — 对 mine_replication_methods.py 四组结果做独立复核"""
import json, os, glob
import numpy as np, pandas as pd
from scipy import stats

ROOT = r"E:\Skill扩散论文_可复现项目"
TMP = r"E:\temp\opencode"
COL = os.path.join(ROOT, "external_data", "collected_20261024")
stars = json.load(open(os.path.join(TMP, "star_history_v2.json"), encoding="utf-8"))
meta = json.load(open(os.path.join(ROOT, "data", "repos_meta.json"), encoding="utf-8"))

best = {}
for fn in glob.glob(os.path.join(TMP, "fork_prs*.jsonl")):
    for line in open(fn, encoding="utf-8", errors="replace"):
        try: d = json.loads(line)
        except Exception: continue
        if d.get("type") == "parent" and d.get("complete"):
            p = d["parent"]
            if p not in best or d.get("n_matched", 0) > best[p].get("n_matched", 0):
                best[p] = d

# ---------- R1 复核 ----------
rows = []
for p, d in best.items():
    nf = d.get("n_forks") or 0
    if nf < 5: continue
    c = len({l.get("fork") for l in (d.get("links") or []) if l.get("fork")})
    rows.append({"parent": p, "n_forks": nf, "contrib": c,
                 "stars": (meta.get(p) or {}).get("stars") or 0})
P = pd.DataFrame(rows).sort_values("stars", ascending=False).reset_index(drop=True)
P["decile"] = pd.qcut(P.index + 1, 10, labels=False) + 1
g = P.groupby("decile").agg(n=("parent", "count"), forks=("n_forks", "sum"),
                            contrib=("contrib", "sum"))
g["eng_w"] = g["contrib"] / g["forks"]          # fork 加权 engagement
g["w"] = g["forks"] / g["forks"].sum()
print("R1 direct rate", round(P["contrib"].sum() / P["n_forks"].sum(), 4))
print("R1 decile weighted eng:\n", g[["n", "w", "eng_w"]].round(4).to_string())
print("R1 identity check sum(w*eng_w) =", round(float((g["w"] * g["eng_w"]).sum()), 4))
# 真实 top3 engagement 分位
top3d = g.nlargest(3, "eng_w")
print("R1 top3 eng deciles", list(top3d.index), "weighted eng",
      round(float(top3d["contrib"].sum() / top3d["forks"].sum()), 4))
eng_top3 = float(top3d["contrib"].sum() / top3d["forks"].sum())
print("R1 cf all get top3 eng:", round(float((g["w"] * eng_top3).sum()), 4))
# 第九分位是否被单仓驱动
d9 = P[P["decile"] == 9].sort_values("contrib", ascending=False)
print("R1 decile9 top contributor share",
      round(float(d9.iloc[0]["contrib"] / d9["contrib"].sum()), 3),
      "n_forks", int(d9.iloc[0]["n_forks"]), "contrib", int(d9.iloc[0]["contrib"]))
d9x = d9.iloc[1:]
print("R1 decile9 eng_w without top contributor:",
      round(float(d9x["contrib"].sum() / d9x["n_forks"].sum()), 4))

# ---------- R2 方差分解（嵌套 R²） ----------
rr = []
for repo, weeks in stars.items():
    for w in sorted(weeks, key=lambda x: x["week"]):
        rr.append((repo, w["week"], max(0, int(w.get("total") or 0))))
DF = pd.DataFrame(rr, columns=["repo", "week", "inc"])
import statsmodels.formula.api as smf
m0 = smf.ols("inc ~ 1", data=DF).fit()
m1 = smf.ols("inc ~ C(repo)", data=DF).fit()
m2 = smf.ols("inc ~ C(repo) + C(week)", data=DF).fit()
r2_repo, r2_full = m1.rsquared, m2.rsquared
print("R2 nested: repo R2", round(r2_repo, 4), "+week incr", round(r2_full - r2_repo, 4),
      "resid", round(1 - r2_full, 4), "sum", round(r2_full + 1 - r2_full, 4))
print("R2 naive var shares sum check:", 0.2316 + 0.0372 + 0.7771)

# ---------- R2 shift 阈值敏感性 ----------
for thr in (1, 2, 4):
    lens, tops, tots, nseg = [], 0.0, 0.0, 0
    for repo, gg in DF.groupby("repo"):
        inc = gg.sort_values("week")["inc"].values
        start, segs, zero_run = 0, [], 0
        for t in range(len(inc)):
            if inc[t] == 0:
                zero_run += 1
            else:
                zero_run = 0
            if zero_run >= thr and t < len(inc) - 1:
                segs.append((t - thr + 1 - start, int(inc[start:t - thr + 1].sum())))
                start = t + 1
        segs.append((len(inc) - start, int(inc[start:].sum())))
        nseg += len(segs)
        lens.extend([ln for ln, tot in segs if tot > 0])
        tops += max([tot for _, tot in segs]) if segs else 0
        tots += sum(tot for _, tot in segs)
    print(f"R2 shift thr>={thr} zero weeks: n_segments {nseg}",
          "median_len_nonzero", round(float(np.median(lens)), 1),
          "top1 share", round(tops / max(tots, 1), 4))

# ---------- R3 复核：筛选用 fold1-3，fold0 只做测试 ----------
installs = {}
for fn in ["market_full.jsonl", "market_retry.jsonl", "market_extra.jsonl"]:
    pth = os.path.join(COL, fn)
    if not os.path.exists(pth): continue
    for line in open(pth, encoding="utf-8", errors="replace"):
        try: d = json.loads(line)
        except Exception: continue
        if d.get("type") == "skills_sh" and d.get("repo") and (d.get("total_installs") or 0) > 0:
            installs[d["repo"]] = max(installs.get(d["repo"], 0), d["total_installs"])
wk = sorted(DF["week"].unique()); late = set(wk[-6:])
late_share = DF[DF["week"].isin(late)].groupby("repo")["inc"].sum()
late_share = late_share / late_share.sum()
fr = []
for repo in stars:
    if repo not in late_share.index: continue
    m = meta.get(repo) or {}
    ws = sorted(stars[repo], key=lambda x: x["week"])
    early = sum(max(0, int(x.get("total") or 0)) for x in ws[:6])
    fp = best.get(repo) or {}
    fr.append({"repo": repo, "y": float(late_share[repo]),
               "log_forks": np.log1p(m.get("forks") or 0),
               "age_days": (pd.Timestamp("2026-10-24") - pd.Timestamp((m.get("created_at") or "2025-01-01")[:10])).days,
               "log_installs": np.log1p(installs[repo]) if repo in installs else np.nan,
               "log_early": np.log1p(early),
               "eng": (fp.get("contrib") or 0) / fp["n_forks"] if fp.get("n_forks") else np.nan})
F = pd.DataFrame(fr)
F["y_logit"] = np.log(F["y"] / (1 - F["y"] + 1e-9) + 1e-9)
rng = np.random.default_rng(20261030); F["fold"] = rng.integers(0, 4, len(F))
cands = ["log_forks", "age_days", "log_installs", "log_early", "eng"]
scores = {}
for f in cands:
    zs = []
    for k in (1, 2, 3):
        te = F[F["fold"] == k].dropna(subset=[f])
        if len(te) < 30 or te[f].nunique() < 2: continue
        r, _ = stats.pearsonr(te[f], te["y_logit"])
        zs.append(np.arctanh(np.clip(r, -.999, .999)))
    if zs: scores[f] = float(np.tanh(np.mean(zs)))
ranked = sorted(scores.items(), key=lambda kv: abs(kv[1]), reverse=True)
print("R3 ranking (fold0 excluded):", [(k, round(v, 3)) for k, v in ranked])
CC = F.dropna(subset=cands + ["y_logit"])
tr, te = CC[CC["fold"] != 0], CC[CC["fold"] == 0]
for cols in ([k for k, _ in ranked[:3]], [k for k, _ in ranked[:5]]):
    mm = smf.ols("y_logit ~ " + " + ".join(cols), data=tr).fit()
    pred = mm.predict(te)
    ssr = float(((te["y_logit"] - pred) ** 2).sum())
    sst = float(((te["y_logit"] - te["y_logit"].mean()) ** 2).sum())
    print("R3 model", cols, "n", len(tr), len(te),
          "train R2", round(mm.rsquared, 3), "test R2", round(1 - ssr / sst, 3))

# ---------- R4 复核：百分位基准 ----------
mr = {}
for line in open(os.path.join(COL, "pr_merged.jsonl"), encoding="utf-8", errors="replace"):
    try: d = json.loads(line)
    except Exception: continue
    if d.get("type") == "repo" and d.get("complete") and (d.get("n_pulls") or 0) >= 5:
        pulls = d.get("pulls") or []
        merged = sum(1 for p in pulls if p.get("merged"))
        closed = sum(1 for p in pulls if p.get("state") == "closed")
        if closed: mr[d["repo"]] = merged / closed
H = pd.DataFrame([{"repo": r, "stars": (meta.get(r) or {}).get("stars") or 0,
                   "forks": (meta.get(r) or {}).get("forks") or 0,
                   "installs": installs.get(r), "merge_rate": mr.get(r)} for r in stars])
H = H[H["stars"] > 0]
for c in ["stars", "forks", "installs", "merge_rate"]:
    H[f"pct_{c}"] = H[c].rank(pct=True)
Hn = H.dropna(subset=["installs", "merge_rate"], how="all")
print("R4 n(all 4 dims)", int(H.dropna(subset=["installs", "merge_rate"]).shape[0]),
      "n(>=3 dims)", int(H.dropna(subset=["installs", "merge_rate"], how="all").shape[0]))
sub = H.dropna(subset=["installs", "merge_rate"], how="all").copy()
sub["geo"] = np.exp(np.log(sub[[f"pct_{c}" for c in ["stars", "forks", "installs", "merge_rate"]]].clip(lower=.01)).mean(axis=1))
rho, _ = stats.spearmanr(sub["stars"].rank(ascending=False), sub["geo"].rank(ascending=False))
print("R4 spearman", round(float(rho), 3), "n", len(sub))
