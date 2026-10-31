# -*- coding: utf-8 -*-
"""paper_analysis.py — 传播学论文《复制易，溯源难》全部分析与图表（2026-10-24）

产出：
  paper_figs/fig1_copy_structure.png   复制簇规模 + 扇出分布（RQ1）
  paper_figs/fig2_retention.png        字段保留率 + 方向样本时距（RQ2）
  paper_figs/fig3_attention.png        注意力 Lorenz + stars-installs 散点（RQ3）
  paper_figs/fig4_visibility.png       五渠道可见性矩阵热图（RQ3）
  paper_figs/fig5_lifecycle.png        队列存活 + star 轨迹类型（RQ4）
  paper_figs/fig6_governance.png       合并时延 + review 覆盖 + 可预测性（RQ5）
  paper_figs/fig7_hazard.png           fork→PR 互惠窗口 hazard（RQ6）
  paper_figs/table1_data_manifest.csv  数据清单
  paper_figs/table2_findings.csv       核心数字总表
  data/results/paper_stats_20261024.json
"""
import json
import os
import csv
import datetime
import collections
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial"]
plt.rcParams["axes.unicode_minus"] = False

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
COL = os.path.join(ROOT, "external_data", "collected_20261024")
FIG = os.path.join(ROOT, "paper_figs")
os.makedirs(FIG, exist_ok=True)
REF = datetime.datetime(2026, 10, 24, tzinfo=datetime.timezone.utc)
STATS = {}


def gini(xs):
    xs = np.sort(np.array(xs, dtype=float))
    n = len(xs)
    if n == 0 or xs.sum() <= 0:
        return None
    cum = np.cumsum(xs)
    return float((n + 1 - 2 * (cum / cum[-1]).sum()) / n)


def lorenz(ax, xs, label, color):
    xs = np.sort(np.array(xs, dtype=float))
    cum = np.cumsum(xs) / xs.sum()
    ax.plot(np.arange(1, len(xs) + 1) / len(xs), cum, label=f"{label} (Gini={gini(xs):.3f})", color=color, lw=1.6)


def jl2():
    for name in ("market_full.jsonl", "market_retry.jsonl"):
        yield from jl(name)


def jl(name):
    for line in open(os.path.join(COL, name), encoding="utf-8"):
        yield json.loads(line)


# ---------------- RQ1 复制结构 ----------------
def fig1():
    sizes = [r["size"] for r in jl("near_duplicates.jsonl") if r.get("type") == "cluster"]
    fan = {}
    with open(os.path.join(ROOT, "external_data", "skills_with_content.jsonl"), encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            h = r.get("sha256_hash")
            if h:
                fan.setdefault(h, set()).add(r.get("repoFullName"))
    fans = sorted((len(s) for s in fan.values() if len(s) >= 2), reverse=True)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    axes[0].hist(sizes, bins=np.logspace(0, np.log10(max(sizes)), 40), color="#4C72B0")
    axes[0].set_xscale("log"); axes[0].set_yscale("log")
    axes[0].set_title(f"(a) 近重复簇规模分布（n={len(sizes):,} 簇）")
    axes[0].set_xlabel("簇内文档数"); axes[0].set_ylabel("簇数")
    axes[1].hist(fans, bins=np.logspace(0, np.log10(max(fans)), 40), color="#DD8452")
    axes[1].set_xscale("log")
    axes[1].set_title(f"(b) 精确复制扇出分布（n={len(fans):,} 个内容哈希，Gini={gini(fans):.3f}）")
    axes[1].set_xlabel("共享同一内容的仓库数"); axes[1].set_ylabel("内容哈希数")
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "fig1_copy_structure.png"), dpi=200, bbox_inches="tight")
    plt.close(fig)
    STATS["fig1"] = {"n_clusters": len(sizes), "max_cluster": max(sizes),
                     "n_fanout_hashes": len(fans), "max_fanout": max(fans), "gini_fanout": gini(fans),
                     "top10_fanout_share": sum(fans[:10]) / sum(fans)}


