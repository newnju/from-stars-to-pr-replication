# -*- coding: utf-8 -*-
"""fetch_copy_edge_gql.py — 用 GraphQL 批量补拉复制边仓库元数据（50 个/请求）

REST 逐仓请求会触发二级限流（连续 500+ 次后 403），而 GraphQL 配额独立且支持别名批量。
输出与 fetch_copy_edge_meta.py 相同的 JSONL，可续跑。
"""
import json, os, sys, time, urllib.request

ROOT = r"E:\Skill扩散论文_可复现项目"
COL = os.path.join(ROOT, "external_data", "collected_20261024")
OUT = r"C:\Users\diamond\AppData\Local\Temp\copy_edge_meta.jsonl"
BATCH = 50


def log(m):
    print(m, file=sys.stderr, flush=True)


TOKEN = open(os.path.join(ROOT, "external_data", "_cache", "gh_token.txt"),
             encoding="utf-8").read().strip()


def gql(query):
    body = json.dumps({"query": query}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql", data=body,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json",
                 "User-Agent": "skill-diffusion-paper-repro"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read())


# 待拉清单
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
        repos.add(ra); repos.add(rb)

frame = {r["full_name"] for r in
         json.load(open(os.path.join(ROOT, "data", "topic_agent_skills_frame.json"),
                        encoding="utf-8"))["repos"]}
todo = sorted(repos - frame)

done = set()
if os.path.exists(OUT):
    for line in open(OUT, encoding="utf-8", errors="replace"):
        try:
            done.add(json.loads(line)["full_name"])
        except Exception:
            pass
todo = [r for r in todo if r not in done]
log(f"todo={len(todo)} (already {len(done)})")

fout = open(OUT, "a", encoding="utf-8")
t0 = time.time()
ok = miss = 0
for i in range(0, len(todo), BATCH):
    chunk = todo[i:i + BATCH]
    parts = []
    for k, r in enumerate(chunk):
        if "/" not in r:
            continue
        o, n = r.split("/", 1)
        parts.append(f'r{k}: repository(owner:{json.dumps(o)}, name:{json.dumps(n)}) '
                     f'{{ nameWithOwner stargazerCount forkCount createdAt }}')
    q = "query{" + " ".join(parts) + "}"
    try:
        res = gql(q)
    except Exception as e:
        log(f"ERR batch {i}: {e}")
        time.sleep(5)
        continue
    data = (res.get("data") or {})
    if not data:
        log(f"NO DATA batch {i}: {str(res)[:200]}")
        time.sleep(5)
        continue
    for k, r in enumerate(chunk):
        node = data.get(f"r{k}")
        if node:
            fout.write(json.dumps({
                "full_name": node.get("nameWithOwner"),
                "stars": node.get("stargazerCount"),
                "forks": node.get("forkCount"),
                "created_at": node.get("createdAt"),
            }, ensure_ascii=False) + "\n")
            ok += 1
        else:
            fout.write(json.dumps({"full_name": r, "missing": 404}, ensure_ascii=False) + "\n")
            miss += 1
    fout.flush()
    if (i // BATCH) % 5 == 0:
        log(f"{i+len(chunk)}/{len(todo)} ok={ok} miss={miss} {time.time()-t0:.0f}s")
    time.sleep(0.8)

log(f"DONE ok={ok} miss={miss} elapsed={time.time()-t0:.0f}s")
