# -*- coding: utf-8 -*-
"""fork_orchestrator.py — fork 链自动监护（供定时任务调用，单行输出）
状态机：
  collect: n<228 → 进程死了就重启；连续 2 次启动无进展 → 接受残余进入 finalize
  finalize: 计算 P2 终值 → 写 p2_final_20261026.json → DONE
状态存 E:\\temp\\opencode\\fork_orch_state.json
"""
import json, os, sys, subprocess, datetime, math

ROOT = r"E:\Skill扩散论文_可复现项目"
JSONL = r"E:\temp\opencode\fork_prs_retry3.jsonl"
LOG = r"E:\temp\opencode\fork_retry3.log"
STATE = r"E:\temp\opencode\fork_orch_state.json"
OUT = r"E:\temp\opencode\p2_final_20261026.json"
SCRIPT = os.path.join(ROOT, "analysis", "fetch_fork_prs.py")
TOTAL = 228

def done_set():
    s = set()
    for fn in [r"E:\temp\opencode\fork_prs.jsonl", JSONL]:
        try:
            for line in open(fn, encoding="utf-8", errors="replace"):
                try: r = json.loads(line)
                except Exception: continue
                if r.get("type") == "parent" and r.get("complete"): s.add(r["parent"])
        except FileNotFoundError: pass
    return s

def alive():
    try:
        o = subprocess.run(["powershell", "-NoProfile", "-Command",
            "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object {$_.CommandLine -like '*fetch_fork_prs*'}).Count"],
            capture_output=True, text=True, timeout=30)
        return int(o.stdout.strip() or 0) > 0
    except Exception:
        return False

def launch():
    env = dict(os.environ); env["FORK_PR_OUT"] = JSONL
    subprocess.Popen([sys.executable, "-X", "utf8", SCRIPT], cwd=ROOT,
                     stdout=open(JSONL, "a", encoding="utf-8"),
                     stderr=open(LOG, "a", encoding="utf-8"), env=env,
                     creationflags=0x00000008 | 0x00000200)  # DETACHED | NEW_PROCESS_GROUP

def wilson(k, n, z=1.959964):
    if not n: return None
    p = k / n; d = 1 + z*z/n
    c = (p + z*z/(2*n)) / d
    h = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / d
    return [round(c-h, 4), round(c+h, 4)]

def finalize(done):
    rows = {}
    for fn in [r"E:\temp\opencode\fork_prs.jsonl", JSONL]:
        try: fh = open(fn, encoding="utf-8", errors="replace")
        except FileNotFoundError: continue
        for line in fh:
            try: r = json.loads(line)
            except Exception: continue
            if r.get("type") == "parent" and r.get("complete"):
                rows[r["parent"]] = r
    total_forks = sum(r.get("n_forks", 0) for r in rows.values())
    forks_ge1 = set(); lags = []
    ts = {}
    try:
        tdata = json.load(open(os.path.join(ROOT, "data", "forks_timestamps_full.json"), encoding="utf-8"))
        for p, lst in tdata.items():
            for f in (lst or []):
                if isinstance(f, dict) and f.get("full_name"): ts[f["full_name"]] = f.get("created_at")
    except Exception: pass
    for p, r in rows.items():
        for l in (r.get("links") or []):
            fk = l.get("fork")
            if fk: forks_ge1.add(fk)
            ca = l.get("created_at"); fc = ts.get(fk)
            if ca and fc:
                try:
                    d1 = datetime.datetime.fromisoformat(ca.replace("Z", "+00:00"))
                    d0 = datetime.datetime.fromisoformat(fc.replace("Z", "+00:00"))
                    h = (d1 - d0).total_seconds() / 86400
                    if h >= 0: lags.append(h)
                except Exception: pass
    lags.sort()
    strata = {}
    for lo, hi, name in [(0, 1000, "100-999"), (1000, 10000, "1k-9.9k"), (10000, 10**12, "10k+")]:
        sel = [r for r in rows.values() if lo <= r.get("n_forks", 0) < hi]
        if sel:
            fk_cnt = set(); tot = 0
            for r in sel:
                tot += r.get("n_forks", 0)
                for l in (r.get("links") or []):
                    if l.get("fork"): fk_cnt.add(l["fork"])
            strata[name] = {"n_parent": len(sel), "n_forks": tot, "rate": round(len(fk_cnt)/tot, 4) if tot else None}
    res = {"date": "2026-10-26", "n_parents": len(rows), "total_forks": total_forks,
           "forks_ge1pr": len(forks_ge1), "rate": round(len(forks_ge1)/total_forks, 4) if total_forks else None,
           "rate_CI": wilson(len(forks_ge1), total_forks), "strata": strata,
           "lag": {"n": len(lags), "share_24h": round(sum(1 for x in lags if x <= 1)/len(lags), 4) if lags else None,
                    "median_days": round(lags[len(lags)//2], 2) if lags else None,
                    "p90_days": round(lags[int(len(lags)*0.9)], 1) if lags else None},
           "residual_failed": TOTAL - len(rows)}
    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return res

try: st = json.load(open(STATE, encoding="utf-8"))
except Exception: st = {"phase": "collect", "empty": 0, "n_at_launch": -1}

n = len(done_set())
now = datetime.datetime.now().strftime("%m-%d %H:%M")

if st["phase"] == "done":
    print(f"[{now}] DONE_ALREADY see {OUT}")

elif n >= TOTAL:
    res = finalize(done_set())
    st["phase"] = "done"; json.dump(st, open(STATE, "w"))
    print(f"[{now}] DONE parents={res['n_parents']} rate={res['rate']} CI={res['rate_CI']} 24h={res['lag']['share_24h']} med={res['lag']['median_days']}d residual={res['residual_failed']} -> {OUT}")

else:
    a = alive()
    if a:
        st["empty"] = 0; st["n_at_launch"] = n
        json.dump(st, open(STATE, "w"))
        print(f"[{now}] RUNNING {n}/{TOTAL}")
    else:
        if n > st.get("n_at_launch", -1):
            st["empty"] = 0
        else:
            st["empty"] = st.get("empty", 0) + 1
        if st["empty"] >= 3:
            res = finalize(done_set())
            st["phase"] = "done"; json.dump(st, open(STATE, "w"))
            print(f"[{now}] DONE_RESIDUAL parents={res['n_parents']} rate={res['rate']} residual={res['residual_failed']} -> {OUT}")
        else:
            launch()
            st["n_at_launch"] = n
            json.dump(st, open(STATE, "w"))
            print(f"[{now}] RESTARTED {n}/{TOTAL} empty={st['empty']}")
