# -*- coding: utf-8 -*-
"""
mine_css_methods.py — 经典计算社科方法在本项目数据上的实作（2026-10-29）
M1 Kleinberg(2002) 突发检测：两状态泊松切换 + Viterbi（周星标序列）
M2 优先连接（Barabási–Albert 1999；Jeong et al. 2003 拟合）：ΔS ~ S 的对数斜率
M3 响应函数/Omori 余震衰减（Crane & Sornette 2008）：爆发后日速率衰减指数 p
M4 Louvain 社区检测（Blondel et al. 2008）：跨仓近重复图
M5 二部图嵌套性 NODF（Almeida-Neto et al. 2008）：评论者×仓
M6 LDA 主题模型（Blei et al. 2003；DiMaggio et al. 2013）：SKILL.md 全文
输出：data/results/mine_css_methods_20261029.json
"""
import json
import os
import re
import math
import random
import collections

import numpy as np
from scipy import stats
import networkx as nx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = r"E:\temp\opencode"
COL = os.path.join(ROOT, "external_data", "collected_20261024")
OUT = os.path.join(ROOT, "data", "results", "mine_css_methods_20261029.json")
RNG = np.random.default_rng(20261029)

R = {"generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds")}

# ---------- 载入星标时序 ----------
stars = json.load(open(os.path.join(TMP, "star_history_v2.json"), encoding="utf-8"))


def weekly_series(weeks):
    ws = sorted(weeks, key=lambda w: w["week"])
    return [max(0, int(w.get("total") or 0)) for w in ws]


def daily_series(weeks):
    ws = sorted(weeks, key=lambda w: w["week"])
    out = []
    for w in ws:
        days = w.get("days") or []
        out.extend([max(0, int(d or 0)) for d in days])
    return out


