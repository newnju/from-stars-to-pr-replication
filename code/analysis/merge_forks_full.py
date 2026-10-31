# -*- coding: utf-8 -*-
"""
merge_forks_full.py —— 把旁路文件合并进 forks_timestamps_full.json（终版收口）

输入：
  data/forks_timestamps_full.json                —— 现有合并文件（A1 段成果）
  external_data/_cache/gh_repos/forks/*.json     —— A2 段旁路文件（每仓库一个）

规则：旁路文件覆盖同键旧值（旁路是更新更全的采集），按 created_at 倒序。
注意：会话内python 无文件写权限，结果经 stdout 输出，由调用方重定向落盘。
"""
import glob
import json
import os
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = r"E:\Skill扩散论文_可复现项目"
DATA = os.path.join(ROOT, "data")
CACHE = os.path.join(ROOT, "external_data", "_cache")
TARGET = os.path.join(DATA, "forks_timestamps_full.json")
OUT = os.path.join(DATA, "forks_timestamps_full_new.json")


def load(p):
    with open(p, encoding="utf-8-sig") as f:
        return json.load(f)


def main():
    emit_json = "--stdout-json" in sys.argv

    def say(msg):
        # 统计信息一律走 stderr，保证 --stdout-json 时 stdout 只有 JSON
        try:
            sys.stderr.write(msg + "\n")
            sys.stderr.flush()
        except Exception:
            pass

    cur = {}
    if os.path.exists(TARGET):
        try:
            cur = load(TARGET)
        except Exception as e:
            say(f"  现有合并文件不可读（{type(e).__name__}），改为完全从旁路重建")
            cur = {}
    meta = load(os.path.join(DATA, "repos_meta.json"))

    added, replaced, stats = 0, 0, {}
    for p in sorted(glob.glob(os.path.join(CACHE, "gh_repos", "forks", "*.json"))):
        repo = os.path.basename(p)[:-5].replace("__", "/", 1)
        recs = load(p)
        if not isinstance(recs, list):
            continue
        if repo in cur and len(cur[repo]) >= len(recs):
            continue                      # 现有更全，不覆盖
        if repo in cur:
            replaced += 1
        else:
            added += 1
        recs.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        cur[repo] = recs
        m = int((meta.get(repo) or {}).get("forks") or 0)
        stats[repo] = {
            "records": len(recs),
            "meta_forks": m,
            "ratio": round(len(recs) / m, 4) if m else None,
        }

    say("=" * 70)
    say("forks_timestamps_full 合并")
    say("=" * 70)
    say(f"  仓库总数：{len(cur)}（新增 {added}，覆盖 {replaced}）")
    low = [(k, v) for k, v in stats.items()
           if v["ratio"] is not None and v["ratio"] < 0.9]
    say(f"  本轮纳入 {len(stats)} 仓库，其中低于元数据 90% 的：{len(low)}")
    for k, v in sorted(stats.items(), key=lambda x: -(x[1]["ratio"] or 0))[:8]:
        say(f"    {k:44s} {v['records']:>8,} / {v['meta_forks']:>8,}"
            f" = {v['ratio']:.1%}" if v["ratio"] else
            f"    {k:44s} {v['records']:>8,} / {v['meta_forks']:>8,}")
    total = sum(len(v) for v in cur.values() if isinstance(v, list))
    say(f"  总记录数：{total:,}")

    if emit_json:
        sys.stdout.write(json.dumps(cur, ensure_ascii=False))
        return

    try:
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False)
        os.replace(OUT, TARGET)
        print(f"\n  已写回 -> {TARGET}")
    except PermissionError:
        print("\n  注：会话内 python 无写权限，请用 --stdout-json + 重定向")


if __name__ == "__main__":
    main()