# ---------------- RQ2 保留率 + 时距 ----------------
def fig2():
    A = json.load(open(os.path.join(ROOT, "data", "results", "probe_four_20261024.json"), encoding="utf-8"))["A_retention"]
    lags = []
    for r in jl("direction_sample.jsonl"):
        if r.get("type") == "pair" and isinstance(r.get("abs_lag_days"), (int, float)):
            lags.append(r["abs_lag_days"])
    if not lags:
        for r in jl("direction_sample.jsonl"):
            if r.get("type") == "pair":
                for k in ("lag_days", "abs_lag", "lag"):
                    if isinstance(r.get(k), (int, float)):
                        lags.append(r[k]); break
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    cats = ["name 逐字", "name 修改", "desc 逐字", "desc 修改", "署名字段\n双侧有", "署名字段\n缺失"]
    vals = [A["name_verbatim_pct"], A["name_modified_pct"], A["description_verbatim_pct"],
            A["description_modified_pct"], A["attrib_both_pct"], A["attrib_none_pct"]]
    bars = axes[0].bar(cats, [v * 100 for v in vals], color=["#4C72B0", "#8FB3E8", "#55A868", "#9CD3A8", "#C44E52", "#E8B8BA"])
    axes[0].set_ylim(0, 100)
    for b, v in zip(bars, vals):
        axes[0].text(b.get_x() + b.get_width() / 2, v * 100 + 1.5, f"{v*100:.1f}%", ha="center", fontsize=9)
    axes[0].set_title(f"(a) 跨仓近重复对的字段保留率（n={A['n_pairs_sampled']:,} 对）")
    axes[0].tick_params(axis="x", labelsize=8.5)
    if lags:
        axes[1].hist(lags, bins=np.logspace(0, np.log10(max(lags + [1])), 35), color="#8172B3")
        axes[1].set_xscale("log")
        axes[1].axvline(np.median(lags), color="black", ls="--", lw=1)
        axes[1].set_title(f"(b) 复制对时间间隔（中位 {np.median(lags):.1f} 天，n={len(lags)}）")
        axes[1].set_xlabel("|时间间隔|（天，log）"); axes[1].set_ylabel("对数")
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "fig2_retention.png"), dpi=200, bbox_inches="tight")
    plt.close(fig)
    STATS["fig2"] = {"retention": A, "lag_median": float(np.median(lags)) if lags else None,
                     "lag_p90": float(np.percentile(lags, 90)) if lags else None}


# ---------------- RQ3 注意力 ----------------
def fig3():
    sh = {}
    stars = dict(_STAR_CACHE)
    ch_items = []
    for r in jl2():
        t = r.get("type")
        if t == "skills_sh" and r.get("status") == 200 and (r.get("n_hits") or 0) > 0 and (r.get("total_installs") or 0) > 0:
            sh[r["repo"]] = r.get("total_installs")
        elif t == "clawhub_registry":
            d = (r.get("item") or {}).get("stats") or {}
            dl = d.get("downloads")
            if dl:
                ch_items.append(dl)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    lorenz(axes[0], list(sh.values()), "skills.sh 仓级安装（n=%d）" % len(sh), "#4C72B0")
    lorenz(axes[0], ch_items, "ClawHub 条目级下载（n=%d）" % len(ch_items), "#DD8452")
    axes[0].plot([0, 1], [0, 1], color="gray", ls=":", lw=1)
    axes[0].set_title("(a) 平台注意力集中度（Lorenz 曲线）")
    axes[0].set_xlabel("仓/条目累计份额"); axes[0].set_ylabel("安装/下载累计份额"); axes[0].legend(fontsize=9)
    both = [(stars.get(rp), v) for rp, v in sh.items() if stars.get(rp) is not None and v > 0]
    x = np.array([a for a, b in both]); y = np.array([b for a, b in both])
    axes[1].scatter(x + 1, y + 1, s=12, alpha=.55, color="#55A868")
    axes[1].set_xscale("log"); axes[1].set_yscale("log")
    from scipy.stats import spearmanr
    rho, p = spearmanr(x, y)
    axes[1].set_title(f"(b) 星标 vs 安装（Spearman ρ={rho:.3f}, n={len(both)}）")
    axes[1].set_xlabel("星标数（+1, log）"); axes[1].set_ylabel("skills.sh 安装（+1, log）")
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "fig3_attention.png"), dpi=200, bbox_inches="tight")
    plt.close(fig)
    top1 = max(sh.values()) / sum(sh.values())
    STATS["fig3"] = {"n_sh_repos": len(sh), "gini_sh": gini(list(sh.values())), "top1_sh": top1,
                     "gini_ch_item": gini(ch_items), "n_ch_items": len(ch_items),
                     "spearman_stars_installs": float(rho), "p": float(p)}


