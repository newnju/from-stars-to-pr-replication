# -*- coding: utf-8 -*-
"""
fetch_pr_merged.py — 补 RQ4：从 GitHub REST 拉 203 仓全部 PR 的 merged_at。

重要环境限制：本机 Python 进程不能直接写文件。所有结果以 JSONL 打到 stdout，
由 PowerShell 重定向落盘：
  python analysis\\fetch_pr_merged.py > E:\\temp\\opencode\\pr_merged.jsonl

每行一个 JSON：
  {"type":"repo", "repo":..., "pulls":[...], ...}
  {"type":"done", ...}

断点续跑：启动时读取 PR_MERGED_OUT（默认 E:\\temp\\opencode\\pr_merged.jsonl），
已有完整 repo 行则跳过。无 token 时匿名 60 请求/小时，按 X-RateLimit-Reset 等待。
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
OUT = os.environ.get("PR_MERGED_OUT", r"E:\temp\opencode\pr_merged.jsonl")
API = "https://api.github.com"
PER_PAGE = int(os.environ.get("PR_PER_PAGE", "100"))
MAX_PAGES = int(os.environ.get("PR_MAX_PAGES", "60"))
ONLY = {x.strip() for x in os.environ.get("PR_ONLY", "").split(",") if x.strip()}
MIN_REMAIN = 2


def log(msg):
    line = f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, file=sys.stderr, flush=True)


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def load_token():
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if tok:
        return tok, "env"
    p = os.path.join(CACHE, "gh_token.txt")
    if os.path.exists(p):
        tok = open(p, encoding="utf-8").read().strip()
        if tok:
            return tok, "file"
    return None, "anon"


TOKEN, TOKEN_SRC = load_token()
HEADERS = {
    "User-Agent": "skill-diffusion-paper-repro",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"


def get_json(url):
    last = None
    for attempt in range(4):
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read()
            remaining = r.headers.get("X-RateLimit-Remaining")
            reset = r.headers.get("X-RateLimit-Reset")
            return json.loads(body), int(remaining) if remaining else None, int(reset) if reset else None
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if e.code in (403, 429):
                reset = e.headers.get("X-RateLimit-Reset")
                if reset:
                    wait = max(5, int(reset) - int(time.time()) + 5)
                    log(f"rate limited HTTP {e.code}; sleep {wait}s")
                    time.sleep(min(wait, 3700))
                else:
                    time.sleep(60)
                raise RuntimeError(f"HTTP {e.code}: {body[:300]}")
            if e.code >= 500 and attempt < 3:
                last = f"HTTP {e.code}"
                log(f"HTTP {e.code}; retry {attempt + 1}/4")
                time.sleep(3 * (attempt + 1))
                continue
            raise RuntimeError(f"HTTP {e.code}: {body[:300]}")
        except Exception as e:  # IncompleteRead / ConnectionReset / timeout 等网络截断
            last = f"{type(e).__name__}: {e}"
            log(f"net {type(e).__name__}; retry {attempt + 1}/4")
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"network retries exhausted: {last}")


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


def fetch_repo(repo, expected_n=None):
    pulls = []
    complete = False
    maxed = False
    page = 1
    while page <= MAX_PAGES:
        url = f"{API}/repos/{repo}/pulls?state=all&per_page={PER_PAGE}&page={page}&sort=created&direction=asc"
        data, remaining, reset = get_json(url)
        if not isinstance(data, list):
            raise RuntimeError(f"unexpected response: {str(data)[:200]}")
        for pr in data:
            head = pr.get("head") or {}
            head_repo = head.get("repo") or {}
            base = pr.get("base") or {}
            base_repo = base.get("repo") or {}
            user = pr.get("user") or {}
            pulls.append({
                "number": pr.get("number"),
                "state": pr.get("state"),
                "draft": pr.get("draft"),
                "title": (pr.get("title") or "")[:300],
                "user": user.get("login"),
                "user_type": user.get("type"),
                "created_at": pr.get("created_at"),
                "updated_at": pr.get("updated_at"),
                "closed_at": pr.get("closed_at"),
                "merged_at": pr.get("merged_at"),
                "merge_commit_sha": pr.get("merge_commit_sha"),
                "head_repo": head_repo.get("full_name"),
                "head_ref": head.get("ref"),
                "head_sha": head.get("sha"),
                "base_repo": base_repo.get("full_name"),
                "base_ref": base.get("ref"),
                "labels": [x.get("name") for x in (pr.get("labels") or [])],
            })
        log(f"{repo} page {page}: {len(data)} pulls (remaining={remaining})")
        if len(data) < PER_PAGE:
            complete = True
            break
        page += 1
        if remaining is not None and remaining <= MIN_REMAIN:
            wait = max(5, (reset or int(time.time()) + 3600) - int(time.time()) + 5)
            log(f"quota floor; sleep {wait}s")
            time.sleep(min(wait, 3700))
        else:
            time.sleep(1.0)
    if page > MAX_PAGES:
        maxed = True
    return {
        "type": "repo",
        "repo": repo,
        "fetched_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "expected_n": expected_n,
        "n_pulls": len(pulls),
        "complete": complete,
        "max_pages_reached": maxed,
        "pulls": pulls,
    }


def main():
    src = json.load(open(SRC, encoding="utf-8"))
    repos = src["repos"]
    items = []
    for repo, v in repos.items():
        n_pr = sum(1 for it in v.get("issues", []) if it.get("is_pr"))
        if n_pr:
            items.append((repo, n_pr))
    items.sort(key=lambda x: x[1])
    done = existing_done()
    log(f"start: {len(items)} repos with PRs; done={len(done)}; token={TOKEN_SRC}; out={OUT}")

    for i, (repo, n_pr) in enumerate(items, 1):
        if ONLY and repo not in ONLY:
            continue
        if repo in done:
            continue
        try:
            d = fetch_repo(repo, n_pr)
            emit(d)
            log(f"[{i}/{len(items)}] {repo}: {d['n_pulls']}/{n_pr} complete={d['complete']}")
        except Exception as e:
            emit({"type": "error", "repo": repo, "error": str(e)[:500],
                  "at": datetime.datetime.now().isoformat(timespec="seconds")})
            log(f"[{i}/{len(items)}] {repo} FAIL: {e}")
    emit({"type": "done", "at": datetime.datetime.now().isoformat(timespec="seconds"),
          "n_repos": len(items), "done_before": len(done)})


if __name__ == "__main__":
    main()
