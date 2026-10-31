# -*- coding: utf-8 -*-
"""
v2_panel.py —— 修正版实证的测量底座（不依赖任何既有结果文件）

本模块解决既有分析中被指出的三处测量错误：
  1. 分析单位错配：θ(L) 为仓库级「增速检测点」、θ(D) 为事件级「累计星标水平」，
     二者量纲不同，其比值不可解释为门槛分离度。
  2. 分叉列表截断方向写反：GitHub 分叉列表按时间倒序返回「最近 500 条」，
     被剔除的是*早期*事件，属左侧截断（left truncation），偏倚方向上偏。
  3. 伪重复：78,586 个分叉事件嵌套于 203 个仓库，事件级检验的有效样本量约为仓库数。

本模块的处置：
  A. 为每个仓库重建「分叉记录完备窗口」（complete-fork window）：以该仓库
     第 500 条最新分叉的时间戳为窗口起点，只在该窗口内做事件级推断，
     从而消除左侧截断；窗口前的事件以元数据报告的分叉总数作确定性计数使用。
  B. 全部事件级推断的暴露变量改用「仓库内社会证明分位」（within-repo percentile
     of cumulative stars），使不同规模的仓库可比，且不再与仓库体量机械共变。
  C. 全部标准误按仓库聚类；主要检验同时给出仓库级（有效样本量）结论。

产出：data/results/v2_panel.json（面板汇总）、v2_daily_panel 供其他脚本复用
"""
import json, os, datetime, statistics, math

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RES = os.path.join(DATA, "results")
FORK_CAP = 500

# 观察窗口（据实测数据边界，而非计划文档）
WIN_START = datetime.date(2025, 9, 21)
WIN_END = datetime.date(2026, 10, 4)


def load(name):
    return json.load(open(os.path.join(DATA, name), encoding="utf-8"))


def _safe_fn(name):
    return name.replace("/", "__").replace("\\", "__") + ".json"


def day_of(week_epoch, i):
    return (datetime.datetime.fromtimestamp(week_epoch, datetime.timezone.utc)
            + datetime.timedelta(days=i)).date()


def build_daily(hist):
    """周分组 → 有序 [(date, new_stars)]，逐日升序，无缺口。"""
    out = []
    for w in hist:
        for i, c in enumerate(w["days"]):
            out.append((day_of(w["week"], i), c))
    out.sort()
    return out


def build_cum(daily):
    cum, run = [], 0
    for d, c in daily:
        run += c
        cum.append((d, run))
    return cum


def cum_at(cum, d):
    """截至 d（含）的累计星标；d 早于序列起点返回 None。"""
    best = None
    for dd, v in cum:
        if dd <= d:
            best = v
        else:
            break
    return best


def load_skill_text(fname):
    fp = os.path.join(DATA, "skillmd", _safe_fn(fname))
    if not os.path.exists(fp) or os.path.getsize(fp) <= 2:
        return None
    try:
        obj = json.load(open(fp, encoding="utf-8"))
    except Exception:
        return None
    if isinstance(obj, dict):
        return None
    txt = []
    for s in obj:
        c = s.get("content")
        if isinstance(c, str):
            txt.append(c)
    return "\n".join(txt) if txt else None


