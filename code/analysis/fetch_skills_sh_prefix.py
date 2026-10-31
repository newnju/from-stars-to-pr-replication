# -*- coding: utf-8 -*-
"""
fetch_skills_sh_prefix.py — 对 skills.sh 200 条封顶仓做前缀枚举。

用于 alirezarezvani/claude-skills、asgeirtj/system_prompts_leaks、
davepoon/buildwithclaude 等 n_hits=200 的仓库。搜索 API 单次最多 200 条，
没有 offset；用 q="owner/repo <prefix>" 递归细分，过滤 source 后合并。

环境限制：Python 不能直接写文件。JSONL 打到 stdout：
  python analysis\\fetch_skills_sh_prefix.py > E:\\temp\\opencode\\skills_sh_prefix.jsonl
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

UA = {"User-Agent": "skill-paper-market-snapshot/0.4 (research)"}
TARGETS = [
    "alirezarezvani/claude-skills",
    "asgeirtj/system_prompts_leaks",
    "davepoon/buildwithclaude",
]
MAX_QUERIES = 90
MAX_DEPTH = 2


def log(msg):
    print(f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {msg}",
          file=sys.stderr, flush=True)


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def search(repo, prefix=""):
    q = repo + ((" " + prefix) if prefix else "")
    url = "https://www.skills.sh/api/search?q=" + urllib.parse.quote(q) + "&limit=200"
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.loads(r.read())
                return [s for s in (d.get("skills") or []) if s.get("source") == repo]
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(3 * (attempt + 1))
                continue
            raise
        except Exception:
            time.sleep(3 * (attempt + 1))
    return []


def main():
    for repo in TARGETS:
        hit = {}
        nq = 0
        stale = 0
        base = search(repo, "")
        nq += 1
        for s in base:
            hit[s.get("id")] = s
        log(f"{repo}: base {len(base)}")
        queue = [(chr(c), 1) for c in range(ord("a"), ord("z") + 1)]
        queue += [(str(i), 1) for i in range(10)]
        while queue and nq < MAX_QUERIES:
            prefix, depth = queue.pop(0)
            sk = search(repo, prefix)
            nq += 1
            before = len(hit)
            for s in sk:
                hit[s.get("id")] = s
            added = len(hit) - before
            if added:
                stale = 0
            else:
                stale += 1
            if added > 0 and len(sk) >= 200 and depth < MAX_DEPTH:
                queue.extend((prefix + chr(c), depth + 1) for c in range(ord("a"), ord("z") + 1))
                queue.extend((prefix + str(i), depth + 1) for i in range(10))
            if stale >= 12:
                log(f"{repo}: stale stop at queries={nq} hits={len(hit)} queue={len(queue)}")
                break
            if nq % 20 == 0:
                log(f"{repo}: queries={nq} hits={len(hit)} queue={len(queue)}")
            time.sleep(0.2)
        complete = not queue or stale >= 12
        emit({"type": "skills_sh_prefix", "repo": repo, "n_hits": len(hit),
              "n_queries": nq, "complete": complete,
              "stopped_stale": stale >= 12,
              "possible_truncation": not complete,
              "total_installs": sum(int(s.get("installs") or 0) for s in hit.values()),
              "skills": sorted(hit.values(), key=lambda s: int(s.get("installs") or 0), reverse=True)})
        log(f"{repo}: done hits={len(hit)} queries={nq} complete={complete}")


if __name__ == "__main__":
    main()
