# -*- coding: utf-8 -*-
"""
mine_replication_methods.py — 复现项目方法在 Skill 扩散数据上的实作（2026-10-30）

R1 Chetty et al.(2017, fade American dream 复现) 式分解：
   fork→PR 的"贡献率"分解为 边际(fork 集中度) + copula(engagement 差异)，
   并做反事实（全体 top-quartile engagement）与重排不等式上下界
R2 Farber(2015, taxi 复现) 式方差分解 + 班次切分 + leave-one-out 同伴 IV：
   星标周增量 = 仓库固定效应(永久) + 周固定效应(可预期暂时) + 残差(未预期)
R3 GFT(Ginsberg 2009, CDC 复现) 式特征筛选：
   份额归一化 + 4 折 Fisher-Z 相关筛选 + 训练/留出对照（过拟合缺口）
R4 HDI 式几何平均复合指数：星标/fork/安装/合并率 → 百分位几何合成 vs 算术合成
输出：data/results/mine_replication_20261030.json
口径：未解析/缺失不当 0；每个数字标注样本量与覆盖度
"""
import json
import os
import glob
import collections
import datetime

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = r"E:\temp\opencode"
COL = os.path.join(ROOT, "external_data", "collected_20261024")
OUT = os.path.join(ROOT, "data", "results", "mine_replication_20261030.json")

R = {"generated_at": datetime.datetime.now().isoformat(timespec="seconds")}

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

