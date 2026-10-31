# -*- coding: utf-8 -*-
"""
mine_nobel_methods.py — 诺奖方法在现有数据上的实作（2026-10-30）
D1 Hall(1978, 2026 诺奖) 随机游走检验：星标增量对滞后水平/滞后增量的可预测性
D2 Acemoglu–Johnson–Robinson(2024 诺奖) 式"制度—绩效"截面回归：
   合并率 ~ 自动化程度 + 正式审查覆盖 + 把关集中度 + 规模
D3 Deaton(2015 诺奖) 式测量审计：五渠道指标的秩相关矩阵（指标可否互相代理）
输出：data/results/mine_nobel_20261030.json
"""
import json
import os
import glob
import re
import collections

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = r"E:\temp\opencode"
COL = os.path.join(ROOT, "external_data", "collected_20261024")
OUT = os.path.join(ROOT, "data", "results", "mine_nobel_20261030.json")

R = {"generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds")}

# ---------- 载入 ----------
stars = json.load(open(os.path.join(TMP, "star_history_v2.json"), encoding="utf-8"))
meta = json.load(open(os.path.join(ROOT, "data", "repos_meta.json"), encoding="utf-8"))

best = {}
for fn in glob.glob(os.path.join(TMP, "fork_prs*.jsonl")):
    for line in open(fn, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("type") == "parent" and d.get("complete"):
            p = d["parent"]
            if p not in best or d.get("n_matched", 0) > best[p].get("n_matched", 0):
                best[p] = d

# ---------- D1 Hall 随机游走检验 ----------
# star_history 的 total 为"当周新增星标"；先累计成水平 L_t，再检验 ΔL_t 是否可由 L_{t-1}、ΔL_{t-1} 预测
rows = []
for repo, weeks in stars.items():
    ws = sorted(weeks, key=lambda w: w["week"])
    gains = [max(0, int(w.get("total") or 0)) for w in ws]
    if len(gains) < 4:
        continue
    L = np.cumsum(gains)
    for t in range(2, len(gains)):
        rows.append((repo, float(L[t - 1]), float(gains[t - 1]), float(gains[t])))
DF1 = pd.DataFrame(rows, columns=["repo", "level_lag", "dL_lag", "dL"])
DF1 = DF1[DF1["level_lag"] >= 10]
D1 = {}
if len(DF1) > 200:
    X = sm.add_constant(DF1[["level_lag", "dL_lag"]])
    model = sm.OLS(DF1["dL"], X).fit(cov_type="cluster", cov_kwds={"groups": DF1["repo"]})
    D1 = {
        "n_obs": int(len(DF1)), "n_repos": int(DF1["repo"].nunique()),
        "coef_level_lag": round(float(model.params["level_lag"]), 5),
        "se_cluster": round(float(model.bse["level_lag"]), 5),
        "p_level_lag": float(model.pvalues["level_lag"]),
        "coef_dL_lag": round(float(model.params["dL_lag"]), 4),
        "p_dL_lag": float(model.pvalues["dL_lag"]),
        "r2": round(float(model.rsquared), 4),
        "verdict": "拒绝随机游走" if model.pvalues["level_lag"] < 0.01 else "不能拒绝随机游走",
        "note": "Hall(1978) RW：ΔL_t 不可由 L_{t-1}、ΔL_{t-1} 预测（系数≈0）。"
                "β>0 表示规模越大周增越快（优先连接），β<0 为均值回归",
    }
else:
    D1 = {"n_obs": len(DF1), "note": "样本不足"}
R["D1_hall_random_walk"] = D1

# ---------- D2 AJR 式制度—绩效回归 ----------
bot_re = re.compile(r"(\[bot\]$|-bot$|^dependabot|^renovate|^github-actions|^codecov|^greenkeeper|^mergify|^imgbot|^allcontributors)", re.I)
repo_stats = collections.defaultdict(lambda: {"prs": 0, "rev": 0, "comments": 0, "bot_comments": 0,
                                              "commenters": collections.Counter()})
for line in open(os.path.join(TMP, "pr_comments.jsonl"), encoding="utf-8", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get("type") != "repo":
        continue
    st = repo_stats[d["repo"]]
    for pr in d.get("prs") or []:
        st["prs"] += 1
        if any((rv.get("state") or "").upper() in ("APPROVED", "CHANGES_REQUESTED") for rv in (pr.get("reviews") or [])):
            st["rev"] += 1
        for c in pr.get("comments") or []:
            a = c.get("author") or ""
            st["comments"] += 1
            if bot_re.match(a):
                st["bot_comments"] += 1
            elif a:
                st["commenters"][a] += 1

rows2 = []
for repo, row in best.items():
    ls = row.get("links") or []
    if len(ls) < 20:
        continue
    st = repo_stats.get(repo)
    if not st or st["prs"] < 10 or st["comments"] < 10:
        continue
    merged = sum(1 for l in ls if l.get("merged_at"))
    top1 = max(st["commenters"].values()) / max(1, sum(st["commenters"].values()))
    rows2.append({
        "repo": repo,
        "merge_rate": merged / len(ls),
        "bot_share": st["bot_comments"] / st["comments"],
        "review_share": st["rev"] / st["prs"],
        "top1_share": top1,
        "log_stars": np.log10(max(1, (meta.get(repo) or {}).get("stars") or 1)),
    })
DF2 = pd.DataFrame(rows2)
D2 = {}
if len(DF2) >= 30:
    X = sm.add_constant(DF2[["bot_share", "review_share", "top1_share", "log_stars"]])
    m = sm.OLS(DF2["merge_rate"], X).fit(cov_type="HC3")
    D2 = {"n_repos": int(len(DF2)),
          "coefs": {k: round(float(m.params[k]), 3) for k in ["bot_share", "review_share", "top1_share", "log_stars"]},
          "p_values": {k: round(float(m.pvalues[k]), 4) for k in ["bot_share", "review_share", "top1_share", "log_stars"]},
          "r2": round(float(m.rsquared), 3),
          "note": "合并率（fork→PR 事件中已合并占比）~ 自动化+审查覆盖+把关集中度+规模；HC3 稳健 SE；截面相关非因果"}
else:
    D2 = {"n_repos": len(DF2), "note": "样本不足"}
R["D2_institutions_regression"] = D2

# ---------- D3 Deaton 式测量审计 ----------
inst = {}
claw = {}
rel = {}
for line in open(os.path.join(COL, "market_full.jsonl"), encoding="utf-8", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    t = d.get("type")
    if t == "skills_sh":
        inst[d.get("repo")] = d.get("total_installs") or 0
    elif t == "clawhub_search":
        claw[d.get("repo")] = d.get("total_downloads") or 0
for line in open(os.path.join(COL, "release_downloads.jsonl"), encoding="utf-8", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get("type") != "repo":
        continue
    gh = d.get("github") or {}
    rel[d.get("repo")] = (gh.get("downloads") or 0)
names = []
data = []
for repo in meta:
    row = [
        meta[repo].get("stars") or 0,
        meta[repo].get("forks") or 0,
        inst.get(repo, 0),
        claw.get(repo, 0),
        rel.get(repo, 0),
    ]
    names.append(repo)
    data.append(row)
A = np.array(data, float)
D3 = {"n_repos": len(names),
      "metrics": ["stars", "forks", "skills_sh_installs", "clawhub_downloads", "release_downloads"],
      "nonzero_share": {m: round(100 * float((A[:, i] > 0).mean()), 1)
                        for i, m in enumerate(["stars", "forks", "installs", "clawhub", "release"])}}
if len(A) >= 50:
    rho = stats.spearmanr(A).correlation
    D3["spearman_matrix"] = [[round(float(x), 3) for x in row] for row in rho]
    # 两两的样本内秩相关（仅共同非零）
    D3["pairwise_nonzero_n"] = {
        "stars~installs": int(((A[:, 0] > 0) & (A[:, 2] > 0)).sum()),
        "stars~clawhub": int(((A[:, 0] > 0) & (A[:, 3] > 0)).sum()),
        "installs~clawhub": int(((A[:, 2] > 0) & (A[:, 3] > 0)).sum()),
    }
R["D3_deaton_metric_audit"] = D3

# ---------- D4 Granger 因果检验（Granger 2003 诺奖）：日星标增益 vs 日 fork 数 ----------
from statsmodels.tsa.stattools import grangercausalitytests

forks_src = json.load(open(os.path.join(ROOT, "data", "forks_timestamps_full.json"), encoding="utf-8"))
D4 = {"per_repo": {}, "summary": {}}
p_star2fork = []
p_fork2star = []
for repo, weeks in stars.items():
    fl = forks_src.get(repo)
    if not fl:
        continue
    ws = sorted(weeks, key=lambda w: w["week"])
    # 重建日星标序列
    days = []
    for w in ws:
        days.extend([max(0, int(d or 0)) for d in (w.get("days") or [])])
    if len(days) < 60:
        continue
    import datetime as _dt
    t0 = _dt.datetime.fromtimestamp(ws[0]["week"], tz=_dt.timezone.utc).date()
    fork_daily = collections.Counter()
    for f in fl:
        c = f.get("created_at")
        if not c:
            continue
        try:
            dd = (_dt.datetime.fromisoformat(c.replace("Z", "+00:00")).date() - t0).days
        except Exception:
            continue
        if 0 <= dd < len(days):
            fork_daily[dd] += 1
    if sum(fork_daily.values()) < 30:
        continue
    fs = np.array([fork_daily.get(i, 0) for i in range(len(days))], float)
    st = np.array(days, float)
    if st.std() == 0 or fs.std() == 0:
        continue
    try:
        # H0: fork 不 Granger 引起 star
        r1 = grangercausalitytests(np.column_stack([st, fs]), maxlag=3)
        # H0: star 不 Granger 引起 fork
        r2 = grangercausalitytests(np.column_stack([fs, st]), maxlag=3)
        p1 = min(r1[k][0]["ssr_ftest"][1] for k in (1, 2, 3))
        p2 = min(r2[k][0]["ssr_ftest"][1] for k in (1, 2, 3))
        D4["per_repo"][repo] = {"p_fork_to_star": round(float(p1), 4),
                                "p_star_to_fork": round(float(p2), 4)}
        p_star2fork.append(p2)
        p_fork2star.append(p1)
    except Exception:
        continue
if p_star2fork:
    D4["summary"] = {
        "n_repos": len(p_star2fork),
        "share_star_granger_fork_5pct": round(100 * float(np.mean([p < 0.05 for p in p_star2fork])), 1),
        "share_fork_granger_star_5pct": round(100 * float(np.mean([p < 0.05 for p in p_fork2star])), 1),
        "median_p_star_to_fork": round(float(np.median(p_star2fork)), 4),
        "median_p_fork_to_star": round(float(np.median(p_fork2star)), 4),
        "note": "日度 VAR(3) F 检验；双侧方向各自检验；样本=星标与 fork 日序列均≥60/30 天",
    }
R["D4_granger"] = D4

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(R, f, ensure_ascii=False, indent=1)
print(json.dumps(R, ensure_ascii=False, indent=1)[:3500])
print("written:", OUT)
