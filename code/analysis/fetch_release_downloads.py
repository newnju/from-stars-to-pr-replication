# -*- coding: utf-8 -*-
"""
fetch_release_downloads.py — 补 RQ3 的第三方下载信号。

对 data/repos_meta.json 的 341 个候选仓库：
  - GitHub releases：拉 /releases?per_page=100，汇总 assets.download_count；
  - npm：读 raw package.json 的 name，查 api.npmjs.org 最近一月下载量。
输出 JSONL 到 stdout：
  python analysis\\fetch_release_downloads.py > E:\\temp\\opencode\\release_downloads.jsonl
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
CACHE = os.path.join(ROOT, "external_data", "_cache")
REPOS = os.path.join(DATA, "repos_meta.json")
API = "https://api.github.com"


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
GH = {"User-Agent": "skill-diffusion-paper-repro",
      "Accept": "application/vnd.github+json"}
if TOKEN:
    GH["Authorization"] = f"Bearer {TOKEN}"
UA = {"User-Agent": "skill-diffusion-paper-repro"}


def get(url, headers, timeout=60):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return 0, None


def gh_releases(repo):
    st, d = get(f"{API}/repos/{repo}/releases?per_page=100", GH)
    if st != 200 or not isinstance(d, list):
        return {"status": st, "n_releases": 0, "downloads": 0}
    downloads = 0
    n_assets = 0
    latest = None
    for rel in d:
        if latest is None:
            latest = rel.get("published_at") or rel.get("created_at")
        for a in rel.get("assets") or []:
            downloads += int(a.get("download_count") or 0)
            n_assets += 1
    return {"status": st, "n_releases": len(d), "n_assets": n_assets,
            "downloads": downloads, "latest_release": latest}


def npm_downloads(repo):
    url = f"https://raw.githubusercontent.com/{repo}/HEAD/package.json"
    st, d = get(url, UA, timeout=30)
    if st != 200 or not isinstance(d, dict) or not d.get("name"):
        return {"status": st, "package": None, "downloads": None}
    name = d.get("name")
    q = urllib.parse.quote(name, safe="@/")
    st2, d2 = get(f"https://api.npmjs.org/downloads/point/last-month/{q}", UA, timeout=30)
    if st2 == 200 and isinstance(d2, dict):
        return {"status": st2, "package": name, "downloads": d2.get("downloads"),
                "start": d2.get("start"), "end": d2.get("end")}
    return {"status": st2, "package": name, "downloads": None}


def main():
    repos = sorted(json.load(open(REPOS, encoding="utf-8")).keys())
    log(f"repos={len(repos)} token={'yes' if TOKEN else 'no'}")
    for i, repo in enumerate(repos, 1):
        r = {"type": "repo", "repo": repo}
        r["github"] = gh_releases(repo)
        time.sleep(0.12)
        r["npm"] = npm_downloads(repo)
        time.sleep(0.12)
        emit(r)
        if i % 20 == 0:
            log(f"{i}/{len(repos)}")
    emit({"type": "done", "at": datetime.datetime.now().isoformat(timespec="seconds")})


if __name__ == "__main__":
    main()