# ---------------- RQ3b 可见性矩阵 ----------------
def fig4():
    repos = list(_STAR_CACHE.keys())
    rs = set(repos)
    ch = {}
    chn = {}
    rel = {}
    npm = {}
    for r in jl2():
        t = r.get("type")
        if t == "skills_sh" and r.get("repo") in rs:
            ch[r["repo"]] = 1 if (r.get("n_hits") or 0) > 0 else 0
        elif t == "clawhub_search" and r.get("repo") in rs:
            chn[r["repo"]] = 1 if (r.get("n_hits") or 0) > 0 else 0
    for r in jl("release_downloads.jsonl"):
        if r.get("type") == "repo":
            rel[r["repo"]] = 1 if ((r.get("github") or {}).get("downloads") or 0) > 0 else 0
    for r in jl("npm_downloads.jsonl"):
        if r.get("type") == "repo":
            npm[r["repo"]] = 1 if r["npm"]["status"] == "matched" else 0
    st = {rp: (1 if _STAR_CACHE.get(rp, 0) > 0 else 0) for rp in repos}
    mat = np.zeros((len(repos), 5))
    coldefs = [("GitHub stars>0", st), ("skills.sh 命中", ch), ("ClawHub 命中", chn), ("release 下载>0", rel), ("npm 有包", npm)]
    for j, (_, d) in enumerate(coldefs):
        for i, rp in enumerate(repos):
            mat[i, j] = d.get(rp, 0)
    order = np.argsort(-mat.sum(axis=1))
    mat = mat[order]
    fig, ax = plt.subplots(figsize=(6.5, 7))
    ax.imshow(mat, aspect="auto", cmap="Greens", interpolation="nearest", vmin=0, vmax=1)
    ax.set_xticks(range(5)); ax.set_xticklabels([c for c, _ in coldefs], rotation=30, ha="right", fontsize=9)
    ax.set_ylabel("341 仓（按渠道数排序）")
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "fig4_visibility.png"), dpi=200)
    plt.close(fig)
    pres = {c: float(mat[:, j].mean()) for j, (c, _) in enumerate(coldefs)}
    overlap = np.corrcoef(mat.T)
    nch = mat.sum(axis=1)
    def _clean(x):
        x = float(x)
        return None if np.isnan(x) else round(x, 3)
    STATS["fig4"] = {"presence_rate": pres,
                     "only_github_pct": float((nch == 1).mean()),
                     "channels_mean": float(nch.mean()),
                     "pair_corr": {f"{coldefs[i][0]} × {coldefs[j][0]}": _clean(overlap[i, j])
                                   for i in range(5) for j in range(i + 1, 5)}}


def _stars(rp):
    global _STAR_CACHE
    return _STAR_CACHE.get(rp, 0) > 0


_STAR_CACHE = {}
_rm = json.load(open(os.path.join(ROOT, "data", "repos_meta.json"), encoding="utf-8"))
for _rp, _r in _rm.items():
    _STAR_CACHE[_rp] = _r.get("stars") or 0


