# -*- coding: utf-8 -*-
"""
mine_comprehensive.py — 第十轮：全数据综合挖掘（2026-10-29）
覆盖四层：
  A. fork→PR 终值层（225 父仓 / 1.83M fork / 447,495 PR 事件）
  B. PR 评论层（45,360 PR / 61,078 评论 / reviews）
  C. SKILL.md 文件历史层（684 侧）
  D. 跨层整合（341 面板：可见性→采纳→贡献→把关）
输出：data/results/mine_comprehensive_20261029.json
"""
import json
import glob
import os
import re
import collections
import datetime
import statistics
import math

import numpy as np
from scipy import stats

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = r"E:\temp\opencode"
COL = os.path.join(ROOT, "external_data", "collected_20261024")
OUT = os.path.join(ROOT, "data", "results", "mine_comprehensive_20261029.json")


def iso(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def gini(xs):
    xs = sorted(x for x in xs if x is not None)
    n = len(xs)
    if n == 0:
        return None
    s = sum(xs)
    if s == 0:
        return 0.0
    cum = 0.0
    for i, x in enumerate(xs, 1):
        cum += i * x
    return round((2 * cum) / (n * s) - (n + 1) / n, 4)


def q(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    k = max(0, min(len(xs) - 1, int(round(p * (len(xs) - 1)))))
    return xs[k]


res = {"generated_at": datetime.datetime.now().isoformat(timespec="seconds")}

# ================= 载入 fork→PR 终值 =================
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

links = []
for p, row in best.items():
    for l in row.get("links") or []:
        ll = dict(l)
        ll["parent"] = p
        links.append(ll)

A = {}
# A1 结局结构
states = collections.Counter((l.get("state") or "").upper() for l in links)
merged = [l for l in links if l.get("merged_at")]
closed_unmerged = [l for l in links if (l.get("state") or "").upper() == "CLOSED" and not l.get("merged_at")]
opened = [l for l in links if (l.get("state") or "").upper() == "OPEN"]
A["A1_outcomes"] = {
    "total_events": len(links),
    "merged": len(merged), "merged_pct": round(100 * len(merged) / len(links), 2),
    "closed_unmerged": len(closed_unmerged),
    "closed_unmerged_pct": round(100 * len(closed_unmerged) / len(links), 2),
    "open": len(opened), "open_pct": round(100 * len(opened) / len(links), 2),
    "merge_share_of_closed": round(100 * len(merged) / max(1, len(merged) + len(closed_unmerged)), 2),
    "note": "merged 以 merged_at 非空判定；REST 与 GraphQL 的 state 约定不同（closed vs CLOSED/MERGED），不单列 raw state",
}

# A2 生命周期
life_m = [(iso(l["merged_at"]) - iso(l["created_at"])).total_seconds() / 3600 for l in merged
          if iso(l["merged_at"]) and iso(l["created_at"])]
life_c = [(iso(l["closed_at"]) - iso(l["created_at"])).total_seconds() / 3600 for l in closed_unmerged
          if iso(l.get("closed_at")) and iso(l["created_at"])]
A["A2_lifetime_hours"] = {
    "merged_n": len(life_m), "merged_median_h": round(statistics.median(life_m), 2),
    "merged_p90_h": round(q(life_m, 0.9), 2),
    "closed_median_h": round(statistics.median(life_c), 2), "closed_p90_h": round(q(life_c, 0.9), 2),
}

# A3 回流 lag 细分布（需 fork 时间戳）
lag_bins = [0, 1 / 24, 6 / 24, 1, 3, 7, 30, 90, 365, 10 ** 9]
lag_labels = ["<1h", "1-6h", "6-24h", "1-3d", "3-7d", "7-30d", "30-90d", "90-365d", ">365d"]
lag_counts = [0] * len(lag_labels)
lags_all = []
try:
    src = json.load(open(os.path.join(ROOT, "data", "forks_timestamps_full.json"), encoding="utf-8"))
    for p, row in best.items():
        fmap = {f.get("full_name"): f.get("created_at") for f in (src.get(p) or [])}
        for l in row.get("links") or []:
            if l.get("matched_by") == "head_repo" and l.get("fork") in fmap:
                tf, tp = iso(fmap[l["fork"]]), iso(l.get("created_at"))
                if tf and tp:
                    dd = (tp - tf).total_seconds() / 86400
                    if dd >= 0:
                        lags_all.append(dd)
                        for i in range(len(lag_labels)):
                            if lag_bins[i] <= dd < lag_bins[i + 1]:
                                lag_counts[i] += 1
                                break
    del src
except Exception as e:
    A["A3_error"] = str(e)[:120]
A["A3_lag_fine_bins"] = {"n": len(lags_all),
                         "bins": {lab: round(100 * c / max(1, len(lags_all)), 2)
                                  for lab, c in zip(lag_labels, lag_counts)}}

# A4 作者集中度
author_cnt = collections.Counter(l.get("author") for l in links if l.get("author"))
top_auth = author_cnt.most_common(10)
A["A4_author_concentration"] = {
    "unique_authors": len(author_cnt),
    "gini": gini(list(author_cnt.values())),
    "top10_share_pct": round(100 * sum(c for _, c in top_auth) / len(links), 2),
    "top10": top_auth,
}
# 每父仓 top1 作者份额（回流单点化）
tp = []
for p, row in best.items():
    cnt = collections.Counter((l.get("author") or "") for l in row.get("links") or [])
    tot = sum(cnt.values())
    if tot >= 10:
        tp.append(max(cnt.values()) / tot)
A["A4_parent_top1_author_share_median"] = round(100 * statistics.median(tp), 2) if tp else None
A["A4_parent_top1_n"] = len(tp)

# A5 父仓转化率分布（双峰）
conv = []
for p, row in best.items():
    nf = row.get("n_forks") or 0
    if nf >= 100:
        ret = len({l.get("fork") or l.get("author") for l in row.get("links") or []})
        conv.append((p, ret / nf, nf))
vals = [c for _, c, _ in conv]
hist_edges = [0, .01, .02, .05, .10, .20, .40, 1.01]
hist_labels = ["0-1%", "1-2%", "2-5%", "5-10%", "10-20%", "20-40%", ">40%"]
hist = [0] * len(hist_labels)
for v in vals:
    for i in range(len(hist_labels)):
        if hist_edges[i] <= v < hist_edges[i + 1]:
            hist[i] += 1
            break
# 帕累托：多少父仓贡献 50% 回流 fork
by_ret = sorted(conv, key=lambda x: -(x[1] * x[2]))
tot_ret = sum(c * n for _, c, n in conv)
acc = 0
n50 = 0
for _, c, n in by_ret:
    acc += c * n
    n50 += 1
    if acc >= tot_ret / 2:
        break
A["A5_conversion_distribution"] = {
    "n_parents_forks_ge100": len(vals),
    "histogram": dict(zip(hist_labels, hist)),
    "median_pct": round(100 * statistics.median(vals), 2) if vals else None,
    "q90_pct": round(100 * q(vals, 0.9), 2) if vals else None,
    "parents_for_half_of_returns": n50,
    "parents_pct_for_half_of_returns": round(100 * n50 / max(1, len(vals)), 1),
}

# A6 月度分布
month = collections.Counter()
for l in links:
    t = iso(l.get("created_at"))
    if t:
        month[t.strftime("%Y-%m")] += 1
A["A6_monthly_events"] = dict(sorted(month.items()))

# A7 父仓特征与转化率
meta = json.load(open(os.path.join(ROOT, "data", "repos_meta.json"), encoding="utf-8"))
rows7 = []
for p, c, nf in conv:
    m = meta.get(p)
    if not m or not m.get("stars"):
        continue
    age = (datetime.datetime.now(datetime.timezone.utc) -
           iso(m["created_at"])).days if m.get("created_at") else None
    if age:
        rows7.append((math.log10(m["stars"]), math.log10(nf), age / 365.0, c))
if len(rows7) >= 20:
    X = np.array([[1, r[0], r[1], r[2]] for r in rows7])
    y = np.array([r[3] for r in rows7])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    yhat = X @ beta
    ss_res = float(((y - yhat) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot else None
    rho, pv = stats.spearmanr([r[0] for r in rows7], y)
    A["A7_regression"] = {
        "n": len(rows7),
        "coef_intercept": round(float(beta[0]), 4),
        "coef_log10_stars": round(float(beta[1]), 4),
        "coef_log10_forks": round(float(beta[2]), 4),
        "coef_age_years": round(float(beta[3]), 4),
        "r2": round(r2, 4) if r2 is not None else None,
        "spearman_stars_conversion": [round(float(rho), 3), round(float(pv), 4)],
    }
else:
    A["A7_regression"] = {"n": len(rows7), "note": "样本不足"}

# A8 各父仓合并率
A["A8_merge_rate_by_parent"] = {
    "median_pct": None,
}
mr = []
for p, row in best.items():
    ls = row.get("links") or []
    if len(ls) >= 20:
        m = sum(1 for l in ls if l.get("merged_at"))
        mr.append(100 * m / len(ls))
A["A8_merge_rate_by_parent"] = {
    "n": len(mr),
    "median_pct": round(statistics.median(mr), 1) if mr else None,
    "p10_pct": round(q(mr, 0.1), 1) if mr else None,
    "p90_pct": round(q(mr, 0.9), 1) if mr else None,
}
res["A_fork_pr"] = A

# ================= B. PR 评论层 =================
B = {}
prs = []
n_repo = 0
for line in open(os.path.join(TMP, "pr_comments.jsonl"), encoding="utf-8", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get("type") != "repo":
        continue
    n_repo += 1
    for pr in d.get("prs") or []:
        pr["_repo"] = d["repo"]
        prs.append(pr)

cc = collections.Counter()
merge_latency_with = []
merge_latency_without = []
first_lags = []
last_pre_merge_lag = []
comment_lens = []
human_lens = []
bot_lens = []
kw = collections.Counter()
per_repo_commenter = collections.defaultdict(collections.Counter)
review_states = collections.Counter()
review_body_lens = []
reviews_per_pr = []
BOT = re.compile(r"(\[bot\]$|-bot$|^dependabot|^renovate|^github-actions|^codecov|^greenkeeper|^mergify|^imgbot|^allcontributors)", re.I)
HUMAN_LENS = []

for pr in prs:
    comments = pr.get("comments") or []
    reviews = pr.get("reviews") or []
    nc = len(comments)
    cc["prs"] += 1
    cc["prs_0" if nc == 0 else ("prs_1" if nc == 1 else ("prs_2_5" if nc <= 5 else "prs_6p"))] += 1
    t0 = iso(pr.get("created_at"))
    tm = iso(pr.get("merged_at"))
    tc = iso(pr.get("closed_at"))
    if comments:
        first = min(iso(c.get("created_at")) for c in comments if iso(c.get("created_at")))
        if first and t0:
            first_lags.append((first - t0).total_seconds() / 3600)
    if tm:
        pre = [c for c in comments if iso(c.get("created_at")) and iso(c.get("created_at")) <= tm]
        lat = (tm - t0).total_seconds() / 3600 if t0 else None
        if lat is not None:
            (merge_latency_with if pre else merge_latency_without).append(lat)
        if pre:
            last = max(iso(c.get("created_at")) for c in pre if iso(c.get("created_at")))
            last_pre_merge_lag.append((tm - last).total_seconds() / 3600)
    for c in comments:
        body = c.get("body") or ""
        a = c.get("author") or ""
        if BOT.match(a):
            bot_lens.append(len(body))
            continue
        human_lens.append(len(body))
        HUMAN_LENS.append(len(body))
        if a:
            per_repo_commenter[pr["_repo"]][a] += 1
        lb = body.lower()
        if "```" in body:
            kw["code_block"] += 1
        if re.search(r"https?://", body):
            kw["url"] += 1
        if re.search(r"\b(lgtm|looks good|approved?|ship it|merge|nice work|thanks|thank you)\b", lb):
            kw["approval_like"] += 1
        if re.search(r"\b(please|fix|change|nit|should|could you|needs? )", lb):
            kw["request_like"] += 1
        if re.search(r"[\u4e00-\u9fff]", body):
            kw["cjk"] += 1
        if len(body.strip()) < 25:
            kw["short_lt25"] += 1
        if re.search(r"\?$|\?\s*$", body.strip()):
            kw["question"] += 1
    reviews_per_pr.append(len(reviews))
    for rv in reviews:
        review_states[(rv.get("state") or "").upper()] += 1
        review_body_lens.append(len(rv.get("body") or ""))

n_com = sum(cc[k] for k in ("prs_0", "prs_1", "prs_2_5", "prs_6p"))
B["B1_comment_coverage"] = {
    "n_repos": n_repo, "n_prs": cc["prs"],
    "zero": cc["prs_0"], "one": cc["prs_1"], "two_to_five": cc["prs_2_5"], "six_plus": cc["prs_6p"],
    "zero_pct": round(100 * cc["prs_0"] / max(1, cc["prs"]), 2),
    "six_plus_pct": round(100 * cc["prs_6p"] / max(1, cc["prs"]), 2),
}
B["B2_timing_hours"] = {
    "first_comment_median_h": round(statistics.median(first_lags), 2) if first_lags else None,
    "first_comment_p90_h": round(q(first_lags, 0.9), 2) if first_lags else None,
    "last_pre_merge_comment_to_merge_median_h": round(statistics.median(last_pre_merge_lag), 2)
    if last_pre_merge_lag else None,
    "n_last_pre_merge": len(last_pre_merge_lag),
}
tot_com = len(HUMAN_LENS)
B["B3_comment_text"] = {
    "n_human_comments": tot_com,
    "len_median_chars": round(statistics.median(HUMAN_LENS), 1) if HUMAN_LENS else None,
    "len_p90_chars": round(q(HUMAN_LENS, 0.9), 1) if HUMAN_LENS else None,
    "code_block_pct": round(100 * kw["code_block"] / max(1, tot_com), 2),
    "url_pct": round(100 * kw["url"] / max(1, tot_com), 2),
    "approval_like_pct": round(100 * kw["approval_like"] / max(1, tot_com), 2),
    "request_like_pct": round(100 * kw["request_like"] / max(1, tot_com), 2),
    "cjk_pct": round(100 * kw["cjk"] / max(1, tot_com), 2),
    "very_short_pct": round(100 * kw["short_lt25"] / max(1, tot_com), 2),
    "question_pct": round(100 * kw["question"] / max(1, tot_com), 2),
    "note": "文本统计仅人类评论；机器人（含 github-actions/codecov）单列",
}
# B4 单点把关
tops = []
for repo, cnt in per_repo_commenter.items():
    tot = sum(cnt.values())
    if tot >= 10:
        tops.append(max(cnt.values()) / tot)
B["B4_single_point_share"] = {
    "n_repos_ge10": len(tops),
    "median_top1_commenter_pct": round(100 * statistics.median(tops), 1) if tops else None,
    "p90_pct": round(100 * q(tops, 0.9), 1) if tops else None,
}
# B5 reviews
B["B5_reviews"] = {
    "state_counts": dict(review_states),
    "review_body_len_median": round(statistics.median(review_body_lens), 1) if review_body_lens else None,
    "empty_review_body_pct": round(100 * sum(1 for x in review_body_lens if x == 0) / max(1, len(review_body_lens)), 1),
    "prs_with_review_pct": round(100 * sum(1 for x in reviews_per_pr if x > 0) / max(1, len(reviews_per_pr)), 1),
}
# B6 把关效果（合并时滞）
if len(merge_latency_with) >= 10 and len(merge_latency_without) >= 10:
    u, pv = stats.mannwhitneyu(merge_latency_with, merge_latency_without, alternative="two-sided")
    B["B6_gatekeeping_effect"] = {
        "merged_with_pre_comment_n": len(merge_latency_with),
        "median_h_with": round(statistics.median(merge_latency_with), 2),
        "merged_without_n": len(merge_latency_without),
        "median_h_without": round(statistics.median(merge_latency_without), 2),
        "mannwhitney_p": round(float(pv), 4),
    }
# B7 bot vs human
B["B7_bot_human"] = {
    "bot_comments": len(bot_lens), "human_comments": len(human_lens),
    "bot_pct": round(100 * len(bot_lens) / max(1, len(bot_lens) + len(human_lens)), 2),
    "bot_len_median": round(statistics.median(bot_lens), 1) if bot_lens else None,
    "human_len_median": round(statistics.median(human_lens), 1) if human_lens else None,
    "definition": "GitHub App 惯例：[bot] 后缀 / dependabot / renovate / github-actions / codecov 等（含登录名不含 bot 的 CI 账号）",
}
res["B_pr_comments"] = B

# ================= C. SKILL.md 历史层 =================
C = {}
rows = []
for line in open(os.path.join(TMP, "skillmd_history.jsonl"), encoding="utf-8", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    rows.append(d)
ok = [r for r in rows if str(r.get("status", "")).startswith("ok")]
commits = [r["n_commits"] for r in ok if r.get("n_commits")]
life = []
for r in ok:
    a, b = iso(r.get("first_commit")), iso(r.get("last_commit"))
    if a and b and b >= a:
        life.append((b - a).total_seconds() / 86400)
status_mix = collections.Counter(r.get("status") for r in rows)
C["C1_history_shape"] = {
    "n_sides_total": len(rows), "n_sides_ok": len(ok),
    "commits_median": int(statistics.median(commits)) if commits else None,
    "commits_p90": int(q(commits, 0.9)) if commits else None,
    "commits_max": max(commits) if commits else None,
    "lifespan_days_median": round(statistics.median(life), 1) if life else None,
    "status_mix": dict(status_mix),
}
# C2 署名动态
added_later_fields = collections.Counter()
for r in rows:
    if r.get("status") == "ok_attr_added_later":
        for f in (r.get("attrib_fields_now") or []):
            added_later_fields[f] += 1
birth_fields = collections.Counter()
for r in rows:
    for f in (r.get("attrib_at_birth") or []):
        birth_fields[f] += 1
C["C2_attribution_dynamics"] = {
    "at_birth_fields": dict(birth_fields.most_common()),
    "added_later_fields": dict(added_later_fields.most_common()),
    "added_later_n": sum(1 for r in rows if r.get("status") == "ok_attr_added_later"),
}
# C3 commit 数 × 署名状态
by_status = collections.defaultdict(list)
for r in ok:
    if r.get("n_commits"):
        by_status[r.get("status")].append(r["n_commits"])
C["C3_commits_by_status"] = {k: {"n": len(v), "median": int(statistics.median(v))} for k, v in by_status.items()}
if "ok_attr_at_birth" in by_status and "ok_no_attr_ever" in by_status and len(by_status["ok_attr_at_birth"]) > 5:
    u, pv = stats.mannwhitneyu(by_status["ok_attr_at_birth"], by_status["ok_no_attr_ever"],
                               alternative="two-sided")
    C["C3_commits_by_status"]["mannwhitney_p_birth_vs_never"] = round(float(pv), 4)
# C4 对子内父/子 commit 对比
pairs = collections.defaultdict(dict)
for r in rows:
    if r.get("pair_id") and r.get("side"):
        pairs[r["pair_id"]][r["side"]] = r
diffs = []
for pid, d in pairs.items():
    a, b = d.get("a"), d.get("b")
    if not a or not b or not a.get("n_commits") or not b.get("n_commits"):
        continue
    fa, fb = iso(a.get("first_commit")), iso(b.get("first_commit"))
    if not fa or not fb:
        continue
    parent, child = (a, b) if fa < fb else (b, a)
    diffs.append((parent["n_commits"], child["n_commits"]))
if diffs:
    pm = [x for x, _ in diffs]
    cm = [y for _, y in diffs]
    C["C4_parent_child_commits"] = {
        "n_pairs": len(diffs),
        "parent_median": int(statistics.median(pm)), "child_median": int(statistics.median(cm)),
        "child_more_commits_pct": round(100 * sum(1 for x, y in diffs if y > x) / len(diffs), 1),
    }
res["C_skillmd_history"] = C

# ================= D. 跨层整合 =================
D = {}
# D1 漏斗（341 面板）
panel = set(meta)
skills_sh = {}
claw = {}
for line in open(os.path.join(COL, "market_full.jsonl"), encoding="utf-8", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    t = d.get("type")
    if t == "skills_sh":
        skills_sh[d.get("repo")] = d.get("total_installs") or 0
    elif t == "clawhub_search":
        claw[d.get("repo")] = d.get("total_downloads") or 0
prs_cnt = {}
for line in open(os.path.join(COL, "issue_counts.jsonl"), encoding="utf-8", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    prs_cnt[d.get("repo")] = d.get("prs_graphql")
D["D1_funnel_341"] = {
    "panel": len(panel),
    "stars_gt0": sum(1 for r in panel if (meta[r].get("stars") or 0) > 0),
    "skills_sh_hit": sum(1 for r in panel if skills_sh.get(r, 0) > 0),
    "clawhub_hit": sum(1 for r in panel if claw.get(r, 0) > 0),
    "forks_ge10": sum(1 for r in panel if (meta[r].get("forks") or 0) >= 10),
    "prs_ge1": sum(1 for r in panel if (prs_cnt.get(r) or 0) > 0),
    "fork_pr_scanned": sum(1 for r in panel if r in best),
    "fork_pr_returning_gt0": sum(1 for r in panel if r in best and best[r].get("n_matched", 0) > 0),
}
# D2 复制强度 × fork（用 local_mining 仓级聚合）
lm_repo = {}
for line in open(os.path.join(COL, "local_mining.jsonl"), encoding="utf-8", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get("type") == "repo":
        lm_repo[d["repo"]] = d
common = [r for r in panel if r in lm_repo and meta[r].get("forks") and lm_repo[r].get("n_skills")]
if len(common) >= 20:
    xs = [lm_repo[r].get("share_cross") or 0 for r in common]
    ys = [meta[r]["forks"] for r in common]
    rho, pv = stats.spearmanr(xs, ys)
    xs2 = [lm_repo[r].get("n_shared_sha") or 0 for r in common]
    rho2, pv2 = stats.spearmanr(xs2, ys)
    # 署名率 × 星标（顺带）
    fa = [(lm_repo[r].get("fm_author") or 0) / max(1, lm_repo[r].get("fm_valid") or 1) for r in common]
    st = [meta[r].get("stars") or 0 for r in common]
    rho3, pv3 = stats.spearmanr(fa, st)
    D["D2_copy_vs_fork"] = {
        "n": len(common),
        "spearman_share_cross_vs_forks": [round(float(rho), 3), round(float(pv), 4)],
        "spearman_shared_sha_vs_forks": [round(float(rho2), 3), round(float(pv2), 4)],
        "spearman_fm_author_rate_vs_stars": [round(float(rho3), 3), round(float(pv3), 4)],
        "share_cross_median_pct": round(100 * statistics.median(xs), 1),
        "share_cross_p90_pct": round(100 * q(xs, 0.9), 1),
    }
# D3 平台命中 × 回流转化
common3 = [r for r in panel if r in best and (best[r].get("n_forks") or 0) >= 100]
hit = [r for r in common3 if skills_sh.get(r, 0) > 0]
miss = [r for r in common3 if skills_sh.get(r, 0) == 0]
def _conv(r):
    nf = best[r]["n_forks"]
    ret = len({l.get("fork") or l.get("author") for l in best[r]["links"]})
    return ret / nf
if len(hit) >= 5 and len(miss) >= 5:
    u, pv = stats.mannwhitneyu([_conv(r) for r in hit], [_conv(r) for r in miss], alternative="two-sided")
    D["D3_platform_vs_return"] = {
        "n_hit": len(hit), "n_miss": len(miss),
        "median_conv_hit_pct": round(100 * statistics.median([_conv(r) for r in hit]), 2),
        "median_conv_miss_pct": round(100 * statistics.median([_conv(r) for r in miss]), 2),
        "mannwhitney_p": round(float(pv), 4),
    }
# D4 审查×评论 交叉（已合并 PR）
cross = collections.Counter()
for pr in prs:
    if not pr.get("merged_at"):
        continue
    has_rev = any((rv.get("state") or "").upper() in ("APPROVED", "CHANGES_REQUESTED") for rv in (pr.get("reviews") or []))
    has_com = bool([c for c in (pr.get("comments") or [])
                    if iso(c.get("created_at")) and iso(c.get("created_at")) <= iso(pr["merged_at"])])
    cross[("review" if has_rev else "no_review") + "|" + ("comment" if has_com else "no_comment")] += 1
tot = sum(cross.values())
D["D4_gate_cross"] = {k: {"n": v, "pct": round(100 * v / max(1, tot), 2)} for k, v in cross.items()}
res["D_cross_layer"] = D

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False, indent=1)
print(json.dumps(res, ensure_ascii=False, indent=1)[:6000])
print("written:", OUT)
