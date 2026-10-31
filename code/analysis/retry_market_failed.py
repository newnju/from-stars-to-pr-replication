# -*- coding: utf-8 -*-
"""
retry_market_failed.py — 重试 market_full 中 429/503 失败的仓库。

读取 E:\\temp\\opencode\\market_full.jsonl（以及可选的 market_retry.jsonl），
找出没有成功 skills_sh / clawhub_search 行的 341 仓，逐个重试；成功后输出同格式
JSONL 到 stdout，追加到 E:\\temp\\opencode\\market_retry.jsonl。

  python analysis\\retry_market_failed.py >> E:\\temp\\opencode\\market_retry.jsonl

重试策略：429/503 退避 10/30/60/120 秒；最多 4 次。
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
REPOS = os.path.join(ROOT, "data", "repos_meta.json")
SRC = os.environ.get("MARKET_SRC", r"E:\temp\opencode\market_full.jsonl")
RETRY = os.environ.get("MARKET_RETRY", r"E:\temp\opencode\market_retry.jsonl")
UA = {"User-Agent": "skill-paper-market-snapshot/0.5 (research)"}


def log(msg):
    print(f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {msg}",
          file=sys.stderr, flush=True)


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def get_json(url, timeout=45):
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            last = e.code
            if e.code in (429, 500, 502, 503, 504):
                wait = [10, 30, 60, 120][attempt]
                log(f"HTTP {e.code}; sleep {wait}s")
                time.sleep(wait)
                continue
            return e.code, None
        except Exception as e:
            last = str(e)
            time.sleep(5 * (attempt + 1))
    return 0, None


def fetch_skills_sh(repo):
    q = urllib.parse.quote(repo)
    st, d = get_json(f"https://www.skills.sh/api/search?q={q}&limit=200")
    if st != 200 or not d:
        return None
    hit = [s for s in (d.get("skills") or []) if s.get("source") == repo]
    return {"type": "skills_sh", "repo": repo, "status": st, "n_hits": len(hit),
            "total_installs": sum(int(s.get("installs") or 0) for s in hit),
            "possible_truncation": len(hit) >= 200,
            "skills": sorted(hit, key=lambda s: int(s.get("installs") or 0), reverse=True)}


def fetch_clawhub(repo):
    q = urllib.parse.quote(repo)
    st, d = get_json(f"https://clawhub.ai/api/search?q={q}&limit=100")
    if st != 200 or not d:
        return None
    results = d.get("results", []) or []
    return {"type": "clawhub_search", "repo": repo, "status": st, "n_hits": len(results),
            "total_downloads": sum(int(r.get("downloads") or 0) for r in results),
            "results": results}


def main():
    repos = sorted(json.load(open(REPOS, encoding="utf-8")).keys())
    sh_ok, ch_ok = set(), set()
    for p in (SRC, RETRY):
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if o.get("type") == "skills_sh" and o.get("status") == 200:
                    sh_ok.add(o.get("repo"))
                elif o.get("type") == "clawhub_search" and o.get("status") == 200:
                    ch_ok.add(o.get("repo"))
    sh_fail = [r for r in repos if r not in sh_ok]
    ch_fail = [r for r in repos if r not in ch_ok]
    log(f"skills_sh ok={len(sh_ok)} fail={len(sh_fail)}; clawhub ok={len(ch_ok)} fail={len(ch_fail)}")

    for i, repo in enumerate(sh_fail, 1):
        r = fetch_skills_sh(repo)
        if r:
            emit(r)
            log(f"skills.sh [{i}/{len(sh_fail)}] {repo}: {r['n_hits']}")
        else:
            log(f"skills.sh [{i}/{len(sh_fail)}] {repo}: FAIL")
        time.sleep(0.4)

    for i, repo in enumerate(ch_fail, 1):
        r = fetch_clawhub(repo)
        if r:
            emit(r)
            log(f"clawhub [{i}/{len(ch_fail)}] {repo}: {r['n_hits']}")
        else:
            log(f"clawhub [{i}/{len(ch_fail)}] {repo}: FAIL")
        time.sleep(0.4)

    emit({"type": "done", "at": datetime.datetime.now().isoformat(timespec="seconds"),
          "sh_fail": len(sh_fail), "ch_fail": len(ch_fail)})


if __name__ == "__main__":
    main()
