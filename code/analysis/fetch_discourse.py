# -*- coding: utf-8 -*-
"""
fetch_discourse.py —— 话语层采集（能力清单 §7 / 总览 #10）

目标：把内容分析从静态文本推进到互动层。采集 203 个面板仓库的
      issues + PR（同一端点，以 pull_request 键区分）与仓库级 commit comments。

设计沿用 analysis/fetch_gh_api.py 的既定约定，不另起一套：
  - token 读取顺序：环境变量 GITHUB_TOKEN > external_data/_cache/gh_token.txt
  - 全局节流锁保证请求间隔 >= THROTTLE（0.8s ≈ 4,500 次/小时，在 5000 配额内）
  - 每仓结果先原子写旁路文件 external_data/_cache/gh_discourse/{issues,comments}/
    （崩溃安全），主线程汇总合并
  - 进度 external_data/_cache/gh_discourse_progress.json（逐仓逐端点 done，可续跑）
  - 日志 external_data/_cache/gh_discourse.log

成本控制：MAX_PAGES 每仓每端点封顶；全局配额低于 QUOTA_FLOOR 即停。
"""
import json
import os
import sys
import time
import datetime
import threading
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
CACHE = os.path.join(ROOT, "external_data", "_cache")
PROG = os.path.join(CACHE, "gh_discourse_progress.json")
LOG = os.path.join(CACHE, "gh_discourse.log")
SIDEDIR = os.path.join(CACHE, "gh_discourse")
OUT = os.path.join(DATA, "gh_discourse.json")
PANEL = os.path.join(DATA, "results", "v2_panel.json")

API = "https://api.github.com"
PER_PAGE = 100
MAX_PAGES = 10          # 每仓每端点封顶 1,000 条
QUOTA_FLOOR = 500       # 剩余配额低于此即停

_log_lock = threading.Lock()


def log(msg):
    line = f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {msg}"
    with _log_lock:
        print(line, flush=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")


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
N_WORKERS = 7 if TOKEN else 1
THROTTLE = 0.8 if TOKEN else 3.0
HEADERS = {"User-Agent": "skill-diffusion-paper-repro",
           "Accept": "application/vnd.github+json"}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"

_th_lock = threading.Lock()
_next_slot = [0.0]
_quota_lock = threading.Lock()
_quota_left = [10 ** 9]
_stop_flag = [False]


def throttle():
    with _th_lock:
        now = time.time()
        wait = max(_next_slot[0] - now, 0.0)
        _next_slot[0] = max(now, _next_slot[0]) + THROTTLE
    if wait > 0:
        time.sleep(wait)


def api_get(path):
    """带节流与限速处理的 GET；返回 (status, headers, body)。"""
    url = f"{API}{path}"
    for attempt in range(6):
        if _stop_flag[0]:
            return 0, {}, None
        throttle()
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                h = dict(r.headers)
                rem = h.get("X-RateLimit-Remaining")
                if rem is not None:
                    with _quota_lock:
                        _quota_left[0] = int(rem)
                # 先一次性读出再解析：跨链路截断（IncompleteRead）须走重试，
                # 而 json.load(r) 流式读会在 200 分支里直接抛出、绕过下方的 HTTPError 处理
                raw = r.read()
                return r.status, h, json.loads(raw)
        except urllib.error.HTTPError as e:
            h = dict(e.headers)
            body = e.read().decode("utf-8", "replace")
            rem = h.get("X-RateLimit-Remaining")
            if rem is not None:
                with _quota_lock:
                    _quota_left[0] = int(rem)
            if e.code in (403, 429):
                reset = h.get("X-RateLimit-Reset")
                if rem == "0" or e.code == 429:
                    wait = max(int(reset or 0) - int(time.time()), 0) + 10
                    log(f"    速率耗尽，睡 {wait}s 至重置（{body[:120]}）")
                    time.sleep(wait)
                    continue
                wait = 30 * (attempt + 1)
                log(f"    403 二级限流，退避 {wait}s（{body[:120]}）")
                time.sleep(wait)
                continue
            if e.code == 404:
                return 404, h, None
            if e.code >= 500:
                time.sleep(10 * (attempt + 1))
                continue
            return e.code, h, None
        except Exception as e:
            # 传输层故障：IncompleteRead / ConnectionReset / Timeout / BadStatusLine
            # 跨链路截断在本机实测出现过（IncompleteRead 389,312/434,847 B）
            log(f"    传输层异常 {type(e).__name__}，退避 {5*(attempt+1)}s（{path[:60]}）")
            time.sleep(5 * (attempt + 1))
            continue
    log(f"    重试耗尽: {path}")
    return 0, {}, None


def load_progress():
    if os.path.exists(PROG):
        try:
            return json.load(open(PROG, encoding="utf-8"))
        except Exception:
            pass
    return {}


PROG_D = load_progress()
PROG_LOCK = threading.Lock()


def mark_done(key):
    with PROG_LOCK:
        PROG_D[key] = True
        tmp = PROG + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(PROG_D, f)
        os.replace(tmp, PROG)


def side_path(kind, repo):
    d = os.path.join(SIDEDIR, kind)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, repo.replace("/", "__") + ".json")


