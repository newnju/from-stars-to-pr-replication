# -*- coding: utf-8 -*-
"""
summarize_exact_near.py — 精确同 SHA 复制与近重复簇的并集/重叠。

口径：
  - exact 行：sha256_hash 在 >=2 个不同 repo 出现的 skills_with_content 行。
  - exact 键：去重到 (repoFullName, sha256_hash)，避免同仓同 SHA 重复行。
  - near 对：near_duplicates.jsonl 中 type=pair；near 键为 (repo, sha)。
  - near_cross：至少一端出现在跨仓 near 对中的键。
  - union：exact 键 ∪ near_cross 键；overlap：两者都出现的键。
输出到 stdout：
  cmd /c python analysis\summarize_exact_near.py > data\results\exact_near_union.json
"""
import collections
import json
import os
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


def main():
    sha_repos = collections.defaultdict(set)
    keys = set()
    n_docs = 0
    for line in open(SKILLS, encoding="utf-8"):
        n_docs += 1
        try:
            o = json.loads(line)
        except Exception:
            continue
        repo = o.get("repoFullName")
        sha = o.get("sha256_hash")
        if repo and sha:
            sha_repos[sha].add(repo)
            keys.add((repo, sha))
    exact = {k for k in keys if len(sha_repos.get(k[1], ())) > 1}

    near_all = set()
    near_cross = set()
    pairs = pairs_cross = 0
    near_meta = None
    clusters = []
    for line in open(NEAR, encoding="utf-8"):
        try:
            o = json.loads(line)
        except Exception:
            continue
        if o.get("type") == "meta":
            near_meta = o
        elif o.get("type") == "pair":
            pairs += 1
            ka = (o["a"].get("repo"), o["a"].get("sha"))
            kb = (o["b"].get("repo"), o["b"].get("sha"))
            near_all.add(ka)
            near_all.add(kb)
            if ka[0] != kb[0]:
                pairs_cross += 1
                near_cross.add(ka)
                near_cross.add(kb)
        elif o.get("type") == "cluster":
            repos = {m.get("repo") for m in o.get("members") or []}
            clusters.append({"size": o.get("size"), "n_repos_in_members": len(repos),
                             "sample_repos": sorted(repos)[:8]})

    union = exact | near_cross
    out = {
        "n_docs_rows": n_docs,
        "exact_docs_rows": None,  # 从 local_mining.jsonl 的 summary 读；行级口径见 note
        "exact_keys": len(exact),
        "exact_key_share": len(exact) / n_docs if n_docs else None,
        "near_pairs": pairs,
        "near_pairs_cross": pairs_cross,
        "near_keys_all": len(near_all),
        "near_keys_cross": len(near_cross),
        "near_cross_key_share": len(near_cross) / n_docs if n_docs else None,
        "union_keys": len(union),
        "union_key_share": len(union) / n_docs if n_docs else None,
        "overlap_exact_near_cross": len(exact & near_cross),
        "near_meta": near_meta,
        "top_clusters": sorted(clusters, key=lambda c: -(c.get("size") or 0))[:10],
        "note": "exact_keys 与 near_keys 都去重到 repo×SHA；行级 exact 47,973 / near docs 21,755 不能直接相加。"
    }
    # exact 行数：本地挖掘汇总里已有 shared_docs_exact；避免再扫一遍 155k 正文。
    try:
        lm = os.path.join(r"E:\temp\opencode", "local_mining.jsonl")
        for line in open(lm, encoding="utf-8"):
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("type") == "summary":
                out["exact_docs_rows"] = o.get("shared_docs_exact")
                out["exact_docs_row_share"] = o.get("shared_docs_exact", 0) / n_docs if n_docs else None
                break
    except Exception:
        pass
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
