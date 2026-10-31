# -*- coding: utf-8 -*-
"""full_fork_hazard.py — 全量 fork 的首次回流风险模型（2026-10-30）
分母=全部 fork（含从未回流者），事件=首次 fork→PR，删失=数据截止 2026-10-24。
输出：data/results/full_fork_hazard_20261030.json（stdout，由 shell 落盘）
"""
import json, os, glob, datetime
import numpy as np
import pandas as pd

ROOT = r"E:\Skill扩散论文_可复现项目"
TMP = r"E:\temp\opencode"
CUT = datetime.datetime(2026, 10, 24)

meta = json.load(open(os.path.join(ROOT, "data", "repos_meta.json"), encoding="utf-8"))
full = json.load(open(os.path.join(ROOT, "data", "forks_timestamps_full.json"), encoding="utf-8"))

# 每个父仓的 fork → 首个 PR 时间
best = {}
for fn in glob.glob(os.path.join(TMP, "fork_prs*.jsonl")):
    for line in open(fn, encoding="utf-8", errors="replace"):
        try: d = json.loads(line)
        except Exception: continue
        if d.get("type") == "parent" and d.get("complete"):
            p = d["parent"]
            if p not in best or d.get("n_matched", 0) > best[p].get("n_matched", 0):
                best[p] = d

def parse(ts):
    if not ts: return None
    try: return datetime.datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
    except Exception: return None

import re
LIST_PAT = re.compile(r"awesome|curated|collection|directory|a list of|list of|resources|合集|清单|导航", re.I)

rows = []
for p, forks in full.items():
    links = (best.get(p) or {}).get("links") or []
    first = {}
    for l in links:
        f = l.get("fork"); t = parse(l.get("created_at"))
        if not f or not t: continue
        if f not in first or t < first[f]: first[f] = t
    is_list = bool(LIST_PAT.search((meta.get(p) or {}).get("description") or ""))
    for f in forks:
        t0 = parse(f.get("created_at"))
        if not t0 or t0 > CUT: continue
        t1 = first.get(f.get("full_name"))
        if t1 is not None and t1 >= t0:
            rows.append((p, (t1 - t0).total_seconds() / 3600.0, 1, is_list))
        else:
            rows.append((p, (CUT - t0).total_seconds() / 3600.0, 0, is_list))

D = pd.DataFrame(rows, columns=["parent", "dur_h", "event", "is_list"])
D = D[D["dur_h"] >= 0]

def km_at(df, times_h):
    dur = df["dur_h"].values.astype(float)
    ev = df["event"].values.astype(int)
    order = np.argsort(dur, kind="mergesort")
    dur, ev = dur[order], ev[order]
    # 每个唯一时间的死亡数与风险集
    ut, idx = np.unique(dur, return_index=True)
    deaths = np.add.reduceat(ev, idx)
    at_risk = len(dur) - idx
    S = np.cumprod(1 - deaths / at_risk)
    out = {}
    for t in times_h:
        k = np.searchsorted(ut, t, side="right") - 1
        out[str(t)] = float(1 - S[k]) if k >= 0 else 0.0
    return out

CURVE_T = [0.1, 0.3, 1, 3, 6, 12, 24, 48, 72, 168, 336, 720, 2160, 4320, 8760]

def hazard_bins(df):
    edges = [0, 1, 24, 24 * 7, 24 * 30, 24 * 90, 24 * 365, np.inf]
    labels = ["<1h", "1–24h", "1–7d", "7–30d", "30–90d", "90–365d", ">365d"]
    out = []
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        at_risk = int(((df["dur_h"] >= lo)).sum())
        ev = int(((df["dur_h"] >= lo) & (df["dur_h"] < hi) & (df["event"] == 1)).sum())
        out.append({"bin": labels[i], "at_risk": at_risk, "events": ev,
                    "hazard_pct": round(100 * ev / at_risk, 4) if at_risk else None})
    return out

def summary(df):
    times = [1, 24, 24 * 7, 24 * 30, 24 * 180, 24 * 365]
    ci = km_at(df, times)
    ev = df[df.event == 1]
    return {
        "n_forks": int(len(df)), "n_events": int(df.event.sum()),
        "event_share_pct": round(100 * float(df.event.mean()), 3),
        "cumulative_incidence_pct": {k: round(100 * v, 3) for k, v in ci.items()},
        "curve": {"times_h": CURVE_T,
                  "cum_pct": [round(100 * v, 3) for v in km_at(df, CURVE_T).values()]},
        "median_days_among_events": round(float(ev.dur_h.median() / 24), 2) if len(ev) else None,
        "share_events_within_24h_pct": round(100 * float((ev.dur_h <= 24).mean()), 2) if len(ev) else None,
        "hazard_bins": hazard_bins(df),
    }

R = {"generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
     "cutoff": "2026-10-24", "n_parents_with_forks": int(D.parent.nunique()),
     "overall": summary(D),
     "list": summary(D[D.is_list]),
     "non_list": summary(D[~D.is_list])}
print(json.dumps(R, ensure_ascii=False, indent=1))
