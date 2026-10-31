# -*- coding: utf-8 -*-
"""
finalize_fork_prs.py — fork→PR 回流终值回填（2026-10-26，进度汇报二.2）

合并 E:/temp/opencode/fork_prs*.jsonl 全部输出，按 parent 取最佳 complete 行，
重算 P2（采纳—贡献）终值并与 108 仓快照口径对照：
  - 覆盖：complete 父仓数 / 228，缺失原因（404 永久 / 网络 / 触顶未完成）
  - fork 层转化率：唯一回流 fork / 全部 fork（父仓中位数）
  - PR 事件层：回流 PR 事件数、每回流 fork 平均 PR 数
  - 时间结构：回流 ≤24h 占比、中位天数、p90（PR created_at − fork created_at）
  - 机器人占比（回流 PR author）
输出：data/results/fork_prs_final_20261026.json
"""
import json
import os
import sys
import glob
import collections
import datetime
import statistics
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = r"E:\temp\opencode"
SRC = os.path.join(ROOT, "data", "forks_timestamps_full.json")
OUT = os.path.join(ROOT, "data", "results", "fork_prs_final_20261026.json")

BOT_RE = re.compile(r"bot", re.I)  # 快照口径：登录名含 bot（不区分大小写）的宽定义
DELETED = {"awesome-selfhosted/awesome-selfhosted",
           "google-antigravity/antigravity-sdk-python",
           "mksglu/context-mode"}


def is_bot(login):
    return bool(login) and bool(BOT_RE.search(login))


def full_pr_bot_pct():
    """全量 PR（pr_merged 三文件）同口径机器人占比，作对照。"""
    n = 0
    b = 0
    for fn in ("pr_merged.jsonl", "pr_merged_retry.jsonl", "pr_merged_retry3.jsonl"):
        p = os.path.join(ROOT, "external_data", "collected_20261024", fn)
        if not os.path.exists(p):
            continue
        for line in open(p, encoding="utf-8", errors="replace"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            for pr in (d.get("pulls") or []):
                n += 1
                if is_bot(pr.get("user") or ""):
                    b += 1
    return round(100 * b / n, 2) if n else None


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


def load_rows():
    best = {}
    partial = {}
    errs = collections.defaultdict(list)
    files = sorted(glob.glob(os.path.join(TMP, "fork_prs*.jsonl")))
    for fn in files:
        for line in open(fn, encoding="utf-8", errors="replace"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            t = d.get("type")
            if t == "parent":
                p = d.get("parent")
                if d.get("complete"):
                    if p not in best or d.get("n_matched", 0) > best[p].get("n_matched", 0):
                        best[p] = d
                else:
                    if p not in partial or d.get("n_matched", 0) > partial[p].get("n_matched", 0):
                        partial[p] = d
            elif t == "error":
                errs[d.get("parent")].append((os.path.basename(fn), d.get("error", "")[:80]))
    return best, partial, errs, [os.path.basename(f) for f in files]


def main():
    best, partial, errs, files = load_rows()
    src = json.load(open(SRC, encoding="utf-8"))
    all_parents = set(src.keys())

    done = set(best)
    missing = sorted(all_parents - done)
    missing_deleted = [p for p in missing if p in DELETED]
    missing_open = [p for p in missing if p not in DELETED]

    # fork 时间戳索引：parent -> {full_name: created_at}
    tindex = {}
    for p in done:
        tindex[p] = {f.get("full_name"): f.get("created_at") for f in (src.get(p) or [])}

    total_forks = 0
    ret_forks = 0
    pr_events = 0
    per_parent = []
    lags = []
    lag_le24 = 0
    lag_resolved = 0
    bot_pr = 0
    authors_all = 0
    ret_set_global = set()

    for p, row in sorted(best.items()):
        nf = row.get("n_forks") or len(src.get(p) or [])
        total_forks += nf
        links = row.get("links") or []
        pr_events += len(links)
        ret = set()
        for lk in links:
            authors_all += 1
            if is_bot(lk.get("author") or ""):
                bot_pr += 1
            fk = lk.get("fork")
            if fk:
                ret.add(fk)
                ret_set_global.add(fk)
                t_fork = iso((tindex.get(p) or {}).get(fk))
                t_pr = iso(lk.get("created_at"))
                if t_fork and t_pr:
                    lag_resolved += 1
                    dd = (t_pr - t_fork).total_seconds() / 86400.0
                    if dd >= 0:
                        lags.append(dd)
                        if dd <= 1.0:
                            lag_le24 += 1
            elif lk.get("author"):
                ret.add(lk.get("author"))
        n_ret = len(ret)
        ret_forks += n_ret
        per_parent.append({
            "parent": p, "n_forks": nf, "returning_forks": n_ret,
            "pr_events": len(links),
            "conversion": round(n_ret / nf, 5) if nf else None,
        })

    rates = [x["conversion"] for x in per_parent if x["conversion"] is not None]
    lags_sorted = sorted(lags)

    def q(arr, frac):
        return round(arr[int(frac * len(arr)) - 1], 2) if arr else None

    out = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "source_files": files,
        "coverage": {
            "parents_total": len(all_parents),
            "parents_complete": len(done),
            "parents_missing": len(missing),
            "missing_deleted_404": missing_deleted,
            "missing_open": missing_open,
            "missing_open_detail": [{"parent": p,
                                     "partial_max_pages": bool(partial.get(p, {}).get("max_pages_reached")),
                                     "partial_n_matched": partial.get(p, {}).get("n_matched"),
                                     "errors": errs.get(p, [])[:3]} for p in missing_open],
        },
        "p2_final": {
            "parents_n": len(done),
            "fork_total": total_forks,
            "returning_forks": ret_forks,
            "fork_conversion_pct": round(100 * ret_forks / total_forks, 2) if total_forks else None,
            "fork_conversion_wilson95": wilson(ret_forks, total_forks),
            "parent_conversion_median_pct": round(100 * statistics.median(rates), 2) if rates else None,
            "parent_conversion_q25_pct": round(100 * sorted(rates)[len(rates) // 4], 2) if rates else None,
            "parent_conversion_q75_pct": round(100 * sorted(rates)[3 * len(rates) // 4], 2) if rates else None,
            "pr_events": pr_events,
            "pr_per_returning_fork": round(pr_events / ret_forks, 2) if ret_forks else None,
            "timing": {
                "resolved_events": lag_resolved,
                "lag_le_24h_pct": round(100 * lag_le24 / len(lags), 1) if lags else None,
                "lag_median_days": round(statistics.median(lags), 2) if lags else None,
                "lag_p90_days": q(lags_sorted, 0.9),
                "lag_negative_events_ignored": lag_resolved - len(lags),
            },
            "bot_author_pct": round(100 * bot_pr / authors_all, 2) if authors_all else None,
            "bot_author_definition": "登录名含 bot（不区分大小写），与 108 仓快照口径一致",
            "full_pr_bot_pct_same_def": full_pr_bot_pct(),
        },
        "p2_snapshot_108_for_compare": {
            "fork_total": 188588, "returning_forks": 8161, "fork_conversion_pct": 4.30,
            "pr_events": 22325, "pr_per_returning_fork": 2.74,
            "timing_le_24h_pct": 41.2, "lag_median_days": 6.6, "lag_p90_days": 349,
            "bot_author_pct": 0.9, "note": "108 已解析父仓快照（大修稿 5 正文口径）",
        },
        "per_parent": per_parent,
    }
    try:
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print("written:", OUT, file=sys.stderr)
    except PermissionError:
        # Python 写盘被安全软件拦截时：JSON 打到 stdout，由 shell 落盘
        pass
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