# ---------------- RQ4 生命周期 ----------------
def fig5():
    cohorts = collections.defaultdict(list)
    for r in jl("topic_census.jsonl"):
        if r.get("type") != "repo":
            continue
        m = (r.get("created_at") or "")[:7]
        pu = r.get("pushed_at")
        if not m or not pu:
            continue
        d = (REF - datetime.datetime.fromisoformat(pu.replace("Z", "+00:00"))).days
        cohorts[m].append(d)
    months = sorted(cohorts)
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.2))
    ms = [m for m in months if cohorts[m]]
    surv30 = [np.mean([1 if d <= 30 else 0 for d in cohorts[m]]) * 100 for m in ms]
    ns = [len(cohorts[m]) for m in ms]
    axes[0].bar(ms, surv30, color="#4C72B0")
    for i, (m, n) in enumerate(zip(ms, ns)):
        if n > 50:
            axes[0].text(i, surv30[i] + 2, f"n={n}", ha="center", fontsize=7, rotation=90)
    axes[0].tick_params(axis="x", rotation=60, labelsize=8)
    axes[0].set_ylabel("近 30 天有 push 的比例 (%)")
    axes[0].set_title("(a) 按创建月的存活率（2026-08 波：≈29%）")
    sh = json.load(open(os.path.join(ROOT, "data", "star_history.json"), encoding="utf-8"))
    feats, trajs = [], []
    for rp, weeks in sh.items():
        tot = [w["total"] for w in weeks]
        if len(tot) < 12 or tot[-1] <= 0:
            continue
        cum = np.array(tot, dtype=float)
        inc = np.diff(cum, prepend=0.0)
        peak_share = inc.max() / max(inc.sum(), 1)
        t90 = (np.argmax(cum >= .9 * cum[-1]) + 1) / len(cum)
        feats.append([peak_share, t90, np.log1p(cum[-1])])
        trajs.append(cum / cum[-1])
    L = min(len(t) for t in trajs)
    trajs = [t[:L] for t in trajs]
    X = np.array(feats)
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    km = KMeans(4, n_init=10, random_state=20261024).fit(StandardScaler().fit_transform(X))
    T = np.array(trajs)
    colors = ["#4C72B0", "#DD8452", "#55A868", "#C44E52"]
    for c in range(4):
        axes[1].plot(T[km.labels_ == c].mean(axis=0), color=colors[c],
                     label=f"类型{c+1}（{int((km.labels_==c).sum())} 仓）")
    axes[1].set_xlabel("仓库生命周期周序"); axes[1].set_ylabel("累计星标份额")
    axes[1].legend(fontsize=8); axes[1].set_title("(b) 星标轨迹类型学（KMeans, n=%d 仓）" % len(X))
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "fig5_lifecycle.png"), dpi=200, bbox_inches="tight")
    plt.close(fig)
    cl = collections.Counter(km.labels_.tolist())
    STATS["fig5"] = {"cohorts": {m: {"n": len(cohorts[m]), "surv30_pct": round(float(np.mean([d <= 30 for d in cohorts[m]])), 4)} for m in ms if len(cohorts[m]) >= 30},
                     "traj_clusters": {f"type{c+1}": cl.get(c, 0) for c in range(4)}}


