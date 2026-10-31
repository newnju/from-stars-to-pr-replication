# -*- coding: utf-8 -*-
"""
fork_full_theta.py —— 全量分叉补采后的首次分叉门槛点识别扩展

背景：正文口径二只对"元数据分叉总数≤500"的 95 个仓库作首次分叉门槛 θ(I) 点识别，
触顶仓库（108 个）只能给区间下界。`fetch_gh_api.py` 全量分页补采
（实测 /forks 无 500 硬上限）完成后，触顶仓库的真实首次分叉亦可点识别。

本脚本（独立于正文流水线，不改动任何既有结果）：
  1) 对补采完成（progress 标记 done）的干净样本仓库，取全量分叉列表的最早
     created_at 为真实首次分叉；
  2) 以 star_history.json 的累计星标曲线取该时点累计星标 = θ(I) 点估计；
  3) 三组对照：(a) 正文 n=95 完备记录子样本（v2_threshold.json 报告值）；
     (b) 全量数据下原触顶仓库的 θ；(c) 全量数据下全体可用仓库的 θ。

输入：data/forks_timestamps_full.json + data/results/gh_api_progress.json(在
      external_data/_cache/) + data/star_history.json + data/repos_meta.json
输出：data/results/fork_full_theta.json
"""
import datetime
import json
import os
import statistics
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
RES = os.path.join(DATA, "results")
CACHE = os.path.join(ROOT, "external_data", "_cache")
OUT = os.path.join(RES, "fork_full_theta.json")


def load(p):
    return json.load(open(p, encoding="utf-8"))


def daily_cum(hist):
    """week 桶 → [(date, 累计星标)] 升序（与 v2_threshold 同构）。"""
    ds = []
    for w in hist:
        for i, c in enumerate(w["days"]):
            ds.append(((datetime.datetime.fromtimestamp(
                w["week"], datetime.timezone.utc)
                + datetime.timedelta(days=i)).date(), c))
    ds.sort()
    out, run = [], 0
    for d, c in ds:
        run += c
        out.append((d, run))
    return out


def cum_at(cum, d):
    """d 日（含）为止的累计星标；早于覆盖起点返回 None。"""
    v = None
    for dd, c in cum:
        if dd <= d:
            v = c
        else:
            break
    return v


def main():
    full_path = os.environ.get("FORKS_FULL_PATH") or os.path.join(
        DATA, "forks_timestamps_full.json")
    full = load(full_path)
    prog = load(os.path.join(CACHE, "gh_api_progress.json"))["forks_full"]
    sh = load(os.path.join(DATA, "star_history.json"))
    meta = load(os.path.join(DATA, "repos_meta.json"))
    clean = load(os.path.join(RES, "clean_sample.json"))["clean_repos"]
    th_pub = load(os.path.join(RES, "v2_threshold.json"))["first_fork_threshold"]

    truncated = {k for k in clean
                 if int((meta.get(k) or {}).get("forks") or 0) > 500}

    rows = []
    skipped = []
    orig = load(os.path.join(DATA, "forks_timestamps.json"))
    for k in clean:
        # 数据源优先级：全量补采版（done）> 原始文件（元数据 forks≤500 即本就完备）
        src, full_fetched = None, False
        if k in full and prog.get(k, {}).get("done"):
            src, full_fetched = full[k], True
        elif int((meta.get(k) or {}).get("forks") or 0) <= 500 and orig.get(k):
            src = orig[k]
        if src is None or k not in sh:
            skipped.append(k)
            continue
        recs = src
        if not recs:
            skipped.append(k)
            continue
        dates = [r["created_at"] for r in recs if r.get("created_at")]
        if not dates:
            skipped.append(k)
            continue
        first = min(dates)
        first_d = datetime.date.fromisoformat(first[:10])
        cum = daily_cum(sh[k])
        # 与 v2_panel 口径一致：取首分叉前一日末的累计存量（分叉决策时点
        # 可得的社会证明），不含分叉当日新增——首分叉常与创建日爆发重合，
        # 含当日会把门槛系统性抬高（实测中位 6→56 的差异即来源于此）
        v = cum_at(cum, first_d - datetime.timedelta(days=1))
        theta = 0 if v is None else v
        created = datetime.date.fromisoformat(meta[k]["created_at"][:10])
        rows.append({
            "repo": k,
            "truncated_before": k in truncated,
            "source_full_fetch": full_fetched,
            "n_full": len(recs),
            "meta_forks": int(meta[k].get("forks") or 0),
            "first_fork": first,
            "days_to_first_fork": (first_d - created).days,
            "theta": theta,
        })

    def summarize(rs):
        pts = [r["theta"] for r in rs if r["theta"] is not None]
        if not pts:
            return {"n": 0}
        return {
            "n": len(pts),
            "median": float(np.median(pts)),
            "mean": float(np.mean(pts)),
            "q25": float(np.percentile(pts, 25)),
            "q75": float(np.percentile(pts, 75)),
            "share_le_10": float(np.mean(np.array(pts) <= 10)),
            "share_zero": float(np.mean(np.array(pts) == 0)),
        }

    paper = {
        "n_point_identified": th_pub["n_point_identified"],
        "median_point": th_pub["median_point"],
        "share_le_10": th_pub["share_at_or_below_10"],
        "note": "正文口径二：仅元数据分叉总数≤500 的完备记录仓库可点识别。",
    }
    out = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "paper_estimate": paper,
        "full_data_all": summarize(rows),
        "full_data_previously_truncated": summarize(
            [r for r in rows if r["truncated_before"]]),
        "full_data_previously_complete": summarize(
            [r for r in rows if not r["truncated_before"]]),
        "days_to_first_fork_previously_truncated": (
            float(np.median([r["days_to_first_fork"]
                             for r in rows if r["truncated_before"]]))
            if any(r["truncated_before"] for r in rows) else None),
        "n_rows": len(rows),
        "n_skipped_not_yet_fetched": len(skipped),
        "skipped": skipped[:30],
        "note": "全量分叉列表的最早 created_at → 真实首次分叉；累计星标取"
                "star_history.json 同日值。原触顶仓库由此从区间下界升级为点识别。",
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=float)

    print("=" * 78)
    print("全量补采后的首次分叉门槛 θ(I) 点识别扩展")
    print("=" * 78)
    print(f"  正文（n={paper['n_point_identified']}，完备记录）: "
          f"中位 {paper['median_point']:,.0f}  ≤10星占比 {paper['share_le_10']*100:.1f}%")
    fa = out["full_data_all"]
    print(f"  全量数据全体（n={fa['n']}，覆盖 {len(rows)}/{len(clean)}）: "
          f"中位 {fa['median']:,.0f}  ≤10星占比 {fa['share_le_10']*100:.1f}%")
    ft = out["full_data_previously_truncated"]
    if ft["n"]:
        print(f"  全量数据·原触顶仓库（n={ft['n']}）: 中位 {ft['median']:,.0f}  "
              f"≤10星占比 {ft['share_le_10']*100:.1f}%  "
              f"首分叉距创建中位 {out['days_to_first_fork_previously_truncated']:.0f} 天")
    print(f"  未取到/未完成: {len(skipped)}")
    print(f"  产出 -> {OUT}")
    print("=" * 78)


if __name__ == "__main__":
    main()
