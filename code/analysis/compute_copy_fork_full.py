# -*- coding: utf-8 -*-
"""用补拉后的全量复制边样本，检验"复制→fork"这一中间环节"""
import json, os, math
from collections import defaultdict
import numpy as np
from scipy import stats

ROOT = r"E:\Skill扩散论文_可复现项目"
COL = os.path.join(ROOT, "external_data", "collected_20261024")
EXTRA = r"C:\Users\diamond\AppData\Local\Temp\copy_edge_meta.jsonl"

# 元数据：普查层 + 补拉
meta = {}
for r in json.load(open(os.path.join(ROOT, "data", "topic_agent_skills_frame.json"),
                        encoding="utf-8"))["repos"]:
    meta[r["full_name"]] = {"forks": r.get("forks_count") or 0,
                            "stars": r.get("stargazers_count") or 0}
for line in open(EXTRA, encoding="utf-8", errors="replace"):
    d = json.loads(line)
    if d.get("missing"):
        continue
    meta[d["full_name"]] = {"forks": d.get("forks") or 0, "stars": d.get("stars") or 0}
print("元数据仓:", len(meta))

# 跨仓复制出度/入度
out_sha, in_sha = defaultdict(set), defaultdict(set)
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
for r in set(out_sha) | set(in_sha):
    if r not in meta:
        continue
    rows.append({"repo": r, "copy_out": len(out_sha.get(r, ())), "copy_in": len(in_sha.get(r, ())),
                 "forks": meta[r]["forks"], "stars": meta[r]["stars"]})
print("有元数据的复制边仓:", len(rows),
      "| 出度>0:", sum(1 for x in rows if x["copy_out"] > 0),
      "| fork>0:", sum(1 for x in rows if x["forks"] > 0))


def tost(x, y, bound):
    x, y = np.array(x, float), np.array(y, float)
    if len(x) < 10:
        return None
    rho, p = stats.spearmanr(x, y)
    z = np.arctanh(np.clip(rho, -0.999, 0.999))
    se = 1 / math.sqrt(len(x) - 3)
    t = (np.arctanh(bound) - abs(z)) / se
    return dict(n=len(x), rho=round(float(rho), 4), p=float(f"{p:.3g}"),
                p_tost=float(f"{1-stats.norm.cdf(t):.3g}"))


print("\n=== 复制 → fork（主检验）===")
for lab, sub in [
    ("出度>0 且 fork>0", [x for x in rows if x["copy_out"] > 0 and x["forks"] > 0]),
    ("入度>0 且 fork>0", [x for x in rows if x["copy_in"] > 0 and x["forks"] > 0]),
]:
    for b in (0.5, 0.35, 0.6):
        print(f"  {lab} |rho|>={b}: {tost([x['copy_out'] if '出度' in lab else x['copy_in'] for x in sub], [x['forks'] for x in sub], b)}")

print("\n=== 对照：复制出度 → 星标 ===")
sub = [x for x in rows if x["copy_out"] > 0 and x["stars"] > 0]
for b in (0.5, 0.35):
    print(f"  |rho|>={b}: {tost([x['copy_out'] for x in sub], [x['stars'] for x in sub], b)}")

print("\n=== 对照：fork → 星标（应接近 1）===")
sub = [x for x in rows if x["forks"] > 0 and x["stars"] > 0]
print("  ", tost([x["forks"] for x in sub], [x["stars"] for x in sub], 0.5))
