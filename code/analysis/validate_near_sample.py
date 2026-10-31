# -*- coding: utf-8 -*-
"""
validate_near_sample.py — 对 near_duplicates.jsonl 的候选对做 5-gram Jaccard 抽样复核。

目的：SimHash 在短文档/模板文档上可能产生假阳性。本脚本固定随机种子，
从跨仓与同仓候选对中各抽 200 / 100 对，回到 skills_with_content.jsonl
取正文，去 frontmatter 后算字符 5-gram Jaccard。

输出 JSON 到 stdout：
  cmd /c python analysis\validate_near_sample.py > data\results\near_validation.json
"""
import json
import os
import random
import re
import statistics
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SKILLS = os.path.join(ROOT, "external_data", "skills_with_content.jsonl")
NEAR = r"E:\temp\opencode\near_duplicates.jsonl"
SEED = 20261024


def strip_fm(s):
    if s.startswith("---"):
        parts = s.split("---", 2)
        if len(parts) >= 3:
            return parts[2]
    return s


def grams(s, n=5):
    s = re.sub(r"\s+", " ", strip_fm(s)).strip().lower()
    return {s[i:i + n] for i in range(max(0, len(s) - n + 1))}


def jac(a, b):
    A, B = grams(a), grams(b)
    if not A or not B:
        return None
    return len(A & B) / len(A | B)


def main():
    random.seed(SEED)
    pairs = []
    for line in open(NEAR, encoding="utf-8", errors="replace"):
        try:
            o = json.loads(line)
        except Exception:
            continue
        if o.get("type") == "pair":
            pairs.append(o)
    cross = [p for p in pairs if not p.get("same_repo")]
    same = [p for p in pairs if p.get("same_repo")]
    sample = random.sample(cross, min(200, len(cross))) + random.sample(same, min(100, len(same)))
    keys = set()
    for p in sample:
        for side in ("a", "b"):
            keys.add((p[side].get("repo"), p[side].get("path"), p[side].get("sha")))
    content = {}
    for line in open(SKILLS, encoding="utf-8"):
        try:
            o = json.loads(line)
        except Exception:
            continue
        k = (o.get("repoFullName"), o.get("path"), o.get("sha256_hash"))
        if k in keys and k not in content:
            content[k] = o.get("full_content") or ""

    rows = []
    for p in sample:
        a = content.get((p["a"].get("repo"), p["a"].get("path"), p["a"].get("sha")), "")
        b = content.get((p["b"].get("repo"), p["b"].get("path"), p["b"].get("sha")), "")
        rows.append({"same_repo": bool(p.get("same_repo")),
                     "jaccard": jac(a, b),
                     "len_a": len(a), "len_b": len(b),
                     "hamming": p.get("hamming")})

    vals = [r["jaccard"] for r in rows if r["jaccard"] is not None]
    vals_sorted = sorted(vals)

    def q(p):
        return vals_sorted[min(len(vals_sorted) - 1, int(len(vals_sorted) * p))]

    def subset(flag):
        v = [r["jaccard"] for r in rows if r["same_repo"] == flag and r["jaccard"] is not None]
        return {"n": len(v),
                "median": statistics.median(v) if v else None,
                "share_ge_0.5": (sum(1 for x in v if x >= 0.5) / len(v)) if v else None}

    out = {
        "seed": SEED,
        "n_pairs_total": len(pairs),
        "n_cross_total": len(cross),
        "n_same_total": len(same),
        "n_sampled": len(rows),
        "n_found_content": len(content),
        "jaccard_n": len(vals),
        "jaccard_min": min(vals) if vals else None,
        "jaccard_p10": q(.1), "jaccard_p25": q(.25),
        "jaccard_median": statistics.median(vals) if vals else None,
        "jaccard_p75": q(.75), "jaccard_max": max(vals) if vals else None,
        "shares": {str(t): (sum(1 for x in vals if x >= t) / len(vals) if vals else None)
                   for t in (0.1, 0.3, 0.5, 0.7, 0.9)},
        "cross": subset(False),
        "same": subset(True),
        "short_lt1000_share_ge_0.5": (
            sum(1 for r in rows if r["jaccard"] is not None and min(r["len_a"], r["len_b"]) < 1000 and r["jaccard"] >= 0.5)
            / max(1, sum(1 for r in rows if r["jaccard"] is not None and min(r["len_a"], r["len_b"]) < 1000))),
        "note": "抽样只估精确率；召回率未知。Jaccard 在去 frontmatter 后的字符 5-gram 上计算。"
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
