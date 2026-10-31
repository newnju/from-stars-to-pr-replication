# -*- coding: utf-8 -*-
"""
fetch_topic_census.py — 补 RQ7：把 topic:agent-skills 全框补到完整。

环境限制：Python 不能直接写文件。结果 JSONL 打到 stdout：
  python analysis\\fetch_topic_census.py > E:\\temp\\opencode\\topic_census.jsonl

策略：GitHub Search 单查询最多 1,000 条。按 created 日期递归切分；
日期切到单日仍 >1,000 时按 stars 区间切分。已有 24,854 条按 id 去重，
只输出新增仓库。匿名 search 10 次/分钟；有 token 时 30 次/分钟。
"""
import datetime
import json
import os
import sys
import time
import urllib.parse
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
EXIST = os.path.join(DATA, "topic_agent_skills_frame.json")
CACHE = os.path.join(ROOT, "external_data", "_cache")
TOPIC = "agent-skills"
OUT = os.environ.get("TOPIC_OUT", r"E:\temp\opencode\topic_census.jsonl")
API = "https://api.github.com/search/repositories"
PER_PAGE = 100
SEARCH_CAP = 1000
START = datetime.date(2008, 1, 1)
END = datetime.date(2026, 10, 24)
STARS_BANDS = ["0..0", "1..5", "6..20", "21..100", "101..500", "501..2000", ">2000"]
SEEN = set()


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
           "Accept": "application/vnd.github+json"}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"
THROTTLE = 2.1 if TOKEN else 6.2
_last = [0.0]


def search(q, page=1, per_page=PER_PAGE):
    url = API + "?" + urllib.parse.urlencode(
        {"q": q, "page": page, "per_page": per_page, "sort": "created", "order": "asc"})
    for attempt in range(5):
        wait = max(0.0, _last[0] + THROTTLE - time.time())
        if wait:
            time.sleep(wait)
        _last[0] = time.time()
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if e.code in (403, 429):
                wait = 65 if e.code == 429 else 30 * (attempt + 1)
                log(f"search {e.code}; sleep {wait}s; {body[:120]}")
                time.sleep(wait)
                continue
            if e.code == 422:
                return 422, {}
            if e.code >= 500:
                time.sleep(10 * (attempt + 1))
                continue
            return e.code, {}
        except Exception as e:
            log(f"search exception {type(e).__name__}: {e}")
            time.sleep(8 * (attempt + 1))
    return 0, {}


def count(q):
    st, d = search(q, page=1, per_page=1)
    if st != 200:
        return None
    return int(d.get("total_count") or 0)


def emit_repo(it):
    emit({
        "type": "repo",
        "id": it.get("id"),
        "full_name": it.get("full_name"),
        "owner": (it.get("owner") or {}).get("login"),
        "owner_type": (it.get("owner") or {}).get("type"),
        "description": (it.get("description") or "")[:500],
        "topics": it.get("topics") or [],
        "language": it.get("language"),
        "stargazers_count": it.get("stargazers_count"),
        "forks_count": it.get("forks_count"),
        "created_at": it.get("created_at"),
        "updated_at": it.get("updated_at"),
        "pushed_at": it.get("pushed_at"),
        "fork": it.get("fork"),
        "archived": it.get("archived"),
        "open_issues_count": it.get("open_issues_count"),
    })


def collect(q, label, seq):
    st, d = search(q, page=1, per_page=1)
    if st != 200:
        log(f"{label}: count failed {st}")
        return 0
    total = int(d.get("total_count") or 0)
    if total == 0:
        return 0
    if total > SEARCH_CAP:
        return -total  # signal split
    got = 0
    for page in range(1, 11):
        st, d = search(q, page=page, per_page=PER_PAGE)
        if st != 200:
            log(f"{label}: page {page} failed {st}")
            break
        items = d.get("items") or []
        if not items:
            break
        for it in items:
            rid = it.get("id")
            if rid is None or rid in SEEN:
                continue
            SEEN.add(rid)
            emit_repo(it)
            got += 1
        if len(items) < PER_PAGE:
            break
    log(f"{label}: total={total} new={got}")
    return got


def split_date(lo, hi):
    if lo == hi:
        return None
    days = (hi - lo).days
    mid = lo + datetime.timedelta(days=days // 2)
    return (lo, mid), (mid + datetime.timedelta(days=1), hi)


def process_range(lo, hi, depth=0):
    q = f"topic:{TOPIC} created:{lo.isoformat()}..{hi.isoformat()}"
    st, d = search(q, page=1, per_page=1)
    if st != 200:
        log(f"range {lo}..{hi}: count failed {st}")
        return 0
    total = int(d.get("total_count") or 0)
    if total == 0:
        return 0
    if total <= SEARCH_CAP:
        return max(0, collect(q, f"{lo}..{hi}", 0))
    if depth < 12:
        sp = split_date(lo, hi)
        if sp:
            return process_range(*sp[0], depth + 1) + process_range(*sp[1], depth + 1)
    # single day / depth cap: split by stars
    got = 0
    for band in STARS_BANDS:
        qq = q + f" stars:{band}"
        st, d = search(qq, page=1, per_page=1)
        if st != 200:
            continue
        n = int(d.get("total_count") or 0)
        if n == 0:
            continue
        if n > SEARCH_CAP:
            log(f"WARN {lo}..{hi} stars:{band} total={n} > cap; taking first 1000")
        got += max(0, collect(qq, f"{lo}..{hi} stars:{band}", 0))
    return got


def main():
    global SEEN
    d = json.load(open(EXIST, encoding="utf-8"))
    SEEN = set()
    for it in d.get("repos", []):
        if it.get("id") is not None:
            SEEN.add(it["id"])
    if os.path.exists(OUT):
        n_prev = 0
        with open(OUT, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if o.get("type") == "repo" and o.get("id") is not None:
                    SEEN.add(o["id"])
                    n_prev += 1
        log(f"resume from {OUT}: {n_prev} prior repo lines")
    log(f"existing ids={len(SEEN)}; token={'yes' if TOKEN else 'no'} throttle={THROTTLE}")
    n = process_range(START, END)
    emit({"type": "summary", "new_repos": len(SEEN) - len(d.get("repos", [])),
          "total_seen": len(SEEN), "existing": len(d.get("repos", [])),
          "generated": datetime.datetime.now().isoformat(timespec="seconds")})
    log(f"done new={len(SEEN)-len(d.get('repos',[]))} total={len(SEEN)}")


if __name__ == "__main__":
    main()
