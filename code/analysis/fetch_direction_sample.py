# -*- coding: utf-8 -*-
"""
fetch_direction_sample.py — 补 RQ1 方向证据：精确复制对的最早 commit 比较。

选择：skills_with_content 中 sha256 完全相同、不同 owner 的仓库对；
     优先 mirror/registry × original/mixed，再 original × original；
     每仓最多出现 3 次；最多 240 对。
证据：
  - /repos/{repo} 的 fork / parent / created_at
  - /repos/{repo}/commits?path=... 的最早 commit 日期
方向：
  - fork 关系直接定向；
  - 否则比较最早 commit；差 >30 天 high，>1 天 medium，<=1 天 low；
  - 缺 commit 记录则 unresolved。

环境限制：Python 不能直接写文件。JSONL 打到 stdout：
  python analysis\\fetch_direction_sample.py > E:\\temp\\opencode\\direction_sample.jsonl
"""
import json
import os
import sys
import time
import random
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
SKILLS = os.path.join(ROOT, "external_data", "skills_with_content.jsonl")
LOCAL = os.environ.get("LOCAL_MINING", r"E:\temp\opencode\local_mining.jsonl")
OUT = os.environ.get("DIRECTION_OUT", r"E:\temp\opencode\direction_sample.jsonl")
API = "https://api.github.com"
MAX_PAIRS = 240
MAX_REPO_REUSE = 3
MAX_GROUP = 12

random.seed(20261024)


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


def api_get(url):
    for attempt in range(4):
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.status, json.loads(r.read()), r.headers
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if e.code in (403, 429):
                reset = e.headers.get("X-RateLimit-Reset")
                wait = max(5, int(reset) - int(time.time()) + 5) if reset else 60
                log(f"rate limited {e.code}; sleep {wait}s")
                time.sleep(min(wait, 3600))
            elif e.code >= 500:
                time.sleep(3 * (attempt + 1))
            else:
                return e.code, None, e.headers
        except Exception as e:
            log(f"request exception {type(e).__name__}; retry {attempt+1}")
            time.sleep(3 * (attempt + 1))
    return 0, None, {}


