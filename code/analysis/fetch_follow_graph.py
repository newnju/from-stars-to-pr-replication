# -*- coding: utf-8 -*-
"""
fetch_follow_graph.py —— 关注图子图采集（研究设计 §4.3 / 待办 #5）

目标：258,558 个 actor 全量不可行。取 out-degree >= 20 的 761 个行动者，
      采集其 following（出边）与 starred（注意力），构造可识别同质性与影响的子图。

行动者名单的重建逻辑**照搬** external_data/_capability_probe.py 第三节，
并把"重建数 == 761"作为硬校验 —— 名单口径若与已记录的实测不一致，
说明某处数据变了，必须报错而非静默继续。

端点可用性（2026-10-16 带 token 实测，见研究设计 §4.3）：
    /repos/{r}/stargazers|subscribers|watchers -> HTTP 404 平台级封锁
    /users/{u}/starred|following               -> HTTP 200 可用
本脚本只走用户级端点。

约定同 analysis/fetch_discourse.py：环境变量取 token、全局节流锁、
旁路缓存崩溃安全、逐 actor 进度可续跑。
"""
import json
import os
import re
import sys
import time
import datetime
import threading
import urllib.request
import urllib.error
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
RES = os.path.join(DATA, "results")
CACHE = os.path.join(ROOT, "external_data", "_cache")
PROG = os.path.join(CACHE, "follow_graph_progress.json")
LOG = os.path.join(CACHE, "follow_graph.log")
SIDEDIR = os.path.join(CACHE, "follow_graph")
OUT = os.path.join(DATA, "follow_graph_subgraph.json")
PANEL = os.path.join(RES, "v2_panel.json")

API = "https://api.github.com"
PER_PAGE = 100
MAX_PAGES = 3          # 每人每端点上限 300 条
MIN_DEG = 20           # 与 probe 的 ge20 口径一致
EXPECT_N = 761         # 研究设计 §3 记录值，硬校验
QUOTA_FLOOR = 400      # 剩余配额低于此即停（留缓冲给别的任务）

ENDPOINTS = (("following", "/users/{u}/following?per_page=%d&page={p}" % PER_PAGE),
             ("starred", "/users/{u}/starred?per_page=%d&page={p}" % PER_PAGE))

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
    """带节流与限速处理的 GET。传输层异常（IncompleteRead 等）单独捕获重试
    —— 跨链路截断在 2026-10-16 的话语层采集中实测反复出现。"""
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
                    log(f"    速率耗尽，睡 {wait}s 至重置（{body[:100]}）")
                    time.sleep(wait)
                    continue
                wait = 30 * (attempt + 1)
                log(f"    403 二级限流，退避 {wait}s（{body[:100]}）")
                time.sleep(wait)
                continue
            if e.code == 404:
                return 404, h, None
            if e.code >= 500:
                time.sleep(10 * (attempt + 1))
                continue
            return e.code, h, None
        except Exception as e:
            log(f"    传输层异常 {type(e).__name__}，退避 {5*(attempt+1)}s（{path[:60]}）")
            time.sleep(5 * (attempt + 1))
            continue
    log(f"    重试耗尽: {path}")
    return 0, {}, None


# ============================================================ 名单重建
def build_actors():
    """照搬 _capability_probe.py 第三节口径，返回 Counter(login -> out-degree)。"""
    pj = json.load(open(PANEL, encoding="utf-8-sig"))
    clean = set(pj["repos"])
    p = os.path.join(DATA, "forks_timestamps_full.json")
    text = open(p, encoding="utf-8-sig").read()
    starts = [(m.start(), m.end(), m.group(1))
              for m in re.finditer(r'"([^"]+)":\s*\[\s*\{', text)]
    rec = re.compile(r'"full_name":\s*"([^"]+)",\s*"created_at":\s*"([^"]+)"')
    full = {}
    for i, (s, e, parent) in enumerate(starts):
        if parent not in clean:
            continue
        nxt = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        full[parent] = rec.findall(text[s:nxt])
    del text
    d1 = json.load(open(os.path.join(DATA, "forks_timestamps.json"),
                        encoding="utf-8-sig"))
    net = {}
    for r in clean:
        v = d1.get(r)
        if r in full:
            net[r] = full[r]
        elif isinstance(v, list):
            net[r] = [(x.get("full_name") or "", x.get("created_at") or "")
                      if isinstance(x, dict) else (x, "") for x in v]
    out = Counter()
    for repo, rows in net.items():
        # 每个仓库内先按行动者去重 —— out-degree 语义是"分叉的不同仓库数"，
        # 不是"分叉事件数"。同一行动者删号后重 fork 同一仓库会在 rows 里出现多行，
        # 直接逐行累加会把 19 算成 20。2026-10-17 硬校验正是因此拦下 762 vs 761。
        # 此逻辑与 _capability_probe.py 第三节的 `seen` 集合逐字对齐。
        seen = set()
        for fn, ts in rows:
            if "/" not in fn:
                continue
            seen.add(fn.split("/", 1)[0])
        for a in seen:
            out[a] += 1
    return out, len(net)


