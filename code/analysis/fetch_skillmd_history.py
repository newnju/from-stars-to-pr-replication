# -*- coding: utf-8 -*-
"""
fetch_skillmd_history.py — SKILL.md 文件历史与署名字段写入时间（2026-10-26）
任务来源：进度汇报二.3「SKILL.md 文件历史采集：获取署名字段的写入时间，
完成审稿人点名的父—子方向性检验」（P3 从部分支持 → 确认性支持的关键证据）。

输入：
  E:/temp/opencode/direction_sample.jsonl           165 对方向样本（a/b 含 repo、path）
  external_data/collected_20261024/local_mining.jsonl   精确复制分组（同 sha 跨仓），扩展抽样
输出（JSONL，每行一个 pair×side）：
  E:/temp/opencode/skillmd_history.jsonl
  {pair_id, side, src, repo, path, sha256, meta, n_commits, first_commit, last_commit,
   attrib_fields_now, attrib_at_birth, attr_write_commit, attr_write_date,
   status, error}
旁路缓存：E:/temp/opencode/skillmd_history_meta.json  （repo → fork/parent/created_at）

方法（对每个 (repo, path)）：
  1) /repos/{repo}/commits?path=… 取该文件全部提交（新→旧，翻页至尾）
  2) 取最旧版本内容，解析 frontmatter，查署名字段（ATTRIB_KEYS 与 probe_four.py 一致）
  3) 最旧无署名而最新有 → 二分查找署名首次写入的提交，记其时间
断点续跑：输出中已有 (pair_id, side) 的行跳过。
限速与配额：每请求间隔 SLEEP 秒（默认 1.2s）；REST 配额剩余 < FLOOR（默认 250）
即睡到 reset —— 把余量让给正在跑的 fork→PR 采集（本脚本只用少量 REST）。
"""
import base64
import json
import os
import random
import re
import sys
import time
import datetime
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
CACHE = os.path.join(ROOT, "external_data", "_cache")
COL = os.path.join(ROOT, "external_data", "collected_20261024")
TMP = r"E:\temp\opencode"
OUT = os.path.join(TMP, "skillmd_history.jsonl")
META_CACHE = os.path.join(TMP, "skillmd_history_meta.json")
DIR_SAMPLE = os.path.join(TMP, "direction_sample.jsonl")
LOG = os.path.join(TMP, "skillmd_history.log")

SLEEP = float(os.environ.get("SKILLMD_SLEEP", "1.2"))
FLOOR = int(os.environ.get("SKILLMD_FLOOR", "250"))
TARGET_PAIRS = int(os.environ.get("SKILLMD_TARGET_PAIRS", "400"))

API = "https://api.github.com"
ATTRIB_KEYS = {"license", "licence", "source", "author", "attribution",
               "credit", "reference", "based-on", "based_on", "original"}
FM_RE = re.compile(r"^---\s*\n(.*?)\n---", re.S)


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
HEAD = {"Authorization": "Bearer " + TOKEN, "User-Agent": "skill-diffusion-repro",
        "Accept": "application/vnd.github+json"} if TOKEN else {
        "User-Agent": "skill-diffusion-repro", "Accept": "application/vnd.github+json"}


def rest(path_or_url, accept_raw=False):
    """GET；返回 (status, parsed_json_or_bytes, rate_remaining, rate_reset)。"""
    url = path_or_url if path_or_url.startswith("http") else API + path_or_url
    hdr = dict(HEAD)
    if accept_raw:
        hdr["Accept"] = "application/vnd.github.raw+json"
    last = None
    for attempt in range(5):
        req = urllib.request.Request(url, headers=hdr)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read()
                rem = r.headers.get("X-RateLimit-Remaining")
                reset = r.headers.get("X-RateLimit-Reset")
                if accept_raw:
                    data = body.decode("utf-8", "replace")
                else:
                    data = json.loads(body.decode("utf-8", "replace")) if body else None
                return r.status, data, rem, reset
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return 404, None, None, None
            if e.code in (403, 429):
                reset = e.headers.get("X-RateLimit-Reset")
                wait = max(5, int(reset) - int(time.time()) + 5) if reset else 60
                log(f"rest {e.code}; sleep {wait}s")
                time.sleep(min(wait, 3700))
                last = f"HTTP {e.code}"
                continue
            if e.code >= 500 and attempt < 4:
                last = f"HTTP {e.code}"
                time.sleep(3 * (attempt + 1))
                continue
            return e.code, None, None, None
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            log(f"net {type(e).__name__}; retry {attempt + 1}/5")
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"rest retries exhausted: {last}")