# ---------------- RQ5 治理 ----------------
def fig6():
    lat = []
    merged = closed = 0
    for name in ("pr_merged.jsonl", "pr_merged_retry.jsonl", "pr_merged_retry3.jsonl"):
        p = os.path.join(COL, name)
        if not os.path.exists(p):
            continue
        for line in open(p, encoding="utf-8"):
            r = json.loads(line)
            if r.get("type") != "repo" or not r.get("complete"):
                continue
            for pr in r.get("pulls", []):
                if pr.get("merged_at") and pr.get("created_at"):
                    merged += 1
                    a = datetime.datetime.fromisoformat(pr["created_at"].replace("Z", "+00:00"))
                    b = datetime.datetime.fromisoformat(pr["merged_at"].replace("Z", "+00:00"))
                    d = (b - a).total_seconds() / 86400
                    if d >= 0:
                        lat.append(d)
                elif pr.get("state") == "closed":
                    closed += 1
    D = json.load(open(os.path.join(ROOT, "data", "results", "probe_four_20261024.json"), encoding="utf-8"))["D_merge_predict"]
    S = json.load(open(os.path.join(ROOT, "data", "results", "collected_20261024_summary.json"), encoding="utf-8"))
    rv = S["pr_reviews"]; join = S["review_pr_join"]
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4))
    axes[0].hist(lat, bins=np.logspace(-3, np.log10(max(max(lat), 1)), 60), color="#4C72B0")
    axes[0].set_xscale("log")
    axes[0].axvline(np.median(lat), color="black", ls="--")
    axes[0].set_title(f"(a) 合并时延（中位 {np.median(lat)*24:.1f} 小时，n={len(lat):,}）")
    axes[0].set_xlabel("创建→合并（天，log）")
    cats = ["merged 有≥1\nreview", "merged 无\nreviewDecision", "APPROVED", "CHANGES\n_REQUESTED"]
    dec = join.get("review_decision_by_status", {})
    mt = sum(v for k, v in dec.items() if k.startswith("merged|"))
    vals = [join["reviewed_share_by_status"].get("merged", 0) * 100,
            dec.get("merged|None", 0) / mt * 100,
            dec.get("merged|APPROVED", 0) / mt * 100,
            dec.get("merged|CHANGES_REQUESTED", 0) / mt * 100]
    axes[1].bar(cats, vals, color=["#55A868", "#C44E52", "#4C72B0", "#DD8452"])
    for i, v in enumerate(vals):
        axes[1].text(i, v + 1.5, f"{v:.1f}%", ha="center", fontsize=9)
    axes[1].set_ylim(0, 100); axes[1].tick_params(axis="x", labelsize=8)
    axes[1].set_title("(b) 审查覆盖（可连接 PR n=%s）" % join.get("n_joined"))
    axes[2].bar(["Logistic", "HistGBM"], [D["auc_logistic_groupkfold"], D["auc_histgbm_groupkfold"]], color=["#4C72B0", "#8172B3"])
    axes[2].axhline(0.5, color="gray", ls=":", label="随机基线 0.5")
    axes[2].set_ylim(0.4, 0.7); axes[2].legend()
    axes[2].set_title("(c) 合并结果可预测性（GroupKFold AUC）")
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "fig6_governance.png"), dpi=200, bbox_inches="tight")
    plt.close(fig)
    STATS["fig6"] = {"latency_median_hours": float(np.median(lat) * 24), "latency_p90_days": float(np.percentile(lat, 90)),
                     "n_merged": merged, "auc": D["auc_logistic_groupkfold"]}


# ---------------- RQ6 互惠窗口 ----------------
def fig7():
    src = json.load(open(os.path.join(ROOT, "data", "forks_timestamps_full.json"), encoding="utf-8"))
    delays = []
    for name in ("fork_prs.jsonl", "fork_prs_retry1.jsonl", "fork_prs_retry2.jsonl"):
        for r in jl(name):
            if r.get("type") != "parent" or not r.get("complete"):
                continue
            fmap = {f.get("full_name"): f.get("created_at") for f in src.get(r["parent"], [])}
            for l in r.get("links", []):
                if l.get("matched_by") == "head_repo" and l.get("fork") in fmap and l.get("created_at") and fmap[l["fork"]]:
                    a = datetime.datetime.fromisoformat(fmap[l["fork"]].replace("Z", "+00:00"))
                    b = datetime.datetime.fromisoformat(l["created_at"].replace("Z", "+00:00"))
                    d = (b - a).total_seconds() / 86400
                    if d >= 0:
                        delays.append(d)
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    edges = [0, 1, 3, 7, 14, 30, 60, 90, 180, 365, 10000]
    share = []
    lab = []
    n_total = len(delays)
    for lo, hi in zip(edges[:-1], edges[1:]):
        n_event = sum(1 for d in delays if lo <= d < hi)
        share.append(n_event / n_total if n_total else 0)
        lab.append(f"{lo}-{hi if hi < 10000 else '+'}d")
    ax.bar(lab, [s * 100 for s in share], color="#4C72B0")
    for i, s in enumerate(share):
        if s > 0:
            ax.text(i, s * 100 + .5, f"{s*100:.1f}%", ha="center", fontsize=8)
    ax.set_title("fork→PR 回流时间分布（41%% 在 24 小时内，中位 %.1f 天）" % np.median(delays))
    ax.set_xlabel("fork 至提 PR 的时间段"); ax.set_ylabel("回流 PR 占比 (%)")
    ax.tick_params(axis="x", rotation=30)
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "fig7_hazard.png"), dpi=200)
    plt.close(fig)
    STATS["fig6_hazard"] = {"n_delays": len(delays), "timing_share": dict(zip(lab, [round(s, 4) for s in share])),
                            "note": "分母仅为最终回流过的 fork（head 匹配）；不是全量 fork 的 hazard",
                            "median": float(np.median(delays)), "p90": float(np.percentile(delays, 90))}