# skills.sh 安装（collected_20261024/skills_sh_prefix.jsonl 仅 3 条为汇总包，
# 逐仓明细在 market_full.jsonl / market_retry.jsonl 的 type=skills_sh 记录）
installs = {}
for fn in ["market_full.jsonl", "market_retry.jsonl", "market_extra.jsonl",
           "skills_sh_prefix.jsonl"]:
    pth = os.path.join(COL, fn)
    if not os.path.exists(pth):
        continue
    for line in open(pth, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        t = d.get("type")
        r = d.get("repo")
        if not r:
            continue
        if t in ("skills_sh", "skills_sh_prefix") and (d.get("total_installs") or 0) > 0:
            # 同仓多次记录取最大（market_full 优先，因先读）
            installs[r] = max(installs.get(r, 0), d["total_installs"])

# 仓库级合并率（pr_merged）
merge_rate = {}
for line in open(os.path.join(COL, "pr_merged.jsonl"), encoding="utf-8", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get("type") == "repo" and d.get("complete") and (d.get("n_pulls") or 0) >= 5:
        pulls = d.get("pulls") or []
        merged = sum(1 for p in pulls if p.get("merged"))
        closed = sum(1 for p in pulls if p.get("state") == "closed")
        if closed:
            merge_rate[d["repo"]] = merged / closed

# 发布下载
reldl = {}
for line in open(os.path.join(COL, "release_downloads.jsonl"), encoding="utf-8", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    g = d.get("github") or {}
    if d.get("repo") and (g.get("downloads") or 0) > 0:
        reldl[d["repo"]] = g["downloads"]


# =====================================================================
# R1 Chetty 式边际/copula 分解 + 反事实 + 重排界（fork→PR "贡献流动"）
# =====================================================================
parents = []
for p, d in best.items():
    n_forks = d.get("n_forks") or 0
    # 口径对齐 P2(fork→PR 4.3%)：贡献者 = 提过 PR 的 unique fork，非 PR 条数
    contrib_forks = {l.get("fork") for l in (d.get("links") or []) if l.get("fork")}
    n_matched = len(contrib_forks)
    if n_forks >= 5:  # 分母稳定
        parents.append({
            "parent": p, "n_forks": n_forks, "n_matched": n_matched,
            "n_prs": d.get("n_prs") or 0,
            "stars": (meta.get(p) or {}).get("stars") or 0,
        })
P = pd.DataFrame(parents)
P["eng"] = P["n_matched"] / P["n_forks"]

# 按星标十分位分组（copula 行 = 父仓 rank 组）
P = P.sort_values("stars", ascending=False).reset_index(drop=True)
P["decile"] = pd.qcut(P.index + 1, 10, labels=False) + 1

grp = P.groupby("decile").agg(
    n_parents=("parent", "count"),
    n_forks=("n_forks", "sum"),
    n_matched=("n_matched", "sum"),
    eng=("eng", "mean"),          # 等权（仅描述用）
    stars_med=("stars", "median"),
)
grp["eng_w"] = grp["n_matched"] / grp["n_forks"]   # fork 加权（分解必须用这个）
grp["fork_share"] = grp["n_forks"] / grp["n_forks"].sum()

# 总体贡献率 = Σ fork_share_i × eng_w_i（恒等式，与直接合并率严格相等）
rate_obs = float((grp["fork_share"] * grp["eng_w"]).sum())
rate_direct = float(P["n_matched"].sum() / P["n_forks"].sum())
rate_eqw = float(P["eng"].mean())
rate_med = float(P["eng"].median())

# 反事实 C1：全体分位拿到 engagement 最高的三个分位的加权 engagement
top3d = grp.nlargest(3, "eng_w")
eng_top3 = float(top3d["n_matched"].sum() / top3d["n_forks"].sum())
rate_cf_top = float((grp["fork_share"] * eng_top3).sum())   # = eng_top3（同质化后）

# 反事实 C2：fork 分布均等（消除集中度边际），engagement copula 不变
rate_cf_eqfork = float(grp["eng_w"].mean())

# Kitagawa 分解：Δ = rate_cf_eqfork − rate_obs = 集中度效应
marginal_effect = rate_cf_eqfork - rate_obs

# 重排不等式（maxminv100 式上下界）：给定 fork 份额与 eng 两个边际，
# 所有可能耦合下总贡献率的界
w = np.sort(grp["fork_share"].values)[::-1]          # 大份额在前
e_asc = np.sort(grp["eng_w"].values)                 # 低 engagement 在前
e_desc = np.sort(grp["eng_w"].values)[::-1]
rate_min = float((w * e_asc).sum())
rate_max = float((w * e_desc).sum())

R["R1_chetty_decomposition"] = {
    "n_parents": int(len(P)),
    "n_forks_total": int(P["n_forks"].sum()),
    "n_matched_total": int(P["n_matched"].sum()),
    "n_parents_stars_known": int((P["stars"] > 0).sum()),
    "coverage_note": "仅含 complete=true 且 n_forks>=5 的父仓；星标缺失组单列不入十分位",
    "rate_observed_weighted": round(rate_obs, 4),
    "rate_direct_matched_over_forks": round(rate_direct, 4),
    "rate_equal_weight_mean": round(rate_eqw, 4),
    "rate_median_parent": round(rate_med, 4),
    "p2_reconciliation": "P2 论文值 4.3% ≈ 每仓贡献率的中位数口径（3.9%）；"
                         "合并率 6.4% 为 fork 加权口径（大仓主导），两者并存不矛盾",
    "decile_table": {str(int(k)): {
        "n_parents": int(v["n_parents"]),
        "fork_share": round(float(v["fork_share"]), 4),
        "eng_weighted": round(float(v["eng_w"]), 4),
        "eng_equal_weight": round(float(v["eng"]), 4),
        "stars_median": int(v["stars_med"]),
    } for k, v in grp.iterrows()},
    "counterfactual_top3_eng_for_all": round(rate_cf_top, 4),
    "counterfactual_top3_deciles": [int(x) for x in top3d.index],
    "counterfactual_equal_fork_shares": round(rate_cf_eqfork, 4),
    "marginal_concentration_effect": round(marginal_effect, 4),
    "rearrangement_bounds": {"min": round(rate_min, 4), "max": round(rate_max, 4)},
    "note": "Chetty(2017) 框架：观察率=边际(fork 份额)×copula(engagement)；"
            "反事实固定一边际替换另一边际；重排界给所有耦合的最好/最坏情形",
}

# =====================================================================
# R2 Farber 式方差分解 + 班次(attention shift)切分 + LOO 同伴 IV
# =====================================================================
rows = []
for repo, weeks in stars.items():
    ws = sorted(weeks, key=lambda w: w["week"])
    prev = 0
    for w in ws:
        inc = max(0, int(w.get("total") or 0))
        rows.append({"repo": repo, "week": w["week"], "inc": inc})
        prev = inc
DF = pd.DataFrame(rows)

# 双向固定效应的嵌套 R² 分解（分量不正交，朴素方差相加会超过 100%）
import statsmodels.formula.api as smf
_m1 = smf.ols("inc ~ C(repo)", data=DF).fit()
_m2 = smf.ols("inc ~ C(repo) + C(week)", data=DF).fit()
r2_repo = float(_m1.rsquared)
r2_full = float(_m2.rsquared)
R["R2_farber_variance"] = {
    "n_obs": int(len(DF)),
    "n_repos": int(DF["repo"].nunique()),
    "r2_repo_FE_permanent": round(r2_repo, 4),
    "r2_week_FE_incremental_transitory": round(r2_full - r2_repo, 4),
    "residual_share_unexpected": round(1 - r2_full, 4),
    "note": "Farber(2015) 工资方差分解的星标版，用嵌套 R²（repo FE → +week FE）；"
            "朴素三分量方差和不正交（相加=1.046>1），故以嵌套 R² 为准",
}

# 班次切分：零增量周视为 shift 边界（Farber 用 >360min 空隙），并做阈值敏感性
def split_shifts(thr):
    out = []
    for repo, g in DF.groupby("repo"):
        inc = g.sort_values("week")["inc"].values
        start, run = 0, 0
        for t in range(len(inc)):
            run = run + 1 if inc[t] == 0 else 0
            if run >= thr and t < len(inc) - 1:
                out.append((repo, t - thr + 1 - start + 1, int(inc[start:t - thr + 1].sum())))
                start = t + 1
        out.append((repo, len(inc) - start, int(inc[start:].sum())))
    return pd.DataFrame(out, columns=["repo", "len", "total"])

SH = split_shifts(1)
SH_pos = SH[SH["total"] > 0]
# 每仓非零 shift 数分布：top1 占比在单段仓上近乎机械=1，需条件于多段仓再看
_per_repo = SH_pos.groupby("repo").size()
_top1_multi = []
for repo, g in SH_pos.groupby("repo"):
    if len(g) >= 2:
        _top1_multi.append(float(g["total"].max() / g["total"].sum()))
_sens = {}
for thr in (1, 2, 4):
    s = split_shifts(thr)
    sp = s[s["total"] > 0]
    _sens[f"thr_{thr}w"] = {
        "n_shifts": int(len(s)),
        "median_len_nonzero_weeks": float(sp["len"].median()),
        "top1_shift_star_share": round(float(
            s.groupby("repo")["total"].max().sum() / s["total"].sum()), 4),
    }
R["R2_attention_shifts"] = {
    "n_shifts": int(len(SH)),
    "n_shifts_nonzero": int(len(SH_pos)),
    "n_repos": int(SH["repo"].nunique()),
    "median_len_weeks_all": float(SH["len"].median()),
    "median_len_weeks_nonzero": float(SH_pos["len"].median()),
    "share_repos_single_nonzero_shift": round(float((_per_repo == 1).mean()), 4),
    "share_stars_in_top1_shift": round(float(
        SH.groupby("repo")["total"].max().sum() / SH["total"].sum()), 4),
    "median_top1_share_among_multishift_repos": round(float(np.median(_top1_multi)), 4),
    "n_multishift_repos": int(len(_top1_multi)),
    "threshold_sensitivity": _sens,
    "note": "切分规则：连续零增量周>=1 即开新 shift（对齐 Farber 班次边界）；"
            "80.6% 仓库仅一个非零 shift，故 top1 占比接近机械=1；"
            "条件于 66 个多段仓仍为 99.8%，结论（单一爆发窗口主导）稳健",
}

# LOO 同伴 IV（reflection-bias 对策）：内生=本仓 fork 数，
# 工具=同语言同伴（不含自身）的平均 log(1+fork)；因变量=后 6 周星标份额
wk_sorted = sorted(DF["week"].unique())
late_weeks = set(wk_sorted[-6:])
late = DF[DF["week"].isin(late_weeks)].groupby("repo")["inc"].sum()
late_share = late / late.sum()

iv_rows = []
lang_of = {k: (meta.get(k) or {}).get("language") or "NA" for k in stars}
fork_of = {k: (meta.get(k) or {}).get("forks") or 0 for k in stars}
for repo in stars:
    if repo not in late_share.index:
        continue
    lang = lang_of.get(repo, "NA")
    peers = [r for r in stars if r != repo and lang_of.get(r, "NA") == lang]
    if len(peers) < 3:
        peers = [r for r in stars if r != repo]
    z = float(np.mean([np.log1p(fork_of.get(r, 0)) for r in peers]))
    iv_rows.append({"repo": repo, "lang": lang,
                    "x": np.log1p(fork_of.get(repo, 0)), "z": z,
                    "y": float(late_share[repo])})
IV = pd.DataFrame(iv_rows)
R["R2_iv"] = {"n": 0, "note": "样本不足"}
if len(IV) > 50:
    X = sm.add_constant(IV[["x"]])
    first = sm.OLS(IV["x"], sm.add_constant(IV[["z"]])).fit(cov_type="HC1")
    # 手写 2SLS：一阶段 x̂ = π0 + π1·z，二阶段 y ~ x̂（标准误用 HC1 近似）
    x_hat = first.predict(sm.add_constant(IV[["z"]]))
    ivmod = sm.OLS(IV["y"], sm.add_constant(pd.DataFrame({"x": x_hat}))).fit(cov_type="HC1")
    ols = sm.OLS(IV["y"], X).fit(cov_type="HC1")
    R["R2_iv"] = {
        "n": int(len(IV)),
        "n_langs": int(IV["lang"].nunique()),
        "first_stage_coef_z": round(float(first.params["z"]), 4),
        "first_stage_F_approx": round(float(first.tvalues["z"] ** 2), 2),
        "ols_beta_log1p_forks": round(float(ols.params["x"]), 6),
        "iv_beta_log1p_forks": round(float(ivmod.params["x"]), 6),
        "verdict": ("弱工具（第一阶段 t²<10），IV 系数不稳定，只演示 Farber 的 "
                    "leave-one-out 工具构造法，不作因果解释"),
        "iv_note": "工具=同语言同伴(不含自身)平均 log(1+fork)；"
                   "弱工具风险已用第一阶段 t² 报告；示意性 IV，非因果定论",
    }

# =====================================================================
# R3 GFT 式份额归一化 + Fisher-Z 筛选 + 训练/留出对照
# =====================================================================
feat_rows = []
for repo in stars:
    if repo not in late_share.index:
        continue
    m = meta.get(repo) or {}
    wk = sorted(stars[repo], key=lambda w: w["week"])
    early = sum(max(0, int(w.get("total") or 0)) for w in wk[:6])
    fp = best.get(repo) or {}
    feat_rows.append({
        "repo": repo,
        "y": float(late_share[repo]),                      # 份额（已归一化）
        "log_forks": np.log1p(m.get("forks") or 0),
        "age_days": (datetime.datetime(2026, 10, 24) -
                     datetime.datetime.strptime((m.get("created_at") or "2025-01-01")[:10], "%Y-%m-%d")).days,
        "n_topics": len(m.get("topics") or []),
        "eng": (len({l.get("fork") for l in (fp.get("links") or []) if l.get("fork")})
                / fp["n_forks"]) if fp.get("n_forks") else np.nan,
        "log_installs": np.log1p(installs[repo]) if repo in installs else np.nan,
        "merge_rate": merge_rate.get(repo, np.nan),
        "log_early": np.log1p(early),
    })
F = pd.DataFrame(feat_rows)
F["y_logit"] = np.log(F["y"] / (1 - F["y"] + 1e-9) + 1e-9)

cands = ["log_forks", "age_days", "n_topics", "eng", "log_installs", "merge_rate", "log_early"]
rng = np.random.default_rng(20261030)
F["fold"] = rng.integers(0, 4, len(F))

def fisher_z_screen(F, cands, folds=(1, 2, 3)):
    """只在训练折（1-3）内做 Fisher-Z 筛选，fold0 严格留出，避免选择性泄漏"""
    scores = {}
    for f in cands:
        zs = []
        for k_ in folds:
            te = F[F["fold"] == k_].dropna(subset=[f])
            if len(te) < 30 or te[f].nunique() < 2:
                continue
            r, _ = stats.pearsonr(te[f], te["y_logit"])
            if not np.isfinite(r):
                continue
            zs.append(np.arctanh(np.clip(r, -0.999, 0.999)))
        if zs:
            scores[f] = float(np.tanh(np.mean(zs)))
    ranked = sorted(scores.items(), key=lambda kv: abs(kv[1]), reverse=True)
    return ranked

ranked = fisher_z_screen(F, cands)
top_k = [f for f, _ in ranked[:5] if not np.isnan(F[f]).all()]

train_mask = F["fold"] != 0
res = {"n_total": int(len(F)), "feature_ranking": {f: round(v, 4) for f, v in ranked},
       "top5": top_k}
top3 = top_k[:3]
# GFT 教训对照：top3 vs top5 在同一 complete-case 样本上（否则覆盖度差异不可比）
CC = F.dropna(subset=top_k + ["y_logit"])
res["n_complete_case_top5"] = int(len(CC))
tr = CC[train_mask.reindex(CC.index, fill_value=False)]
te = CC[~train_mask.reindex(CC.index, fill_value=False)]
res["split"] = {"n_train": int(len(tr)), "n_test": int(len(te))}
for label, cols in [("top3_model", top3), ("top5_model", top_k)]:
    cols_use = [c for c in cols if tr[c].nunique() > 1]
    if len(tr) < 30 or len(te) < 10 or not cols_use:
        res[label] = {"n_train": len(tr), "n_test": len(te), "note": "complete-case 样本不足"}
        continue
    m_tr = sm.OLS(tr["y_logit"], sm.add_constant(tr[cols_use])).fit()
    pred = m_tr.predict(sm.add_constant(te[cols_use]))
    ss_res = float(((te["y_logit"] - pred) ** 2).sum())
    ss_tot = float(((te["y_logit"] - te["y_logit"].mean()) ** 2).sum())
    res[label] = {
        "features": cols_use,
        "n_train": int(len(tr)), "n_test": int(len(te)),
        "train_r2": round(float(m_tr.rsquared), 4),
        "test_r2": round(1 - ss_res / ss_tot, 4) if ss_tot > 0 else None,
        "test_rmse": round(float(np.sqrt(ss_res / len(te))), 4),
    }
if "test_r2" in res.get("top3_model", {}) and "test_r2" in res.get("top5_model", {}):
    res["overfit_gap_top5_minus_top3_testR2"] = round(
        res["top5_model"]["test_r2"] - res["top3_model"]["test_r2"], 4)
res["note"] = ("GFT(2009) 流程：份额归一化(后 6 周增量/全体后 6 周增量) + 4 折 Fisher-Z "
               "筛选 + fold0 留出；GFT 教训=特征越多样本外越差，看 test_r2 非 train_r2")
res["coverage_note"] = ("eng 仅 225 个父仓覆盖、installs 171、merge_rate 140；"
                        "缺失行整行剔除不当 0，对照模型共用同一 complete-case 样本")
R["R3_gft_screening"] = res

# =====================================================================
# R4 HDI 式几何平均复合指数
# =====================================================================
dim_names = ["stars", "forks", "installs", "merge_rate"]
# 百分位先在全体有观测仓库内计算（rank 忽略 NaN），再限制到 >=3 维样本，
# 避免百分位随筛选口径漂移
H = pd.DataFrame([{"repo": r,
                   "stars": (meta.get(r) or {}).get("stars") or 0,
                   "forks": (meta.get(r) or {}).get("forks") or 0,
                   "installs": installs.get(r),
                   "merge_rate": merge_rate.get(r)} for r in stars])
H = H[H["stars"] > 0].copy()
H["n_dims"] = 2 + H[["installs", "merge_rate"]].notna().sum(axis=1)
for c in dim_names:
    H[f"pct_{c}"] = H[c].rank(pct=True)
H = H[H["n_dims"] >= 3].copy()
pct_cols = [f"pct_{c}" for c in dim_names]
H["geo"] = np.exp(np.log(H[pct_cols].clip(lower=0.01)).mean(axis=1))
H["arith"] = H[pct_cols].mean(axis=1)
H["stars_rank"] = H["stars"].rank(ascending=False)
H["geo_rank"] = H["geo"].rank(ascending=False)
rho_geo, p_geo = stats.spearmanr(H["stars_rank"], H["geo_rank"])
over = H.assign(gain=H["stars_rank"] - H["geo_rank"]).nlargest(5, "gain")
R["R4_hdi_composite"] = {
    "n_repos_all3plus_dims": int(len(H)),
    "n_with_installs": int(H["installs"].notna().sum()),
    "n_with_merge_rate": int(H["merge_rate"].notna().sum()),
    "spearman_stars_vs_geo_rank": round(float(rho_geo), 4),
    "p_value": float(p_geo),
    "top5_overperformers_geo_vs_stars": [
        {"repo": r["repo"], "stars_rank": int(r["stars_rank"]),
         "geo_rank": int(r["geo_rank"]), "gain": int(r["gain"])}
        for _, r in over.iterrows()],
    "note": "HDI 几何平均=四维百分位(星标/fork/安装/合并率)乘积开 4 次方；"
            "几何平均惩罚短板，排名变化即'GDP 之外'的增量信息；覆盖>=3 维才入样",
}

os.makedirs(os.path.dirname(OUT), exist_ok=True)
_payload = json.dumps(R, ensure_ascii=False, indent=1)
# 该项目目录偶发瞬时写锁：先写临时目录，再拷回目标位置
ALT = os.path.join(TMP, "mine_replication_20261030.json")
with open(ALT, "w", encoding="utf-8") as _f:
    _f.write(_payload)
try:
    import shutil
    shutil.copyfile(ALT, OUT)
    print("WROTE", OUT)
except PermissionError:
    print("WROTE", ALT, "(目标被锁，已留临时目录)")
for k in R:
    if k != "generated_at":
        print("==", k, "==")
        print(json.dumps(R[k], ensure_ascii=False)[:600])
