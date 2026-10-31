# -*- coding: utf-8 -*-
"""
mine_patterns.py — 纯数据驱动的规律挖掘（2026-10-29）
不预设论文命题，只问：数据本身服从什么分布、呈现什么时间结构、
什么特征可预测结果、有哪些潜在类别与异常、文本与网络呈现什么形态。

方法矩阵：
  P1 重尾分布拟合：Clauset–Shalizi–Newman MLE 幂律 + KS 选 xmin，对数正态/指数对照（对数似然）
  P2 点过程：爆发度 B=(σ−μ)/(σ+μ)、Fano 因子、昼夜/星期季节性（χ²）、自相关、间隔分布拟合
  P3 生存分析：Kaplan–Meier（合并时滞）+ 对数秩检验 + Cox（statsmodels PHReg，按仓聚类稳健 SE）
  P4 预测模型：合并结果 = f(静态元数据) / f(+24h 早期信号)，HistGradientBoosting + GroupKFold(仓)，AUC + 置换重要度
  P5 聚类与异常：GMM/KMeans（轮廓系数/BIC 选 k）+ IsolationForest
  P6 网络：评论者—仓二部图度分布（幂律）、回流集中度（HHI/Gini）
  P7 文本：TF-IDF + KMeans（评论簇与词表）
  P8 配对估计：仓内按 PR 编号近邻配对，估计"有合并前评论"对 log(合并时滞) 的效应（bootstrap CI）

输出：data/results/mine_patterns_20261029.json
"""
import json
import glob
import os
import re
import math
import collections
import datetime
import statistics

import numpy as np
from scipy import stats
from scipy.optimize import minimize
from sklearn.ensemble import HistGradientBoostingClassifier, IsolationForest
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.metrics import roc_auc_score
from sklearn.cluster import KMeans
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.inspection import permutation_importance

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = r"E:\temp\opencode"
COL = os.path.join(ROOT, "external_data", "collected_20261024")
OUT = os.path.join(ROOT, "data", "results", "mine_patterns_20261029.json")
RNG = np.random.default_rng(20261029)
NOW = datetime.datetime(2026, 10, 28, tzinfo=datetime.timezone.utc)