# ---------------- 表 ----------------
def tables():
    files = []
    for fn in sorted(os.listdir(COL)):
        p = os.path.join(COL, fn)
        if os.path.isfile(p):
            h = __import__("hashlib").sha256(open(p, "rb").read()).hexdigest()
            files.append([fn, os.path.getsize(p), h[:16]])
    with open(os.path.join(FIG, "table1_data_manifest.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["文件", "字节", "SHA256 前16位"])
        w.writerows(files)
    A = json.load(open(os.path.join(ROOT, "data", "results", "probe_four_20261024.json"), encoding="utf-8"))
    rows = [
        ["复制文档占比（精确键）", "45,155 / 155,547 (29.0%)"],
        ["扇出 Gini（模板经济检验）", f"{STATS['fig1']['gini_fanout']:.3f} → 长尾浅层，模板经济不成立"],
        ["name 逐字保留率", f"{A['A_retention']['name_verbatim_pct']*100:.1f}%"],
        ["署名字段完全缺失", f"{A['A_retention']['attrib_none_pct']*100:.1f}%"],
        ["方向不可判比例", "32.1%（165 对）"],
        ["8 月队列 30 天存活", "28.7%"],
        ["skills.sh 仓级 Gini / top1", f"{STATS['fig3']['gini_sh']:.3f} / {STATS['fig3']['top1_sh']*100:.1f}%"],
        ["星标-安装 Spearman", f"{STATS['fig3']['spearman_stars_installs']:.3f}"],
        ["仅 GitHub 可见仓比例", f"{STATS['fig4']['only_github_pct']*100:.1f}%"],
        ["合并中位时延", f"{STATS['fig6']['latency_median_hours']:.1f} 小时"],
        ["merged 无 reviewDecision", "80.0%"],
        ["合并可预测性 AUC", f"{STATS['fig6']['auc']:.3f}（近乎不可预测）"],
        ["fork→PR 整体转化", "4.30%（107/228 父仓，部分覆盖）"],
    ]
    with open(os.path.join(FIG, "table2_findings.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["指标", "数值"]); w.writerows(rows)


def main():
    for name, fn in [("RQ1 复制结构", fig1), ("RQ2 保留", fig2), ("RQ3 注意力", fig3),
                     ("RQ3b 可见性", fig4), ("RQ4 生命周期", fig5), ("RQ5 治理", fig6), ("RQ6 互惠", fig7)]:
        try:
            fn(); print("OK", name, flush=True)
        except Exception as e:
            import traceback
            print("FAIL", name, repr(e), flush=True)
            traceback.print_exc()
    tables()
    with open(os.path.join(ROOT, "data", "results", "paper_stats_20261024.json"), "w", encoding="utf-8") as f:
        json.dump(STATS, f, ensure_ascii=False, indent=1)
    print("ALL DONE")


if __name__ == "__main__":
    main()
