# -*- coding: utf-8 -*-
"""
fetch_pr_comments.py — PR 评论全文采集（2026-10-26）
任务来源：进度汇报二.4「PR 评论全文采集：量化合并前的评论式把关，
回应"非正式审查不可观测"的审稿意见」（P4）。

输入：external_data/collected_20261024/pr_merged*.jsonl（164 仓 / 45,203 PR，
      同仓多文件取 pulls 最长者）
输出（JSONL，每仓一行）：E:/temp/opencode/pr_comments.jsonl
  {type:"repo", repo, n_prs, n_fetched, complete, pages,
   prs:[{number, state, merged_at, created_at, author,
         comments:[{author, created_at, body}], comments_truncated,
         reviews:[{author, state, submitted_at, body}], reviews_truncated}]}

通道：GraphQL（与 fork→PR 采集的 REST 配额池隔离，互不抢量）。
每查询 20 个 PR × comments(first:25) + reviews(first:10)；线程超长时打
truncated 标记（截断不影响"是否有评论/评论密度/时序"的把关量化）。
断点续跑：complete=true 的仓跳过；单仓中断则整仓重拉。
限速：rateLimit.remaining < 50 时睡到 resetAt；网络错误重试 4 次。
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
COL = os.path.join(ROOT, "external_data", "collected_20261024")
CACHE = os.path.join(ROOT, "external_data", "_cache")
TMP = r"E:\temp\opencode"
OUT = os.path.join(TMP, "pr_comments.jsonl")
LOG = os.path.join(TMP, "pr_comments.log")

API = "https://api.github.com/graphql"
BATCH = int(os.environ.get("PRC_BATCH", "20"))
SLEEP = float(os.environ.get("PRC_SLEEP", "0.25"))
MAX_PAGES = int(os.environ.get("PRC_MAX_PAGES", "500"))


def log(msg):
    line = f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, file=sys.stderr, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


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
HEAD = {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json",
        "User-Agent": "skill-diffusion-repro"}

QUERY = """
query($owner:String!,$name:String!,$cursor:String,$batch:Int!){
  repository(owner:$owner,name:$name){
    pullRequests(first:$batch, after:$cursor, orderBy:{field:CREATED_AT,direction:ASC}){
      pageInfo{hasNextPage endCursor}
      nodes{
        number
        state
        mergedAt
        createdAt
        closedAt
        author{login}
        comments(first:25){
          pageInfo{hasNextPage}
          nodes{ author{login} createdAt body }
        }
        reviews(first:10){
          pageInfo{hasNextPage}
          nodes{ author{login} state submittedAt body }
        }
      }
    }
  }
  rateLimit{cost remaining resetAt}
}
"""


def gql(owner, name, cursor=None):
    body = json.dumps({"query": QUERY,
                       "variables": {"owner": owner, "name": name,
                                     "cursor": cursor, "batch": BATCH}}).encode()
    last = None
    for attempt in range(5):
        req = urllib.request.Request(API, data=body, headers=HEAD)
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
                return d
        except urllib.error.HTTPError as e:
            txt = e.read().decode("utf-8", "replace")
            if e.code in (403, 429):
                log(f"HTTP {e.code}: {txt[:120]}; sleep 90s")
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


def load_pr_index():
    """repo -> sorted [number, …]（pr_merged 三文件取最长）。"""
    pr_by_repo = {}
    for fn in ("pr_merged.jsonl", "pr_merged_retry.jsonl", "pr_merged_retry3.jsonl"):
        p = os.path.join(COL, fn)
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("type") != "repo":
                    continue
                pulls = d.get("pulls") or []
                key = d.get("repo")
                if key and len(pulls) > len(pr_by_repo.get(key, [])):
                    pr_by_repo[key] = pulls
    out = {}
    for repo, pulls in pr_by_repo.items():
        out[repo] = sorted({p.get("number") for p in pulls if p.get("number") is not None})
    return out


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


def node_comments(n):
    c = n.get("comments") or {}
    return ([{"author": ((x or {}).get("author") or {}).get("login"),
              "created_at": x.get("createdAt"),
              "body": x.get("body")} for x in (c.get("nodes") or [])],
            bool((c.get("pageInfo") or {}).get("hasNextPage")))


def node_reviews(n):
    r = n.get("reviews") or {}
    return ([{"author": ((x or {}).get("author") or {}).get("login"),
              "state": x.get("state"),
              "submitted_at": x.get("submittedAt"),
              "body": x.get("body")} for x in (r.get("nodes") or [])],
            bool((r.get("pageInfo") or {}).get("hasNextPage")))


def fetch_repo(repo, want_numbers):
    owner, name = repo.split("/", 1)
    prs = {}
    cursor = None
    pages = 0
    while pages < MAX_PAGES:
        d = gql(owner, name, cursor)
        if d.get("errors") and not (d.get("data") or {}).get("repository"):
            raise RuntimeError(str(d["errors"])[:300])
        data = d.get("data") or {}
        quota_guard(data.get("rateLimit"))
        repo_d = data.get("repository") or {}
        conn = repo_d.get("pullRequests") or {}
        for n in (conn.get("nodes") or []):
            if n.get("number") is None:
                continue
            comments, c_trunc = node_comments(n)
            reviews, r_trunc = node_reviews(n)
            prs[n["number"]] = {
                "number": n["number"],
                "state": n.get("state"),
                "merged_at": n.get("mergedAt"),
                "created_at": n.get("createdAt"),
                "closed_at": n.get("closedAt"),
                "author": ((n.get("author") or {}) or {}).get("login"),
                "comments": comments,
                "comments_truncated": c_trunc,
                "reviews": reviews,
                "reviews_truncated": r_trunc,
            }
        pages += 1
        pi = conn.get("pageInfo") or {}
        if not pi.get("hasNextPage"):
            break
        cursor = pi.get("endCursor")
        time.sleep(SLEEP)
    missing = [x for x in want_numbers if x not in prs]
    return prs, pages, missing


def main():
    index = load_pr_index()
    done = existing_done()
    todo = sorted((r, ns) for r, ns in index.items() if r not in done)
    total_prs = sum(len(ns) for _, ns in todo)
    log(f"repos={len(index)} done={len(done)} todo={len(todo)} prs={total_prs} "
        f"token={'yes' if TOKEN else 'no'} batch={BATCH}")
    n_err = 0
    with open(OUT, "a", encoding="utf-8") as f:
        for i, (repo, nums) in enumerate(todo, 1):
            try:
                prs, pages, missing = fetch_repo(repo, nums)
                row = {"type": "repo", "repo": repo,
                       "n_prs": len(nums), "n_fetched": len(prs),
                       "missing": missing[:50], "n_missing": len(missing),
                       "complete": True, "pages": pages,
                       "prs": list(prs.values())}
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                log(f"[{i}/{len(todo)}] {repo}: {len(prs)}/{len(nums)} prs, "
                    f"missing={len(missing)}, pages={pages}")
            except Exception as e:
                n_err += 1
                f.write(json.dumps({"type": "error", "repo": repo,
                                    "error": f"{type(e).__name__}: {e}"[:300]}) + "\n")
                f.flush()
                log(f"[{i}/{len(todo)}] {repo} FAIL {type(e).__name__}: {e}")
            time.sleep(SLEEP)
    log(f"完成：错误 {n_err} 仓，输出 {OUT}")


if __name__ == "__main__":
    main()
