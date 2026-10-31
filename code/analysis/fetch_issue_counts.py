# -*- coding: utf-8 -*-
"""
fetch_issue_counts.py — 用 GraphQL 给 203 面板仓补 issue / PR 精确计数。

背景：旧 gh_discourse.json 的 issue/PR 列表只取到每个仓的第一页（100 条），
大仓被严重截断（如 Gentleman 旧 29 PR、实际 2,325）。本脚本不重采正文，
只补两个 totalCount，用来量化旧面板的截断方向与倍数。

GraphQL:
  issues(states:[OPEN,CLOSED]){totalCount}    # 含 PR
  pullRequests(states:[OPEN,CLOSED,MERGED]){totalCount}
  pure_issues = issues_total - pr_total

输出 JSONL 到 stdout：
  python analysis\\fetch_issue_counts.py > E:\\temp\\opencode\\issue_counts.jsonl
"""
import json
import os
import sys
import time
import datetime
import urllib.request
import urllib.error

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
CACHE = os.path.join(ROOT, "external_data", "_cache")
SRC = os.path.join(DATA, "gh_discourse.json")
API = "https://api.github.com/graphql"

QUERY = """
query($owner:String!,$name:String!){
  repository(owner:$owner,name:$name){
    issues(states:[OPEN,CLOSED]){totalCount}
    pullRequests(states:[OPEN,CLOSED,MERGED]){totalCount}
  }
  rateLimit{limit remaining resetAt cost}
}
"""


def log(msg):
    print(f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {msg}",
          file=sys.stderr, flush=True)


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def load_token():
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if tok:
        return tok
    p = os.path.join(CACHE, "gh_token.txt")
    if os.path.exists(p):
        return open(p, encoding="utf-8").read().strip()
    return None


TOKEN = load_token()
HEADERS = {"User-Agent": "skill-diffusion-paper-repro",
           "Authorization": f"Bearer {TOKEN}",
           "Content-Type": "application/json"}


def gql(owner, name):
    body = json.dumps({"query": QUERY,
                       "variables": {"owner": owner, "name": name}}).encode()
    req = urllib.request.Request(API, data=body, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "replace")
        if e.code in (403, 429):
            time.sleep(60)
        raise RuntimeError(f"HTTP {e.code}: {txt[:200]}")


def main():
    src = json.load(open(SRC, encoding="utf-8"))["repos"]
    repos = sorted(src)
    log(f"repos={len(repos)} token={'yes' if TOKEN else 'no'}")
    for i, repo in enumerate(repos, 1):
        owner, name = repo.split("/", 1)
        try:
            d = gql(owner, name)
            if "errors" in d:
                raise RuntimeError(str(d["errors"])[:200])
            r = (d.get("data") or {}).get("repository") or {}
            pr = ((r.get("pullRequests") or {}).get("totalCount"))
            ip = ((r.get("issues") or {}).get("totalCount"))
            old = src.get(repo, {}).get("issues", [])
            old_pr = sum(1 for it in old if it.get("is_pr"))
            old_issue = sum(1 for it in old if not it.get("is_pr"))
            # GitHub GraphQL 的 issues 连接不含 PR；ip 就是纯 issue 数。
            emit({"type": "repo", "repo": repo,
                  "issues_graphql": ip, "prs_graphql": pr,
                  "issues_plus_prs_graphql": (ip + pr) if (ip is not None and pr is not None) else None,
                  "pure_issues_graphql": ip,
                  "old_prs": old_pr, "old_issues": old_issue,
                  "pr_ratio": (pr / old_pr) if (pr and old_pr) else None,
                  "issue_ratio": (ip / old_issue) if (ip is not None and old_issue) else None})
            rl = d.get("data", {}).get("rateLimit") or {}
            if i % 20 == 0:
                log(f"{i}/{len(repos)} {repo} pr={pr} issues={ip} rem={rl.get('remaining')}")
            time.sleep(0.15)
        except Exception as e:
            emit({"type": "error", "repo": repo, "error": str(e)[:300]})
            log(f"{i}/{len(repos)} {repo} FAIL {e}")
            time.sleep(1)
    emit({"type": "done", "at": datetime.datetime.now().isoformat(timespec="seconds"),
          "n_repos": len(repos)})


if __name__ == "__main__":
    main()