# ============================================================ 进度/缓存
def _load_json(p, default):
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            pass
    return default


PROG_D = _load_json(PROG, {})
PROG_LOCK = threading.Lock()


def mark_done(key):
    with PROG_LOCK:
        PROG_D[key] = True
        tmp = PROG + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(PROG_D, f)
        os.replace(tmp, PROG)


def atomic_write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def fetch_actor(a):
    if _stop_flag[0]:
        return a, None
    out = {}
    for kind, tpl in ENDPOINTS:
        key = f"{a}|{kind}"
        sp = os.path.join(SIDEDIR, kind, a.replace("/", "__") + ".json")
        if PROG_D.get(key) and os.path.exists(sp):
            out[kind] = _load_json(sp, {"rows": []}).get("rows", [])
            continue
        if _stop_flag[0]:
            return a, None
        rows, truncated = [], False
        for p in range(1, MAX_PAGES + 1):
            if _stop_flag[0]:
                return a, None
            st, h, body = api_get(tpl.format(u=a, p=p))
            if st == 404 or body is None:
                break
            if st != 200 or not isinstance(body, list):
                break
            # 用户不存在（改名/删号）也记为空，避免反复重试
            if kind == "following":
                rows.extend(x.get("login") for x in body if x.get("login"))
            else:
                rows.extend(x.get("full_name") for x in body if x.get("full_name"))
            if len(body) < PER_PAGE:
                break
            if p == MAX_PAGES:
                truncated = True
        out[kind] = rows
        atomic_write_json(sp, {"n": len(rows), "truncated": truncated, "rows": rows})
        mark_done(key)
    return a, out


def main():
    os.makedirs(CACHE, exist_ok=True)
    log("行动者名单重建（口径同 _capability_probe.py 第三节）…")
    deg, n_net = build_actors()
    actors = sorted([a for a, d in deg.items() if d >= MIN_DEG])
    log("  覆盖仓库 %d    行动者总数 %s    out-degree>=%d -> %d 个"
        % (n_net, "{:,}".format(len(deg)), MIN_DEG, len(actors)))

    if len(actors) != EXPECT_N:
        log("!! 硬校验失败：重建 %d 个，已记录值为 %d（差 %d）。"
            % (len(actors), EXPECT_N, len(actors) - EXPECT_N))
        log("!! 数据口径已变，拒绝继续采集。查清差异后改 EXPECT_N 或修数据。")
        sys.exit(2)
    log("  硬校验通过：重建数 == 记录值 %d" % EXPECT_N)

    log("开始采集  token=%s  workers=%d  throttle=%.1fs  每人每端点上限 %d 条"
        % (TOKEN_SRC, N_WORKERS, THROTTLE, PER_PAGE * MAX_PAGES))
    t0 = time.time()
    done = n_fol = n_sta = 0
    with ThreadPoolExecutor(max_workers=N_WORKERS) as ex:
        futs = {ex.submit(fetch_actor, a): a for a in actors}
        for fut in as_completed(futs):
            a, res = fut.result()
            done += 1
            if res:
                n_fol += len(res.get("following", []))
                n_sta += len(res.get("starred", []))
            if _quota_left[0] < QUOTA_FLOOR and not _stop_flag[0]:
                _stop_flag[0] = True
                log("!! 配额剩余 %d < %d，触发停机保护（进度已存，可续跑）"
                    % (_quota_left[0], QUOTA_FLOOR))
            if done % 50 == 0 or done == len(actors):
                el = time.time() - t0
                log("  进度 %d/%d  用时 %.1f 分  following %s + starred %s  配额剩余 %d"
                    % (done, len(actors), el / 60,
                       "{:,}".format(n_fol), "{:,}".format(n_sta), _quota_left[0]))

    merged = {"generated": datetime.date.today().isoformat(),
              "min_degree": MIN_DEG, "expect_n": EXPECT_N,
              "actors": {}}
    for kind in ("following", "starred"):
        d = os.path.join(SIDEDIR, kind)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if not fn.endswith(".json"):
                continue
            a = fn[:-5]
            o = _load_json(os.path.join(d, fn), {"rows": []})
            merged["actors"].setdefault(a, {})[kind] = o.get("rows", [])
            if o.get("truncated"):
                merged["actors"][a][kind + "_truncated"] = True
    atomic_write_json(OUT, merged)

    el = time.time() - t0
    log("=" * 74)
    log("关注图子图采集完成  用时 %.1f 分" % (el / 60))
    log("  actor %d / %d    following 边 %s    starred %s"
        % (len(merged["actors"]), len(actors),
           "{:,}".format(n_fol), "{:,}".format(n_sta)))
    log("  触顶截断（每人每端点 %d 条）%d 个"
        % (PER_PAGE * MAX_PAGES,
           sum(1 for v in merged["actors"].values()
               if v.get("following_truncated") or v.get("starred_truncated"))))
    log("  最终配额剩余 %d" % _quota_left[0])
    log("  已写 %s（%s B）" % (OUT, "{:,}".format(os.path.getsize(OUT))))


if __name__ == "__main__":
    main()
