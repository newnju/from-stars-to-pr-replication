# -*- coding: utf-8 -*-
"""
fetch_topic_frame.py —— 话题全框采集（能力清单 §7 末行 / 总览待办 #2）

目标：`topic:agent-skills` 的全部仓库（记录值 30,953 个），
      构成不依赖 star 的**全框**，用于抽样框外部效度与话题层分析。

难点：搜索 API **单查询最多返回 1,000 条**（total_count 仍准确，可超 1,000，
      但能翻到的只有前 1,000）。故必须按 created 日期把区间切到每片 <=1,000。

做法：自适应二分
      collect(lo, hi): 先用 per_page=1 拿该区间 total_count
        - 0    -> 跳过
        - <=1000 -> 翻完该片全部页（每页 100，最多 10 页）
        - >1000  -> 按中点拆成两段递归

限速：search 与 core 是**独立配额桶**（实测 search 30 次/分钟，core 5000/小时）。
      本脚本只占 search 桶，THROTTLE 设 2.1s 保证 <=28.5 次/分钟。
可续跑：进度文件记录已完成区间，按仓库 id 去重落盘。
"""
import datetime
import json
import os
import sys
import time
import threading
import urllib.parse
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
PROG = os.path.join(CACHE, "topic_frame_progress.json")
LOG = os.path.join(CACHE, "topic_frame.log")
SIDEDIR = os.path.join(CACHE, "topic_frame")
OUT = os.path.join(DATA, "topic_agent_skills_frame.json")

API = "https://api.github.com/search/repositories"
QUERY = "topic:agent-skills"
PER_PAGE = 100
SEARCH_CAP = 1000        # 单查询可翻取上限
THROTTLE = 2.1           # 30 次/分钟 => >=2.0s；留 0.1s 余量
N_WORKERS = 3            # 共用一把全局节流锁，并发只抵消延迟、不抬吞吐
EXPECT_N = 30953         # 研究设计记录值；实际值会另报，不一致仅提示不阻断
PROBE_DAY = "2026-10-16"  # 日期上界用"今天"，避免漏掉新增仓库

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
        return tok
    p = os.path.join(CACHE, "gh_token.txt")
    if os.path.exists(p):
        t = open(p, encoding="utf-8").read().strip()
        if t:
            return t
    return None


TOKEN = load_token()
HEADERS = {"User-Agent": "skill-diffusion-paper-repro",
           "Accept": "application/vnd.github+json"}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"

_th_lock = threading.Lock()
_next_slot = [0.0]
_lock = threading.Lock()


def throttle():
    with _th_lock:
        now = time.time()
        wait = max(_next_slot[0] - now, 0.0)
        _next_slot[0] = max(now, _next_slot[0]) + THROTTLE
    if wait > 0:
        time.sleep(wait)


def search(q, page=1, per_page=PER_PAGE):
    """返回 (status, dict)。search 桶独立，但 403/429 仍需退避。"""
    url = "%s?%s" % (API, urllib.parse.urlencode(
        {"q": q, "page": page, "per_page": per_page, "sort": "created",
         "order": "desc"}))
    for attempt in range(6):
        throttle()
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if e.code in (403, 429):
                # search 桶耗尽或二级限速：search 的 reset 在 resources.search
                wait = 60 if e.code == 429 else 45 * (attempt + 1)
                log("    search 限速(HTTP %d)，退避 %ss（%s）" % (e.code, wait, body[:90]))
                time.sleep(wait)
                continue
            if e.code == 422:
                # 区间无结果或语法问题
                return 422, {}
            if e.code >= 500:
                time.sleep(10 * (attempt + 1))
                continue
            return e.code, {}
        except Exception as e:
            log("    传输层异常 %s，退避 %ss" % (type(e).__name__, 5 * (attempt + 1)))
            time.sleep(5 * (attempt + 1))
            continue
    return 0, {}


def _load(p, d):
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            pass
    return d


PROG_D = _load(PROG, {})
_done_ranges = set(PROG_D.get("ranges", []))
_STORE = _load(os.path.join(SIDEDIR, "_all.json"), {})
_prog_lock = threading.Lock()


def save_progress():
    tmp = PROG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"ranges": sorted(_done_ranges), "n": len(_STORE)}, f)
    os.replace(tmp, PROG)


