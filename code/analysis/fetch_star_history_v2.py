# -*- coding: utf-8 -*-
"""fetch_star_history_v2.py — 重采 341 仓星标周时序（2026-10-24）
修复：旧 star_history.json 的 week 错位与页内乱序。新采按 week 排序（升序），
以 repos_meta.created_at 与 stars 总量做锚定校验。输出 E:/temp/opencode/star_history_v2.json
口径：每条 {week(周起始epoch秒), total(该周新增), days[7](每日新增)}；sum(all totals)≈当前星标。
"""
import json
import os
import time
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN = open(os.path.join(ROOT, "external_data", "_cache", "gh_token.txt")).read().strip()
OUT = r"E:\temp\opencode\star_history_v2.json"
HEAD = {"Authorization": "Bearer " + TOKEN, "User-Agent": "skill-diffusion-repro",
        "Accept": "application/vnd.github+json"}


def get(url, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEAD)
            with urllib.request.urlopen(req, timeout=45) as r:
                rem = r.headers.get("X-RateLimit-Remaining")
                if rem is not None and int(rem) <= 3:
                    reset = int(r.headers.get("X-RateLimit-Reset", time.time() + 3600))
                    w = max(5, reset - int(time.time()) + 5)
                    print(f"quota floor; sleep {w}s", flush=True)
                    time.sleep(min(w, 3700))
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                reset = e.headers.get("X-RateLimit-Reset")
                w = max(5, int(reset) - int(time.time()) + 5) if reset else 60
                print(f"ratelimited; sleep {w}s", flush=True)
                time.sleep(min(w, 3700)); last = e; continue
            raise
        except Exception as e:
            last = e; time.sleep(3 * (i + 1))
    raise last


def fetch_repo(full_name):
    out, page = [], 1
    while True:
        d = get(f"https://api.github.com/repos/{full_name}/stargazers/history?page={page}&per_page=30")
        if not isinstance(d, list) or not d:
            break
        out.extend(d)
        if len(d) < 30:
            break
        page += 1
        time.sleep(0.25)
    return out


def main():
    meta = json.load(open(os.path.join(ROOT, "data", "repos_meta.json"), encoding="utf-8"))
    repos = sorted(meta.keys())
    result, report = {}, []
    for i, rp in enumerate(repos):
        try:
            raw = fetch_repo(rp)
            rows = sorted({r["week"]: r for r in raw}.values(), key=lambda x: x["week"])
            total_new = sum(r["total"] for r in rows)
            stars_now = meta[rp].get("stars") or 0
            first_week = rows[0]["week"] if rows else None
            ok_sum = abs(total_new - stars_now) <= max(50, 0.05 * stars_now)
            report.append({"repo": rp, "n_weeks": len(rows), "sum_total": total_new,
                           "stars_meta": stars_now, "sum_ok": ok_sum, "first_week": first_week})
            result[rp] = rows
        except Exception as e:
            report.append({"repo": rp, "error": str(e)[:120]})
        if (i + 1) % 40 == 0:
            print(f"[{i+1}/{len(repos)}]", flush=True)
        time.sleep(0.3)
    json.dump(result, open(OUT, "w", encoding="utf-8"))
    n_ok = sum(1 for r in report if r.get("sum_ok"))
    n_err = sum(1 for r in report if "error" in r)
    print(json.dumps({"n": len(report), "sum_ok": n_ok, "errors": n_err}, ensure_ascii=False))
    for r in report[:6]:
        print(r)


if __name__ == "__main__":
    main()