def quota_guard(rem, reset):
    """REST 配额余量不足就睡到 reset，给 fork→PR 采集留量。"""
    if rem is None:
        return
    if int(rem) <= FLOOR:
        wait = max(5, int(reset) - int(time.time()) + 5) if reset else 120
        log(f"quota floor {rem}<={FLOOR}; sleep {wait}s (留给 fork 采集)")
        time.sleep(min(wait, 3700))


def parse_fm(content):
    if not content:
        return {}
    m = FM_RE.match(content.strip("﻿ \n"))
    if not m:
        return {}
    fields = {}
    for ln in m.group(1).splitlines():
        if ":" in ln:
            k, v = ln.split(":", 1)
            k = k.strip().lower()
            if k and not k.startswith("#"):
                fields[k] = v.strip().strip('"').strip("'")
    return fields


def attrib_fields(fields):
    return sorted(ATTRIB_KEYS & set(fields))


# ---------------- 对构造 ----------------

def build_pairs():
    pairs = []
    seen = set()
    rng = random.Random(20261026)

    def add(pair_id, a, b, src, extra=None):
        key = tuple(sorted([(a["repo"], a["path"]), (b["repo"], b["path"])]))
        if key in seen:
            return False
        seen.add(key)
        row = {"pair_id": pair_id, "src": src,
               "a": {"repo": a["repo"], "path": a["path"]},
               "b": {"repo": b["repo"], "path": b["path"]}}
        if extra:
            row.update(extra)
        pairs.append(row)
        return True

    if os.path.exists(DIR_SAMPLE):
        for i, line in enumerate(open(DIR_SAMPLE, encoding="utf-8")):
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("type") != "pair":
                continue
            a, b = d.get("a") or {}, d.get("b") or {}
            if not (a.get("repo") and a.get("path") and b.get("repo") and b.get("path")):
                continue
            add(f"d{i}", a, b, "direction_sample",
                {"old_direction": d.get("direction"),
                 "category": d.get("category"), "sha256": d.get("sha")})

    if len(pairs) < TARGET_PAIRS:
        groups = {}
        try:
            with open(os.path.join(COL, "local_mining.jsonl"), encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    sha = r.get("sha")
                    if sha:
                        groups.setdefault(sha, []).append((r.get("repo"), r.get("path")))
        except FileNotFoundError:
            log("local_mining.jsonl 缺失，跳过扩展抽样")
        multi = [(sha, v) for sha, v in groups.items()
                 if len({rp[0] for rp in v if rp[0]}) >= 2]
        rng.shuffle(multi)
        use = {}
        for sha, g in multi:
            if len(pairs) >= TARGET_PAIRS:
                break
            by = {}
            for repo, path in g:
                if repo and path and repo not in by:
                    by[repo] = path
            if len(by) < 2:
                continue
            items = sorted(by.items(), key=lambda kv: (use.get(kv[0], 0), rng.random()))
            (ra, pa), (rb, pb) = items[0], items[1]
            if use.get(ra, 0) >= 3 or use.get(rb, 0) >= 3:
                continue
            if add(f"x{len(pairs)}", {"repo": ra, "path": pa}, {"repo": rb, "path": pb},
                   "local_mining_exact", {"sha256": sha}):
                use[ra] = use.get(ra, 0) + 1
                use[rb] = use.get(rb, 0) + 1
    return pairs


# ---------------- 仓库元信息（fork/parent） ----------------

def load_meta_cache():
    try:
        return json.load(open(META_CACHE, encoding="utf-8"))
    except Exception:
        return {}


def save_meta_cache(cache):
    try:
        with open(META_CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass


def repo_meta(repo, cache):
    if repo in cache:
        return cache[repo]
    st, d, rem, reset = rest(f"/repos/{repo}")
    quota_guard(rem, reset)
    time.sleep(SLEEP)
    if st != 200 or not isinstance(d, dict):
        m = {"status": st}
    else:
        m = {"status": st, "fork": d.get("fork"),
             "parent": (d.get("parent") or {}).get("full_name"),
             "created_at": d.get("created_at")}
    cache[repo] = m
    save_meta_cache(cache)
    return m


# ---------------- 单侧历史 ----------------

def commit_history(repo, path):
    """该路径全部提交（新→旧列表）。返回 (list|None, status)。"""
    commits = []
    page = 1
    qpath = urllib.parse.quote(path)
    while page <= 30:
        st, d, rem, reset = rest(f"/repos/{repo}/commits?path={qpath}&per_page=100&page={page}")
        quota_guard(rem, reset)
        time.sleep(SLEEP)
        if st == 404:
            return commits, 404
        if st != 200 or not isinstance(d, list):
            return None, st
        for c in d:
            commits.append({
                "sha": c.get("sha"),
                "author_date": (c.get("commit") or {}).get("author", {}).get("date"),
                "committer_date": (c.get("commit") or {}).get("committer", {}).get("date"),
            })
        if len(d) < 100:
            return commits, 200
        page += 1
    return commits, 200  # 触顶，近似全量


def file_fm_at(repo, path, sha):
    qpath = urllib.parse.quote(path)
    st, d, rem, reset = rest(f"/repos/{repo}/contents/{qpath}?ref={sha}")
    quota_guard(rem, reset)
    time.sleep(SLEEP)
    if st != 200 or not isinstance(d, dict):
        return None
    try:
        content = base64.b64decode(d.get("content") or "").decode("utf-8", "replace")
    except Exception:
        return None
    return parse_fm(content)


def side_row(pair, side, repo, path, cache):
    row = {"pair_id": pair["pair_id"], "side": side, "src": pair.get("src"),
           "repo": repo, "path": path,
           "old_direction": pair.get("old_direction"),
           "sha256": pair.get("sha256")}
    try:
        row["meta"] = repo_meta(repo, cache)
        commits, st = commit_history(repo, path)
        if commits is None:
            row["status"] = f"history_fail_{st}"
            return row
        row["n_commits"] = len(commits)
        row["history_status"] = st
        if not commits:
            row["status"] = "no_history"
            return row
        oldest, newest = commits[-1], commits[0]
        row["first_commit"] = oldest.get("author_date") or oldest.get("committer_date")
        row["last_commit"] = newest.get("author_date") or newest.get("committer_date")

        fm_old = file_fm_at(repo, path, oldest["sha"])
        attrs_old = attrib_fields(fm_old or {})
        row["attrib_at_birth"] = attrs_old
        if attrs_old:
            row["attr_write_commit"] = oldest["sha"]
            row["attr_write_date"] = row["first_commit"]
            row["status"] = "ok_attr_at_birth"
            return row

        fm_new = file_fm_at(repo, path, newest["sha"])
        attrs_new = attrib_fields(fm_new or {})
        row["attrib_fields_now"] = attrs_new
        if not attrs_new:
            row["status"] = "ok_no_attr_ever"
            return row

        # 最旧无、最新有 → 二分查找署名首次出现的提交（commits 旧→新 = reversed）
        seq = list(reversed(commits))  # [oldest … newest]
        lo, hi = 0, len(seq) - 1
        # 已知 seq[0] 无、seq[-1] 有
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            fm_mid = file_fm_at(repo, path, seq[mid]["sha"])
            if attrib_fields(fm_mid or {}):
                hi = mid
            else:
                lo = mid
        w = seq[hi]
        row["attr_write_commit"] = w["sha"]
        row["attr_write_date"] = w.get("author_date") or w.get("committer_date")
        row["status"] = "ok_attr_added_later"
        return row
    except Exception as e:
        row["status"] = "error"
        row["error"] = f"{type(e).__name__}: {e}"[:200]
        return row


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
            if o.get("pair_id") and o.get("side"):
                done.add((o["pair_id"], o["side"]))
    return done


def main():
    pairs = build_pairs()
    done = existing_done()
    cache = load_meta_cache()
    log(f"pairs={len(pairs)} done_sides={len(done)} token={'yes' if TOKEN else 'no'} "
        f"sleep={SLEEP}s floor={FLOOR}")
    n_new = 0
    with open(OUT, "a", encoding="utf-8") as f:
        for i, p in enumerate(pairs, 1):
            for side in ("a", "b"):
                if (p["pair_id"], side) in done:
                    continue
                node = p[side]
                row = side_row(p, side, node["repo"], node["path"], cache)
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                n_new += 1
            if (i % 10 == 0) or i == len(pairs):
                log(f"[{i}/{len(pairs)}] 新增 {n_new} 侧")
    log(f"完成：{n_new} 侧新增，输出 {OUT}")


if __name__ == "__main__":
    main()
