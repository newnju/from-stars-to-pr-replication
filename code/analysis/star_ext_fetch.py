# -*- coding: utf-8 -*-
"""
star_ext_fetch.py —— stargazers/history 全史补采（独立于 fetch_gh_api 的星标任务）

起因：2026-10-12 实测该端点**忽略 per_page（恒 30 条/页）且按周倒序返回**，
fetch_gh_api v1/v2 的"短页即止"逻辑只取到最近 30 周（vuejs/awesome-vue
原版 484 周 → 错采 30 周、27 颗星）。本脚本翻到空页为止，独立进度/输出，
可与 fetch_gh_api 的分叉任务并行（不共享任何文件）。

输出：data/star_history_ext_v2.json（合并去重后按 week 降序，格式对齐 star_history.json）
进度：external_data/_cache/star_ext_v2_progress.json + 旁路文件 gh_repos/star2/
启动：必须以脱离 opencode 会话的方式运行（会话内 python 无文件写权限），
      例如 Invoke-CimMethod Win32_Process Create。
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
PROG = os.path.join(CACHE, "star_ext_v2_progress.json")
LOG = os.path.join(CACHE, "gh_api.log")
SIDEDIR = os.path.join(CACHE, "gh_repos", "star2")
OUT = os.path.join(DATA, "star_history_ext_v2.json")

API = "https://api.github.com"
PAGE_SIZE = 30          # 实测恒定
MAX_PAGES = 60
N_WORKERS = 7
THROTTLE = 0.8

_log_lock = threading.Lock()


def log(msg):
    line = f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {msg}"
    with _log_lock:
        try:
            print(line, flush=True)
        except Exception:
            pass
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def load_token():
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if tok:
        return tok
    p = os.path.join(CACHE, "gh_token.txt")
    if os.path.exists(p):
        tok = open(p, encoding="utf-8").read().strip()
        if tok:
            return tok
    return None


TOKEN = load_token()
HEADERS = {"User-Agent": "skill-diffusion-paper-repro",
           "Accept": "application/vnd.github+json"}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"

_th_lock = threading.Lock()
_next_slot = [0.0]


def throttle():
    with _th_lock:
        now = time.time()
        wait = max(_next_slot[0] - now, 0.0)
        _next_slot[0] = max(now, _next_slot[0]) + THROTTLE
    if wait > 0:
        time.sleep(wait)


def api_get(path):
    url = f"{API}{path}"
    for attempt in range(6):
        throttle()
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.status, dict(r.headers), json.load(r)
        except urllib.error.HTTPError as e:
            h = dict(e.headers)
            body = e.read().decode("utf-8", "replace")
            if e.code in (403, 429):
                rem = h.get("X-RateLimit-Remaining")
                reset = h.get("X-RateLimit-Reset")
                if rem == "0" or e.code == 429:
                    wait = max(int(reset or 0) - int(time.time()), 0) + 10
                    log(f"    速率耗尽，睡 {wait}s")
                    time.sleep(wait)
                    continue
                wait = 30 * (attempt + 1)
                log(f"    403 二级限流，退避 {wait}s")
                time.sleep(wait)
                continue
            if e.code == 404:
                return 404, h, None
            if e.code >= 500:
                time.sleep(10 * (attempt + 1))
                continue
            return e.code, h, None
        except Exception as e:
            log(f"    网络异常 {type(e).__name__}: {e}，重试 {attempt + 1}/6")
            time.sleep(5 * (attempt + 1))
    return None, {}, None


def fetch_star_full(repo):
    owner, name = repo.split("/", 1)
    weeks = {}
    page = 1
    while True:
        st, h, body = api_get(
            f"/repos/{owner}/{name}/stargazers/history?page={page}")
        if st == 404:
            return None, "404"
        if not isinstance(body, list):
            return None, f"status={st}"
        if len(body) == 0:
            break
        for w in body:
            if "week" in w:
                weeks[w["week"]] = w
        page += 1
        if page > MAX_PAGES:
            break
        rem = h.get("X-RateLimit-Remaining")
        if rem is not None and int(rem) <= 30:
            wait = max(int(h.get("X-RateLimit-Reset", "0")) - int(time.time()), 0) + 8
            log(f"  配额剩 {rem}，睡 {wait}s")
            time.sleep(wait)
    out = sorted(weeks.values(), key=lambda w: w["week"], reverse=True)
    return out, ""


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def side_path(repo):
    owner, name = repo.split("/", 1)
    return os.path.join(SIDEDIR, f"{owner}__{name}.json")


def write_side(repo, obj):
    p = side_path(repo)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, p)


def main():
    log("=" * 70)
    log("启动 star_ext_fetch v2（翻到空页为止；per_page 忽略、恒 30/页、倒序）")
    meta = json.load(open(os.path.join(DATA, "repos_meta.json"), encoding="utf-8"))
    prog = {}
    if os.path.exists(PROG):
        prog = json.load(open(PROG, encoding="utf-8"))
    res = {}
    if os.path.exists(SIDEDIR) and os.path.isdir(SIDEDIR):
        for fn in os.listdir(SIDEDIR):
            if fn.endswith(".json"):
                repo = fn[:-5].replace("__", "/", 1)
                try:
                    res[repo] = json.load(
                        open(os.path.join(SIDEDIR, fn), encoding="utf-8"))
                except Exception:
                    pass
    todo = [k for k in sorted(meta) if not prog.get(k, {}).get("done")]
    log(f"队列 {len(todo)}（已完成 {len(prog)}）；token={'yes' if TOKEN else 'no'}")

    t0 = time.time()
    n = 0
    errs = 0
    with ThreadPoolExecutor(max_workers=N_WORKERS) as pool:
        futs = {pool.submit(fetch_star_full, k): k for k in todo}
        for fut in as_completed(futs):
            k = futs[fut]
            try:
                weeks, note = fut.result()
            except Exception as e:
                log(f"  [star] {k} 异常: {type(e).__name__}: {e}")
                prog[k] = {"done": True, "error": str(e)}
                errs += 1
                continue
            if weeks is None:
                prog[k] = {"done": True, "error": note}
                log(f"  [star] {k} 失败: {note}")
                errs += 1
                continue
            write_side(k, weeks)
            res[k] = weeks
            prog[k] = {"done": True, "weeks": len(weeks)}
            n += 1
            el = (time.time() - t0) / 3600
            log(f"  [star] {k} 完成 {len(weeks):,} 周"
                f"（{el:.2f}h，{n / el if el else 0:.0f} 仓库/小时）")
            if n % 10 == 0:
                write_json(PROG, prog)
                write_json(OUT, res)
    write_json(PROG, prog)
    write_json(OUT, res)
    el = (time.time() - t0) / 3600
    total_weeks = sum(len(v) for v in res.values())
    log(f"本轮结束：完成 {n}，失败 {errs}，耗时 {el:.2f}h；"
        f"产出 {OUT}（{len(res)} 仓库，{total_weeks:,} 周）")


if __name__ == "__main__":
    main()