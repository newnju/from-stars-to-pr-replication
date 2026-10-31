# -*- coding: utf-8 -*-
"""dbg_granger.py — 调试 Granger 检验的样本筛选"""
import json
import os
import collections
import datetime as dt
import numpy as np
from statsmodels.tsa.stattools import grangercausalitytests

ROOT = r"E:\Skill扩散论文_可复现项目"
TMP = r"E:\temp\opencode"
stars = json.load(open(os.path.join(TMP, "star_history_v2.json"), encoding="utf-8"))
forks = json.load(open(os.path.join(ROOT, "data", "forks_timestamps_full.json"), encoding="utf-8"))

inter = [r for r in stars if r in forks]
print("intersection:", len(inter))
ok = 0
errs = collections.Counter()
for repo in inter[:60]:
    weeks = sorted(stars[repo], key=lambda w: w["week"])
    days = []
    for w in weeks:
        days.extend([max(0, int(d or 0)) for d in (w.get("days") or [])])
    if len(days) < 60:
        errs["short_days"] += 1
        continue
    t0 = dt.datetime.fromtimestamp(weeks[0]["week"], tz=dt.timezone.utc).date()
    fd = collections.Counter()
    for f in forks[repo]:
        c = f.get("created_at")
        if not c:
            continue
        try:
            dd = (dt.datetime.fromisoformat(c.replace("Z", "+00:00")).date() - t0).days
        except Exception:
            continue
        if 0 <= dd < len(days):
            fd[dd] += 1
    if sum(fd.values()) < 30:
        errs["few_forks"] += 1
        continue
    fs = np.array([fd.get(i, 0) for i in range(len(days))], float)
    st = np.array(days, float)
    if st.std() == 0 or fs.std() == 0:
        errs["const"] += 1
        continue
    try:
        r = grangercausalitytests(np.column_stack([st, fs]), maxlag=3)
        ok += 1
        print("OK", repo, "days=", len(days), "forksum=", int(fs.sum()))
    except Exception as e:
        errs[type(e).__name__] += 1
        print("ERR", repo, type(e).__name__, str(e)[:80])
print("passed:", ok, "errors:", dict(errs))