def iso(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


R = {"generated_at": datetime.datetime.now().isoformat(timespec="seconds")}

# ---------------- 数据装载 ----------------
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

links_by_parent = {p: row.get("links") or [] for p, row in best.items()}
all_links = [(p, l) for p, ls in links_by_parent.items() for l in ls]

# PR 表（评论层 + 标题层 join）
pr_rows = []
for line in open(os.path.join(TMP, "pr_comments.jsonl"), encoding="utf-8", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get("type") != "repo":
        continue
    for pr in d.get("prs") or []:
        pr["_repo"] = d["repo"]
        pr_rows.append(pr)

title_map = {}
for fn in ("pr_merged.jsonl", "pr_merged_retry.jsonl", "pr_merged_retry3.jsonl", "pr_merged_fix.jsonl"):
    for path in (os.path.join(COL, fn), os.path.join(TMP, fn)):
        if not os.path.exists(path):
            continue
        for line in open(path, encoding="utf-8", errors="replace"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("type") != "repo":
                continue
            for p in d.get("pulls") or []:
                title_map[(d["repo"], p.get("number"))] = p

# ---------------- P1 重尾分布 ----------------
def pl_mle(x, xmin):
    x = np.asarray([v for v in x if v >= xmin], dtype=float)
    n = len(x)
    if n < 20:
        return None
    alpha = 1 + n / np.sum(np.log(x / xmin))
    # KS
    xs = np.sort(x)
    cdf_emp = np.arange(1, n + 1) / n
    cdf_fit = 1 - (xs / xmin) ** (1 - alpha)
    D = float(np.max(np.abs(cdf_emp - cdf_fit)))
    ll = float(n * np.log(alpha - 1) + (alpha - 1) * n * np.log(xmin) - alpha * np.sum(np.log(x)))
    return alpha, D, ll, n, xmin


def fit_heavy_tail(vals, name):
    vals = [float(v) for v in vals if v and v > 0]
    out = {"n": len(vals)}
    if len(vals) < 30:
        out["note"] = "样本不足"
        return out
    arr = np.array(vals)
    uniq = np.unique(arr)
    cand = uniq[max(0, int(len(uniq) * 0.1)):int(len(uniq) * 0.9):max(1, len(uniq) // 20)]
    best_fit = None
    for xm in cand:
        f = pl_mle(arr, xm)
        if f and (best_fit is None or f[1] < best_fit[1]):
            best_fit = f
    if not best_fit:
        out["note"] = "幂律拟合失败"
        return out
    alpha, D, ll_pl, n_tail, xmin = best_fit
    # 对数正态（同尾样本）
    tail = arr[arr >= xmin]
    s, loc, scale = stats.lognorm.fit(tail, floc=0)
    ll_ln = float(np.sum(stats.lognorm.logpdf(tail, s, loc=0, scale=scale)))
    # 指数
    loc_e, scale_e = 0, float(np.mean(tail))
    ll_exp = float(np.sum(stats.expon.logpdf(tail, loc=0, scale=scale_e)))
    out.update({
        "powerlaw": {"alpha": round(float(alpha), 3), "xmin": float(xmin), "ks": round(D, 4),
                     "n_tail": int(n_tail), "loglik": round(ll_pl, 1)},
        "lognormal": {"mu_sigma": [round(float(np.log(scale)), 3), round(float(s), 3)],
                      "loglik": round(ll_ln, 1)},
        "exponential": {"loglik": round(ll_exp, 1)},
        "best_by_loglik": max([("powerlaw", ll_pl), ("lognormal", ll_ln), ("exponential", ll_exp)],
                              key=lambda kv: kv[1])[0],
        "delta_ll_ln_minus_pl": round(ll_ln - ll_pl, 1),
    })
    return out


P1 = {}
P1["parent_returning_forks"] = fit_heavy_tail(
    [len({l.get("fork") or l.get("author") for l in ls}) for ls in links_by_parent.values()],
    "回流 fork/父仓")
P1["parent_pr_events"] = fit_heavy_tail([len(ls) for ls in links_by_parent.values()], "PR事件/父仓")
P1["comment_thread_len"] = fit_heavy_tail(
    [len(pr.get("comments") or []) for pr in pr_rows], "评论数/PR")
P1["comment_chars"] = fit_heavy_tail(
    [len(c.get("body") or "") for pr in pr_rows for c in (pr.get("comments") or [])], "评论字符")
P1["author_pr_events"] = fit_heavy_tail(
    list(collections.Counter(l.get("author") for _, l in all_links if l.get("author")).values()),
    "回流PR/作者")
R["P1_heavy_tails"] = P1

# ---------------- P2 点过程 ----------------
P2 = {}
# 每日事件序列（全生态）
daily = collections.Counter()
for _, l in all_links:
    t = iso(l.get("created_at"))
    if t and t.year >= 2025:
        daily[t.date()] += 1
if daily:
    d0, d1 = min(daily), max(daily)
    span = (d1 - d0).days + 1
    series = np.array([daily.get(d0 + datetime.timedelta(days=i), 0) for i in range(span)], float)
    mu, sd = series.mean(), series.std()
    P2["daily_series"] = {"from": str(d0), "to": str(d1), "days": span,
                          "mean": round(float(mu), 1), "fano_factor": round(float(sd ** 2 / mu), 1),
                          "burstiness_B": round(float((sd - mu) / (sd + mu)), 3)}
    # 自相关 lag1..14
    ac = [round(float(np.corrcoef(series[:-k], series[k:])[0, 1]), 3) for k in range(1, 15)]
    P2["daily_autocorr_lag1_14"] = ac
# 大仓间隔时间
big = sorted(links_by_parent.items(), key=lambda kv: -len(kv[1]))[:5]
ie = {}
for p, ls in big:
    ts = sorted(t for t in (iso(l.get("created_at")) for l in ls) if t)
    if len(ts) < 100:
        continue
    gaps = np.array([(b - a).total_seconds() / 3600 for a, b in zip(ts, ts[1:]) if b > a])
    if len(gaps) < 50:
        continue
    cv = gaps.std() / gaps.mean()
    B = (gaps.std() - gaps.mean()) / (gaps.std() + gaps.mean())
    ie[p] = {"n_events": len(ts), "gap_median_h": round(float(np.median(gaps)), 3),
             "cv": round(float(cv), 2), "burstiness_B": round(float(B), 3)}
P2["inter_event_top_repos"] = ie
# 昼夜/星期
hours = collections.Counter()
week = collections.Counter()
for _, l in all_links:
    t = iso(l.get("created_at"))
    if t:
        hours[t.hour] += 1
        week[t.weekday()] += 1
tot = sum(hours.values())
hcounts = np.array([hours.get(h, 0) for h in range(24)], float)
chi2_h = float(((hcounts - hcounts.mean()) ** 2 / hcounts.mean()).sum())
wcounts = np.array([week.get(w, 0) for w in range(7)], float)
chi2_w = float(((wcounts - wcounts.mean()) ** 2 / wcounts.mean()).sum())
P2["seasonality"] = {
    "hour_pct": {h: round(100 * hours.get(h, 0) / tot, 1) for h in range(24)},
    "weekday_pct": {w: round(100 * week.get(w, 0) / tot, 1) for w in range(7)},
    "chi2_hour_df23": round(chi2_h, 0), "chi2_week_df6": round(chi2_w, 0),
    "peak_hour_utc": int(hcounts.argmax()), "trough_hour_utc": int(hcounts.argmin()),
    "peak_weekday": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][int(wcounts.argmax())],
}
# 合并时滞间隔分布（hours）重尾拟合
lat = []
for pr in pr_rows:
    t0, tm = iso(pr.get("created_at")), iso(pr.get("merged_at"))
    if t0 and tm and tm >= t0:
        lat.append((tm - t0).total_seconds() / 3600 + 1e-3)
P2["merge_latency_fit"] = fit_heavy_tail(lat, "合并时滞(小时)")
R["P2_point_process"] = P2

# ---------------- P3 生存分析（time-to-merge） ----------------
P3 = {}
dur = []
for pr in pr_rows:
    t0 = iso(pr.get("created_at"))
    if not t0:
        continue
    tm, tc = iso(pr.get("merged_at")), iso(pr.get("closed_at"))
    if tm:
        dur.append(((tm - t0).total_seconds() / 3600, 1))
    elif tc:
        dur.append(((tc - t0).total_seconds() / 3600, 0))
    else:
        dur.append(((NOW - t0).total_seconds() / 3600, 0))
T = np.array([max(0.01, x[0]) for x in dur])
E = np.array([x[1] for x in dur], int)


def km_median(T, E):
    order = np.argsort(T)
    T, E = T[order], E[order]
    n = len(T)
    surv = 1.0
    for i in range(n):
        if E[i] == 1:
            at_risk = n - i
            surv *= (1 - 1 / at_risk)
            if surv <= 0.5:
                return float(T[i])
    return None


def logrank(T, E, G):
    # 两组对数秩检验（Mantel–Haenszel）
    df = sorted(set(G))
    if len(df) != 2:
        return None
    times = sorted(set(T[E == 1]))
    O1 = E1 = V = 0.0
    for t in times:
        risk = T >= t
        n = risk.sum()
        n1 = (risk & (G == df[0])).sum()
        d = ((T == t) & (E == 1)).sum()
        d1 = ((T == t) & (E == 1) & (G == df[0])).sum()
        if n <= 1:
            continue
        O1 += d1
        E1 += d * n1 / n
        V += d * (n1 / n) * (1 - n1 / n) * (n - d) / (n - 1)
    if V <= 0:
        return None
    chi2 = (O1 - E1) ** 2 / V
    p = float(stats.chi2.sf(chi2, 1))
    return round(float(chi2), 2), round(p, 5)


groups = {}
Gc = []
Gr = []
Gbot = []
for pr in pr_rows:
    n_com = len(pr.get("comments") or [])
    has_rev = any((rv.get("state") or "").upper() in ("APPROVED", "CHANGES_REQUESTED") for rv in (pr.get("reviews") or []))
    Gc.append(1 if n_com > 0 else 0)
    Gr.append(1 if has_rev else 0)
    Gbot.append(1 if re.search(r"(\[bot\]$|^dependabot|^renovate|^github-actions)", pr.get("author") or "", re.I) else 0)
Gc, Gr, Gbot = np.array(Gc), np.array(Gr), np.array(Gbot)
m_all = km_median(T, E)
res3 = {"n": int(len(T)), "events": int(E.sum()), "median_merge_h_all": round(m_all, 2) if m_all else None}
for name, G in (("comment", Gc), ("review", Gr), ("bot_author", Gbot)):
    lr = logrank(T, E, G)
    mA = km_median(T[G == 0], E[G == 0])
    mB = km_median(T[G == 1], E[G == 1])
    res3[name] = {"logrank_chi2_p": lr,
                  "km_median_h_group0": round(mA, 2) if mA else None,
                  "km_median_h_group1": round(mB, 2) if mB else None,
                  "n1": int((G == 1).sum())}
# Cox（若有 statsmodels）
try:
    from statsmodels.duration.hazard_regression import PHReg
    repo_ids = {r: i for i, r in enumerate(sorted({pr["_repo"] for pr in pr_rows}))}
    exog = np.column_stack([np.ones(len(pr_rows)), Gc, Gr])
    grp = np.array([repo_ids[pr["_repo"]] for pr in pr_rows])
    model = PHReg(T, exog, status=E, groups=grp)
    fit = model.fit(disp=0)
    res3["cox"] = {"coef_has_comment": round(float(fit.params[1]), 3),
                   "coef_has_review": round(float(fit.params[2]), 3),
                   "p_has_comment": round(float(fit.pvalues[1]), 6),
                   "p_has_review": round(float(fit.pvalues[2]), 6),
                   "note": "按仓聚类稳健 SE；时间单位=小时"}
except Exception as e:
    res3["cox"] = {"error": str(e)[:120]}
P3.update(res3)
R["P3_survival"] = P3

# ---------------- P4 预测模型 ----------------
P4 = {}
feat_static = []
feat_early = []
y = []
groups4 = []
rows4 = []
for pr in pr_rows:
    tm = iso(pr.get("merged_at"))
    t0 = iso(pr.get("created_at"))
    if tm is None and iso(pr.get("closed_at")) is None:
        continue  # 未结案不参与
    meta = title_map.get((pr["_repo"], pr.get("number"))) or {}
    title = meta.get("title") or ""
    labels = meta.get("labels") or []
    user_type = meta.get("user_type") or "User"
    num = pr.get("number") or 0
    # 早期信号：创建后 24h 内的评论/审查
    first24 = t0 + datetime.timedelta(hours=24) if t0 else None
    nc24 = sum(1 for c in (pr.get("comments") or [])
               if iso(c.get("created_at")) and first24 and iso(c.get("created_at")) <= first24)
    nr24 = sum(1 for r in (pr.get("reviews") or [])
               if iso(r.get("submitted_at")) and first24 and iso(r.get("submitted_at")) <= first24)
    pref = 1 if re.match(r"^(feat|fix|chore|docs|refactor|test|ci|perf|build|style|revert)(\(|:|！|!)", title, re.I) else 0
    rows4.append({
        "repo": pr["_repo"], "num": num,
        "title_len": len(title), "has_cjk_title": 1 if re.search(r"[\u4e00-\u9fff]", title) else 0,
        "conv_prefix": pref, "n_labels": len(labels), "is_bot": 1 if user_type == "Bot" else 0,
        "nc24": nc24, "nr24": nr24,
    })
    y.append(1 if tm else 0)
    groups4.append(pr["_repo"])
import pandas as pd
DF = pd.DataFrame(rows4)
Y = np.array(y)
G4 = np.array(groups4)


def cv_auc(Xdf, y, groups, model_fn):
    aucs = []
    gkf = GroupKFold(n_splits=5)
    for tr, te in gkf.split(Xdf, y, groups):
        m = model_fn()
        m.fit(Xdf.iloc[tr], y[tr])
        p = m.predict_proba(Xdf.iloc[te])[:, 1]
        if len(set(y[te])) > 1:
            aucs.append(roc_auc_score(y[te], p))
    return aucs


base_cols = ["num", "title_len", "has_cjk_title", "conv_prefix", "n_labels", "is_bot"]
early_cols = base_cols + ["nc24", "nr24"]
Xb = DF[base_cols].copy()
Xb["num"] = np.log1p(Xb["num"])
Xe = DF[early_cols].copy()
Xe["num"] = np.log1p(Xe["num"])
auc_b = cv_auc(Xb, Y, G4, lambda: HistGradientBoostingClassifier(max_iter=200, random_state=0))
auc_e = cv_auc(Xe, Y, G4, lambda: HistGradientBoostingClassifier(max_iter=200, random_state=0))
P4["predict_merge"] = {
    "n": int(len(Y)), "merged": int(Y.sum()),
    "auc_static_only": {"mean": round(float(np.mean(auc_b)), 3), "folds": [round(a, 3) for a in auc_b]},
    "auc_static_plus_24h": {"mean": round(float(np.mean(auc_e)), 3), "folds": [round(a, 3) for a in auc_e]},
    "note": "GroupKFold(仓)；静态=编号/标题/标签/账号类型；24h=+创建后24h内评论与审查数",
}
# 置换重要度（全量拟合后）
m = HistGradientBoostingClassifier(max_iter=200, random_state=0).fit(Xe, Y)
pi = permutation_importance(m, Xe, Y, n_repeats=5, random_state=0, scoring="roc_auc")
P4["permutation_importance"] = {c: round(float(v), 4) for c, v in zip(early_cols, pi.importances_mean)}
R["P4_prediction"] = P4

# ---------------- P5 聚类与异常 ----------------
P5 = {}
meta = json.load(open(os.path.join(ROOT, "data", "repos_meta.json"), encoding="utf-8"))
lm = {}
for line in open(os.path.join(COL, "local_mining.jsonl"), encoding="utf-8", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get("type") == "repo":
        lm[d["repo"]] = d
inst = {}
for line in open(os.path.join(COL, "market_full.jsonl"), encoding="utf-8", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get("type") == "skills_sh":
        inst[d.get("repo")] = d.get("total_installs") or 0
feat = []
names = []
for repo, row in best.items():
    mm = meta.get(repo)
    if not mm:
        continue
    links = row.get("links") or []
    nf = row.get("n_forks") or 1
    ret = len({l.get("fork") or l.get("author") for l in links})
    merged = sum(1 for l in links if l.get("merged_at"))
    n_com = sum(len(r.get("comments") or []) for r in [])
    feat.append([
        math.log10(max(1, mm.get("stars") or 1)),
        math.log10(max(1, nf)),
        ret / nf if nf else 0,
        merged / len(links) if links else 0,
        math.log10(max(1, inst.get(repo, 0) + 1)),
        (lm.get(repo, {}) or {}).get("share_cross") or 0,
        math.log10(max(1, (lm.get(repo, {}) or {}).get("n_skills") or 1)),
    ])
    names.append(repo)
X5 = np.array(feat)
if len(X5) >= 40:
    Z = StandardScaler().fit_transform(X5)
    ks = []
    for k in range(2, 8):
        km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(Z)
        ks.append({"k": k, "silhouette": round(float(
            __import__("sklearn.metrics", fromlist=["silhouette_score"]).silhouette_score(Z, km.labels_)), 3),
                   "inertia": round(float(km.inertia_), 1)})
    best_k = max(ks, key=lambda x: x["silhouette"])["k"]
    km = KMeans(n_clusters=best_k, n_init=10, random_state=0).fit(Z)
    prof = []
    for c in range(best_k):
        idx = np.where(km.labels_ == c)[0]
        prof.append({"cluster": c, "n": int(len(idx)),
                     "mean_features": {n: round(float(X5[idx, i].mean()), 2) for i, n in enumerate(
                         ["log10_stars", "log10_forks", "conversion", "merge_rate", "log10_installs",
                          "share_cross", "log10_skills"])},
                     "examples": [names[i] for i in idx[:3]]})
    iso_f = IsolationForest(contamination=0.05, random_state=0).fit(Z)
    anom = np.argsort(iso_f.score_samples(Z))[:8]
    P5 = {"n_repos": len(X5), "k_search": ks, "best_k": best_k, "clusters": prof,
          "anomalies_top8": [names[i] for i in anom]}
else:
    P5 = {"n_repos": len(X5), "note": "样本不足"}
R["P5_clustering"] = P5

# ---------------- P6 网络 ----------------
P6 = {}
commenter_repos = collections.defaultdict(set)
comment_count = collections.Counter()
BOT = re.compile(r"(\[bot\]$|-bot$|^dependabot|^renovate|^github-actions|^codecov|^greenkeeper|^mergify|^imgbot|^allcontributors)", re.I)
for pr in pr_rows:
    for c in pr.get("comments") or []:
        a = c.get("author") or ""
        if not a or BOT.match(a):
            continue
        commenter_repos[a].add(pr["_repo"])
deg = [len(v) for v in commenter_repos.values()]
P6["commenter"] = {"n_commenters": len(deg),
                   "degree_median": int(np.median(deg)) if deg else None,
                   "degree_p90": int(np.percentile(deg, 90)) if deg else None,
                   "degree_max": int(max(deg)) if deg else None,
                   "single_repo_pct": round(100 * sum(1 for d in deg if d == 1) / max(1, len(deg)), 1),
                   "fit_degree": fit_heavy_tail(deg, "评论者跨仓度")}
# 回流集中度 HHI（父仓层）
hhi = []
for p, ls in links_by_parent.items():
    c = collections.Counter(l.get("author") for l in ls)
    tot = sum(c.values())
    if tot >= 20:
        hhi.append(sum((v / tot) ** 2 for v in c.values()))
P6["return_hhi"] = {"n": len(hhi), "median": round(float(np.median(hhi)), 3) if hhi else None,
                    "p90": round(float(np.percentile(hhi, 90)), 3) if hhi else None}
R["P6_network"] = P6

# ---------------- P7 文本 ----------------
P7 = {}
texts = []
for pr in pr_rows:
    for c in pr.get("comments") or []:
        a = c.get("author") or ""
        b = (c.get("body") or "").strip()
        if BOT.match(a) or len(b) < 20:
            continue
        texts.append(b[:2000])
if len(texts) >= 500:
    sample = texts if len(texts) <= 30000 else [texts[i] for i in RNG.choice(len(texts), 30000, replace=False)]
    vec = TfidfVectorizer(max_features=1500, min_df=20, token_pattern=r"[A-Za-z]{3,}|[\u4e00-\u9fff]{1,4}",
                          sublinear_tf=True)
    Xt = vec.fit_transform(sample)
    k = 6
    kmt = KMeans(n_clusters=k, n_init=5, random_state=0).fit(Xt)
    terms = np.array(vec.get_feature_names_out())
    clusters = []
    for c in range(k):
        idx = np.where(kmt.labels_ == c)[0]
        centroid = Xt[idx].mean(axis=0).A1
        top = terms[np.argsort(-centroid)[:10]]
        clusters.append({"cluster": c, "n": int(len(idx)), "share_pct": round(100 * len(idx) / len(sample), 1),
                         "top_terms": list(top)})
    P7 = {"n_texts": len(sample), "k": k, "clusters": clusters}
else:
    P7 = {"n_texts": len(texts), "note": "样本不足"}
R["P7_text"] = P7

# ---------------- P8 配对估计 ----------------
P8 = {}
# 仓内最近邻配对：合并 PR，有合并前评论（处理）vs 无（对照），按 PR 编号差
by_repo = collections.defaultdict(list)
for pr in pr_rows:
    tm = iso(pr.get("merged_at"))
    t0 = iso(pr.get("created_at"))
    if not tm or not t0:
        continue
    pre = [c for c in (pr.get("comments") or [])
           if iso(c.get("created_at")) and iso(c.get("created_at")) <= tm]
    by_repo[pr["_repo"]].append({
        "num": pr.get("number") or 0,
        "lat": math.log(max(0.01, (tm - t0).total_seconds() / 3600)),
        "treated": 1 if pre else 0,
    })
pairs = []
for repo, rows in by_repo.items():
    if len(rows) < 20:
        continue
    tr = [r for r in rows if r["treated"]]
    co = [r for r in rows if not r["treated"]]
    if not tr or not co:
        continue
    co_nums = np.array([r["num"] for r in co])
    used = set()
    for r in tr:
        order = np.argsort(np.abs(co_nums - r["num"]))
        for j in order[:10]:
            if j in used:
                continue
            if abs(co_nums[j] - r["num"]) <= max(20, 0.02 * max(1, r["num"])):
                used.add(j)
                pairs.append((r["lat"] - co[j]["lat"], repo))
            break
if len(pairs) >= 30:
    diffs = np.array([p[0] for p in pairs])
    boots = []
    for _ in range(1000):
        idx = RNG.integers(0, len(diffs), len(diffs))
        boots.append(np.median(diffs[idx]))
    P8 = {"n_pairs": len(pairs), "n_repos": len({p[1] for p in pairs}),
          "median_delta_log_latency": round(float(np.median(diffs)), 3),
          "mean_delta": round(float(diffs.mean()), 3),
          "ci95_median": [round(float(np.percentile(boots, 2.5)), 3),
                          round(float(np.percentile(boots, 97.5)), 3)],
          "exp_median_ratio": round(float(math.exp(np.median(diffs))), 2),
          "note": "Δ=log(时滞)_有评论−log(时滞)_无评论；仓内按 PR 编号近邻 1:1 配对；正=评论使合并更慢"}
else:
    P8 = {"n_pairs": len(pairs), "note": "配对不足"}
R["P8_matched_estimate"] = P8

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(R, f, ensure_ascii=False, indent=1)
print(json.dumps({k: R[k] for k in ("P1_heavy_tails", "P2_point_process", "P3_survival")},
                 ensure_ascii=False, indent=1)[:4000])
print("written:", OUT)