def store_repos(items):
    with _prog_lock:
        got = 0
        for it in items:
            rid = it.get("id")
            if rid is None or rid in _STORE:
                continue
            _STORE[rid] = {
                "id": rid,
                "full_name": it.get("full_name"),
                "owner": (it.get("owner") or {}).get("login"),
                "owner_type": (it.get("owner") or {}).get("type"),
                "description": (it.get("description") or "")[:500],
                "topics": it.get("topics") or [],
                "language": it.get("language"),
                "stargazers_count": it.get("stargazers_count"),
                "forks_count": it.get("forks_count"),
                "created_at": it.get("created_at"),
                "updated_at": it.get("updated_at"),
                "pushed_at": it.get("pushed_at"),
                "fork": it.get("fork"),
                "parent": ((it.get("parent") or {}).get("full_name")),
                "archived": it.get("archived"),
                "disabled": it.get("disabled"),
                "open_issues_count": it.get("open_issues_count"),
            }
            got += 1
        if got:
            tmp = os.path.join(SIDEDIR, "_all.json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(_STORE, f, ensure_ascii=False)
            os.replace(tmp, os.path.join(SIDEDIR, "_all.json"))
        return got


def slice_range(lo, hi, depth=0):
    """递归切片：返回该区间处理是否完整。"""
    key = "%s..%s" % (lo, hi)
    if key in _done_ranges:
        return True
    if depth > 40:
        log("  !! 二分超深 %s，放弃该区间" % key)
        return False
    q = "%s created:%s..%s" % (QUERY, lo, hi)
    st, b = search(q, page=1, per_page=1)
    if st != 200:
        log("  !! count 失败 HTTP %s %s" % (st, key))
        return False
    total = b.get("total_count", 0)
    if b.get("incomplete_results"):
        log("  !! incomplete_results=true，total=%s %s（计数不可信，仍继续）" % (total, key))
    if total == 0:
        with _prog_lock:
            _done_ranges.add(key)
            save_progress()
        return True

    if total <= SEARCH_CAP:
        # 翻完该片
        need_pages = (total + PER_PAGE - 1) // PER_PAGE
        got = 0
        for p in range(1, need_pages + 1):
            st, b = search(q, page=p, per_page=PER_PAGE)
            if st != 200 or not b.get("items"):
                log("  !! 取页失败 %s p%d (HTTP %s)" % (key, p, st))
                return False
            got += store_repos(b["items"])
            if len(b["items"]) < PER_PAGE:
                break
        with _prog_lock:
            _done_ranges.add(key)
            save_progress()
        log("  片 %-24s total=%-5d 存 %d（累计 %d）" % (key, total, got, len(_STORE)))
        return True

    # 需要二分
    d0 = datetime.date.fromisoformat(lo)
    d1 = datetime.date.fromisoformat(hi)
    if d0 >= d1:
        log("  !! 已到单日仍 >%d 条，无法再切：%s" % (SEARCH_CAP, key))
        return False
    mid = d0 + (d1 - d0) // 2
    a = slice_range(lo, mid.isoformat(), depth + 1)
    b2 = slice_range((mid + datetime.timedelta(days=1)).isoformat(), hi, depth + 1)
    return a and b2


def find_bounds():
    """探测创建日期的上下界（各 1 次调用）。"""
    st, b = search("%s created:<2000-01-01" % QUERY, page=1, per_page=1)
    lo = "2000-01-01" if st == 200 and b.get("total_count", 0) else None
    st, b = search("%s created:2000-01-01..%s" % (QUERY, PROBE_DAY),
                   page=1, per_page=1)
    if st != 200:
        return None, None, 0
    total = b.get("total_count", 0)
    # 二分找下界
    d_lo = datetime.date(2000, 1, 1)
    d_hi = datetime.date.fromisoformat(PROBE_DAY)
    for _ in range(40):
        if d_lo >= d_hi:
            break
        mid = d_lo + (d_hi - d_lo) // 2
        st, b = search("%s created:<%s" % (QUERY, mid.isoformat()), page=1, per_page=1)
        if st != 200:
            break
        if b.get("total_count", 0) == 0:
            d_lo = mid + datetime.timedelta(days=1)
        else:
            d_hi = mid
    return d_lo.isoformat(), PROBE_DAY, total


def main():
    os.makedirs(SIDEDIR, exist_ok=True)
    log("话题全框采集  query=%s  限速 %.1fs/次（search 30/分桶）  期望 %s 条"
        % (QUERY, THROTTLE, "{:,}".format(EXPECT_N)))
    lo, hi, total = find_bounds()
    if not lo:
        log("!! 探测日期边界失败")
        sys.exit(1)
    log("  创建日期区间 %s .. %s    当前全框 total_count=%s"
        % (lo, hi, "{:,}".format(total)))
    if total != EXPECT_N:
        log("  注意：与记录值 %s 差 %+d（可能因新增仓库或话题变更，非错误）"
            % ("{:,}".format(EXPECT_N), total - EXPECT_N))
    log("  已完成区间 %d 个，已存 %d 个仓库" % (len(_done_ranges), len(_STORE)))

    t0 = time.time()
    ok = slice_range(lo, hi)
    el = (time.time() - t0) / 60

    # 总账
    st, b = search("%s created:%s..%s" % (QUERY, lo, hi), page=1, per_page=1)
    final_total = b.get("total_count", 0) if st == 200 else None
    n = len(_STORE)

    obj = {"generated": datetime.date.today().isoformat(),
           "query": QUERY, "date_range": [lo, hi],
           "search_total_count": final_total,
           "expected_recorded": EXPECT_N,
           "n_repos": n,
           "complete": bool(ok and final_total is not None and n >= final_total),
           "repos": list(_STORE.values())}
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, OUT)

    log("=" * 74)
    log("话题全框采集完成  用时 %.1f 分" % el)
    log("  区间 %s .. %s    已切片完成 %d 个" % (lo, hi, len(_done_ranges)))
    log("  search total_count=%s    实存 %d    完整=%s"
        % (final_total, n, obj["complete"]))
    if final_total is not None and n < final_total:
        log("  !! 少 %d 条，缺口来自 1,000 条上限下未能切尽的单日片或结果变动"
            % (final_total - n))
    log("  已写 %s（%s B）" % (OUT, "{:,}".format(os.path.getsize(OUT))))


if __name__ == "__main__":
    main()
