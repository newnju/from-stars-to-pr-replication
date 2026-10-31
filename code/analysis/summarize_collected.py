# -*- coding: utf-8 -*-
"""
summarize_collected.py — 汇总 2026-10-24 补齐批次，输出 JSON 到 stdout。

  python analysis\\summarize_collected.py > data\\results\\collected_20261024_summary.json

只读；不写文件。输入默认 E:\\temp\\opencode\\*.jsonl，可用 COLLECT_DIR 覆盖。
"""
import json
import os
import sys
import glob
import math
import datetime
import collections
import statistics

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
MKT = os.path.join(ROOT, "external_data", "market")
CD = os.environ.get("COLLECT_DIR", r"E:\temp\opencode")


def load_jsonl(name, typ=None):
    p = os.path.join(CD, name)
    out = []
    if not os.path.exists(p):
        return out
    with open(p, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                o = json.loads(line)
            except Exception:
                continue
            if typ is None or o.get("type") == typ:
                out.append(o)
    return out


def gini(xs):
    xs = sorted(float(x) for x in xs if x is not None and x >= 0)
    n = len(xs)
    s = sum(xs)
    if n < 2 or s <= 0:
        return None
    cum = 0.0
    for i, x in enumerate(xs):
        cum += (2 * i - n + 1) * x
    return cum / (n * s)


def top1(xs):
    xs = [float(x) for x in xs if x is not None and x >= 0]
    s = sum(xs)
    return (max(xs) / s) if xs and s > 0 else None


def dt(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def pr_section():
    rows = (load_jsonl("pr_merged.jsonl", "repo") + load_jsonl("pr_merged_retry.jsonl", "repo")
            + load_jsonl("pr_merged_retry3.jsonl", "repo"))
    by = {}
    for r in rows:
        old = by.get(r["repo"])
        if old is None or (r.get("n_pulls", 0) > old.get("n_pulls", 0)):
            by[r["repo"]] = r
    rows = list(by.values())
    old = json.load(open(os.path.join(DATA, "gh_discourse.json"), encoding="utf-8"))["repos"]
    meta = json.load(open(os.path.join(DATA, "repos_meta.json"), encoding="utf-8"))

    def basic(rs):
        n = merged = closed = open_ = bot = botm = 0
        lat, repo_lat = [], []
        for r in rs:
            lr = []
            for p in r.get("pulls", []):
                n += 1
                if p.get("merged_at"):
                    merged += 1
                    a, b = dt(p.get("created_at")), dt(p.get("merged_at"))
                    if a and b:
                        d = (b - a).total_seconds() / 86400.0
                        lat.append(d)
                        lr.append(d)
                elif p.get("state") == "closed":
                    closed += 1
                else:
                    open_ += 1
                if p.get("user_type") == "Bot":
                    bot += 1
                    if p.get("merged_at"):
                        botm += 1
            if lr:
                repo_lat.append(statistics.median(lr))
        return {"n_repos": len(rs), "n_prs": n, "merged": merged,
                "closed_unmerged": closed, "open": open_,
                "merge_rate_all": merged / n if n else None,
                "merge_rate_closed": merged / (merged + closed) if merged + closed else None,
                "bot_prs": bot, "bot_merged": botm,
                "latency_median_days": statistics.median(lat) if lat else None,
                "latency_p90_days": sorted(lat)[int(len(lat) * .9)] if lat else None,
                "repo_latency_median_days": statistics.median(repo_lat) if repo_lat else None,
                "repo_latency_p90_days": sorted(repo_lat)[int(len(repo_lat) * .9)] if repo_lat else None}

    top3 = sorted(rows, key=lambda r: -r.get("n_pulls", 0))[:3]
    top3_names = {r["repo"] for r in top3}
    ex = [r for r in rows if r["repo"] not in top3_names]
    overall = basic(rows)
    exclude = basic(ex)

    # old vs new PR counts
    trunc = []
    for r in rows:
        o = sum(1 for it in old.get(r["repo"], {}).get("issues", []) if it.get("is_pr"))
        trunc.append({"repo": r["repo"], "old_prs": o, "new_prs": r.get("n_pulls"),
                      "ratio": (r.get("n_pulls") / o) if o else None})
    trunc.sort(key=lambda x: -(x["ratio"] or 0))
    old_eq = sum(1 for x in trunc if x["old_prs"] == x["new_prs"])
    new_gt = sum(1 for x in trunc if (x["new_prs"] or 0) > x["old_prs"])

    # by star tier
    tiers = []
    for lo, hi, label in [(0, 0, "0"), (1, 10, "1-10"), (11, 50, "11-50"),
                          (51, 200, "51-200"), (201, 1000, "201-1000"),
                          (1001, 10**9, "1001+")]:
        rs = [r for r in rows if lo <= (meta.get(r["repo"], {}).get("stars") or 0) <= hi]
        if rs:
            s = basic(rs)
            s["star_tier"] = label
            tiers.append(s)

    return {"n_repos": len(rows), "overall": overall, "exclude_top3": exclude,
            "incomplete_repos": [{"repo": r["repo"], "n_pulls": r.get("n_pulls"),
                                  "complete": r.get("complete"),
                                  "max_pages_reached": r.get("max_pages_reached")}
                                 for r in rows if not r.get("complete")],
            "top3": [r["repo"] for r in top3], "old_new": {
                "old_prs": sum(x["old_prs"] for x in trunc),
                "new_prs": sum(x["new_prs"] or 0 for x in trunc),
                "old_eq_new": old_eq, "new_gt_old": new_gt,
                "top_undercount": trunc[:15]},
            "by_star_tier": tiers,
            "top_repos": [{"repo": r["repo"], "n": r.get("n_pulls"),
                           "stars": meta.get(r["repo"], {}).get("stars")}
                          for r in sorted(rows, key=lambda r: -r.get("n_pulls", 0))[:15]]}


def reviews_section():
    rows = load_jsonl("pr_reviews.jsonl", "repo") + load_jsonl("pr_reviews_retry.jsonl", "repo")
    by = {}
    for r in rows:
        old = by.get(r["repo"])
        if old is None or r.get("n_prs", 0) > old.get("n_prs", 0):
            by[r["repo"]] = r
    rows = list(by.values())
    n = reviewed = 0
    dec = collections.Counter()
    merged_by = collections.Counter()
    for r in rows:
        for x in r.get("reviews", {}).values():
            n += 1
            rv = x.get("reviews") or 0
            if rv:
                reviewed += 1
            dec[x.get("review_decision")] += 1
            merged_by[x.get("merged_by")] += 1
    errs = load_jsonl("pr_reviews.jsonl", "error") + load_jsonl("pr_reviews_retry.jsonl", "error")
    done = {r["repo"] for r in rows}
    return {"n_repos": len(rows), "n_prs": n, "reviewed_prs": reviewed,
            "reviewed_share": reviewed / n if n else None,
            "review_decision": dict(dec),
            "n_error_rows": len(errs),
            "unresolved_error_repos": sorted({e.get("repo") for e in errs} - done),
            "top_merged_by": merged_by.most_common(15)}


def review_join_section():
    pr = {}
    for name in ("pr_merged.jsonl", "pr_merged_retry.jsonl", "pr_merged_retry3.jsonl"):
        for r in load_jsonl(name, "repo"):
            old = pr.get(r["repo"])
            if old is None or r.get("n_pulls", 0) > old.get("n_pulls", 0):
                pr[r["repo"]] = r
    rv = {}
    for r in load_jsonl("pr_reviews.jsonl", "repo") + load_jsonl("pr_reviews_retry.jsonl", "repo"):
        old = rv.get(r["repo"])
        if old is None or r.get("n_prs", 0) > old.get("n_prs", 0):
            rv[r["repo"]] = r
    inter = reviewed = 0
    st = collections.Counter()
    rs = collections.Counter()
    dec = collections.Counter()
    for repo, r in pr.items():
        if repo not in rv:
            continue
        m = rv[repo].get("reviews", {})
        for p in r.get("pulls", []):
            x = m.get(str(p.get("number")))
            if not x:
                continue
            inter += 1
            s = "merged" if p.get("merged_at") else ("closed" if p.get("state") == "closed" else "open")
            st[s] += 1
            if x.get("reviews"):
                reviewed += 1
                rs[s] += 1
            dec[(s, x.get("review_decision"))] += 1
    return {"n_joined": inter, "reviewed": reviewed,
            "reviewed_share": reviewed / inter if inter else None,
            "by_status": dict(st),
            "reviewed_by_status": dict(rs),
            "reviewed_share_by_status": {k: rs[k] / st[k] for k in st if st[k]},
            "review_decision_by_status": {f"{k[0]}|{k[1]}": v for k, v in dec.items()},
            "note": "只统计 pr_merged/pr_merged_retry 与 pr_reviews 的 PR number 交集；不是 189 仓全量。"}


def fork_section():
    rows = []
    for name in ("fork_prs.jsonl", "fork_prs_retry1.jsonl", "fork_prs_retry2.jsonl", "fork_prs_retry3.jsonl"):
        rows.extend(load_jsonl(name, "parent"))
    by = {}
    for r in rows:
        if r["parent"] not in by or (r.get("complete") and not by[r["parent"]].get("complete")):
            by[r["parent"]] = r
    src = json.load(open(os.path.join(DATA, "forks_timestamps_full.json"), encoding="utf-8"))
    tot_f = tot_head = tot_union = 0
    conv, delays, per = [], [], []
    for r in by.values():
        parent = r["parent"]
        forks = src.get(parent, [])
        fmap = {f.get("full_name"): f.get("created_at") for f in forks}
        head, auth = set(), set()
        for l in r.get("links", []):
            if l.get("matched_by") == "head_repo" and l.get("fork"):
                head.add(l["fork"])
            elif l.get("matched_by") == "author" and l.get("author"):
                auth.add(l["author"])
            # 只用 head_repo 匹配估时延；author 匹配会把非该父仓 fork 的人算进来
            if l.get("matched_by") == "head_repo" and l.get("fork"):
                ft = fmap.get(l.get("fork"))
                if ft and l.get("created_at"):
                    a, b = dt(ft), dt(l["created_at"])
                    if a and b:
                        delays.append((b - a).total_seconds() / 86400.0)
        union = head | auth
        tot_f += r.get("n_forks", 0)
        tot_head += len(head)
        tot_union += len(union)
        c = len(head) / r["n_forks"] if r.get("n_forks") else None
        conv.append(c)
        per.append({"parent": parent, "n_forks": r.get("n_forks"),
                    "head_matched": len(head), "author_only": len(auth - head),
                    "union_matched": len(union),
                    "head_conversion": c,
                    "union_conversion": len(union) / r["n_forks"] if r.get("n_forks") else None,
                    "n_prs": r.get("n_prs"), "n_matched_prs": r.get("n_matched")})
    per.sort(key=lambda x: -(x["head_conversion"] or 0))
    err_parents = set()
    for n in ("fork_prs.jsonl", "fork_prs_retry1.jsonl", "fork_prs_retry2.jsonl", "fork_prs_retry3.jsonl"):
        for e in load_jsonl(n, "error"):
            err_parents.add(e.get("parent"))
    n_errors = len(err_parents)
    return {"n_parents": len(by), "n_errors": n_errors, "total_forks": tot_f,
            "head_matched": tot_head, "author_only": tot_union - tot_head,
            "union_matched": tot_union,
            "head_conversion": tot_head / tot_f if tot_f else None,
            "union_conversion_upper_bound": tot_union / tot_f if tot_f else None,
            "median_parent_head_conversion": statistics.median([x for x in conv if x is not None]) if conv else None,
            "zero_head_match_parents": sum(1 for x in per if x["head_matched"] == 0),
            "delay_median_days": statistics.median(delays) if delays else None,
            "delay_p90_days": sorted(delays)[int(len(delays) * .9)] if delays else None,
            "note": "head_conversion 是可用下界；union 含 author 匹配，可能 >1，只能当上界。",
            "top_parents": per[:20]}


def market_section():
    # merge full + retry; choose max hits per repo/type
    sh, ch, reg = {}, {}, {}
    for name in ("market_full.jsonl", "market_retry.jsonl"):
        for o in load_jsonl(name):
            t = o.get("type")
            if t == "skills_sh":
                r = o.get("repo")
                if r and (r not in sh or (o.get("n_hits") or 0) > (sh[r].get("n_hits") or 0)):
                    sh[r] = o
            elif t == "clawhub_search":
                r = o.get("repo")
                if r and (r not in ch or (o.get("n_hits") or 0) > (ch[r].get("n_hits") or 0)):
                    ch[r] = o
            elif t == "clawhub_registry":
                it = o.get("item") or {}
                key = (it.get("ownerHandle"), it.get("slug"))
                reg[key] = it

    # prefix overrides
    for o in load_jsonl("skills_sh_prefix.jsonl", "skills_sh_prefix"):
        r = o.get("repo")
        if r:
            sh[r] = o

    # old 20-item lists
    old_rows = {}
    for p in glob.glob(os.path.join(MKT, "skills_sh_search_*.json")):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        for r in d.get("rows", []):
            old_rows[r.get("repo")] = r

    within = []
    old_compare = []
    for repo, o in sh.items():
        skills = o.get("skills") or []
        inst = [int(s.get("installs") or 0) for s in skills]
        if len(inst) >= 2:
            within.append({"repo": repo, "n": len(inst), "gini": gini(inst),
                           "top1": top1(inst), "total": sum(inst)})
        old = old_rows.get(repo)
        if old and old.get("skills"):
            oi = [int(s.get("installs") or 0) for s in old["skills"]]
            if len(oi) >= 2 and len(inst) >= 2:
                old_compare.append({
                    "repo": repo, "old_n": len(oi), "new_n": len(inst),
                    "old_total": sum(oi), "new_total": sum(inst),
                    "ratio": sum(inst) / sum(oi) if sum(oi) else None,
                    "old_gini": gini(oi), "new_gini": gini(inst),
                    "old_top1": top1(oi), "new_top1": top1(inst)})
    old_compare.sort(key=lambda x: -(x["ratio"] or 0))
    within_g = [x["gini"] for x in within if x["gini"] is not None]

    # clawhub registry platform concentration
    reg_dl = []
    reg_by_owner = collections.Counter()
    for it in reg.values():
        stats = it.get("stats") or {}
        d = int(stats.get("downloads") or 0)
        reg_dl.append(d)
        reg_by_owner[it.get("ownerHandle")] += d
    reg_g = gini(reg_dl) if reg_dl else None
    return {"skills_sh": {
                "n_repos_ok": len(sh),
                "n_with_hits": sum(1 for o in sh.values() if o.get("n_hits")),
                "possible_truncation": sum(1 for o in sh.values() if o.get("possible_truncation") or o.get("stopped_stale")),
                "within_repo_n": len(within),
                "within_repo_gini_median": statistics.median(within_g) if within_g else None,
                "within_repo_top1_median": statistics.median([x["top1"] for x in within if x["top1"] is not None]) if within else None,
                "old_vs_new": {"n": len(old_compare),
                               "median_total_ratio": statistics.median([x["ratio"] for x in old_compare if x["ratio"]]) if old_compare else None,
                               "n_ratio_gt_2": sum(1 for x in old_compare if (x["ratio"] or 0) > 2),
                               "top": old_compare[:20]}},
            "clawhub": {
                "n_repos_ok": len(ch),
                "n_with_hits": sum(1 for o in ch.values() if o.get("n_hits")),
                "registry_items": len(reg),
                "registry_owners": len(reg_by_owner),
                "registry_downloads": sum(reg_dl),
                "registry_gini": reg_g,
                "registry_top1_owner": (reg_by_owner.most_common(1)[0] if reg_by_owner else None)}}


def local_section():
    rows = load_jsonl("local_mining.jsonl", "repo")
    summary = next(iter(load_jsonl("local_mining.jsonl", "summary")), None)
    total_stars = sum(r.get("stars", 0) for r in rows)
    out = {"summary": summary, "total_stars": total_stars}
    for thr in (0.1, 0.3, 0.5, 0.7, 0.9, 0.99):
        rs = [r for r in rows if r.get("n_skills", 0) >= 5 and (r.get("share_cross") or 0) > thr]
        out[f"share_gt_{thr}"] = {"repos": len(rs),
                                  "repo_share": len(rs) / len(rows) if rows else None,
                                  "stars": sum(r.get("stars", 0) for r in rs),
                                  "star_share": sum(r.get("stars", 0) for r in rs) / total_stars if total_stars else None}
    bins = [("low_lt_0.1", lambda s: s < 0.1),
            ("mid_0.1_lt_0.5", lambda s: 0.1 <= s < 0.5),
            ("high_0.5_lt_0.9", lambda s: 0.5 <= s < 0.9),
            ("very_high_ge_0.9", lambda s: s >= 0.9)]
    out["n_repos_ge5"] = sum(1 for r in rows if r.get("n_skills", 0) >= 5)
    out["saturation_bins_n_ge5"] = {}
    for label, f in bins:
        rs = [r for r in rows if r.get("n_skills", 0) >= 5 and r.get("share_cross") is not None and f(r["share_cross"])]
        out["saturation_bins_n_ge5"][label] = {
            "repos": len(rs),
            "share_of_all_repos": len(rs) / len(rows) if rows else None,
            "stars": sum(r.get("stars", 0) for r in rs),
            "star_share": sum(r.get("stars", 0) for r in rs) / total_stars if total_stars else None}
    out["repo_type_note"] = "repo_type 的 mirror/original 是 share_cross 饱和度启发式，不是 source/mirror；anthropics/skills share_cross=1.0 也被标成 mirror。不要用它算镜像占比或传播方向。"
    return out


def near_section():
    meta = next(iter(load_jsonl("near_duplicates.jsonl", "meta")), None)
    pairs = 0
    same = cross = 0
    for o in load_jsonl("near_duplicates.jsonl", "pair"):
        pairs += 1
        if o.get("same_repo"):
            same += 1
        else:
            cross += 1
    clusters = load_jsonl("near_duplicates.jsonl", "cluster")
    return {"meta": meta, "pair_lines": pairs, "same_repo_pairs": same,
            "cross_repo_pairs": cross,
            "top_cluster_sizes": [c.get("size") for c in sorted(clusters, key=lambda x: -x.get("size", 0))[:15]]}


def topic_section():
    old = json.load(open(os.path.join(DATA, "topic_agent_skills_frame.json"), encoding="utf-8"))
    new = load_jsonl("topic_census.jsonl", "repo")
    seen = set()
    merged = []
    for r in old.get("repos", []):
        if r.get("id") not in seen:
            seen.add(r.get("id"))
            merged.append(r)
    for r in new:
        if r.get("id") not in seen:
            seen.add(r.get("id"))
            merged.append(r)
    def zero_share(rs):
        return sum(1 for r in rs if (r.get("stargazers_count") or 0) == 0) / len(rs) if rs else None
    years = collections.Counter((r.get("created_at") or "")[:4] for r in merged)
    return {"existing": len(old.get("repos", [])), "new": len(new),
            "merged_unique": len(merged),
            "search_total_count_claim": old.get("search_total_count"),
            "coverage_vs_claim": len(merged) / old.get("search_total_count") if old.get("search_total_count") else None,
            "zero_star_share_existing": zero_share(old.get("repos", [])),
            "zero_star_share_new": zero_share(new),
            "zero_star_share_merged": zero_share(merged),
            "median_stars_existing": statistics.median([r.get("stargazers_count") or 0 for r in old.get("repos", [])]) if old.get("repos") else None,
            "median_stars_new": statistics.median([r.get("stargazers_count") or 0 for r in new]) if new else None,
            "year_counts": dict(sorted(years.items())),
            "coverage_note": "search_total_count 是近似值；分区补采后唯一仓数已超过该值，不能把它当精确总量或缺失分母。"}


def direction_section():
    rows = load_jsonl("direction_sample.jsonl", "pair")
    dirs = collections.Counter(o.get("direction") for o in rows)
    conf = collections.Counter(o.get("confidence") for o in rows)
    cats = collections.Counter(o.get("category") for o in rows)
    neutral = {"mirror_original": "at_least_one_high_saturation",
               "original_original": "both_low_saturation",
               "other": "other_mixed"}
    cats_neutral = {neutral.get(k, k): v for k, v in cats.items()}
    lags = [abs(o["lag_days"]) for o in rows if o.get("lag_days") is not None]
    lags_sorted = sorted(lags)
    return {"n_pairs": len(rows), "direction": dict(dirs), "confidence": dict(conf),
            "category_raw": dict(cats), "category_neutral": cats_neutral,
            "abs_lag_median_days": statistics.median(lags) if lags else None,
            "abs_lag_p90_days": lags_sorted[int(len(lags_sorted) * .9)] if lags else None,
            "note": "category_raw 继承 local_mining 的 repo_type；该字段是复制饱和度启发式，不是 source/mirror。不要把它读成 original→mirror。meta 行是首轮 106 对的旧计数，已作废；只用 pair 行重算。"}


def issue_counts_section():
    rows = load_jsonl("issue_counts.jsonl", "repo")
    errors = load_jsonl("issue_counts.jsonl", "error")
    old_pr = sum(r.get("old_prs") or 0 for r in rows)
    actual_pr = sum(r.get("prs_graphql") or 0 for r in rows)
    old_is = sum(r.get("old_issues") or 0 for r in rows)
    actual_is = sum(r.get("pure_issues_graphql") or 0 for r in rows)
    pr_ratios = [r["pr_ratio"] for r in rows if r.get("pr_ratio")]
    is_ratios = [r["issue_ratio"] for r in rows if r.get("issue_ratio")]
    top = sorted([r for r in rows if r.get("pr_ratio") or r.get("issue_ratio")],
                 key=lambda r: -max(r.get("pr_ratio") or 0, r.get("issue_ratio") or 0))[:15]
    return {"n_repos": len(rows), "n_errors": len(errors),
            "old_prs": old_pr, "actual_prs": actual_pr,
            "old_issues": old_is, "actual_issues": actual_is,
            "pr_coverage_old_over_actual": old_pr / actual_pr if actual_pr else None,
            "issue_coverage_old_over_actual": old_is / actual_is if actual_is else None,
            "median_pr_ratio": statistics.median(pr_ratios) if pr_ratios else None,
            "median_issue_ratio": statistics.median(is_ratios) if is_ratios else None,
            "top_undercount": [{"repo": r["repo"], "old_prs": r.get("old_prs"),
                                "actual_prs": r.get("prs_graphql"),
                                "old_issues": r.get("old_issues"),
                                "actual_issues": r.get("pure_issues_graphql"),
                                "pr_ratio": r.get("pr_ratio"),
                                "issue_ratio": r.get("issue_ratio")} for r in top]}


def market_extra_section():
    rows = load_jsonl("market_extra.jsonl")
    sh = {r["repo"]: r for r in rows if r.get("type") == "skills_sh"}
    ch = {r["repo"]: r for r in rows if r.get("type") == "clawhub_search"}
    return {"n_repos": len(set(sh) | set(ch)),
            "repos": [{"repo": r,
                       "skills_sh_hits": sh.get(r, {}).get("n_hits"),
                       "skills_sh_installs": sh.get(r, {}).get("total_installs"),
                       "clawhub_hits": ch.get(r, {}).get("n_hits"),
                       "clawhub_downloads": ch.get(r, {}).get("total_downloads")}
                      for r in sorted(set(sh) | set(ch))]}


def release_section():
    rows = load_jsonl("release_downloads.jsonl", "repo")
    gh = [r for r in rows if (r.get("github") or {}).get("downloads", 0) > 0]
    npm = [r for r in rows if (r.get("npm") or {}).get("downloads")]
    return {"n_repos": len(rows), "github_with_downloads": len(gh),
            "github_total_downloads": sum((r.get("github") or {}).get("downloads", 0) for r in rows),
            "npm_with_downloads": len(npm),
            "top_github": [{"repo": r["repo"], **(r.get("github") or {})}
                           for r in sorted(rows, key=lambda r: -((r.get("github") or {}).get("downloads") or 0))[:15]]}


def load_result_json(name):
    p = os.path.join(ROOT, "data", "results", name)
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return None


def main():
    out = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "collect_dir": CD,
        "pr_merged": pr_section(),
        "pr_reviews": reviews_section(),
        "review_pr_join": review_join_section(),
        "fork_prs": fork_section(),
        "market": market_section(),
        "market_extra": market_extra_section(),
        "issue_counts": issue_counts_section(),
        "local": local_section(),
        "near_duplicates": near_section(),
        "near_validation": load_result_json("near_validation.json"),
        "exact_near_union": load_result_json("exact_near_union.json"),
        "topic_census": topic_section(),
        "direction": direction_section(),
        "release_downloads": release_section(),
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
