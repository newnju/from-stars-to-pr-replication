# -*- coding: utf-8 -*-
"""fetch_copy_edge_meta.py — 补拉"有跨仓复制边"但不在普查层内的仓库元数据

用途：检验中间环节"复制→fork"。复制边来自 near_duplicates.jsonl（121,127 对），
涉及 2,484 个仓；普查层（topic_agent_skills_frame.json，24,854 仓）只覆盖其中 64 个，
故需补拉其余 2,420 个仓的 stars/forks/created_at。

输出：%TEMP%\\copy_edge_meta.jsonl（每行一个仓，断点续跑：已存在的会跳过）
"""
import json, os, sys, time, urllib.request, urllib.error
from collections import defaultdict

ROOT = r"E:\Skill扩散论文_可复现项目"
COL = os.path.join(ROOT, "external_data", "collected_20261024")
OUT = r"C:\Users\diamond\AppData\Local\Temp\copy_edge_meta.jsonl"


def load_token():
    p = os.path.join(ROOT, "external_data", "_cache", "gh_token.txt")
    if os.path.exists(p):
        t = open(p, encoding="utf-8").read().strip()
        if t:
            return t
    return os.environ.get("GITHUB_TOKEN", "").strip() or None


TOKEN = load_token()
HEAD = {"User-Agent": "skill-diffusion-paper-repro",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"}
if TOKEN:
    HEAD["Authorization"] = f"Bearer {TOKEN}"


def log(m):
    print(m, file=sys.stderr, flush=True)


# 1. 复制边涉及的仓
repos = set()
for line in open(os.path.join(COL, "near_duplicates.jsonl"), encoding="utf-8", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get("type") != "pair":
        continue
    a, b = d.get("a") or {}, d.get("b") or {}
    ra, rb = a.get("repo"), b.get("repo")
    if ra and rb and ra != rb:
        repos.add(ra)
        repos.add(rb)

# 2. 已在普查层的
frame = {r["full_name"] for r in
         json.load(open(os.path.join(ROOT, "data", "topic_agent_skills_frame.json"),
                        encoding="utf-8"))["repos"]}
todo = sorted(repos - frame)
log(f"copy-edge repos={len(repos)} in_frame={len(repos & frame)} todo={len(todo)}")

# 3. 断点续跑
done = set()
if os.path.exists(OUT):
    for line in open(OUT, encoding="utf-8", errors="replace"):
        try:
            done.add(json.loads(line)["full_name"])
        except Exception:
            pass
log(f"already done={len(done)}")

fout = open(OUT, "a", encoding="utf-8")
ok = err = n404 = 0
t0 = time.time()
for i, r in enumerate(todo, 1):
    if r in done:
        continue
    url = f"https://api.github.com/repos/{r}"
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=HEAD)
            with urllib.request.urlopen(req, timeout=25) as resp:
                d = json.loads(resp.read().decode("utf-8"))
            fout.write(json.dumps({
                "full_name": d.get("full_name"), "stars": d.get("stargazers_count"),
                "forks": d.get("forks_count"), "created_at": d.get("created_at"),
                "topics": d.get("topics") or [], "description": d.get("description"),
            }, ensure_ascii=False) + "\n")
            fout.flush()
            ok += 1
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                fout.write(json.dumps({"full_name": r, "missing": 404}, ensure_ascii=False) + "\n")
                fout.flush()
                n404 += 1
                break
            if e.code in (403, 429):
                reset = e.headers.get("X-RateLimit-Reset")
                wait = max(5, int(reset) - int(time.time()) + 2) if reset else 60
                log(f"rate limited, sleep {wait}s")
                time.sleep(min(wait, 900))
                continue
            err += 1
            time.sleep(2)
        except Exception:
            err += 1
            time.sleep(2)
    if i % 100 == 0:
        log(f"{i}/{len(todo)} ok={ok} 404={n404} err={err} {time.time()-t0:.0f}s")
    time.sleep(0.35)

log(f"DONE ok={ok} 404={n404} err={err} elapsed={time.time()-t0:.0f}s -> {OUT}")