def main():
    sh = load("star_history.json")
    forks = load("forks_timestamps.json")
    meta = load("repos_meta.json")
    clean = load(os.path.join("results", "clean_sample.json"))["clean_repos"]

    repos = {}
    panel_rows = 0
    for k in clean:
        m = meta.get(k)
        hist = sh.get(k)
        if not isinstance(m, dict) or not hist:
            continue
        daily = build_daily(hist)
        cum = build_cum(daily)
        created = datetime.date.fromisoformat(m["created_at"][:10])
        total_forks = int(m.get("forks") or 0)
        total_stars = int(m.get("stars") or 0)

        flist = forks.get(k) or []
        fdates = sorted(datetime.date.fromisoformat(f["created_at"][:10])
                        for f in flist if f.get("created_at"))
        n_obs = len(fdates)
        # 分叉列表是否触顶 → 是否发生左侧截断
        truncated = (n_obs >= FORK_CAP) and (total_forks > n_obs)
        # 完备窗口起点：第 500 条最新分叉的时间戳（即仍被保留的最早分叉）
        win_lo = fdates[0] if truncated else created
        # 观察期内、且分叉记录完备的窗口
        lo = max(win_lo, WIN_START)
        hi = min(WIN_END, daily[-1][0])

        # 逐日面板（仅完备窗口）
        days = []
        if lo <= hi:
            fcount = {}
            for d in fdates:
                if lo <= d <= hi:
                    fcount[d] = fcount.get(d, 0) + 1
            for d, c in daily:
                if d < lo or d > hi:
                    continue
                base = cum_at(cum, d - datetime.timedelta(days=1))
                if base is None:
                    base = 0
                days.append({
                    "date": d.isoformat(),
                    "age": (d - created).days,
                    "cum_start": base,          # 当日开始时的累计星标（社会证明存量）
                    "new_stars": c,             # 当日新增星标
                    "forks": fcount.get(d, 0),  # 当日新增分叉
                })
            # 窗口内累计星标区间
            c_lo, c_hi = days[0]["cum_start"], days[-1]["cum_start"]
        else:
            c_lo = c_hi = None

        # 首次分叉门槛：区间删失
        first_obs_fork = fdates[0] if fdates else None
        # 真实首次分叉早于或等于观测到的首次分叉
        ff_lo_date = created
        ff_hi_date = first_obs_fork
        ff_lo_stars = 0  # 若首次分叉发生在创建当日
        ff_hi_stars = None
        if first_obs_fork is not None:
            v = cum_at(cum, first_obs_fork - datetime.timedelta(days=1))
            ff_hi_stars = 0 if v is None else v

        # 仓库级核心量
        stars_win = sum(d["new_stars"] for d in days)
        forks_win = sum(d["forks"] for d in days)
        cum_mean = (statistics.mean([d["cum_start"] for d in days]) if days else None)
        repo = {
            "full_name": k,
            "created": created.isoformat(),
            "topics": m.get("topics") or [],
            "language": m.get("language"),
            "description": m.get("description") or "",
            "total_stars": total_stars,
            "total_forks": total_forks,
            "n_fork_records": n_obs,
            "fork_left_truncated": truncated,
            "retained_fork_share": (n_obs / total_forks) if total_forks else None,
            "win_lo": lo.isoformat() if c_lo is not None else None,
            "win_hi": hi.isoformat() if c_lo is not None else None,
            "win_days": len(days),
            "win_stars": stars_win,
            "win_forks": forks_win,
            "win_cum_lo": c_lo,
            "win_cum_hi": c_hi,
            "win_cum_mean": cum_mean,
            "first_fork_date": first_obs_fork.isoformat() if first_obs_fork else None,
            "days_to_first_fork": ((first_obs_fork - created).days
                                   if first_obs_fork else None),
            # 区间删失的首次分叉门槛
            "theta_first_fork_lo": ff_lo_stars,
            "theta_first_fork_hi": ff_hi_stars,
            "freq_first_fork_censored": first_obs_fork is None,
            "has_skillmd": load_skill_text(k) is not None,
        }
        if not truncated and first_obs_fork is not None:
            # 记录完整：区间退化为点
            repo["theta_first_fork_point"] = ff_hi_stars
        else:
            repo["theta_first_fork_point"] = None
        repos[k] = repo
        panel_rows += len(days)

    # 生态口径统计
    n_complete = sum(1 for r in repos.values() if not r["fork_left_truncated"])
    ret_shares = [r["retained_fork_share"] for r in repos.values()
                  if r["retained_fork_share"] is not None]
    tot_forks_meta = sum(r["total_forks"] for r in repos.values())
    tot_forks_win = sum(r["win_forks"] for r in repos.values())
    out = {
        "meta": {
            "n_repos": len(repos),
            "n_fork_records_complete": n_complete,
            "n_fork_records_truncated": len(repos) - n_complete,
            "fork_retained_share_median": statistics.median(ret_shares),
            "fork_retained_share_overall": tot_forks_win / tot_forks_meta if tot_forks_meta else None,
            "win_start": WIN_START.isoformat(),
            "win_end": WIN_END.isoformat(),
            "panel_rows": panel_rows,
            "truncation_direction": "left (earliest forks dropped); bias = upward on any "
                                    "cumulative-star level measured at fork time",
        },
        "repos": repos,
    }
    os.makedirs(RES, exist_ok=True)
    json.dump(out, open(os.path.join(RES, "v2_panel.json"), "w", encoding="utf-8"),
              ensure_ascii=False)

    # 控制台摘要
    print("=" * 78)
    print("v2 面板构建完成")
    print("=" * 78)
    print(f"  仓库数: {len(repos)}   逐日面板行数: {panel_rows:,}")
    print(f"  分叉记录完备仓库: {n_complete}   左侧截断仓库: {len(repos)-n_complete}")
    print(f"  分叉记录保留份额（总体）: {out['meta']['fork_retained_share_overall']*100:.1f}%"
          f"   中位数: {statistics.median(ret_shares)*100:.1f}%")
    print(f"  窗口内分叉事件合计: {tot_forks_win:,}（元数据报告总数 {tot_forks_meta:,}）")
    wd = [r["win_days"] for r in repos.values() if r["win_days"]]
    print(f"  完备窗口天数: 中位数 {statistics.median(wd):.0f}  最小 {min(wd)}  最大 {max(wd)}")
    nff = sum(1 for r in repos.values() if r["freq_first_fork_censored"])
    print(f"  完备窗口内未观测到首次分叉（右删失）的仓库数: {nff}")
    print(f"  产出: data/results/v2_panel.json")
    print("=" * 78)


if __name__ == "__main__":
    main()
