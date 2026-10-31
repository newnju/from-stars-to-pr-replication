# -*- coding: utf-8 -*-
"""mine_deep.py — 深度挖掘套件（2026-10-25）
A 技能类型学：描述 TF-IDF + KMeans，类目 × 安全标记 × 语言
B 复制网络：repo 图（共享 SHA 为边）、度分布幂律检验、社区、hub×星标
C ClawHub 供给侧：owner 幂律、版本数×下载、名称冲突
D mergedBy 集中度：每仓头部合并者份额
E 安全事件窗口（描述性）：ClawHavoc/Snyk/Silverfort 前后日级星标事件率
F 轨迹类型学重做（v2 时序修正版）
输出 data/results/deep_mining_20261025.json + paper_figs/fig8/9/10 + fig5(修正)
"""
import json
import os
import re
import collections
import datetime
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COL = os.path.join(ROOT, "external_data", "collected_20261024")
SWC = os.path.join(ROOT, "external_data", "skills_with_content.jsonl")
FIG = os.path.join(ROOT, "paper_figs")
RES = {}
REF = datetime.datetime(2026, 10, 24, tzinfo=datetime.timezone.utc)

import warnings
warnings.filterwarnings("ignore")


# ---------- A+B 公共流：一次读 SWC，取描述/名称/frontmatter 字段/SHA→repos ----------
def stream_docs():
    FM = re.compile(r"^---\s*\n(.*?)\n---", re.S)
    with open(SWC, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            content = r.get("full_content") or ""
            m = FM.match(content.strip("\ufeff \n"))
            fm = {}
            if m:
                for ln in m.group(1).splitlines():
                    if ":" in ln:
                        k, v = ln.split(":", 1)
                        fm[k.strip().lower()] = v.strip()
            yield r, fm


def gini(xs):
    xs = np.sort(np.array(xs, dtype=float))
    n = len(xs)
    if n == 0 or xs.sum() <= 0:
        return None
    cum = np.cumsum(xs)
    return float((n + 1 - 2 * (cum / cum[-1]).sum()) / n)


def section_AB():
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.cluster import MiniBatchKMeans
    import networkx as nx
    from scipy.stats import kstest

    descs, names, lang, tool_docs = [], [], [], 0
    sha_repos = {}
    sec_by_repo = collections.defaultdict(int)
    n_doc = 0
    for r, fm in stream_docs():
        n_doc += 1
        descs.append((fm.get("description") or r.get("description") or "")[:300])
        names.append(fm.get("name") or r.get("name") or "")
        t = fm.get("description") or ""
        lang.append("zh" if sum('\u4e00' <= ch <= '\u9fff' for ch in t) > len(t) * 0.15 else "en")
        if fm.get("allowed-tools") or fm.get("allowed_tools"):
            tool_docs += 1
        h = r.get("sha256_hash")
        if h:
            sha_repos.setdefault(h, set()).add(r.get("repoFullName"))
        n_doc = n_doc
    # A) 类型学（仅非空描述）
    idx = [i for i, d in enumerate(descs) if len(d) >= 20]
    vec = TfidfVectorizer(max_features=4000, stop_words="english", min_df=5)
    X = vec.fit_transform([descs[i] for i in idx])
    km = MiniBatchKMeans(8, n_init=10, random_state=20261025).fit(X)
    terms = np.array(vec.get_feature_names_out())
    topics = []
    for c in range(8):
        cen = km.cluster_centers_[c]
        top = terms[np.argsort(-cen)[:8]].tolist()
        topics.append({"cluster": c, "n": int((km.labels_ == c).sum()), "top_terms": top})
    zh_share = float(np.mean([lang[i] == "zh" for i in idx]))
    RES["A_typology"] = {"n_docs": n_doc, "n_desc_used": len(idx), "clusters": topics,
                         "zh_share_among_desc": zh_share, "allowed_tools_declared_pct": round(100 * tool_docs / n_doc, 2)}
    # 图8：类型学
    fig, ax = plt.subplots(figsize=(8.5, 5))
    order = np.argsort([-t["n"] for t in topics])
    ax.barh([f"类{topics[i]['cluster']+1}" for i in order][::-1],
            [topics[i]["n"] for i in order][::-1], color="#4C72B0")
    for j, i in enumerate(order[::-1]):
        ax.text(topics[i]["n"], j, "  " + "/".join(topics[i]["top_terms"][:4]), va="center", fontsize=8)
    ax.set_xlabel("文档数"); ax.set_title("技能类型学：描述文本 TF-IDF+KMeans（8 类，n=%s）" % f"{len(idx):,}")
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "fig8_typology.png"), dpi=200); plt.close(fig)

    # B) 复制网络
    G = nx.Graph()
    edges = 0
    for h, rs in sha_repos.items():
        if len(rs) >= 2:
            rl = sorted(rs)
            for i in range(len(rl) - 1):
                for j in range(i + 1, min(i + 6, len(rl))):  # 大仓限连边防爆
                    if G.has_edge(rl[i], rl[j]):
                        G[rl[i]][rl[j]]["w"] += 1
                    else:
                        G.add_edge(rl[i], rl[j], w=1); edges += 1
    degs = np.array([d for _, d in G.degree()]) if G.number_of_nodes() else np.array([])
    # 幂律检验（度>0，KS 对拟合指数）
    dpos = degs[degs > 0].astype(float)
    alpha = 1 + len(dpos) / np.sum(np.log(dpos / (dpos.min() - 0.5)))
    cdf = lambda x: 1 - (x / dpos.min()) ** (-(alpha - 1))
    ks, ksp = kstest(dpos, cdf)
    # 社区（greedy，限制规模）
    if G.number_of_edges() > 0:
        import networkx.algorithms.community as nxcom
        com = list(nxcom.greedy_modularity_communities(G, weight="w"))[:2000]
        com_sizes = sorted((len(c) for c in com), reverse=True)
    else:
        com, com_sizes = [], []
    # hub × 星标
    stars = {}
    for line in open(os.path.join(COL, "local_mining.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        if r.get("type") == "repo":
            stars[r["repo"]] = r.get("stars") or 0
    top_deg = sorted(G.degree, key=lambda x: -x[1])[:12]
    RES["B_copy_network"] = {"nodes": G.number_of_nodes(), "edges": edges,
                             "powerlaw_alpha": round(float(alpha), 3), "ks_p": round(float(ksp), 4),
                             "n_communities": len(com), "top_com_sizes": com_sizes[:8],
                             "top_hubs": [{"repo": r, "deg": d, "stars": stars.get(r)} for r, d in top_deg],
                             "gini_degree": gini(degs)}
    # 图9：度分布 + 社区规模
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    axes[0].hist(dpos, bins=np.logspace(0, np.log10(dpos.max()), 40), color="#4C72B0")
    axes[0].set_xscale("log"); axes[0].set_yscale("log")
    axes[0].set_title("(a) 复制网络度分布（幂律指数 α=%.2f, KS p=%.3f）" % (alpha, ksp))
    axes[0].set_xlabel("度（log）"); axes[0].set_ylabel("仓库数")
    if com_sizes:
        axes[1].hist([s for s in com_sizes if s >= 3], bins=40, color="#DD8452")
        axes[1].set_title("(b) 复制社区规模分布（≥3 仓，n=%d 社区）" % len([s for s in com_sizes if s >= 3]))
        axes[1].set_xlabel("社区内仓库数"); axes[1].set_ylabel("社区数")
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "fig9_copy_network.png"), dpi=200); plt.close(fig)


