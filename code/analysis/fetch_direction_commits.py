# -*- coding: utf-8 -*-
"""fetch_direction_commits.py — commit 级溯源（2026-10-24 补齐项）
对 direction_sample.jsonl 的 165 对，拉两仓该文件路径的提交历史（REST commits?path=），
取最早提交（author date + SHA），重判方向：
  a_first / b_first / same_sha(同源历史，多见于 fork 继承) / none(404或无记录)
输出 E:/temp/opencode/direction_commits.jsonl
"""
import json
import os
import time
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COL = os.path.join(ROOT, "external_data", "collected_20261024")
TOKEN = open(os.path.join(ROOT, "external_data", "_cache", "gh_token.txt")).read().strip()
OUT = r"E:\temp\opencode\direction_commits.jsonl"
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
                    time.sleep(min(max(5, reset - int(time.time()) + 5), 3700))
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return 404, None
            if e.code in (403, 429):
                reset = e.headers.get("X-RateLimit-Reset")
                time.sleep(min(max(5, (int(reset) - int(time.time()) + 5) if reset else 60), 3700))
                last = e; continue
            last = e; time.sleep(3 * (i + 1))
        except Exception as e:
            last = e; time.sleep(3 * (i + 1))
    raise last


def earliest_commit(repo, path):
    """该路径最早提交：commits API 新→旧，取可见列表最后一条；>100 条时翻到尾页。"""
    st, d = get(f"https://api.github.com/repos/{repo}/commits?path={urllib.parse.quote(path)}&per_page=100")
    if st != 200 or not isinstance(d, list) or not d:
        return None
    if len(d) == 100:  # 翻尾页
        n_pages = None
        # 链接头不可得（urllib）；按 100 递进探测一次尾页
        page = 2
        last = d
        while len(last) == 100 and page <= 30:
            st2, d2 = get(f"https://api.github.com/repos/{repo}/commits?path={urllib.parse.quote(path)}&per_page=100&page={page}")
            if st2 != 200 or not d2:
                break
            last = d2; page += 1
        d = last
    c = d[-1]
    return {"sha": c["sha"][:10],
            "author_date": (c.get("commit") or {}).get("author", {}).get("date"),
            "committer_date": (c.get("commit") or {}).get("committer", {}).get("date")}


import urllib.parse


def main():
    pairs = [json.loads(l) for l in open(os.path.join(COL, "direction_sample.jsonl"), encoding="utf-8")]
    pairs = [p for p in pairs if p.get("type") == "pair"]
    print("pairs:", len(pairs), flush=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for i, p in enumerate(pairs):
            a, b = p["a"], p["b"]
            row = {"type": "commitdir", "a": a["repo"], "b": b["repo"],
                   "a_path": a.get("path"), "b_path": b.get("path"), "old_direction": p.get("direction")}
            try:
                ca = earliest_commit(a["repo"], a.get("path") or "")
                time.sleep(0.2)
                cb = earliest_commit(b["repo"], b.get("path") or "")
                row["a_first_commit"], row["b_first_commit"] = ca, cb
                if not ca or not cb:
                    row["verdict"] = "none"
                elif ca["sha"] == cb["sha"]:
                    row["verdict"] = "same_sha"
                else:
                    ta = ca["author_date"] or ca["committer_date"]
                    tb = cb["author_date"] or cb["committer_date"]
                    if ta is None or tb is None:
                        row["verdict"] = "none"
                    elif ta < tb:
                        row["verdict"] = "a_first"
                    elif tb < ta:
                        row["verdict"] = "b_first"
                    else:
                        row["verdict"] = "tie"
            except Exception as e:
                row["verdict"] = "error"
                row["error"] = str(e)[:120]
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            if (i + 1) % 20 == 0:
                print(f"[{i+1}/{len(pairs)}]", flush=True)
            time.sleep(0.3)
    import collections
    c = collections.Counter(json.loads(l)["verdict"] for l in open(OUT, encoding="utf-8"))
    print(dict(c))


if __name__ == "__main__":
    main()