def load_repo_types():
    types = {}
    if not os.path.exists(LOCAL):
        return types
    with open(LOCAL, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("type") == "repo":
                types[o.get("repo")] = o
    return types


def build_groups(types):
    groups = {}
    n = 0
    with open(SKILLS, encoding="utf-8") as f:
        for line in f:
            n += 1
            try:
                o = json.loads(line)
            except Exception:
                continue
            repo = o.get("repoFullName")
            sha = o.get("sha256_hash")
            if not repo or not sha or repo not in types:
                continue
            path = o.get("path")
            if not path:
                continue
            g = groups.setdefault(sha, [])
            if len(g) < MAX_GROUP:
                g.append({"repo": repo, "path": path, "stars": o.get("stars"),
                          "type": types[repo].get("repo_type")})
            if n % 50000 == 0:
                log(f"read {n}, groups {len(groups)}")
    return groups


def select_pairs(groups):
    cand = {"mirror_original": [], "original_original": [], "other": []}
    for sha, items in groups.items():
        if len(items) < 2:
            continue
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                if a["repo"] == b["repo"]:
                    continue
                if a["repo"].split("/")[0] == b["repo"].split("/")[0]:
                    continue
                ta, tb = a["type"], b["type"]
                if ta in ("mirror", "registry") or tb in ("mirror", "registry"):
                    cat = "mirror_original"
                elif ta == "original" and tb == "original":
                    cat = "original_original"
                else:
                    cat = "other"
                cand[cat].append((sha, a, b))

    for k in cand:
        random.shuffle(cand[k])
        log(f"candidates {k}: {len(cand[k])}")

    quotas = {"mirror_original": 140, "original_original": 80, "other": 20}
    selected = []
    reuse = {}
    seen = set()
    for cat, quota in quotas.items():
        for sha, a, b in cand[cat]:
            if len([x for x in selected if x[0] == cat]) >= quota:
                break
            key = (a["repo"], b["repo"], sha)
            if key in seen:
                continue
            if reuse.get(a["repo"], 0) >= MAX_REPO_REUSE or reuse.get(b["repo"], 0) >= MAX_REPO_REUSE:
                continue
            seen.add(key)
            reuse[a["repo"]] = reuse.get(a["repo"], 0) + 1
            reuse[b["repo"]] = reuse.get(b["repo"], 0) + 1
            selected.append((cat, sha, a, b))
            if len(selected) >= MAX_PAIRS:
                break
    random.shuffle(selected)
    return selected[:MAX_PAIRS]


def repo_meta(repo):
    st, d, _ = api_get(f"{API}/repos/{repo}")
    if st != 200 or not d:
        return {"status": st, "fork": None, "parent": None, "created_at": None}
    parent = (d.get("parent") or {}).get("full_name")
    return {"status": st, "fork": d.get("fork"), "parent": parent,
            "created_at": d.get("created_at"), "pushed_at": d.get("pushed_at"),
            "stars": d.get("stargazers_count")}


def first_commit(repo, path):
    """返回 (最早 commit 时间, commit sha, n_pages, status)。"""
    page = 1
    last = None
    total = 0
    while page <= 8:
        q = urllib.parse.quote(path, safe="/")
        st, d, _ = api_get(f"{API}/repos/{repo}/commits?path={q}&per_page=100&page={page}")
        if st != 200 or not isinstance(d, list):
            return None, None, page, st
        total += len(d)
        if d:
            last = d[-1]
        if len(d) < 100:
            break
        page += 1
    if not last:
        return None, None, page, 200
    commit = last.get("commit") or {}
    date = (commit.get("author") or {}).get("date") or (commit.get("committer") or {}).get("date")
    return date, last.get("sha"), page, 200


def parse_dt(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def main():
    types = load_repo_types()
    log(f"repo types={len(types)}")
    groups = build_groups(types)
    log(f"sha groups={len(groups)}")
    selected = select_pairs(groups)
    log(f"selected pairs={len(selected)}")

    done = set()
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if o.get("type") == "pair":
                    done.add((o.get("category"), o.get("sha"),
                              (o.get("a") or {}).get("repo"), (o.get("b") or {}).get("repo")))
            log(f"resume: {len(done)} pairs already in {OUT}")

    meta_cache = {}
    out = []
    counts = {"a_to_b": 0, "b_to_a": 0, "ambiguous": 0, "unresolved": 0,
              "high": 0, "medium": 0, "low": 0}

    for idx, (cat, sha, a, b) in enumerate(selected, 1):
        if (cat, sha, a["repo"], b["repo"]) in done:
            continue
        for r in (a["repo"], b["repo"]):
            if r not in meta_cache:
                meta_cache[r] = repo_meta(r)
                time.sleep(0.15)
        ma, mb = meta_cache[a["repo"]], meta_cache[b["repo"]]
        da, sa, pa, sta = first_commit(a["repo"], a["path"])
        db, sb, pb, stb = first_commit(b["repo"], b["path"])
        dta, dtb = parse_dt(da), parse_dt(db)

        direction = "unresolved"
        lag_days = None
        conf = "low"
        # fork 关系优先
        if ma.get("parent") == b["repo"]:
            direction = "b_to_a"
            conf = "high"
        elif mb.get("parent") == a["repo"]:
            direction = "a_to_b"
            conf = "high"
        elif dta and dtb:
            diff = (dtb - dta).total_seconds() / 86400.0
            lag_days = diff
            if abs(diff) <= 1:
                direction = "ambiguous"
                conf = "low"
            elif diff > 0:
                direction = "a_to_b"
                conf = "high" if diff > 30 else "medium"
            else:
                direction = "b_to_a"
                conf = "high" if -diff > 30 else "medium"
        counts[direction] += 1
        counts[conf] += 1
        o = {
            "type": "pair", "category": cat, "sha": sha,
            "a": {"repo": a["repo"], "path": a["path"], "stars": a["stars"], "type": a["type"],
                  "meta": ma, "first_commit": da, "first_sha": sa, "commit_pages": pa, "commit_status": sta},
            "b": {"repo": b["repo"], "path": b["path"], "stars": b["stars"], "type": b["type"],
                  "meta": mb, "first_commit": db, "first_sha": sb, "commit_pages": pb, "commit_status": stb},
            "direction": direction, "lag_days": lag_days, "confidence": conf,
        }
        emit(o)
        if idx % 20 == 0:
            log(f"{idx}/{len(selected)} direction={direction} conf={conf}")

    emit({"type": "meta", "n_selected": len(selected), "counts": counts,
          "generated": datetime.datetime.now().isoformat(timespec="seconds"),
          "note": "方向由最早 path commit 近似；fork 关系优先；commit 日期可被改写/压缩，需按 confidence 分层"})
    log(f"done counts={counts}")


if __name__ == "__main__":
    main()