def atomic_write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def pick_issue(it):
    """精简字段，避免整包入库。"""
    u = (it.get("user") or {}).get("login")
    return {
        "number": it.get("number"),
        "title": it.get("title"),
        "body": (it.get("body") or "")[:8000],
        "state": it.get("state"),
        "is_pr": "pull_request" in it,
        "user": u,
        "user_type": (it.get("user") or {}).get("type"),
        "labels": [l.get("name") for l in (it.get("labels") or [])],
        "created_at": it.get("created_at"),
        "closed_at": it.get("closed_at"),
        "comments": it.get("comments"),
        "reactions": (it.get("reactions") or {}).get("total_count"),
        "html_url": it.get("html_url"),
    }


def pick_comment(c):
    return {
        "body": (c.get("body") or "")[:8000],
        "user": (c.get("user") or {}).get("login"),
        "user_type": (c.get("user") or {}).get("type"),
        "created_at": c.get("created_at"),
        "commit_id": (c.get("commit_id") or "")[:12],
        "html_url": c.get("html_url"),
    }


def fetch_repo(repo):
    """一个仓库：issues(+PRs) 与 commit comments 两条线。"""
    if _stop_flag[0]:
        return repo, None
    owner = repo.split("/", 1)[0]
    name = repo.split("/", 1)[1]
    out = {}

    for kind, path_tpl in (
        ("issues", f"/repos/{owner}/{name}/issues?state=all&per_page={PER_PAGE}&page={{p}}"),
        ("comments", f"/repos/{owner}/{name}/comments?per_page={PER_PAGE}&page={{p}}"),
    ):
        key = f"{repo}|{kind}"
        sp = side_path(kind, repo)
        if PROG_D.get(key) and os.path.exists(sp):
            out[kind] = json.load(open(sp, encoding="utf-8"))
            continue
        if _stop_flag[0]:
            return repo, None
        rows = []
        truncated = False
        for p in range(1, MAX_PAGES + 1):
            if _stop_flag[0]:
                return repo, None
            st, h, body = api_get(path_tpl.format(p=p))
            if st == 404 or body is None:
                break
            if st != 200 or not isinstance(body, list):
                break
            fn = pick_issue if kind == "issues" else pick_comment
            rows.extend(fn(x) for x in body)
            if len(body) < PER_PAGE:
                break
            if p == MAX_PAGES:
                truncated = True
        out[kind] = rows
        atomic_write_json(sp, {"n": len(rows), "truncated": truncated, "rows": rows})
        mark_done(key)
        log(f"  {repo} {kind:9s} {len(rows):5d} 条"
            + ("（触顶截断）" if truncated else ""))
    return repo, out


def main():
    os.makedirs(CACHE, exist_ok=True)
    panel = sorted(json.load(open(PANEL, encoding="utf-8-sig"))["repos"])
    log(f"面板仓库 {len(panel)} 个   token={TOKEN_SRC}   workers={N_WORKERS}   "
        f"throttle={THROTTLE}s   max_pages={MAX_PAGES}")
    if not TOKEN:
        log("!! 未取到 token，匿名限额 60 次/小时，将极慢")

    t0 = time.time()
    done = 0
    tot_iss = tot_com = 0
    trunc = 0
    with ThreadPoolExecutor(max_workers=N_WORKERS) as ex:
        futs = {ex.submit(fetch_repo, r): r for r in panel}
        for fut in as_completed(futs):
            repo, res = fut.result()
            done += 1
            if res:
                tot_iss += len(res.get("issues", []))
                tot_com += len(res.get("comments", []))
                trunc += sum(1 for k in ("issues", "comments")
                             if res.get(k) and len(res[k]) >= PER_PAGE * MAX_PAGES)
            if _quota_left[0] < QUOTA_FLOOR and not _stop_flag[0]:
                _stop_flag[0] = True
                log(f"!! 配额剩余 {_quota_left[0]} < {QUOTA_FLOOR}，触发停机保护")
            if done % 20 == 0 or done == len(panel):
                el = time.time() - t0
                log(f"  进度 {done}/{len(panel)}  用时 {el/60:.1f} 分  "
                    f"累计 issues {tot_iss} + comments {tot_com}  配额剩余 {_quota_left[0]}")

    merged = {"generated": datetime.date.today().isoformat(),
              "repos": {}, "n_repos": len(panel)}
    for kind in ("issues", "comments"):
        d = os.path.join(SIDEDIR, kind)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if not fn.endswith(".json"):
                continue
            repo = fn[:-5].replace("__", "/")
            obj = json.load(open(os.path.join(d, fn), encoding="utf-8"))
            merged["repos"].setdefault(repo, {})[kind] = obj["rows"]
            if obj.get("truncated"):
                merged["repos"][repo][kind + "_truncated"] = True
    atomic_write_json(OUT, merged)

    el = time.time() - t0
    log("=" * 70)
    log(f"采集完成  用时 {el/60:.1f} 分")
    log(f"  仓库 {len(merged['repos'])} / {len(panel)}")
    log(f"  issues+PR 总条数 {tot_iss}   commit comments {tot_com}")
    log(f"  触顶截断的 仓库-端点 组合 {trunc} 个（每端点上限 {PER_PAGE*MAX_PAGES} 条）")
    log(f"  最终配额剩余 {_quota_left[0]}")
    log(f"  已写 {OUT}（{os.path.getsize(OUT):,} B）")
    n_pr = sum(1 for v in merged["repos"].values()
               for i in v.get("issues", []) if i.get("is_pr"))
    log(f"  其中 PR {n_pr} 条，纯 issue {tot_iss - n_pr} 条")


if __name__ == "__main__":
    main()