def section_C():
    items = []
    for line in open(os.path.join(COL, "market_full.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        if r.get("type") == "clawhub_registry":
            items.append(r.get("item") or {})
    owners = collections.Counter()
    name_owners = collections.defaultdict(set)
    vers, dls = [], []
    for it in items:
        st = it.get("stats") or {}
        dl = st.get("downloads") or 0
        v = st.get("versions") or 0
        oh = it.get("ownerHandle")
        slug = it.get("slug")
        if oh:
            owners[oh] += dl
        if slug:
            name_owners[slug.split("--")[-1] if "--" in slug else slug].add(oh)
        if dl:
            dls.append(dl); vers.append(v)
    from scipy.stats import spearmanr
    rho, p = spearmanr(vers, dls)
    collide = {k: len(v) for k, v in name_owners.items() if len(v) >= 3}
    RES["C_registry_supply"] = {"n_items": len(items), "n_owners": len(owners),
                                "top_owners_by_downloads": owners.most_common(8),
                                "versions_downloads_spearman": round(float(rho), 3), "p": float(p),
                                "n_names_shared_by_3plus_owners": len(collide),
                                "top_collisions": sorted(collide.items(), key=lambda x: -x[1])[:8]}


def section_D():
    merger = collections.defaultdict(collections.Counter)
    for line in open(os.path.join(COL, "pr_reviews.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        if r.get("type") != "repo":
            continue
        for pr, x in (r.get("reviews") or {}).items():
            mb = x.get("merged_by")
            if mb:
                merger[r["repo"]][mb] += 1
    shares = []
    for rp, c in merger.items():
        tot = sum(c.values())
        if tot >= 20:
            shares.append(c.most_common(1)[0][1] / tot)
    RES["D_merged_by"] = {"n_repos_ge20": len(shares),
                          "median_top_merger_share": round(float(np.median(shares)), 3) if shares else None,
                          "mean_top_merger_share": round(float(np.mean(shares)), 3) if shares else None,
                          "share_ge90": round(float(np.mean([s >= 0.9 for s in shares])), 3) if shares else None}


def section_E():
    sh2 = json.load(open(r"E:\temp\opencode\star_history_v2.json", encoding="utf-8"))
    events = collections.Counter()
    for rp, rows in sh2.items():
        for w in rows:
            wt = datetime.datetime.fromtimestamp(w["week"], tz=datetime.timezone.utc)
            for i, dn in enumerate(w["days"]):
                if dn:
                    events[(wt + datetime.timedelta(days=i)).strftime("%Y-%m-%d")] += dn
    days = sorted(events)
    vals = np.array([events[d] for d in days], dtype=float)
    dates = [datetime.datetime.strptime(d, "%Y-%m-%d") for d in days]
    shocks = [("ClawHavoc", "2026-02-03"), ("Snyk ToxicSkills", "2026-02-05"), ("Silverfort", "2026-03-24")]
    out = []
    fig, ax = plt.subplots(figsize=(9.5, 4.2))
    ax.plot(dates, vals, lw=0.8, color="#4C72B0", alpha=0.8, label="全生态日星标事件")
    rng = np.random.default_rng(20261025)
    for name, d0 in shocks:
        t0 = datetime.datetime.strptime(d0, "%Y-%m-%d")
        w = [i for i, dt in enumerate(dates) if 0 <= (dt - t0).days <= 14]
        pre = [i for i, dt in enumerate(dates) if -28 <= (dt - t0).days < 0]
        post = [i for i, dt in enumerate(dates) if 0 <= (dt - t0).days <= 14]
        bw = vals[pre].mean() if pre else np.nan
        aw = vals[post].mean() if post else np.nan
        boot = []
        for _ in range(1000):
            samp = rng.choice(vals[pre], size=len(post)) if pre else None
            boot.append(samp.mean())
        lo, hi = np.percentile(boot, [2.5, 97.5]) if boot else (np.nan, np.nan)
        out.append({"shock": name, "date": d0, "pre28_mean": round(float(bw), 1),
                    "post14_mean": round(float(aw), 1), "ratio": round(float(aw / bw), 3) if bw else None,
                    "ci95": [round(float(lo), 1), round(float(hi), 1)]})
        ax.axvline(t0, color="#C44E52", ls="--", lw=1)
        ax.text(t0, vals.max() * 0.92, " " + name, fontsize=8, color="#C44E52")
    ax.set_title("图 10  安全披露事件前后全生态日星标事件（描述性对齐，n=341 仓）")
    ax.set_ylabel("日星标事件数"); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "fig10_event_window.png"), dpi=200); plt.close(fig)
    RES["E_event_window"] = {"note": "描述性前后对比+基线bootstrap；非因果", "shocks": out}


def section_F():
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    sh2 = json.load(open(r"E:\temp\opencode\star_history_v2.json", encoding="utf-8"))
    feats, trajs = [], []
    for rp, rows in sh2.items():
        rows = sorted(rows, key=lambda w: w["week"])
        tot = [w["total"] for w in rows]
        if len(tot) < 12 or sum(tot) <= 0:
            continue
        cum = np.cumsum(tot)
        peak = max(tot) / sum(tot)
        t90 = (np.argmax(cum >= 0.9 * cum[-1]) + 1) / len(cum)
        feats.append([peak, t90, np.log1p(cum[-1])])
        trajs.append(cum / cum[-1])
    L = min(len(t) for t in trajs)
    T = np.array([t[:L] for t in trajs])
    X = StandardScaler().fit_transform(np.array(feats))
    km = KMeans(4, n_init=10, random_state=20261025).fit(X)
    cl = collections.Counter(km.labels_.tolist())
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.2))
    axes[0].plot(T[km.labels_ == 0].mean(axis=0), color="#4C72B0", label=f"长跑型（{cl.get(0,0)}）")
    axes[0].plot(T[km.labels_ == 1].mean(axis=0), color="#DD8452", label=f"爆发型（{cl.get(1,0)}）")
    axes[0].plot(T[km.labels_ == 2].mean(axis=0), color="#55A868", label=f"缓增型（{cl.get(2,0)}）")
    axes[0].plot(T[km.labels_ == 3].mean(axis=0), color="#C44E52", label=f"迟发型（{cl.get(3,0)}）")
    axes[0].legend(fontsize=8); axes[0].set_xlabel("生命周期周序（自创建）"); axes[0].set_ylabel("累计星标份额")
    axes[0].set_title("(b) 星标轨迹类型学（v2 修正时序，n=%d 仓）" % len(T))
    # (a) 队列存活沿用 census
    cohorts = collections.defaultdict(list)
    for line in open(os.path.join(COL, "topic_census.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        if r.get("type") != "repo":
            continue
        m = (r.get("created_at") or "")[:7]; pu = r.get("pushed_at")
        if not m or not pu:
            continue
        d = (REF - datetime.datetime.fromisoformat(pu.replace("Z", "+00:00"))).days
        cohorts[m].append(d <= 30)
    ms = sorted(m for m in cohorts if len(cohorts[m]) >= 30)
    axes[1].bar(ms, [100 * np.mean(cohorts[m]) for m in ms], color="#4C72B0")
    axes[1].tick_params(axis="x", rotation=60, labelsize=8)
    axes[1].set_ylabel("近30天存活(%)"); axes[1].set_title("(a) 创建月队列存活率")
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "fig5_lifecycle.png"), dpi=200); plt.close(fig)
    RES["F_traj_v2"] = {"n": len(T), "clusters": {f"type{i+1}": cl.get(i, 0) for i in range(4)},
                        "note": "fig5 已用 v2 修正时序重做（替换旧缺陷时序版）"}


def main():
    for name, fn in [("AB 类型学+复制网络", section_AB), ("C 供给侧", section_C),
                     ("D mergedBy", section_D), ("E 事件窗口", section_E), ("F 轨迹v2", section_F)]:
        try:
            fn(); print("OK", name, flush=True)
        except Exception as e:
            import traceback
            RES[name] = {"error": str(e)[:200]}
            print("FAIL", name, repr(e), flush=True)
            traceback.print_exc()
    with open(os.path.join(ROOT, "data", "results", "deep_mining_20261025.json"), "w", encoding="utf-8") as f:
        json.dump(RES, f, ensure_ascii=False, indent=1)
    print("ALL DONE")


if __name__ == "__main__":
    main()
