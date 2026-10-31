# -*- coding: utf-8 -*-
"""
fetch_pr_reviews_graphql.py — 补 PR 审查/合并者：GraphQL 每仓分页。

REST /pulls 只给 merged_at 与 labels；本脚本补：
  - mergedBy.login
  - reviewDecision
  - reviews.totalCount

环境限制：Python 不能直接写文件。JSONL 打到 stdout：
  python analysis\\fetch_pr_reviews_graphql.py >> E:\\temp\\opencode\\pr_reviews.jsonl

断点续跑：读取 PR_REVIEW_OUT（默认 E:\\temp\\opencode\\pr_reviews.jsonl）
中 complete=true 的 repo 行并跳过。
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
OUT = os.environ.get("PR_REVIEW_OUT", r"E:\temp\opencode\pr_reviews.jsonl")
API = "https://api.github.com/graphql"
PER_PAGE = 100
MAX_PAGES = int(os.environ.get("PR_REVIEW_MAX_PAGES", "300"))

QUERY = """
query($owner:String!,$name:String!,$cursor:String){
  repository(owner:$owner,name:$name){
    pullRequests(first:100, after:$cursor, orderBy:{field:CREATED_AT,direction:ASC}){
      pageInfo{hasNextPage endCursor}
      nodes{
        number
        merged
        mergedAt
        mergedBy{login}
        reviewDecision
        reviews(first:1){totalCount}
      }
    }
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
        t = open(p, encoding="utf-8").read().strip()
        if t:
            return t
    return None


TOKEN = load_token()
HEADERS = {"User-Agent": "skill-diffusion-paper-repro",
           "Authorization": f"Bearer {TOKEN}",
           "Content-Type": "application/json"}


def gql(owner, name, cursor=None):
    body = json.dumps({"query": QUERY,
                       "variables": {"owner": owner, "name": name, "cursor": cursor}}).encode()
    last = None
    for attempt in range(6):
        req = urllib.request.Request(API, data=body, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            txt = e.read().decode("utf-8", "replace")
            if e.code in (403, 429):
                time.sleep(60)
                last = f"HTTP {e.code}"
                continue
            if e.code >= 500 and attempt < 5:
                last = f"HTTP {e.code}"
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(f"HTTP {e.code}: {txt[:300]}")
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(4 * (attempt + 1))
    raise RuntimeError(f"gql retries exhausted: {last}")


def existing_done():
    done = set()
    if not os.path.exists(OUT):
        return done
    with open(OUT, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("type") == "repo" and o.get("complete"):
                done.add(o.get("repo"))
    return done


def fetch_repo(repo):
    owner, name = repo.split("/", 1)
    rows = {}
    cursor = None
    complete = False
    pages = 0
    while pages < MAX_PAGES:
        d = gql(owner, name, cursor)
        if "errors" in d:
            raise RuntimeError(str(d["errors"])[:300])
        data = d.get("data") or {}
        prs = data.get("repository") or {}
        prs = prs.get("pullRequests") or {}
        nodes = prs.get("nodes") or []
        for n in nodes:
            num = str(n.get("number"))
            rows[num] = {
                "number": n.get("number"),
                "merged": n.get("merged"),
                "merged_at": n.get("mergedAt"),
                "merged_by": (n.get("mergedBy") or {}).get("login"),
                "review_decision": n.get("reviewDecision"),
                "reviews": (n.get("reviews") or {}).get("totalCount"),
            }
        pages += 1
        pi = prs.get("pageInfo") or {}
        if not pi.get("hasNextPage"):
            complete = True
            break
        cursor = pi.get("endCursor")
        rl = data.get("rateLimit") or {}
        rem = rl.get("remaining")
        if rem is not None and int(rem) < 50:
            reset = rl.get("resetAt")
            wait = 60
            if reset:
                try:
                    dt = datetime.datetime.fromisoformat(reset.replace("Z", "+00:00"))
                    wait = max(5, (dt - datetime.datetime.now(datetime.timezone.utc)).total_seconds() + 5)
                except Exception:
                    pass
            log(f"rate low {rem}; sleep {wait:.0f}s")
            time.sleep(min(wait, 3600))
        else:
            time.sleep(0.15)
    return {"type": "repo", "repo": repo, "n_prs": len(rows),
            "complete": complete, "pages": pages,
            "reviews": rows}


def main():
    src = json.load(open(SRC, encoding="utf-8"))
    repos = []
    for repo, v in src["repos"].items():
        n_pr = sum(1 for it in v.get("issues", []) if it.get("is_pr"))
        if n_pr:
            repos.append(repo)
    repos.sort()
    done = existing_done()
    log(f"repos={len(repos)} done={len(done)} token={'yes' if TOKEN else 'no'}")
    for i, repo in enumerate(repos, 1):
        if repo in done:
            continue
        try:
            d = fetch_repo(repo)
            emit(d)
            log(f"[{i}/{len(repos)}] {repo}: {d['n_prs']} PRs pages={d['pages']} complete={d['complete']}")
        except Exception as e:
            emit({"type": "error", "repo": repo, "error": str(e)[:400]})
            log(f"[{i}/{len(repos)}] {repo} FAIL {e}")
    emit({"type": "done", "at": datetime.datetime.now().isoformat(timespec="seconds"),
          "n_repos": len(repos), "done_before": len(done)})


if __name__ == "__main__":
    main()
