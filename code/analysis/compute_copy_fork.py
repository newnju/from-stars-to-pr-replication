# -*- coding: utf-8 -*-
"""用普查层（24,854 仓，自带 forks/stars）检验"复制→fork"这一中间环节"""
import json, os, math
from collections import defaultdict
import numpy as np
from scipy import stats

ROOT = r"E:\Skill扩散论文_可复现项目"
COL = os.path.join(ROOT, "external_data", "collected_20261024")

frame = json.load(open(os.path.join(ROOT, "data", "topic_agent_skills_frame.json"), encoding="utf-8"))["repos"]
meta = {r["full_name"]: r for r in frame}
print("census repos:", len(meta))

# 跨仓复制：出度（本仓的文档被别人复制）、入度（本仓复制了别人的）
out_sha = defaultdict(set)
in_sha = defaultdict(set)
for line in open(os.path.join(COL, "near_duplicates.jsonl"), encoding="utf-8", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get("type") != "pair":
        continue
    a, b = d.get("a") or {}, d.get("b") or {}
    ra, rb = a.get("repo"), b.get("repo")
    if not ra or not rb or ra == rb:
        continue
    out_sha[ra].add(a.get("sha"))
    in_sha[rb].add(a.get("sha"))

rows = []
for r, m in meta.items():
    co = len(out_sha.get(r, ()))
    ci = len(in_sha.get(r, ()))
    if co + ci == 0:
        continue
    rows.append({"repo": r, "copy_out": co, "copy_in": ci,
                 "forks": m.get("forks_count") or 0,
                 "stars": m.get("stargazers_count") or 0})
print("有跨仓复制边的普查仓:", len(rows))
print("  出度>0:", sum(1 for x in rows if x["copy_out"] > 0),
      "| 入度>0:", sum(1 for x in rows if x["copy_in"] > 0))


def tost(x, y, bound):
    x = np.array(x, float); y = np.array(y, float)
    if len(x) < 10:
        return None
    rho, p = stats.spearmanr(x, y)
    z = np.arctanh(np.clip(rho, -0.999, 0.999))
    se = 1 / math.sqrt(len(x) - 3)
    t = (np.arctanh(bound) - abs(z)) / se
    return dict(n=len(x), rho=round(float(rho), 4), p=float(f"{p:.3g}"),
                p_tost=float(f"{1-stats.norm.cdf(t):.3g}"))


print("\n=== 复制 → fork ===")
for lab, key, sub in [
    ("出度>0 且 fork>0", "copy_out", [x for x in rows if x["copy_out"] > 0 and x["forks"] > 0]),
    ("入度>0 且 fork>0", "copy_in", [x for x in rows if x["copy_in"] > 0 and x["forks"] > 0]),
    ("任一边>0 且 fork>0", "copy_out", [x for x in rows if x["forks"] > 0]),
]:
    for b in (0.5, 0.35):
        r = tost([x[key] for x in sub], [x["forks"] for x in sub], b)
        print(f"  {lab} |rho|>={b}: {r}")

print("\n=== 对照：复制 → 星标 ===")
sub = [x for x in rows if x["copy_out"] > 0 and x["stars"] > 0]
for b in (0.5, 0.35):
    print(f"  出度>0 |rho|>={b}: {tost([x['copy_out'] for x in sub], [x['stars'] for x in sub], b)}")

print("\n=== 对照：fork → 星标（应高）===")
sub = [x for x in rows if x["forks"] > 0 and x["stars"] > 0]
print("  ", tost([x["forks"] for x in sub], [x["stars"] for x in sub], 0.5))
