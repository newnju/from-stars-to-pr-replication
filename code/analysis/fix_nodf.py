# -*- coding: utf-8 -*-
"""fix_nodf.py — 重算 M5 NODF（nan 安全）"""
import json
import os
import re
import collections
import numpy as np

ROOT = r"E:\Skill扩散论文_可复现项目"
TMP = r"E:\temp\opencode"
OUT = os.path.join(ROOT, "data", "results", "mine_css_methods_20261029.json")

bot_re = re.compile(r"(\[bot\]$|-bot$|^dependabot|^renovate|^github-actions|^codecov|^greenkeeper|^mergify|^imgbot|^allcontributors)", re.I)
rows = collections.defaultdict(set)
cols = collections.defaultdict(set)
for line in open(os.path.join(TMP, "pr_comments.jsonl"), encoding="utf-8", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get("type") != "repo":
        continue
    for pr in d.get("prs") or []:
        for c in pr.get("comments") or []:
            a = c.get("author") or ""
            if not a or bot_re.match(a):
                continue
            rows[d["repo"]].add(a)
            cols[a].add(d["repo"])

keep_r = {r: cs for r, cs in rows.items() if len(cs) >= 2}
keep_c = {c: rs for c, rs in cols.items() if len(rs) >= 2}
repos5 = sorted(keep_r)
comments5 = sorted(keep_c)
ri = {r: i for i, r in enumerate(repos5)}
ci = {c: i for i, c in enumerate(comments5)}
M = np.zeros((len(repos5), len(comments5)), dtype=np.int8)
for r, cs in keep_r.items():
    for c in cs:
        if c in ci:
            M[ri[r], ci[c]] = 1


def nodf_block(mat):
    deg = mat.sum(axis=1).astype(float)
    idx = np.argsort(-deg)
    ds = deg[idx]
    n = len(ds)
    O = (mat @ mat.T)[np.ix_(idx, idx)].astype(float)
    up = np.triu(np.ones((n, n), bool), 1)
    diff = np.abs(ds[:, None] - ds[None, :]) > 1e-9
    mask = up & diff
    if not mask.any():
        return 0.0, 0
    D = np.minimum.outer(ds, ds)
    D = np.where(D == 0, np.nan, D)
    vals = 100.0 * O[mask] / D[mask]
    vals = vals[~np.isnan(vals)]
    if len(vals) == 0:
        return 0.0, 0
    return float(np.nanmean(vals)), int(len(vals))


rn, nr = nodf_block(M)
cn, nc = nodf_block(M.T)
total = (rn * nr + cn * nc) / max(1, nr + nc)

res = json.load(open(OUT, encoding="utf-8"))
res["M5_nodf"] = {
    "n_repos": len(repos5), "n_commenters": len(comments5),
    "fill_pct": round(100 * float(M.mean()), 2),
    "row_nodf": round(rn, 1), "col_nodf": round(cn, 1), "nodf": round(total, 1),
    "row_degree_median": float(np.median(M.sum(axis=1))),
    "col_degree_median": float(np.median(M.sum(axis=0))),
    "note": "NODF 高=嵌套（小参与者是最大参与者子集）；低=模块化/专业化",
}
json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(res["M5_nodf"], ensure_ascii=False, indent=1))
