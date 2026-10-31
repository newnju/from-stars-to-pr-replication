# -*- coding: utf-8 -*-
"""补算中间环节：安装→复制、复制→fork 的效度边界；以及 0.6 阈值与分层敏感性"""
import json, os, math
from collections import defaultdict
import numpy as np
from scipy import stats

ROOT = r"E:\Skill扩散论文_可复现项目"
COL = os.path.join(ROOT, "external_data", "collected_20261024")

meta = json.load(open(os.path.join(ROOT, "data", "repos_meta.json"), encoding="utf-8"))
print("panel repos:", len(meta))

# ---------- 安装量 ----------
inst = {}
for fn in ["market_full.jsonl", "market_retry.jsonl", "market_extra.jsonl"]:
    p = os.path.join(COL, fn)
    if not os.path.exists(p):
        continue
    for line in open(p, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("type") == "skills_sh" and d.get("repo") and (d.get("total_installs") or 0) > 0:
            inst[d["repo"]] = max(inst.get(d["repo"], 0), d["total_installs"])
print("installs>0:", len(inst))

# ---------- 跨仓复制（出度/入度） ----------
out_cnt = defaultdict(set)
in_cnt = defaultdict(set)
npair = 0
for line in open(os.path.join(COL, "near_duplicates.jsonl"), encoding="utf-8", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get("type") != "pair":
        continue
    a, b = d.get("a") or {}, d.get("b") or {}
    ra, rb = a.get("repo"), b.get("repo")
    if not ra or not rb or ra == rb:
        continue
    npair += 1
    out_cnt[ra].add(a.get("sha"))
    in_cnt[rb].add(a.get("sha"))
print("cross-repo pairs:", npair)
print("repos with copy-out:", len(out_cnt), "| copy-in:", len(in_cnt))

copy = {}
for r in set(out_cnt) | set(in_cnt):
    copy[r] = len(out_cnt.get(r, set())) + len(in_cnt.get(r, set()))

# ---------- 合并 ----------
rows = []
for r, m in meta.items():
    rows.append({
        "repo": r,
        "stars": m.get("stars") or 0,
        "forks": m.get("forks") or 0,
        "inst": inst.get(r),
        "copy": copy.get(r, 0),
        "listed": r in inst,
    })
print("merged:", len(rows))
print("有 fork 的仓:", sum(1 for x in rows if x["forks"] > 0))
print("复制>0 的仓:", sum(1 for x in rows if x["copy"] > 0))


def tost(x, y, bound, alpha=0.05):
    """Spearman + Fisher z TOST（对 |rho|>=bound 的等价检验）"""
    ok = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    xs = np.array([p[0] for p in ok], float)
    ys = np.array([p[1] for p in ok], float)
    if len(xs) < 10:
        return None
    rho, p = stats.spearmanr(xs, ys)
    n = len(xs)
    z = np.arctanh(np.clip(rho, -0.999, 0.999))
    se = 1 / math.sqrt(n - 3)
    z0 = np.arctanh(bound)
    t = (z0 - abs(z)) / se
    p_tost = 1 - stats.norm.cdf(t)
    return dict(n=n, rho=float(rho), p=float(p), p_tost=float(p_tost), se=float(se))


print("\n=== 中间环节：安装→复制 ===")
sub = [x for x in rows if x["inst"] is not None]
for bound in (0.5, 0.4, 0.35, 0.6):
    r = tost([x["inst"] for x in sub], [x["copy"] for x in sub], bound)
    print(f"  |rho|>={bound}: ", {k: round(v, 6) for k, v in r.items()})

print("\n=== 中间环节：复制→fork ===")
sub2 = [x for x in rows if x["forks"] > 0]
for bound in (0.5, 0.4, 0.35, 0.6):
    r = tost([x["copy"] for x in sub2], [x["forks"] for x in sub2], bound)
    print(f"  |rho|>={bound}: ", {k: round(v, 6) for k, v in r.items()})

print("\n=== 对照：星标×安装（已知 P1）===")
sub3 = [x for x in rows if x["inst"] is not None]
for bound in (0.5, 0.6):
    r = tost([x["stars"] for x in sub3], [x["inst"] for x in sub3], bound)
    print(f"  |rho|>={bound}: ", {k: round(v, 6) for k, v in r.items()})

print("\n=== P1 分层：按是否被平台收录 ===")
for lab, grp in (("收录", [x for x in sub3 if x["listed"]]), ("未收录", [x for x in sub3 if not x["listed"]])):
    r = tost([x["stars"] for x in grp], [x["inst"] for x in grp], 0.5)
    print(f"  {lab}: ", {k: round(v, 6) for k, v in r.items()} if r else "n<10")

print("\n=== P1 分层：年龄 × 星标 双维 ===")
import datetime as dt
now = dt.datetime(2026, 10, 24)
for x in rows:
    c = (meta.get(x["repo"]) or {}).get("created_at")
    x["age_d"] = (now - dt.datetime.strptime(c[:10], "%Y-%m-%d")).days if c else None
sub4 = [x for x in sub3 if x["age_d"] is not None]
med_age = np.median([x["age_d"] for x in sub4])
med_star = np.median([x["stars"] for x in sub4])
for alab, af in (("新仓", lambda x: x["age_d"] <= med_age), ("老仓", lambda x: x["age_d"] > med_age)):
    for slab, sf in (("低星", lambda x: x["stars"] <= med_star), ("高星", lambda x: x["stars"] > med_star)):
        g = [x for x in sub4 if af(x) and sf(x)]
        r = tost([x["stars"] for x in g], [x["inst"] for x in g], 0.5)
        print(f"  {alab}×{slab} (n={len(g)}): ", {k: round(v, 4) for k, v in r.items()} if r else "n<10")
