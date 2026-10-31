# -*- coding: utf-8 -*-
"""fetch_npm_downloads.py — 补采 npm 下载量（2026-10-24 追加，替代 release_downloads.jsonl 中 npm.status=0 的空缺）

背景：analysis/fetch_release_downloads.py 原方案是读 raw.githubusercontent.com 的
package.json 拿包名，再查 api.npmjs.org；因 raw.githubusercontent.com 断连未获取。
本脚本改为零 GitHub API 方案：
  1) registry.npmjs.org /-/v1/search 按仓短名（必要时 owner/repo 全名）搜索；
  2) 仅当搜索结果的 links.repository 归一化后指向 github.com/<owner>/<repo> 才算匹配；
  3) 匹配包查 api.npmjs.org/downloads/point/last-month 与 last-year。

口径注意：
- status=no_match 表示「npm 搜索未找到 repository 指向该仓的包」，不是下载量为 0；
- status=error 表示请求失败，不得当 0；
- 只覆盖 release_downloads.jsonl 的 341 仓面板，不是全生态；
- 匹配依据是 npm 搜索索引（按短名/全名两轮），非穷举：包名与仓名无关且描述/关键词
  不含短名的包会漏掉，因此匹配数是下界。

用法：python analysis/fetch_npm_downloads.py [输出文件]
默认输出 E:/temp/opencode/npm_downloads.jsonl；已有行自动跳过（断点续跑）。
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

UA = {"User-Agent": "skill-diffusion-research/20261024 (npm downloads supplement)"}
OUT_DEFAULT = r"E:\temp\opencode\npm_downloads.jsonl"
SRC = os.path.join(os.path.dirname(__file__), "..", "external_data", "collected_20261024", "release_downloads.jsonl")


def get_json(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def get_with_retry(url, tries=4):
    last = None
    for i in range(tries):
        try:
            return get_json(url)
        except Exception as e:  # 429/5xx/超时统一退避
            last = e
            time.sleep(2 * (i + 1) ** 2)
    raise last


def norm_repo_url(u):
    """归一化 repository URL，返回 'owner/repo' 或 None。"""
    if not u:
        return None
    u = u.strip().lower()
    u = re.sub(r"^(git\+)?(https?://)?(www\.)?", "", u)
    u = re.sub(r"^git@", "github.com:", u)
    u = u.split("#")[0].split("?")[0]
    u = u[:-4] if u.endswith(".git") else u
    u = u.rstrip("/")
    m = re.match(r"^(?:github\.com[:/])([a-z0-9_.-]+)/([a-z0-9_.-]+)$", u)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def search_hits(text, size=25):
    q = urllib.parse.quote(text)
    st, d = get_with_retry(f"https://registry.npmjs.org/-/v1/search?text={q}&size={size}")
    out = []
    for o in d.get("objects", []):
        p = o["package"]
        out.append({
            "package": p["name"],
            "version": p.get("version"),
            "repository_raw": p.get("links", {}).get("repository"),
            "repo_norm": norm_repo_url(p.get("links", {}).get("repository")),
        })
    return out


def point_downloads(pkg, period):
    st, d = get_with_retry(f"https://api.npmjs.org/downloads/point/{period}/{urllib.parse.quote(pkg)}")
    return d.get("downloads")


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else OUT_DEFAULT
    repos = []
    for line in open(SRC, encoding="utf-8"):
        r = json.loads(line)
        if r.get("type") == "repo":
            repos.append(r["repo"])
    done = set()
    if os.path.exists(out_path):
        for line in open(out_path, encoding="utf-8"):
            try:
                done.add(json.loads(line).get("repo"))
            except Exception:
                pass
    print(f"panel={len(repos)} already={len(done)}", file=sys.stderr)
    with open(out_path, "a", encoding="utf-8") as f:
        for i, repo in enumerate(repos):
            if repo in done:
                continue
            row = {"type": "repo", "repo": repo}
            try:
                owner, short = repo.split("/", 1)
                hits = search_hits(short)
                matched = [h for h in hits if h["repo_norm"] == repo.lower()]
                queries = [short]
                if not matched:
                    hits2 = search_hits(f"{owner}/{repo}")
                    queries.append(f"{owner}/{repo}")
                    matched = [h for h in hits2 if h["repo_norm"] == repo.lower()]
                if not matched:
                    row["npm"] = {"status": "no_match", "queries": queries,
                                  "candidates_checked": len(hits) + len(hits2) if not matched else len(hits)}
                else:
                    pkgs = []
                    for h in matched[:5]:
                        time.sleep(0.3)
                        pkgs.append({"package": h["package"],
                                     "repository": h["repository_raw"],
                                     "downloads_last_month": point_downloads(h["package"], "last-month"),
                                     "downloads_last_year": point_downloads(h["package"], "last-year")})
                    row["npm"] = {"status": "matched", "queries": queries, "packages": pkgs}
            except Exception as e:
                row["npm"] = {"status": "error", "error": str(e)[:200]}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            if (i + 1) % 25 == 0:
                print(f"[{i+1}/{len(repos)}]", file=sys.stderr)
            time.sleep(0.4)
    # meta 行
    n_match = n_no = n_err = 0
    for line in open(out_path, encoding="utf-8"):
        r = json.loads(line)
        if r.get("type") != "repo":
            continue
        s = r["npm"]["status"]
        n_match += s == "matched"
        n_no += s == "no_match"
        n_err += s == "error"
    meta = {"type": "meta", "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "n_panel": len(repos), "n_matched": n_match, "n_no_match": n_no, "n_error": n_err,
            "match_rule": "npm search by repo short name then owner/repo; accepted only if links.repository normalizes to the repo",
            "caveat": "匹配数是下界；no_match 不是零下载；仅覆盖 341 仓面板"}
    with open(out_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    main()
