# -*- coding: utf-8 -*-
"""probe_four.py — 四个先验空白探针（2026-10-24 夜）

A 溯源字段保留率：跨仓近重复对的前置元数据（name/description/license 等）逐字段对比
B 复制扇出集中度：按 sha256 分组，每个内容哈希被多少仓共享；top-K 哈希占跨仓复制文档的份额
C 新仓存活率：topic 普查按创建月队列的 pushed_at 活跃度 / 零星 / fork 比例
D 合并可预测性：GroupKFold(按仓) 5 折 CV，Logistic vs HistGBM 的 AUC

输出：data/results/probe_four_20261024.json（stdout 打印摘要）
"""
import json
import os
import re
import random
import collections
import datetime
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
COL = os.path.join(ROOT, "external_data", "collected_20261024")
SWC = os.path.join(ROOT, "external_data", "skills_with_content.jsonl")
REF_DAY = datetime.datetime(2026, 10, 24, tzinfo=datetime.timezone.utc)


def gini(xs):
    xs = np.sort(np.array(xs, dtype=float))
    n = len(xs)
    if n == 0 or xs.sum() == 0:
        return None
    cum = np.cumsum(xs)
    return float((n + 1 - 2 * (cum / cum[-1]).sum()) / n)


# ---------- B: 复制扇出集中度 ----------
def probe_b():
    hash_repos = {}
    hash_docname = {}
    n_docs = 0
    with open(SWC, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            n_docs += 1
            h = r.get("sha256_hash")
            if not h:
                continue
            repo = r.get("repoFullName")
            hash_repos.setdefault(h, set()).add(repo)
            hash_docname.setdefault(h, (r.get("name"), repo))
    fan = {h: len(s) for h, s in hash_repos.items() if len(s) >= 2}
    shared_docs = sum(fan.values())  # 文档数（每仓一份）
    sizes = sorted(fan.values(), reverse=True)
    top10 = sum(sizes[:10])
    top50 = sum(sizes[:50])
    top200 = sum(sizes[:200])
    top = []
    for h, n in sorted(fan.items(), key=lambda kv: -kv[1])[:15]:
        name, repo = hash_docname[h]
        top.append({"hash": h[:12], "n_repos": n, "name": name, "example_repo": repo})
    return {"n_docs": n_docs, "n_hashes_multi_repo": len(fan),
            "docs_in_multi_repo_hashes": shared_docs,
            "share_of_docs": shared_docs / n_docs,
            "top10_hash_share_of_shared": top10 / shared_docs,
            "top50_hash_share_of_shared": top50 / shared_docs,
            "top200_hash_share_of_shared": top200 / shared_docs,
            "gini_fanout": gini(sizes),
            "max_fanout": sizes[0], "top_hashes": top}


# ---------- A: 溯源字段保留率 ----------
FM_RE = re.compile(r"^---\s*\n(.*?)\n---", re.S)


def parse_fm(content):
    if not content:
        return None
    m = FM_RE.match(content.strip("\ufeff \n"))
    if not m:
        return None
    fields = {}
    for ln in m.group(1).splitlines():
        if ":" in ln:
            k, v = ln.split(":", 1)
            k = k.strip().lower()
            if k and not k.startswith("#"):
                fields[k] = v.strip().strip('"').strip("'")
    return fields


ATTRIB_KEYS = {"license", "licence", "source", "author", "attribution", "credit", "reference", "based-on", "based_on", "original"}


def probe_a(sample_n=4000, seed=20261024):
    pairs = []
    for line in open(os.path.join(COL, "near_duplicates.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        if r.get("type") == "pair" and not r.get("same_repo"):
            pairs.append((r["a"]["id"], r["b"]["id"]))
    random.seed(seed)
    sample = random.sample(pairs, min(sample_n, len(pairs)))
    want = {i for p in sample for i in p}
    docs = {}
    with open(SWC, encoding="utf-8") as f:
        for line in f:
            if len(docs) >= len(want):
                break
            r = json.loads(line)
            if r.get("id") in want:
                docs[r["id"]] = parse_fm(r.get("full_content")) or {}
    stat = collections.Counter()
    field_rate = collections.Counter()
    n = 0
    for a, b in sample:
        fa, fb = docs.get(a), docs.get(b)
        if fa is None or fb is None or (not fa and not fb):
            continue
        n += 1
        for k in ("name", "description"):
            for ff in (fa, fb):
                if k in ff:
                    field_rate[k + "_present"] += 1
            if k in fa and k in fb:
                if fa[k] == fb[k]:
                    stat[k + "_verbatim"] += 1
                else:
                    stat[k + "_modified"] += 1
            else:
                stat[k + "_dropped"] += 1
        for ff in (fa, fb):
            if ATTRIB_KEYS & set(ff):
                field_rate["attrib_field_present"] += 1
        if (ATTRIB_KEYS & set(fa)) and (ATTRIB_KEYS & set(fb)):
            stat["attrib_both"] += 1
        elif (ATTRIB_KEYS & set(fa)) or (ATTRIB_KEYS & set(fb)):
            stat["attrib_one"] += 1
        else:
            stat["attrib_none"] += 1
    out = {"n_pairs_sampled": n}
    for k in ("name_verbatim", "name_modified", "name_dropped",
              "description_verbatim", "description_modified", "description_dropped",
              "attrib_both", "attrib_one", "attrib_none"):
        out[k] = stat[k]
        out[k + "_pct"] = round(stat[k] / n, 4) if n else None
    out["any_attrib_field_pct"] = round((stat["attrib_both"] + stat["attrib_one"]) / n, 4) if n else None
    return out


# ---------- C: 新仓存活率 ----------
def probe_c():
    cohorts = collections.defaultdict(lambda: collections.Counter())
    for line in open(os.path.join(COL, "topic_census.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        if r.get("type") != "repo":
            continue
        ca = r.get("created_at") or ""
        month = ca[:7]
        if not month:
            continue
        c = cohorts[month]
        c["n"] += 1
        if not r.get("stargazers_count"):
            c["zero_star"] += 1
        if r.get("fork"):
            c["is_fork"] += 1
        pu = r.get("pushed_at")
        if pu:
            d = (REF_DAY - datetime.datetime.fromisoformat(pu.replace("Z", "+00:00"))).days
            if d <= 30:
                c["active_30d"] += 1
            if d <= 90:
                c["active_90d"] += 1
    out = {}
    for m in sorted(cohorts):
        c = cohorts[m]
        n = c["n"]
        out[m] = {"n": n,
                  "zero_star_pct": round(c["zero_star"] / n, 4),
                  "is_fork_pct": round(c["is_fork"] / n, 4),
                  "active_30d_pct": round(c["active_30d"] / n, 4),
                  "active_90d_pct": round(c["active_90d"] / n, 4)}
    return out


# ---------- D: 合并可预测性 ----------
def probe_d():
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.model_selection import GroupKFold
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import make_pipeline
    from sklearn.metrics import roc_auc_score
    stars = {}
    for line in open(os.path.join(COL, "local_mining.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        if r.get("type") == "repo":
            stars[r["repo"]] = r.get("stars") or 0
    rows = []
    for name in ("pr_merged.jsonl", "pr_merged_retry.jsonl", "pr_merged_retry3.jsonl"):
        p = os.path.join(COL, name)
        if not os.path.exists(p):
            continue
        for line in open(p, encoding="utf-8"):
            r = json.loads(line)
            if r.get("type") != "repo" or not r.get("complete"):
                continue
            repo = r["repo"]
            for pr in r.get("pulls", []):
                if pr.get("state") == "open":
                    continue
                merged = 1 if pr.get("merged_at") else 0
                u = (pr.get("user") or "").lower()
                is_bot = 1 if ("bot" in u or (pr.get("user_type") or "").lower() == "bot") else 0
                ca = pr.get("created_at") or ""
                wd = datetime.datetime.fromisoformat(ca.replace("Z", "+00:00")).weekday() if ca else 0
                hr = int(ca[11:13]) if len(ca) >= 13 else 0
                rows.append((merged, is_bot, len(pr.get("title") or ""), len(pr.get("labels") or []),
                             1 if pr.get("draft") else 0, wd >= 5, hr // 6,
                             np.log1p(r.get("n_pulls") or 0), np.log1p(stars.get(repo, 0)), repo))
    arr = np.array(rows, dtype=object)
    y = arr[:, 0].astype(int)
    X = arr[:, 1:9].astype(float)
    groups = arr[:, 9]
    gkf = GroupKFold(n_splits=5)
    aucs_lr, aucs_gb = [], []
    for tr, te in gkf.split(X, y, groups):
        lr = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, class_weight="balanced"))
        lr.fit(X[tr], y[tr])
        aucs_lr.append(roc_auc_score(y[te], lr.predict_proba(X[te])[:, 1]))
        gb = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.1)
        gb.fit(X[tr], y[tr])
        aucs_gb.append(roc_auc_score(y[te], gb.predict_proba(X[te])[:, 1]))
    feats = ["is_bot", "title_len", "n_labels", "is_draft", "weekend", "daypart", "log_repo_prs", "log_repo_stars"]
    lr_full = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, class_weight="balanced")).fit(X, y)
    coefs = dict(zip(feats, np.round(lr_full[-1].coef_[0], 3).tolist()))
    return {"n_prs": len(y), "merge_rate": round(float(y.mean()), 4),
            "auc_logistic_groupkfold": round(float(np.mean(aucs_lr)), 4),
            "auc_histgbm_groupkfold": round(float(np.mean(aucs_gb)), 4),
            "logistic_coefs": coefs, "features": feats,
            "note": "GroupKFold by repo；预测非因果"}


def main():
    out = {"generated": datetime.datetime.now().isoformat(timespec="seconds"),
           "B_fanout": probe_b(),
           "A_retention": probe_a(),
           "C_survival": probe_c(),
           "D_merge_predict": probe_d()}
    p = os.path.join(ROOT, "data", "results", "probe_four_20261024.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
