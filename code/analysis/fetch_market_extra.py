# -*- coding: utf-8 -*-
"""
fetch_market_extra.py — 补查高复制/镜像/registry 仓在两个安装平台上的信号。

341 仓是既有面板，不包含低星 registry/mirror；本脚本只查 8 个已知高复制仓，
用于检验“复制多 ≠ 安装多”。输出 JSONL 到 stdout：
  python analysis\\fetch_market_extra.py > E:\\temp\\opencode\\market_extra.jsonl
"""
import json
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

TARGETS = [
    "NeverSight/skills_feed",
    "majiayu000/claude-skill-registry",
    "aiskillstore/marketplace",
    "Microck/ordinary-claude-skills",
    "davila7/claude-code-templates",
    "sickn33/antigravity-awesome-skills",
    "Brmbobo/Web2podcast",
    "HelixDevelopment/HelixAgent",
]
UA = {"User-Agent": "skill-paper-market-extra/0.1 (research)"}


def log(msg):
    print(f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {msg}",
          file=sys.stderr, flush=True)


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def get_json(url, timeout=45):
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep([5, 15, 30, 60][attempt])
                continue
            return e.code, None
        except Exception:
            time.sleep(3 * (attempt + 1))
    return 0, None


def skills_sh(repo):
    q = urllib.parse.quote(repo)
    st, d = get_json(f"https://www.skills.sh/api/search?q={q}&limit=200")
    if st != 200 or not d:
        return {"type": "skills_sh", "repo": repo, "status": st, "n_hits": 0,
                "total_installs": 0, "possible_truncation": False, "skills": [],
                "note": "supplemental; query failed or no row"}
    hit = [s for s in (d.get("skills") or []) if s.get("source") == repo]
    return {"type": "skills_sh", "repo": repo, "status": st, "n_hits": len(hit),
            "total_installs": sum(int(s.get("installs") or 0) for s in hit),
            "possible_truncation": len(hit) >= 200,
            "skills": sorted(hit, key=lambda s: int(s.get("installs") or 0), reverse=True)}


def clawhub(repo):
    q = urllib.parse.quote(repo)
    st, d = get_json(f"https://clawhub.ai/api/search?q={q}&limit=100")
    if st != 200 or not d:
        return {"type": "clawhub_search", "repo": repo, "status": st, "n_hits": 0,
                "total_downloads": 0, "results": [], "note": "supplemental"}
    res = d.get("results", []) or []
    return {"type": "clawhub_search", "repo": repo, "status": st, "n_hits": len(res),
            "total_downloads": sum(int(r.get("downloads") or 0) for r in res),
            "results": res}


def main():
    for repo in TARGETS:
        emit(skills_sh(repo))
        time.sleep(0.5)
        emit(clawhub(repo))
        time.sleep(0.5)
    emit({"type": "done", "at": datetime.datetime.now().isoformat(timespec="seconds")})


if __name__ == "__main__":
    main()
