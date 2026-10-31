# -*- coding: utf-8 -*-
"""fetch_npm_downloads_pass2.py — npm 匹配第二轮回退（2026-10-24 追加）

第一轮（fetch_npm_downloads.py）按仓短名搜索；本轮对 no_match/error 仓追加：
  1) error 仓：重试短名搜索（首轮 400 为瞬时错误）；
  2) 全部目标仓：`maintainer:<owner>` 限定搜索，捕捉「npm 用户名=GitHub owner、
     包名与仓名无关」的包；仍只接受 links.repository 归一化后指向该仓的命中。

输出直接改写 npm_downloads.jsonl（逐行重写，保留原 queries 记录），meta 行更新。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from fetch_npm_downloads import search_hits, norm_repo_url, point_downloads, OUT_DEFAULT


def try_match(repo, queries):
    owner = repo.split("/", 1)[0]
    hits = search_hits(f"maintainer:{owner}")
    matched = [h for h in hits if h["repo_norm"] == repo.lower()]
    return matched, queries + [f"maintainer:{owner}"]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else OUT_DEFAULT
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    targets = [r for r in rows if r.get("type") == "repo" and r["npm"]["status"] in ("no_match", "error")]
    print(f"targets={len(targets)}", file=sys.stderr)
    for i, r in enumerate(targets):
        repo = r["repo"]
        npm = r["npm"]
        try:
            matched = []
            queries = list(npm.get("queries", []))
            if npm["status"] == "error":
                short = repo.split("/", 1)[1]
                hits = search_hits(short)
                matched = [h for h in hits if h["repo_norm"] == repo.lower()]
            if not matched:
                m2, q2 = try_match(repo, queries)
                matched, queries = m2, q2
            if matched:
                pkgs = []
                for h in matched[:5]:
                    time.sleep(0.3)
                    pkgs.append({"package": h["package"],
                                 "repository": h["repository_raw"],
                                 "downloads_last_month": point_downloads(h["package"], "last-month"),
                                 "downloads_last_year": point_downloads(h["package"], "last-year")})
                r["npm"] = {"status": "matched", "queries": queries, "packages": pkgs,
                            "matched_in": "pass2_maintainer"}
            else:
                r["npm"] = {"status": "no_match", "queries": queries,
                            "pass2_maintainer_checked": True}
        except Exception as e:
            r["npm"] = {"status": "error", "error": str(e)[:200],
                        "queries": npm.get("queries", []) + ["pass2"]}
        if (i + 1) % 40 == 0:
            print(f"[{i+1}/{len(targets)}]", file=sys.stderr)
        time.sleep(0.4)
    repos = [r for r in rows if r.get("type") == "repo"]
    n_match = sum(r["npm"]["status"] == "matched" for r in repos)
    n_no = sum(r["npm"]["status"] == "no_match" for r in repos)
    n_err = sum(r["npm"]["status"] == "error" for r in repos)
    meta = {"type": "meta", "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "n_panel": len(repos), "n_matched": n_match, "n_no_match": n_no, "n_error": n_err,
            "match_rule": "pass1: npm search by repo short name; pass2: maintainer:<owner> qualifier; accepted only if links.repository normalizes to the repo",
            "caveat": "匹配数是下界；no_match 不是零下载；仅覆盖 341 仓面板"}
    out = [r for r in rows if r.get("type") != "meta"] + [meta]
    with open(path, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    main()
