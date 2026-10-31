# -*- coding: utf-8 -*-
"""
fetch_fork_prs_gql.py — fork→PR 回流补扫（GraphQL 版，2026-10-26）
用于 fetch_fork_prs.py 触顶/大响应失败仓的定向补扫：GraphQL 只取匹配所需
字段（number/state/时间/author/headRepository），响应体小、不易 IncompleteRead，
且与 REST 配额池隔离。

输入：data/forks_timestamps_full.json（fork 全名与 owner 集合）
输出（stdout JSONL，与 fetch_fork_prs.py 同构）：
  {"type":"parent","parent":...,"n_forks":...,"n_prs":...,"n_matched":...,
   "complete":bool,"max_pages_reached":bool,"links":[...]}
断点续跑：FORK_PR_OUT（默认 E:/temp/opencode/fork_prs_fix.jsonl）中 complete=true 跳过。
环境：FORK_ONLY（逗号分隔父仓）、FORK_MAX_PAGES（默认 200，每页 100 PR）
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
CACHE = os.path.join(ROOT, "external_data", "_cache")
SRC = os.path.join(ROOT, "data", "forks_timestamps_full.json")
OUT = os.environ.get("FORK_PR_OUT", r"E:\temp\opencode\fork_prs_fix.jsonl")
ONLY = {x.strip() for x in os.environ.get("FORK_ONLY", "").split(",") if x.strip()}
MAX_PAGES = int(os.environ.get("FORK_MAX_PAGES", "200"))
BATCH = 100

API = "https://api.github.com/graphql"
QUERY = """
query($owner:String!,$name:String!,$cursor:String,$batch:Int!){
  repository(owner:$owner,name:$name){
    pullRequests(first:$batch, after:$cursor, orderBy:{field:CREATED_AT,direction:ASC}){
      pageInfo{hasNextPage endCursor}
      nodes{
        number state createdAt closedAt mergedAt
        author{login}
        headRepository{nameWithOwner}
      }
    }
  }
  rateLimit{remaining resetAt cost}
}
"""


def log(msg):
    print(f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {msg}",
          file=sys.stderr, flush=True)


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


TOKEN = ""
try:
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if not tok:
        tok = open(os.path.join(CACHE, "gh_token.txt"), encoding="utf-8").read().strip()
    TOKEN = tok
except Exception:
    pass
HEAD = {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json",
        "User-Agent": "skill-diffusion-repro"}


def gql(owner, name, cursor):
    body = json.dumps({"query": QUERY,
                       "variables": {"owner": owner, "name": name,
                                     "cursor": cursor, "batch": BATCH}}).encode()
    last = None
    for attempt in range(5):
        req = urllib.request.Request(API, data=body, headers=HEAD)
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            txt = e.read().decode("utf-8", "replace")
            if e.code in (403, 429):
                log(f"HTTP {e.code}; sleep 90s")
                time.sleep(90)
                last = f"HTTP {e.code}"
                continue
            if e.code >= 500 and attempt < 4:
                last = f"HTTP {e.code}"
                time.sleep(3 * (attempt + 1))
                continue
            raise RuntimeError(f"HTTP {e.code}: {txt[:200]}")
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            log(f"net {type(e).__name__}; retry {attempt + 1}/5")
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"gql retries exhausted: {last}")


def quota_guard(rl):
    if not rl:
        return
    try:
        rem = int(rl.get("remaining") or 0)
    except Exception:
        return
    if rem <= 50:
        reset = rl.get("resetAt")
        wait = 60
        if reset:
            try:
                t = datetime.datetime.fromisoformat(reset.replace("Z", "+00:00"))
                wait = max(5, int((t - datetime.datetime.now(datetime.timezone.utc)).total_seconds()) + 5)
            except Exception:
                pass
        log(f"graphql quota {rem}<=50; sleep {wait}s")
        time.sleep(min(wait, 3700))


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
            if o.get("type") == "parent" and o.get("complete"):
                done.add(o.get("parent"))
    return done


def fetch_parent(parent, forks):
    fork_names, fork_owners = set(), set()
    for f in forks:
        fn = f.get("full_name") or ""
        if "/" in fn:
            fork_names.add(fn)
            fork_owners.add(fn.split("/", 1)[0])

    owner, name = parent.split("/", 1)
    links = []
    n_prs = 0
    complete = False
    maxed = False
    cursor = None
    pages = 0
    while pages < MAX_PAGES:
        d = gql(owner, name, cursor)
        if d.get("errors") and not (d.get("data") or {}).get("repository"):
            raise RuntimeError(str(d["errors"])[:250])
        data = d.get("data") or {}
        quota_guard(data.get("rateLimit"))
        conn = (data.get("repository") or {}).get("pullRequests") or {}
        nodes = conn.get("nodes") or []
        n_prs += len(nodes)
        for pr in nodes:
            head_repo = ((pr.get("headRepository") or {}) or {}).get("nameWithOwner")
            user = ((pr.get("author") or {}) or {}).get("login")
            matched = None
            if head_repo and head_repo in fork_names:
                matched = "head_repo"
            elif user and user in fork_owners:
                matched = "author"
            if matched:
                links.append({
                    "fork": head_repo,
                    "author": user,
                    "matched_by": matched,
                    "number": pr.get("number"),
                    "state": pr.get("state"),
                    "created_at": pr.get("createdAt"),
                    "closed_at": pr.get("closedAt"),
                    "merged_at": pr.get("mergedAt"),
                })
        pages += 1
        pi = conn.get("pageInfo") or {}
        if not pi.get("hasNextPage"):
            complete = True
            break
        cursor = pi.get("endCursor")
        if pages % 10 == 0:
            log(f"{parent} page {pages}: prs={n_prs} matched={len(links)}")
        time.sleep(0.15)
    if pages >= MAX_PAGES and not complete:
        maxed = True
    return {
        "type": "parent", "parent": parent,
        "n_forks": len(forks), "n_prs": n_prs, "n_matched": len(links),
        "complete": complete, "max_pages_reached": maxed, "links": links,
    }


def main():
    src = json.load(open(SRC, encoding="utf-8"))
    items = sorted(src.items(), key=lambda kv: len(kv[1]))
    done = existing_done()
    log(f"parents={len(items)} done={len(done)} only={len(ONLY) or 'ALL'} token={'yes' if TOKEN else 'no'}")
    for i, (parent, forks) in enumerate(items, 1):
        if ONLY and parent not in ONLY:
            continue
        if parent in done:
            continue
        try:
            d = fetch_parent(parent, forks)
            emit(d)
            log(f"[{i}/{len(items)}] {parent}: {d['n_matched']}/{d['n_prs']} complete={d['complete']}")
        except Exception as e:
            emit({"type": "error", "parent": parent, "error": str(e)[:400]})
            log(f"[{i}/{len(items)}] {parent} FAIL {e}")
    emit({"type": "done", "at": datetime.datetime.now().isoformat(timespec="seconds"),
          "n_parents": len(items), "done_before": len(done), "mode": "graphql"})


if __name__ == "__main__":
    main()