# ---------- M1 Kleinberg 突发检测（两状态泊松 + Viterbi） ----------
def viterbi_burst(x, gamma=0.08):
    x = np.asarray(x, float)
    if len(x) < 8:
        return None
    lam0 = max(0.5, float(np.median(x)))
    top = np.sort(x)[-max(3, len(x) // 10):]
    lam1 = max(lam0 * 2.5, float(np.mean(top)))
    if lam1 <= lam0 * 1.2:
        return None
    lp0 = stats.poisson.logpmf(x, lam0)
    lp1 = stats.poisson.logpmf(x, lam1)
    n = len(x)
    V = np.full((n, 2), -1e18)
    B = np.zeros((n, 2), int)
    V[0] = [lp0[0], lp1[0]]
    lg, l1g = math.log(gamma), math.log(1 - gamma)
    for t in range(1, n):
        for s in (0, 1):
            stay = V[t - 1, s] + l1g
            switch = V[t - 1, 1 - s] + lg
            if stay >= switch:
                V[t, s] = stay + (lp0[t] if s == 0 else lp1[t])
                B[t, s] = s
            else:
                V[t, s] = switch + (lp0[t] if s == 0 else lp1[t])
                B[t, s] = 1 - s
    path = np.zeros(n, int)
    path[-1] = int(np.argmax(V[-1]))
    for t in range(n - 1, 0, -1):
        path[t - 1] = B[t, path[t]]
    segs = []
    i = 0
    while i < n:
        if path[i] == 1:
            j = i
            while j + 1 < n and path[j + 1] == 1:
                j += 1
            segs.append((i, j, float(np.mean(x[i:j + 1]) / lam0)))
            i = j + 1
        else:
            i += 1
    return {"n_weeks": n, "lam0": round(lam0, 2), "lam1": round(lam1, 2),
            "burst_segments": len(segs), "burst_week_share": round(100 * sum(j - i + 1 for i, j, _ in segs) / n, 1),
            "max_intensity": round(max([s[2] for s in segs], default=1), 2),
            "short_bursts_le2w": sum(1 for i, j, _ in segs if j - i + 1 <= 2)}


M1 = {"per_repo": {}, "aggregate": {}}
n_seg_tot = []
for repo, weeks in stars.items():
    r = viterbi_burst(weekly_series(weeks))
    if r:
        M1["per_repo"][repo] = r
        n_seg_tot.append(r["burst_segments"])
if n_seg_tot:
    M1["aggregate"] = {
        "n_repos": len(n_seg_tot),
        "bursts_per_repo_median": float(np.median(n_seg_tot)),
        "bursts_per_repo_p90": float(np.percentile(n_seg_tot, 90)),
        "repos_with_zero_burst": int(sum(1 for v in n_seg_tot if v == 0)),
        "median_burst_week_share_pct": round(float(np.median(
            [v["burst_week_share"] for v in M1["per_repo"].values()])), 1),
        "short_burst_share_pct": round(100 * sum(v["short_bursts_le2w"] for v in M1["per_repo"].values()) /
                                       max(1, sum(v["burst_segments"] for v in M1["per_repo"].values())), 1),
        "top_intensity": sorted(((k, v["max_intensity"]) for k, v in M1["per_repo"].items()),
                                key=lambda kv: -kv[1])[:5],
    }
R["M1_kleinberg_bursts"] = M1

# ---------- M2 优先连接 ----------
pairs = []
for repo, weeks in stars.items():
    s = weekly_series(weeks)
    for t in range(len(s) - 1):
        if s[t] >= 5:
            pairs.append((s[t], max(0, s[t + 1] - s[t])))
M2 = {}
if len(pairs) >= 100:
    xs = np.array([p[0] for p in pairs], float)
    ys = np.array([p[1] for p in pairs], float) + 0.5
    # 分箱（对数等距）后拟合 log(ΔS) ~ log(S)
    bins = np.logspace(np.log10(5), np.log10(xs.max() + 1), 16)
    bx, by = [], []
    for i in range(len(bins) - 1):
        m = (xs >= bins[i]) & (xs < bins[i + 1])
        if m.sum() >= 20:
            bx.append(np.log10(np.mean(xs[m])))
            by.append(np.log10(np.mean(ys[m])))
    slope, icpt, rv, pv, se = stats.linregress(bx, by)
    M2 = {"n_pairs": len(pairs), "n_bins": len(bx),
          "pa_exponent": round(float(slope), 3), "se": round(float(se), 3),
          "p": round(float(pv), 6), "r2": round(float(rv ** 2), 3),
          "note": "ΔS(t+1) ~ S(t) 的对数斜率；≈1 为线性优先连接"}
else:
    M2 = {"note": "样本不足"}
R["M2_preferential_attachment"] = M2

# ---------- M3 Omori 响应函数 ----------
resp = collections.defaultdict(list)
for repo, weeks in stars.items():
    d = daily_series(weeks)
    if len(d) < 60:
        continue
    d = np.array(d, float)
    base = max(0.5, float(np.median(d[d > 0])) if (d > 0).any() else 0.5)
    th = max(3 * base, np.percentile(d, 95))
    for t in range(len(d)):
        if d[t] >= th and d[t] > base:
            for tau in range(1, 22):
                if t + tau < len(d):
                    resp[tau].append(d[t + tau] / max(1.0, d[t]))
M3 = {}
if resp:
    taus = sorted(resp)
    means = [float(np.mean(resp[t])) for t in taus]
    # 拟合 log(R) = a - p log(tau)
    slope, icpt, rv, pv, se = stats.linregress(np.log(taus), np.log(np.array(means) + 1e-6))
    M3 = {"n_burst_days": int(sum(len(v) for v in resp.values()) / max(1, len(taus))),
          "n_taus": len(taus),
          "omori_p": round(float(-slope), 3), "se": round(float(se), 3),
          "r2": round(float(rv ** 2), 3), "p_value": round(float(pv), 6),
          "decay_curve": {int(t): round(float(np.mean(resp[t])), 3) for t in (1, 2, 3, 5, 7, 10, 14, 21) if t in resp},
          "note": "爆发日后的归一化日速率 R(τ)；p≈0.7–1.0 为典型 Omori 衰减"}
else:
    M3 = {"note": "样本不足"}
R["M3_omori_response"] = M3

# ---------- M4 Louvain（跨仓近重复图） ----------
G = nx.Graph()
n_pairs = 0
for line in open(os.path.join(COL, "near_duplicates.jsonl"), encoding="utf-8", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get("type") != "pair" or d.get("same_repo"):
        continue
    a = (d.get("a") or {}).get("repo")
    b = (d.get("b") or {}).get("repo")
    if not a or not b or a == b:
        continue
    n_pairs += 1
    if G.has_edge(a, b):
        G[a][b]["w"] += 1
    else:
        G.add_edge(a, b, w=1)
M4 = {"n_nodes": G.number_of_nodes(), "n_edges": G.number_of_edges(), "n_pairs_used": n_pairs}
if G.number_of_nodes() >= 100:
    comms = nx.community.louvain_communities(G, weight="w", seed=7)
    comms = sorted(comms, key=len, reverse=True)
    mod = nx.community.modularity(G, comms, weight="w")
    sizes = [len(c) for c in comms]
    M4.update({
        "modularity": round(float(mod), 3),
        "n_communities": len(comms),
        "size_median": int(np.median(sizes)), "size_p90": int(np.percentile(sizes, 90)),
        "size_max": int(sizes[0]) if sizes else None,
        "largest_communities": [{"n": len(c), "examples": list(c)[:4]} for c in comms[:3]],
    })
R["M4_louvain"] = M4

# ---------- M5 NODF（评论者×仓） ----------
bot_re = re.compile(r"(\[bot\]$|-bot$|^dependabot|^renovate|^github-actions|^codecov|^greenkeeper|^mergify|^imgbot|^allcontributors)", re.I)
rows = collections.defaultdict(set)
cols = collections.defaultdict(set)
for line in open(os.path.join(TMP, "pr_comments.jsonl"), encoding="utf-8", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get("type") != "repo":
        continue
    for pr in d.get("prs") or []:
        for c in pr.get("comments") or []:
            a = c.get("author") or ""
            if not a or bot_re.match(a):
                continue
            rows[d["repo"]].add(a)
            cols[a].add(d["repo"])
# 只保留 ≥2 连接的行列
keep_r = {r: cs for r, cs in rows.items() if len(cs) >= 2}
keep_c = {c: rs for c, rs in cols.items() if len(rs) >= 2}
repos5 = sorted(keep_r)
comments5 = sorted(keep_c)
if len(repos5) >= 10 and len(comments5) >= 10:
    M = np.zeros((len(repos5), len(comments5)), dtype=np.int8)
    ri = {r: i for i, r in enumerate(repos5)}
    ci = {c: i for i, c in enumerate(comments5)}
    for r, cs in keep_r.items():
        for c in cs:
            if c in ci:
                M[ri[r], ci[c]] = 1
    r_deg = M.sum(axis=1)
    c_deg = M.sum(axis=0)


    def _nodf_block(mat):
        """向量化 NODF 单边：返回 (mean_nodf, n_pairs)"""
        deg = mat.sum(axis=1).astype(float)
        idx = np.argsort(-deg)
        ds = deg[idx]
        O = (mat @ mat.T)[np.ix_(idx, idx)].astype(float)
        n = len(ds)
        up = np.triu(np.ones((n, n), bool), 1)
        diff = np.abs(ds[:, None] - ds[None, :]) > 1e-9
        mask = up & diff
        if not mask.any():
            return 0.0, 0
        D = np.minimum.outer(ds, ds)
        vals = 100.0 * O[mask] / D[mask]
        return float(np.mean(vals)), int(mask.sum())

    row_n_mean, n_rp = _nodf_block(M)
    col_n_mean, n_cp = _nodf_block(M.T)
    total = (row_n_mean * n_rp + col_n_mean * n_cp) / max(1, n_rp + n_cp)
    R["M5_nodf"] = {
        "n_repos": len(repos5), "n_commenters": len(comments5),
        "fill_pct": round(100 * M.mean(), 2),
        "row_nodf": round(row_n_mean, 1), "col_nodf": round(col_n_mean, 1), "nodf": round(total, 1),
        "row_degree_median": float(np.median(r_deg)), "col_degree_median": float(np.median(c_deg)),
        "note": "NODF 高=嵌套结构（小参与者是最大参与者子集）；低=模块化/专业化",
    }
else:
    R["M5_nodf"] = {"n_repos": len(repos5), "n_commenters": len(comments5), "note": "样本不足"}

# ---------- M6 LDA 主题模型（SKILL.md 全文） ----------
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.decomposition import LatentDirichletAllocation

texts = []
sample_n = 40000
seen = 0
with open(os.path.join(ROOT, "external_data", "skills_with_content.jsonl"), encoding="utf-8",
          errors="replace") as f:
    for line in f:
        try:
            d = json.loads(line)
        except Exception:
            continue
        c = d.get("full_content") or ""
        if len(c) < 100:
            continue
        seen += 1
        if RNG.random() < sample_n / 155547:
            texts.append(c[:4000])
        if len(texts) >= sample_n:
            break
M6 = {}
if len(texts) >= 5000:
    vec = CountVectorizer(max_features=12000, min_df=25, stop_words="english",
                          token_pattern=r"[A-Za-z][A-Za-z\-]{2,}")
    X = vec.fit_transform(texts)
    lda = LatentDirichletAllocation(n_components=12, max_iter=6, learning_method="batch",
                                    random_state=0, n_jobs=-1)
    lda.fit(X)
    terms = np.array(vec.get_feature_names_out())
    topics = []
    for k in range(12):
        top = terms[np.argsort(-lda.components_[k])[:10]]
        topics.append({"topic": k, "top_terms": list(top)})
    doc_topic = lda.transform(X)
    dom = doc_topic.argmax(axis=1)
    share = {int(k): round(100 * float((dom == k).mean()), 1) for k in range(12)}
    M6 = {"n_docs": len(texts), "n_topics": 12, "topics": topics, "doc_share_pct": share,
          "perplexity": round(float(lda.perplexity(X)), 1)}
else:
    M6 = {"n_docs": len(texts), "note": "样本不足"}
R["M6_lda_skills"] = M6

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(R, f, ensure_ascii=False, indent=1)
print(json.dumps({k: R[k] for k in R if k != "M6_lda_skills"}, ensure_ascii=False, indent=1)[:4500])
print("M6 topics:")
for t in M6.get("topics", []):
    print(t["topic"], t["top_terms"][:8])
print("written:", OUT)
