# -*- coding: utf-8 -*-
"""
fetch_qa.py —— 补采结果质量核验与星标延长覆盖对照

1) 分叉补采质量：对每个已采仓库，比较采得条数与元数据分叉总数，列出
   采得 < 元数据（改名/删除/翻页空洞）的仓库及其缺口比例——若缺口过大，
   该仓库的真实首次分叉可能晚于采得值（θ 点识别被高估的风险面）。
2) 星标延长覆盖：star_history_ext.json（341 仓库全史）与 star_history.json
   （正文所用窗口，起点 2025-09-21）的对照——延长了多少周、覆盖了多少额外
   星标事件、元数据星数与复算总量的差异。
输出：data/results/fetch_qa.json
"""
import datetime
import json
import os
import re
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

WIN_START = datetime.date(2025, 9, 21)


def load(p):
    # utf-8-sig：兼容 PowerShell 5.1 写出的带 BOM 文件（本轮 PROG 被 PS 改写）
    with open(p, encoding="utf-8-sig") as f:
        return json.load(f)


def main():
    emit_json = "--stdout-json" in sys.argv
    meta = load(os.path.join(DATA, "repos_meta.json"))
    prog = load(os.path.join(CACHE, "gh_api_progress.json"))
    pf = prog.get("forks_full", {})
    ps = prog.get("star_ext", {})
    forks_full = load(os.path.join(DATA, "forks_timestamps_full.json"))
    clean = load(os.path.join(RES, "clean_sample.json"))["clean_repos"]
    clean_set = set(clean)

    # ---------------- 1) 分叉补采质量 ----------------
    gaps = []
    errs = []
    n_done = 0
    for k, v in pf.items():
        if not v.get("done"):
            continue
        n_done += 1
        if v.get("error"):
            errs.append({"repo": k, "error": v["error"]})
            continue
        m = int((meta.get(k) or {}).get("forks") or 0)
        c = int(v.get("count") or 0)
        if m and c < m:
            gaps.append({
                "repo": k, "fetched": c, "meta": m,
                "gap_ratio": round(1 - c / m, 4),
                "in_clean_sample": k in clean_set,
                "side_file_ok": len(forks_full.get(k, [])) == c,
            })
    gaps.sort(key=lambda g: -g["gap_ratio"])

    # 采得条数与最终合并文件的一致性（合并文件 = 旁路 + 阶段末整写）
    mism = [k for k, v in pf.items()
            if v.get("done") and not v.get("error")
            and len(forks_full.get(k, [])) != int(v.get("count") or 0)]

    # ---------------- 2) 星标延长覆盖 ----------------
    star_ext = load(os.path.join(DATA, "star_history_ext.json"))
    star_orig = load(os.path.join(DATA, "star_history.json"))

    def total_stars(hist):
        return sum(int(c) for w in hist for c in w.get("days", []) if c)

    def earliest_week(hist):
        return min(w["week"] for w in hist) if hist else None

    rows = []
    for k, weeks in star_ext.items():
        te = total_stars(weeks)
        to = total_stars(star_orig.get(k, []))
        m = int((meta.get(k) or {}).get("stars") or 0)
        early_weeks = 0
        for w in weeks:
            d = datetime.datetime.fromtimestamp(
                w["week"], datetime.timezone.utc).date()
            if d < WIN_START:
                early_weeks += 1
        rows.append({
            "repo": k,
            "ext_weeks": len(weeks),
            "orig_weeks": len(star_orig.get(k, [])),
            "ext_stars_total": te,
            "orig_stars_total": to,
            "meta_stars": m,
            "weeks_before_orig_window": early_weeks,
            "ext_over_orig": round(te / to, 4) if to else None,
            "ext_below_meta": te < m,
            "earliest_week": (datetime.datetime.fromtimestamp(
                earliest_week(weeks), datetime.timezone.utc
            ).date().isoformat() if earliest_week(weeks) else None),
        })
    n_earlier = sum(1 for r in rows if r["weeks_before_orig_window"] > 0)
    ext_t = np.array([r["ext_stars_total"] for r in rows], dtype=float)
    ratio = np.array([r["ext_over_orig"] for r in rows
                      if r["ext_over_orig"] is not None], dtype=float)

    out = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "forks_quality": {
            "n_done": n_done,
            "n_errors": len(errs),
            "errors": errs,
            "n_fewer_than_meta": len(gaps),
            "n_fewer_among_clean": sum(1 for g in gaps if g["in_clean_sample"]),
            "worst_gaps": gaps[:20],
            "merged_file_mismatches": len(mism),
            "note": "缺口 <2% 属改名/删除的正常抖动；>5% 需警惕翻页空洞，"
                    "该仓库真实首次分叉可能晚于采得值。",
        },
        "star_extension": {
            "n_repos": len(rows),
            "n_with_earlier_history": n_earlier,
            "ext_stars_total": int(ext_t.sum()) if len(ext_t) else 0,
            "ext_over_orig_median": float(np.median(ratio)) if len(ratio) else None,
            "ext_below_meta_count": sum(1 for r in rows if r["ext_below_meta"]),
            "sample": sorted(rows, key=lambda r: -r["ext_stars_total"])[:10],
        },
    }
    if emit_json:
        # 会话内 python 无文件写权限（见 README 备注）：只输出 JSON，
        # 由 PowerShell 重定向落盘（python ... > data/results/fetch_qa.json）
        sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=2))
        return

    try:
        with open(os.path.join(RES, "fetch_qa.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    except PermissionError:
        print("\n  注：本会话内 python 无文件写权限，JSON 落盘请用 "
              "--stdout-json + PowerShell/cmd 重定向")

    fq = out["forks_quality"]
    se = out["star_extension"]
    print("=" * 78)
    print("补采质量核验")
    print("=" * 78)
    print(f"  已采仓库 {fq['n_done']}，接口错误 {fq['n_errors']}，"
          f"采得<元数据 {fq['n_fewer_than_meta']}（干净样本内 {fq['n_fewer_among_clean']}）")
    if fq["worst_gaps"]:
        print("  缺口最大的 8 个：")
        for g in fq["worst_gaps"][:8]:
            print(f"    {g['repo']}: {g['fetched']:,}/{g['meta']:,} "
                  f"缺口 {g['gap_ratio']:.1%}"
                  f"{' [干净样本]' if g['in_clean_sample'] else ''}")
    print(f"  合并文件与进度不一致: {fq['merged_file_mismatches']}")
    print(f"\n  星标延长: {se['n_repos']} 仓库，"
          f"{se['n_with_earlier_history']} 个有早于原窗口的星史，"
          f"总量 {se['ext_stars_total']:,}")
    print(f"  延长倍数（原窗口总量）: 中位 {se['ext_over_orig_median']:.2f}×；"
          f"复算星数低于元数据快照的仓库 {se['ext_below_meta_count']} 个")
    print(f"\n  产出 -> {os.path.join(RES, 'fetch_qa.json')}")
    print("=" * 78)


if __name__ == "__main__":
    main()