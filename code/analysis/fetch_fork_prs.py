# -*- coding: utf-8 -*-
"""
fetch_fork_prs.py — 补 RQ5/RQ6：fork→PR 回流。

数据：data/forks_timestamps_full.json（228 父仓 + 1.85M fork 子仓）
方法：对每个父仓拉 /pulls?state=all，按 head.repo.full_name 匹配 fork 全名；
      匹配不到时按 author.login 匹配 fork owner，标 matched_by=author。
输出 JSONL 到 stdout：
  {"type":"parent","parent":...,"n_forks":...,"n_prs":...,"n_matched":...,"links":[...]}
  {"type":"done",...}

环境限制：Python 不能直接写文件；用 PowerShell 重定向/追加。
断点续跑：读取 FORK_PR_OUT（默认 E:\\temp\\opencode\\fork_prs.jsonl）中
complete=true 的 parent 行并跳过。
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
SRC = os.path.join(DATA, "forks_timestamps_full.json")
OUT = os.environ.get("FORK_PR_OUT", r"E:\temp\opencode\fork_prs.jsonl")
ONLY = {x.strip() for x in os.environ.get("FORK_ONLY", "").split(",") if x.strip()}
API = "https://api.github.com"
PER_PAGE = int(os.environ.get("FORK_PER_PAGE", "100"))
MAX_PAGES = int(os.environ.get("FORK_MAX_PAGES", "50"))


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
           "Accept": "application/vnd.github+json",
           "X-GitHub-Api-Version": "2022-11-28"}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"


def get_json(url):
    last = None
    for attempt in range(4):
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                body = r.read()
                return json.loads(body), r.headers.get("X-RateLimit-Remaining"), r.headers.get("X-RateLimit-Reset")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if e.code in (403, 429):
                reset = e.headers.get("X-RateLimit-Reset")
                wait = max(5, int(reset) - int(time.time()) + 5) if reset else 60
                log(f"rate limited {e.code}; sleep {wait}s")
                time.sleep(min(wait, 3700))
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
            if o.get("type") == "parent" and o.get("complete"):
                done.add(o.get("parent"))
    return done


def fetch_parent(parent, forks):
    fork_names = set()
    fork_owners = set()
    for f in forks:
        fn = f.get("full_name") or ""
        if "/" in fn:
            fork_names.add(fn)
            fork_owners.add(fn.split("/", 1)[0])

    links = []
    n_prs = 0
    complete = False
    maxed = False
    page = 1
    while page <= MAX_PAGES:
        url = f"{API}/repos/{parent}/pulls?state=all&per_page={PER_PAGE}&page={page}&sort=created&direction=asc"
        data, remaining, reset = get_json(url)
        if not isinstance(data, list):
            raise RuntimeError(f"unexpected: {str(data)[:200]}")
        n_prs += len(data)
        for pr in data:
            head = pr.get("head") or {}
            head_repo = (head.get("repo") or {}).get("full_name")
            user = (pr.get("user") or {}).get("login")
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
                    "created_at": pr.get("created_at"),
                    "closed_at": pr.get("closed_at"),
                    "merged_at": pr.get("merged_at"),
                })
        log(f"{parent} page {page}: {len(data)} prs, matched={len(links)} (remaining={remaining})")
        if len(data) < PER_PAGE:
            complete = True
            break
        page += 1
        if remaining is not None and int(remaining) <= 2:
            wait = max(5, (int(reset) if reset else int(time.time()) + 3600) - int(time.time()) + 5)
            log(f"quota floor; sleep {wait}s")
            time.sleep(min(wait, 3700))
        else:
            time.sleep(0.15)
    if page > MAX_PAGES:
        maxed = True
    return {
        "type": "parent",
        "parent": parent,
        "n_forks": len(forks),
        "n_prs": n_prs,
        "n_matched": len(links),
        "complete": complete,
        "max_pages_reached": maxed,
        "links": links,
    }


def main():
    src = json.load(open(SRC, encoding="utf-8"))
    items = sorted(src.items(), key=lambda kv: len(kv[1]))
    done = existing_done()
    log(f"parents={len(items)} done={len(done)} token={'yes' if TOKEN else 'no'}")
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
          "n_parents": len(items), "done_before": len(done)})


if __name__ == "__main__":
    main()
