# -*- coding: utf-8 -*-
"""
analyze_skillmd_prcomments.py — 两项新采集的分析（2026-10-26）
对应进度汇报二.3 / 二.4 的结论层：

A. 父—子方向性检验（P3 复制—溯源，确认性支持）
   输入：E:/temp/opencode/skillmd_history.jsonl（pair×side 文件历史与署名写入时间）
        E:/temp/opencode/direction_commits.jsonl（165 对最早提交判定，对照）
   指标：
   - 方向判别：文件首创时间 / 署名写入时间 / fork 元数据 三种证据的一致率
   - 署名写入时点：诞生即写 vs 后补 vs 从未写（生产端稀薄 vs 复制磨损）
   - 复制对署名保留：沿方向（父→子）的保留率，与独立期望对照

B. 评论式把关（P4 规模—把关）
   输入：E:/temp/opencode/pr_comments.jsonl（164 仓 PR 评论全文）
   指标：
   - 合并前评论覆盖（PR 层 / 仓层随规模）
   - 评论时序（首评距创建、合并前评论占比）
   - 机器人与人类评论者结构
   - 仅评论无正式审查（非正式把关）的规模

输出：data/results/direction_gatekeep_20261026.json
"""
import json
import os
import re
import collections
import datetime
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = r"E:\temp\opencode"
OUT = os.path.join(ROOT, "data", "results", "direction_gatekeep_20261026.json")

BOT_RE = re.compile(r"(\[bot\]$|-bot$|^dependabot|^renovate|^github-actions|^codecov|^greenkeeper|^mergify|^imgbot|^allcontributors|^sourcery-|^copybara)", re.I)


def is_bot(login):
    return bool(login) and bool(BOT_RE.match(login))


