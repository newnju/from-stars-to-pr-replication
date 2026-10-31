# -*- coding: utf-8 -*-
"""
fetch_gh_api.py —— GitHub REST API 补采（并行 v2：7 线程、可续跑、自动限速）

背景：README 曾声称 /forks 有"500 条上限"，2026-10-12 实测接口**无上限**
（page=6 / 100 / 213 / 214 均返回 200），500 条系原采集脚本自截。
本脚本全量分页补采，从根上消除左侧截断：

  任务A forks_full —— 补全触顶仓库的完整分叉列表
        -> data/forks_timestamps_full.json（格式同 forks_timestamps.json）
  任务B star_ext   —— stargazers/history 全量分页
        -> data/star_history_ext.json（不改动正文使用的 star_history.json）

执行优先级：A1 干净样本触顶仓库 -> B 全部 341 星标 -> A2 其余触顶仓库

并行 v2 设计（v1 单线程被跨境延迟 ~5s/页卡死，配额只用 500/5000）：
  - ThreadPoolExecutor(N_WORKERS) 按仓库并行，仓库内部仍顺序翻页；
  - 全局节流锁保证请求间隔 ≥ THROTTLE 秒（7 线程 ≈4,500 次/小时，在配额内）；
  - 每仓库结果先原子写旁路文件 external_data/_cache/gh_repos/{forks,star}/
    （崩溃安全；A2 巨型仓库不再触发 GB 级整文件重写），主线程汇总合并；
  - 阶段边界（A1 结束 / 全部结束）才整写 forks_timestamps_full.json。

速率：未认证 60 次/小时；token 则 5000 次/小时
      （token 读取顺序：环境变量 GITHUB_TOKEN > external_data/_cache/gh_token.txt）
状态：external_data/_cache/gh_api_progress.json（逐仓库 done 标记，中断可续跑）
日志：external_data/_cache/gh_api.log
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
PROG = os.path.join(CACHE, "gh_api_progress.json")
LOG = os.path.join(CACHE, "gh_api.log")
SIDEDIR = os.path.join(CACHE, "gh_repos")
FORKS_OUT = os.path.join(DATA, "forks_timestamps_full.json")
STAR_OUT = os.path.join(DATA, "star_history_ext.json")

API = "https://api.github.com"
PER_PAGE = 100

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
RATE_HR = 5000 if TOKEN else 60
N_WORKERS = 7 if TOKEN else 1
# 节流可调：python fetch_gh_api.py --throttle 1.4（与其他补采并行时降速，
# 避免合计超配额招致二级限速——2026-10-12 曾因此出现翻页 38s/页与重试耗尽）
_throttle_arg = 0.0
for _a in sys.argv[1:]:
    if _a.startswith("--throttle"):
        _throttle_arg = float(_a.split("=", 1)[1]) if "=" in _a else 0.0
        if not _throttle_arg and len(sys.argv) > sys.argv.index(_a) + 1:
            _throttle_arg = float(sys.argv[sys.argv.index(_a) + 1])
THROTTLE = _throttle_arg or (0.8 if TOKEN else 3.0)
HEADERS = {"User-Agent": "skill-diffusion-paper-repro",
           "Accept": "application/vnd.github+json"}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"

# 全局节流：所有线程共享一个最小请求间隔
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
    """带节流与限速处理的 GET；返回 (status, headers, body)。"""
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
                    log(f"    速率耗尽，睡 {wait}s 至重置（{body[:120]}）")
                    time.sleep(wait)
                    continue
                # 403 但配额未尽：二级限流，退避重试
                wait = 30 * (attempt + 1)
                log(f"    403 二级限流，退避 {wait}s（{body[:120]}）")
                time.sleep(wait)
                continue
            if e.code == 404:
                return 404, h, None
            if e.code >= 500:
                time.sleep(10 * (attempt + 1))
                continue
            log(f"    HTTP {e.code}: {body[:160]}")
            return e.code, h, None
        except Exception as e:  # 网络抖动
            log(f"    网络异常 {type(e).__name__}: {e}，重试 {attempt + 1}/6")
            time.sleep(5 * (attempt + 1))
    log("    重试耗尽，放弃本次请求")
    return None, {}, None


def pace(headers):
    """根据响应头节流：配额见底（留 30 余量）则睡到重置。"""
    rem = headers.get("X-RateLimit-Remaining")
    if rem is not None and int(rem) <= 30:
        wait = max(int(headers.get("X-RateLimit-Reset", "0")) - int(time.time()), 0) + 8
        log(f"  配额剩 {rem}，睡 {wait}s 到重置")
        time.sleep(wait)


# ---------------------------------------------------------------- 任务 A
def fetch_forks_full(repo, n_existing):
    """全量分页 /forks。页内按 full_name 去重；空页需二次确认（防翻页漂移误停）。"""
    owner, name = repo.split("/", 1)
    seen = {}
    page = 1
    empty = 0
    while True:
        st, h, body = api_get(f"/repos/{owner}/{name}/forks?per_page={PER_PAGE}&page={page}")
        if st == 404:
            return None, "404"
        if not isinstance(body, list):
            return None, f"status={st}"
        if len(body) == 0:
            empty += 1
            if empty >= 2:
                break
            time.sleep(30)   # 新 fork 会把页码整体下推，空页后等 30s 再确认
            continue
        empty = 0
        for it in body:
            fn = it.get("full_name")
            if fn:
                seen[fn] = it.get("created_at")
        if len(body) < PER_PAGE:
            break
        page += 1
        if page % 25 == 0:
            log(f"    {repo} page={page} 已收 {len(seen):,}")
        pace(h)
    recs = sorted(({"full_name": k, "created_at": v} for k, v in seen.items()
                   if v), key=lambda r: r["created_at"], reverse=True)
    note = ""
    if len(recs) < n_existing - max(5, int(0.02 * n_existing)):
        note = (f"警告: 采得 {len(recs)} < 元数据 {n_existing}，"
                "可能有改名/删除或翻页空洞")
    return recs, note


# ---------------------------------------------------------------- 任务 B
def fetch_star_history(repo):
    """stargazers/history 全量分页（2026-10-12 实测：**忽略 per_page，恒 30
    条/页，且按周倒序**），因此必须翻到空页为止；短页（<30 周）不是结束信号。
    返回按 week 降序的周桶列表（对齐 star_history.json）。"""
    owner, name = repo.split("/", 1)
    weeks = {}
    page = 1
    while True:
        st, h, body = api_get(
            f"/repos/{owner}/{name}/stargazers/history?per_page=100&page={page}")
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
        if page % 40 == 0:
            log(f"    {repo} page={page} 已收 {len(weeks):,} 周")
        pace(h)
        if page > 60:      # 安全上限：60×30=1,800 周（>34 年），实际不会触发
            break
    out = sorted(weeks.values(), key=lambda w: w["week"], reverse=True)
    return out, ""


# ---------------------------------------------------------------- 存储
def load_json(path):
    # utf-8-sig：兼容 PowerShell 5.1 写出的带 BOM 文件（PROG/FORKS_OUT 曾被 PS 改写）
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def side_path(task, repo):
    owner, name = repo.split("/", 1)
    return os.path.join(SIDEDIR, task, f"{owner}__{name}.json")


def write_side(task, repo, obj):
    p = side_path(task, repo)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, p)


def overlay_sides(base, task):
    """把旁路文件叠加到 dict 上（同名以旁路为准）。"""
    d = os.path.join(SIDEDIR, task)
    if not os.path.isdir(d):
        return base
    for fn in os.listdir(d):
        if fn.endswith(".json") and not fn.endswith(".tmp.json"):
            repo = fn[:-5].replace("__", "/", 1)
            try:
                base[repo] = load_json(os.path.join(d, fn))
            except Exception as e:
                log(f"  旁路文件损坏跳过 {fn}: {e}")
    return base


# ---------------------------------------------------------------- 主流程
def main():
    log("=" * 70)
    log(f"启动 fetch_gh_api v2(parallel)  token={TOKEN_SRC}  "
        f"速率={RATE_HR}/h  workers={N_WORKERS}  throttle={THROTTLE}s")

    meta = load_json(os.path.join(DATA, "repos_meta.json"))
    clean = load_json(os.path.join(DATA, "results",
                                   "clean_sample.json"))["clean_repos"]
    existing = load_json(os.path.join(DATA, "forks_timestamps.json"))

    prog = {}
    if os.path.exists(PROG):
        prog = load_json(PROG)
    forks_res = {}
    if os.path.exists(FORKS_OUT):
        forks_res = load_json(FORKS_OUT)
    forks_res = overlay_sides(forks_res, "forks")   # 续跑：叠加旁路成果
    star_res = {}
    if os.path.exists(STAR_OUT):
        star_res = load_json(STAR_OUT)
    star_res = overlay_sides(star_res, "star")
    pf = prog.setdefault("forks_full", {})
    ps = prog.setdefault("star_ext", {})

    def missing(k):
        m = int((meta.get(k) or {}).get("forks") or 0)
        return m - len(existing.get(k) or [])

    a1 = sorted([k for k in clean if missing(k) > 0 and not pf.get(k, {}).get("done")],
                key=missing)
    b = sorted([k for k in meta if not ps.get(k, {}).get("done")])
    a2 = sorted([k for k in meta
                 if k not in clean and missing(k) > 0
                 and not pf.get(k, {}).get("done")], key=missing)

    n_pages = sum(-(-missing(k) // PER_PAGE) for k in a1)
    n_pages += sum(-(-missing(k) // PER_PAGE) for k in a2)
    n_req = n_pages + len(b)
    eff_rate = RATE_HR if TOKEN else 60
    log(f"队列 A1(干净触顶)={len(a1)}  B(星标)={len(b)}  A2(其余触顶)={len(a2)}")
    log(f"预计请求 ≈{n_req:,}（fork 页 {n_pages:,} + 星标 {len(b):,}）"
        f" → 并行 {N_WORKERS} 线程  理论吞吐 ≈{eff_rate}/h  "
        f"ETA ≈ {n_req / eff_rate:.1f} 小时（受延迟约束可能略长）")

    t0 = time.time()
    stats = {"fork": 0, "star": 0, "fail": 0}

    def handle_fork(k, recs, note):
        if recs is None:
            pf[k] = {"done": True, "error": note}
            log(f"  [forks] {k} 失败: {note}")
            stats["fail"] += 1
            return
        write_side("forks", k, recs)      # 崩溃安全：先落旁路
        forks_res[k] = recs
        pf[k] = {"done": True, "count": len(recs),
                 "added": len(recs) - len(existing.get(k) or [])}
        stats["fork"] += 1
        el = (time.time() - t0) / 3600
        rate = stats["fork"] / el if el > 0 else 0
        log(f"  [forks] {k} 完成 {len(recs):,} 条"
            f"（原 {len(existing.get(k) or [])}，新增 {pf[k]['added']:,}）"
            f"{(' ' + note) if note else ''}"
            f"  [累计 {stats['fork']}，{rate:.0f} 仓库/小时]")
        if stats["fork"] % 10 == 0:
            write_json(PROG, prog)

    def handle_star(k, weeks, note):
        if weeks is None:
            ps[k] = {"done": True, "error": note}
            log(f"  [star] {k} 失败: {note}")
            stats["fail"] += 1
            return
        write_side("star", k, weeks)
        star_res[k] = weeks
        ps[k] = {"done": True, "weeks": len(weeks)}
        stats["star"] += 1
        if stats["star"] % 10 == 0:
            write_json(STAR_OUT, star_res)
            write_json(PROG, prog)
            log(f"  [star] 进度 {stats['star']}/{len(b)}")

    def run_phase(kind, keys):
        if not keys:
            return
        log(f"  —— 阶段开始：{kind} ×{len(keys)} ——")
        with ThreadPoolExecutor(max_workers=N_WORKERS) as pool:
            futs = {}
            for k in keys:
                if kind == "forks":
                    futs[pool.submit(
                        fetch_forks_full, k,
                        int((meta.get(k) or {}).get("forks") or 0))] = k
                else:
                    futs[pool.submit(fetch_star_history, k)] = k
            for fut in as_completed(futs):
                k = futs[fut]
                try:
                    payload, note = fut.result()
                except Exception as e:
                    log(f"  [{kind}] {k} 异常: {type(e).__name__}: {e}")
                    (pf if kind == "forks" else ps)[k] = {
                        "done": True, "error": f"{type(e).__name__}: {e}"}
                    stats["fail"] += 1
                    continue
                if kind == "forks":
                    handle_fork(k, payload, note)
                else:
                    handle_star(k, payload, note)
        log(f"  —— 阶段结束：{kind} ——")

    try:
        run_phase("forks", a1)          # A1：干净样本触顶（论文核心）
        write_json(PROG, prog)
        write_json(FORKS_OUT, forks_res)   # A1 结束即合并落盘（theta 可用）
        log(f"  A1 合并落盘 {FORKS_OUT}（{len(forks_res)} 仓库）")
        run_phase("star", b)            # B：星标延长
        write_json(STAR_OUT, star_res)
        run_phase("forks", a2)          # A2：其余触顶（含巨型清单仓库）
    except KeyboardInterrupt:
        log("用户中断，状态已保存（可续跑）")
    finally:
        write_json(PROG, prog)
        write_json(FORKS_OUT, forks_res)
        write_json(STAR_OUT, star_res)
        el = (time.time() - t0) / 3600
        log(f"本轮结束：fork 完成 {stats['fork']}，star 完成 {stats['star']}，"
            f"失败 {stats['fail']}，耗时 {el:.2f}h")
        log(f"产出：{FORKS_OUT}（{len(forks_res)} 仓库）/ "
            f"{STAR_OUT}（{len(star_res)} 仓库）")


if __name__ == "__main__":
    main()
