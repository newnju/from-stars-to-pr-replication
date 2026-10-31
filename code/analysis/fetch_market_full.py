# -*- coding: utf-8 -*-
"""
fetch_market_full.py — 补 RQ3：skills.sh / ClawHub 完整列表。

环境限制：Python 不能直接写文件。结果全部以 JSONL 打到 stdout，由 PowerShell 重定向：
  python analysis\\fetch_market_full.py > E:\\temp\\opencode\\market_full.jsonl

输出行类型：
  {"type":"skills_sh","repo":...,"n_hits":...,"skills":[...]}
  {"type":"clawhub_search","repo":...,"n_hits":...,"results":[...]}
  {"type":"clawhub_registry","item":{...}}
  {"type":"manifest",...}

修正：
  - skills.sh 单次 limit=200（旧采集截 20）。
  - 对 200 封顶仓标记 possible_truncation；前缀枚举放到单独脚本，
    避免一次跑太多查询。
  - ClawHub 用 nextCursor 拉全量 registry。
"""
import json
import os
import sys
import time
import datetime
import urllib.request
import urllib.parse
import urllib.error

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
REPOS = os.path.join(DATA, "repos_meta.json")
UA = {"User-Agent": "skill-paper-market-snapshot/0.3 (research; contact via repo issues)"}
DELAY = 0.25


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def get_json(url, timeout=45):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read())


def fetch_skills_sh(repo):
    q = urllib.parse.quote(repo)
    st, d = get_json(f"https://www.skills.sh/api/search?q={q}&limit=200")
    skills = d.get("skills", []) or []
    hit = [s for s in skills if s.get("source") == repo]
    return {
        "type": "skills_sh",
        "repo": repo,
        "status": st,
        "n_hits": len(hit),
        "total_installs": sum(int(s.get("installs") or 0) for s in hit),
        "possible_truncation": len(hit) >= 200,
        "skills": sorted(hit, key=lambda s: int(s.get("installs") or 0), reverse=True),
    }


def fetch_clawhub_search(repo):
    q = urllib.parse.quote(repo)
    st, d = get_json(f"https://clawhub.ai/api/search?q={q}&limit=100")
    results = d.get("results", []) or []
    return {
        "type": "clawhub_search",
        "repo": repo,
        "status": st,
        "n_hits": len(results),
        "total_downloads": sum(int((r.get("downloads") or 0)) for r in results),
        "results": results,
    }


def slim_clawhub(it):
    return {
        "ownerHandle": it.get("ownerHandle"),
        "slug": it.get("slug"),
        "displayName": it.get("displayName"),
        "summary": (it.get("summary") or "")[:800],
        "description": (it.get("description") or "")[:800] if it.get("description") else None,
        "topics": it.get("topics"),
        "tags": list((it.get("tags") or {}).keys())[:30] if isinstance(it.get("tags"), dict) else it.get("tags"),
        "stats": it.get("stats"),
        "createdAt": it.get("createdAt"),
        "updatedAt": it.get("updatedAt"),
        "latestVersion": it.get("latestVersion"),
        "metadata": it.get("metadata"),
    }


def main():
    repos = sorted(json.load(open(REPOS, encoding="utf-8")).keys())
    log(f"repos={len(repos)}")
    n_sh = n_ch = 0
    trunc = 0
    for i, repo in enumerate(repos, 1):
        try:
            r = fetch_skills_sh(repo)
            emit(r)
            n_sh += 1
            if r["possible_truncation"]:
                trunc += 1
        except Exception as e:
            emit({"type": "skills_sh_error", "repo": repo, "error": str(e)[:300]})
            log(f"skills.sh {repo} ERR {e}")
        time.sleep(DELAY)
        try:
            r = fetch_clawhub_search(repo)
            emit(r)
            n_ch += 1
        except Exception as e:
            emit({"type": "clawhub_search_error", "repo": repo, "error": str(e)[:300]})
            log(f"clawhub {repo} ERR {e}")
        time.sleep(DELAY)
        if i % 20 == 0:
            log(f"  search {i}/{len(repos)}")

    log("fetching clawhub registry ...")
    cursor = None
    pages = 0
    n_items = 0
    while True:
        url = "https://clawhub.ai/api/v1/skills?limit=100"
        if cursor:
            url += "&cursor=" + urllib.parse.quote(str(cursor))
        try:
            st, d = get_json(url)
        except Exception as e:
            emit({"type": "clawhub_registry_error", "page": pages + 1, "error": str(e)[:300]})
            log(f"registry page {pages+1} ERR {e}")
            time.sleep(3)
            continue
        items = d.get("items", []) or []
        for it in items:
            emit({"type": "clawhub_registry", "item": slim_clawhub(it)})
            n_items += 1
        pages += 1
        nxt = d.get("nextCursor")
        if not nxt or not items:
            break
        cursor = nxt
        if pages % 20 == 0:
            log(f"  registry page {pages}, items {n_items}")
        time.sleep(DELAY)
        if pages > 5000:
            emit({"type": "clawhub_registry_error", "error": "page cap 5000"})
            break

    emit({"type": "manifest",
          "fetched": datetime.datetime.now().isoformat(timespec="seconds"),
          "repos": len(repos), "skills_sh_rows": n_sh,
          "clawhub_search_rows": n_ch, "skills_sh_possible_truncation": trunc,
          "clawhub_registry_items": n_items, "clawhub_registry_pages": pages})
    log(f"done: sh={n_sh} ch={n_ch} trunc={trunc} reg={n_items}/{pages}")


if __name__ == "__main__":
    main()