def iso(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def wilson(k, n, z=1.96):
    if n == 0:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return [round((c - h) / d, 4), round((c + h) / d, 4)]


# ================= A. 父—子方向性检验 =================

def analyze_direction():
    sides = collections.defaultdict(dict)  # pair_id -> {side: row}
    for path in (os.path.join(TMP, "skillmd_history.jsonl"),):
        if not os.path.exists(path):
            continue
        for line in open(path, encoding="utf-8", errors="replace"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("pair_id") and r.get("side"):
                sides[r["pair_id"]][r["side"]] = r

    old_dir = {}
    p = os.path.join(TMP, "direction_commits.jsonl")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8", errors="replace"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            key = (r.get("a"), r.get("b"), r.get("a_path"), r.get("b_path"))
            old_dir[key] = r.get("verdict")

    stats = collections.Counter()
    n_pairs = 0
    agree_history_attr = 0
    comp_attr = 0
    comp_attr_trivial = 0
    comp_attr_nontrivial = 0
    agree_attr_nontrivial = 0
    n_both_times = 0
    agree_old_hist = 0
    n_old_comparable = 0
    fork_directed = 0
    attr_birth = 0
    attr_later = 0
    attr_never = 0
    pair_parent_has_attr = 0
    pair_child_keeps_attr = 0
    comp_write_before = 0
    write_before_child = 0
    lags = []
    detail = []

    for pid, d in sorted(sides.items()):
        a, b = d.get("a"), d.get("b")
        if not a or not b:
            continue
        ok = [x for x in (a, b) if x.get("n_commits")]
        if len(ok) < 2:
            stats["pair_skipped_incomplete"] += 1
            continue
        n_pairs += 1
        fa = iso(a.get("first_commit"))
        fb = iso(b.get("first_commit"))
        aa = iso(a.get("attr_write_date"))
        ab = iso(b.get("attr_write_date"))
        ma = (a.get("meta") or {})
        mb = (b.get("meta") or {})

        # fork 直接定向：谁是谁的 parent
        fork_dir = None
        if ma.get("parent") == b.get("repo"):
            fork_dir = "b_parent"
        elif mb.get("parent") == a.get("repo"):
            fork_dir = "a_parent"
        if fork_dir:
            fork_directed += 1

        # 文件首创时间方向（独立证据）
        hist_dir = None
        if fa and fb:
            if fa < fb:
                hist_dir = "a_parent"
            elif fb < fa:
                hist_dir = "b_parent"
        # 署名写入时间方向（仅双方都有写入时间时可比；只作被检验对象）
        attr_order = None
        if aa and ab:
            n_both_times += 1
            if aa < ab:
                attr_order = "a_parent"
            elif ab < aa:
                attr_order = "b_parent"

        # 主方向：fork 元数据优先，其次文件首创时间
        main_dir = fork_dir or hist_dir

        if main_dir and attr_order:
            comp_attr += 1
            if main_dir == attr_order:
                agree_history_attr += 1
            # 两侧署名都诞生即写 → 写入时间=首创时间，属平凡一致，单列
            both_birth = bool(a.get("attrib_at_birth")) and bool(b.get("attrib_at_birth"))
            if both_birth:
                comp_attr_trivial += 1
            else:
                comp_attr_nontrivial += 1
                if main_dir == attr_order:
                    agree_attr_nontrivial += 1

        key = (a.get("repo"), b.get("repo"), a.get("path"), b.get("path"))
        verd_old = old_dir.get(key)
        if verd_old and hist_dir:
            n_old_comparable += 1
            mapped = {"a_first": "a_parent", "b_first": "b_parent"}.get(verd_old)
            if mapped == hist_dir:
                agree_old_hist += 1

        for x in (a, b):
            st = x.get("status", "")
            if st == "ok_attr_at_birth":
                attr_birth += 1
            elif st == "ok_attr_added_later":
                attr_later += 1
            elif st == "ok_no_attr_ever":
                attr_never += 1

        # 沿独立方向（main_dir）检验署名写入时点与保留
        if main_dir == "a_parent":
            parent, child = a, b
        elif main_dir == "b_parent":
            parent, child = b, a
        else:
            parent = child = None
        if parent is not None:
            p_has = bool(parent.get("attrib_fields_now") or parent.get("attrib_at_birth"))
            c_has = bool(child.get("attrib_fields_now") or child.get("attrib_at_birth"))
            if p_has:
                pair_parent_has_attr += 1
                if c_has:
                    pair_child_keeps_attr += 1
            pw = iso(parent.get("attr_write_date"))
            fc = iso(child.get("first_commit"))
            if pw and fc:
                comp_write_before += 1
                if pw <= fc:
                    write_before_child += 1
            fp = iso(parent.get("first_commit"))
            if fp and fc and fc > fp:
                lags.append((fc - fp).total_seconds() / 86400.0)

        detail.append({"pair_id": pid, "fork_dir": fork_dir, "hist_dir": hist_dir,
                       "attr_order": attr_order, "old_verdict": verd_old,
                       "a": {"repo": a.get("repo"), "first": a.get("first_commit"),
                             "attr_write": a.get("attr_write_date"),
                             "attr_birth": a.get("attrib_at_birth"),
                             "attr_now": a.get("attrib_fields_now")},
                       "b": {"repo": b.get("repo"), "first": b.get("first_commit"),
                             "attr_write": b.get("attr_write_date"),
                             "attr_birth": b.get("attrib_at_birth"),
                             "attr_now": b.get("attrib_fields_now")}})

    n_sides = attr_birth + attr_later + attr_never
    out = {
        "n_pairs_analyzed": n_pairs,
        "n_sides": n_sides,
        "direction_evidence": {
            "fork_directed_pairs": fork_directed,
            "attr_order_vs_direction_agree": agree_history_attr,
            "attr_order_vs_direction_comparable": comp_attr,
            "attr_order_vs_direction_agree_pct": round(agree_history_attr / comp_attr, 4) if comp_attr else None,
            "attr_order_vs_direction_agree_wilson95": wilson(agree_history_attr, comp_attr),
            "attr_order_comparable_trivial_both_birth": comp_attr_trivial,
            "attr_order_comparable_nontrivial": comp_attr_nontrivial,
            "attr_order_nontrivial_agree": agree_attr_nontrivial,
            "attr_order_nontrivial_agree_pct": round(agree_attr_nontrivial / comp_attr_nontrivial, 4)
            if comp_attr_nontrivial else None,
            "old_vs_history_agree": agree_old_hist,
            "old_vs_history_comparable": n_old_comparable,
            "old_vs_history_agree_pct": round(agree_old_hist / n_old_comparable, 4) if n_old_comparable else None,
            "attr_written_before_child_copy": write_before_child,
            "attr_written_before_child_copy_comparable": comp_write_before,
            "attr_written_before_child_copy_pct": round(write_before_child / comp_write_before, 4)
            if comp_write_before else None,
            "attr_written_before_child_copy_wilson95": wilson(write_before_child, comp_write_before),
        },
        "attr_write_timing": {
            "at_birth": attr_birth,
            "at_birth_pct": round(attr_birth / n_sides, 4) if n_sides else None,
            "added_later": attr_later,
            "added_later_pct": round(attr_later / n_sides, 4) if n_sides else None,
            "never": attr_never,
            "never_pct": round(attr_never / n_sides, 4) if n_sides else None,
        },
        "retention_along_direction": {
            "parent_has_attr_pairs": pair_parent_has_attr,
            "child_keeps_attr_pairs": pair_child_keeps_attr,
            "child_keep_pct": round(pair_child_keeps_attr / pair_parent_has_attr, 4)
            if pair_parent_has_attr else None,
            "child_keep_wilson95": wilson(pair_child_keeps_attr, pair_parent_has_attr),
            "copy_lag_days_median": round(statistics.median(lags), 2) if lags else None,
            "copy_lag_days_p90": round(sorted(lags)[int(0.9 * len(lags)) - 1], 2) if lags else None,
            "n_lags": len(lags),
        },
        "status_mix": dict(collections.Counter(
            s.get("status") for pair in sides.values() for s in pair.values())),
    }
    out["_detail_sample"] = detail[:12]
    return out


# ================= B. 评论式把关 =================

def analyze_gatekeep():
    path = os.path.join(TMP, "pr_comments.jsonl")
    if not os.path.exists(path):
        return {"error": "pr_comments.jsonl 不存在"}
    prs = []
    n_repo_err = 0
    n_repos = 0
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("type") == "error":
            n_repo_err += 1
            continue
        if r.get("type") != "repo":
            continue
        n_repos += 1
        for pr in r.get("prs") or []:
            pr["_repo"] = r.get("repo")
            prs.append(pr)

    c = collections.Counter()
    first_comment_lags = []
    pre_merge_comments = 0
    total_comments = 0
    bot_comments = 0
    human_comments = 0
    merged_n = 0
    merged_with_pre_comment = 0
    closed_unmerged_n = 0
    comment_only = 0        # 有合并前评论但无 review
    with_review = 0
    gate = collections.Counter()   # merged PR 把关形态：both/comment_only/review_only/neither
    per_repo = collections.defaultdict(lambda: {"prs": 0, "commented": 0})

    for pr in prs:
        repo = pr.get("_repo")
        per_repo[repo]["prs"] += 1
        c["prs_total"] += 1
        merged = bool(pr.get("merged_at"))
        if merged:
            merged_n += 1
        elif pr.get("state") == "CLOSED" or pr.get("closed_at"):
            closed_unmerged_n += 1
        comments = pr.get("comments") or []
        reviews = pr.get("reviews") or []
        t_created = iso(pr.get("created_at"))
        t_merged = iso(pr.get("merged_at"))
        has_review = any((rv.get("state") or "").upper() in
                         ("APPROVED", "CHANGES_REQUESTED", "COMMENTED", "DISMISSED")
                         for rv in reviews)
        if has_review:
            with_review += 1
        pre = []
        for cm in comments:
            total_comments += 1
            if is_bot(cm.get("author")):
                bot_comments += 1
            else:
                human_comments += 1
            t = iso(cm.get("created_at"))
            if t_merged and t and t <= t_merged:
                pre.append(cm)
                pre_merge_comments += 1
            elif not merged and t:
                pre.append(cm)  # 未合并的评论按并前计（其不存在“并后”）
            if t and t_created:
                first_comment_lags.append((t - t_created).total_seconds() / 86400.0)
        if pre:
            c["prs_with_pre_comment"] += 1
            per_repo[repo]["commented"] += 1
            if merged:
                merged_with_pre_comment += 1
            if not has_review:
                comment_only += 1
        if merged:
            if pre and has_review:
                gate["both"] += 1
            elif pre:
                gate["comment_only"] += 1
            elif has_review:
                gate["review_only"] += 1
            else:
                gate["neither"] += 1
        if comments:
            c["prs_with_any_comment"] += 1
        if reviews:
            c["prs_with_any_review"] += 1
        c["comments_truncated"] += int(bool(pr.get("comments_truncated")))
        c["reviews_truncated"] += int(bool(pr.get("reviews_truncated")))

    def rate(k, n):
        return round(k / n, 4) if n else None

    # 仓层：评论覆盖随规模
    sizes = sorted(per_repo.items(), key=lambda kv: kv[1]["prs"])
    tert = max(1, len(sizes) // 3)
    bands = {"small": sizes[:tert], "mid": sizes[tert:2 * tert], "large": sizes[2 * tert:]}
    scale = {}
    for name, items in bands.items():
        tp = sum(v["prs"] for _, v in items)
        tc = sum(v["commented"] for _, v in items)
        scale[name] = {"n_repos": len(items), "prs": tp, "commented_prs": tc,
                       "comment_rate": rate(tc, tp)}

    out = {
        "n_repos": n_repos, "n_repos_error": n_repo_err,
        "prs_total": c["prs_total"],
        "merged": merged_n,
        "closed_unmerged": closed_unmerged_n,
        "prs_with_any_comment": c["prs_with_any_comment"],
        "prs_with_any_comment_pct": rate(c["prs_with_any_comment"], c["prs_total"]),
        "prs_with_pre_comment": c["prs_with_pre_comment"],
        "prs_with_pre_comment_pct": rate(c["prs_with_pre_comment"], c["prs_total"]),
        "prs_with_any_review": c["prs_with_any_review"],
        "prs_with_any_review_pct": rate(c["prs_with_any_review"], c["prs_total"]),
        "merged_with_pre_comment": merged_with_pre_comment,
        "merged_with_pre_comment_pct": rate(merged_with_pre_comment, merged_n),
        "comment_only_no_review": comment_only,
        "comment_only_no_review_pct": rate(comment_only, c["prs_total"]),
        "merged_gatekeeping_mix": {
            "both_comment_and_review": gate["both"],
            "comment_only": gate["comment_only"],
            "review_only": gate["review_only"],
            "neither": gate["neither"],
            "both_pct": rate(gate["both"], merged_n),
            "comment_only_pct": rate(gate["comment_only"], merged_n),
            "review_only_pct": rate(gate["review_only"], merged_n),
            "neither_pct": rate(gate["neither"], merged_n),
        },
        "total_comments": total_comments,
        "pre_merge_comments": pre_merge_comments,
        "pre_merge_comments_pct": rate(pre_merge_comments, total_comments),
        "bot_comments": bot_comments,
        "bot_comments_pct": rate(bot_comments, total_comments),
        "human_comments": human_comments,
        "first_comment_lag_days_median": round(statistics.median(first_comment_lags), 3)
        if first_comment_lags else None,
        "first_comment_lag_days_p90": round(sorted(first_comment_lags)[int(0.9 * len(first_comment_lags)) - 1], 3)
        if first_comment_lags else None,
        "truncated_flags": {"comments": c["comments_truncated"], "reviews": c["reviews_truncated"]},
        "comment_rate_by_repo_size_tertile": scale,
    }
    return out


def main():
    res = {"generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
           "A_direction_test": analyze_direction(),
           "B_comment_gatekeeping": analyze_gatekeep()}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1)[:4000])
    print(f"\nwritten: {OUT}")


if __name__ == "__main__":
    main()
