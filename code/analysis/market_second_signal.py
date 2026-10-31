# -*- coding: utf-8 -*-
"""
market_second_signal.py —— 市场侧第二采纳信号
（《数据来源全清单》第八节第 6 项，market/ 快照已采集）

skills.sh 的 installs 与 ClawHub 的 downloads 是独立于 GitHub fork 图的
采纳度量：记录技能被安装/下载的次数。用途：
  1) 覆盖率：203 干净样本在两站的命中占比；
  2) 量级：安装/下载数分布（中位 / p90 / 总量）；
  3) 一致性：与星标、分叉总数的 Spearman（同向性）；
  4) 背离：安装高、分叉排名低的仓库清单——若 fork 图存在截断或
     「空转」（星标多分叉少），市场侧能给出独立佐证。

输入：external_data/market/skills_sh_search_*.json、clawhub_search_*.json
输出：data/results/market_second_signal.json
"""
import glob
import json
import os
import sys
import datetime

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import numpy as np
from scipy import stats as st

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
MKT = os.path.join(ROOT, "external_data", "market")
OUT = os.path.join(DATA, "results", "market_second_signal.json")


def latest(pat):
    fs = sorted(glob.glob(os.path.join(MKT, pat)))
    if not fs:
        raise SystemExit(f"缺少输入: {pat}")
    return fs[-1]


def dist(vals):
    v = np.asarray(vals, dtype=float)
    if not len(v):
        return {"n": 0}
    return {
        "n": int(len(v)),
        "sum": float(v.sum()),
        "median": float(np.median(v)),
        "p75": float(np.percentile(v, 75)),
        "p90": float(np.percentile(v, 90)),
        "max": float(v.max()),
        "share_of_zero": float((v == 0).mean()),
    }


def main():
    clean = json.load(open(os.path.join(DATA, "results", "clean_sample.json"),
                           encoding="utf-8"))["clean_repos"]
    meta = json.load(open(os.path.join(DATA, "repos_meta.json"), encoding="utf-8"))

    sh = {r["repo"]: r for r in json.load(
        open(latest("skills_sh_search_*.json"), encoding="utf-8"))["rows"]}
    ch = {r["repo"]: r for r in json.load(
        open(latest("clawhub_search_*.json"), encoding="utf-8"))["rows"]}

    rows = []
    for k in clean:
        m = meta.get(k) or {}
        s = sh.get(k) or {}
        c = ch.get(k) or {}
        rows.append({
            "repo": k,
            "stars": int(m.get("stars") or 0),
            "forks": int(m.get("forks") or 0),
            "sh_hits": int(s.get("n_hits") or 0),
            "installs": int(s.get("total_installs") or 0),
            "ch_hits": int(c.get("n_hits") or 0),
            "downloads": int(c.get("total_downloads") or 0),
        })

    n = len(rows)
    hit_sh = [r for r in rows if r["sh_hits"] > 0]
    hit_ch = [r for r in rows if r["ch_hits"] > 0]
    hit_either = [r for r in rows if r["sh_hits"] > 0 or r["ch_hits"] > 0]
    hit_both = [r for r in rows if r["sh_hits"] > 0 and r["ch_hits"] > 0]

    def spear(a, b, xs, ys):
        """log1p-Spearman（两侧都取 log1p 以压尾部）。"""
        if len(xs) < 5:
            return None
        rho, p = st.spearmanr(np.log1p(xs), np.log1p(ys))
        return {"rho": float(rho), "p": float(p), "n": len(xs)}

    same = lambda key: [r for r in rows if r[key] > 0]
    inst = same("installs")
    cons = same("downloads")

    consistency = {
        "installs_x_stars": spear("i", "s", [r["installs"] for r in inst],
                                  [r["stars"] for r in inst]),
        "installs_x_forks": spear("i", "f", [r["installs"] for r in inst],
                                  [r["forks"] for r in inst]),
        "downloads_x_stars": spear("d", "s", [r["downloads"] for r in cons],
                                   [r["stars"] for r in cons]),
        "downloads_x_forks": spear("d", "f", [r["downloads"] for r in cons],
                                   [r["forks"] for r in cons]),
        "installs_x_forks_all": spear("i", "fa", [r["installs"] for r in rows],
                                      [r["forks"] for r in rows]),
    }

    # 背离：安装数分位高、分叉分位低（市场采纳超前于 fork 图）
    with_inst = [r for r in rows if r["installs"] > 0]
    fork_sorted = np.sort([r["forks"] for r in rows])
    inst_sorted = np.sort([r["installs"] for r in with_inst])
    divergent = []
    for r in with_inst:
        pf = float(np.searchsorted(fork_sorted, r["forks"], side="right") / n)
        pi = float(np.searchsorted(inst_sorted, r["installs"], side="right")
                   / len(with_inst))
        r["pct_forks"], r["pct_installs"] = pf, pi
        if pi - pf >= 0.30:
            divergent.append(r)
    divergent.sort(key=lambda r: r["pct_installs"] - r["pct_forks"], reverse=True)

    out = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "n_clean": n,
        "coverage": {
            "skills_sh": {"hit": len(hit_sh), "share": len(hit_sh) / n},
            "clawhub": {"hit": len(hit_ch), "share": len(hit_ch) / n},
            "either": {"hit": len(hit_either), "share": len(hit_either) / n},
            "both": {"hit": len(hit_both), "share": len(hit_both) / n},
        },
        "installs": dist([r["installs"] for r in rows]),
        "downloads": dist([r["downloads"] for r in rows]),
        "consistency": consistency,
        "divergent_install_over_fork": [
            {k: r[k] for k in ("repo", "installs", "forks", "stars",
                               "pct_installs", "pct_forks")}
            for r in divergent[:15]],
        "note": "installs/downloads 为抓取快照（2026-10-11）的累计值，"
                "站点统计口径（去重、时间窗）由各站自行定义，故只作第二信号的"
                "方向性佐证，不并入正文主测量。",
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("=" * 78)
    print("市场侧第二采纳信号（skills.sh / ClawHub）")
    print("=" * 78)
    print(f"  覆盖: skills.sh {len(hit_sh)}/{n} ({len(hit_sh)/n:.0%})  "
          f"ClawHub {len(hit_ch)}/{n} ({len(hit_ch)/n:.0%})  "
          f"任一站 {len(hit_either)/n:.0%}")
    i0 = out["installs"]
    print(f"  installs: 中位 {i0['median']:.0f}  p90 {i0['p90']:.0f}  "
          f"总量 {i0['sum']:,.0f}  命中站内非零 {1 - i0['share_of_zero']:.0%}")
    for key, v in consistency.items():
        if v:
            print(f"  {key:<22} ρ={v['rho']:+.3f}  p={v['p']:.4f}  n={v['n']}")
    print(f"  安装高·分叉低（分位差≥0.30）: {len(divergent)} 个，头部：")
    for r in divergent[:5]:
        print(f"    {r['repo']}: installs={r['installs']:,}  "
              f"forks={r['forks']:,}  (pct {r['pct_installs']:.2f} vs {r['pct_forks']:.2f})")
    print(f"\n  产出 -> {OUT}")
    print("=" * 78)


if __name__ == "__main__":
    main()
