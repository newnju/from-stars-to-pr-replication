# -*- coding: utf-8 -*-
"""count_pr_coverage.py — PR 列表/审查 覆盖度盘点（2026-10-29）"""
import json
import os

COL = r"E:/Skill扩散论文_可复现项目/external_data/collected_20261024"
TMP = r"E:/temp/opencode"

pr_rows = {}
for fn in ("pr_merged.jsonl", "pr_merged_retry.jsonl", "pr_merged_retry3.jsonl", "pr_merged_fix.jsonl"):
    for path in (os.path.join(COL, fn), os.path.join(TMP, fn)):
        if not os.path.exists(path):
            continue
        for line in open(path, encoding="utf-8", errors="replace"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("type") == "repo":
                pr_rows[d["repo"]] = max(pr_rows.get(d["repo"], False), bool(d.get("complete")))

rev_rows = {}
for fn in ("pr_reviews.jsonl", "pr_reviews_retry.jsonl", "pr_reviews_fix.jsonl"):
    for path in (os.path.join(COL, fn), os.path.join(TMP, fn)):
        if not os.path.exists(path):
            continue
        for line in open(path, encoding="utf-8", errors="replace"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("type") == "repo":
                rev_rows[d["repo"]] = max(rev_rows.get(d["repo"], False), bool(d.get("complete")))

fix_only = {}
p = os.path.join(TMP, "pr_merged_fix.jsonl")
for line in open(p, encoding="utf-8", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get("type") == "repo":
        fix_only[d["repo"]] = max(fix_only.get(d["repo"], False), bool(d.get("complete")))

print("pr_merged_fix complete:", sum(1 for v in fix_only.values() if v), "/", len(fix_only))
print("PR 列表总覆盖（并集）:", sum(1 for v in pr_rows.values() if v), "/", len(pr_rows))
print("reviews 总覆盖（并集）:", sum(1 for v in rev_rows.values() if v), "/", len(rev_rows))
