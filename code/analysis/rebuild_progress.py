# -*- coding: utf-8 -*-
"""从旁路文件重建 gh_api_progress.json（stdout 输出，由 PowerShell 重定向落盘）。

背景：进度文件在一次失败的 ConvertFrom-Json 后被写坏。它只是账本，
权威数据是 gh_repos/forks/ 下的旁路文件与最终合并文件。
"""
import datetime
import glob
import json
import os

CACHE = r"E:\Skill扩散论文_可复现项目\external_data\_cache"
meta = json.load(open(r"E:\Skill扩散论文_可复现项目\data\repos_meta.json",
                      encoding="utf-8"))
orig = json.load(open(r"E:\Skill扩散论文_可复现项目\data\forks_timestamps.json",
                      encoding="utf-8"))

forks_full = {}
# 2026-10-14：统一指向 star_history_ext.json。
# 旧的 star_history_ext_v2.json 与前者字节相同（sha256 前缀 1a61f15ade0b8979），
# 是修正"倒序/忽略 per_page"缺陷前的临时产物，已删除；此处若仍指向它，
# 删除后 star_ext 账本会被静默重建为空。
star_ext_path = os.path.join(r"E:\Skill扩散论文_可复现项目\data",
                            "star_history_ext.json")
star_ext = json.load(open(star_ext_path, encoding="utf-8")) \
    if os.path.exists(star_ext_path) else {}

for p in glob.glob(os.path.join(CACHE, "gh_repos", "forks", "*.json")):
    repo = os.path.basename(p)[:-5].replace("__", "/", 1)
    try:
        n = len(json.load(open(p, encoding="utf-8-sig")))
    except Exception:
        continue
    forks_full[repo] = {"done": True, "count": n,
                        "added": n - len(orig.get(repo) or [])}

for repo, weeks in star_ext.items():
    star_ext[repo] = {"done": True, "weeks": len(weeks)}

out = {
    "forks_full": forks_full,
    "star_ext": star_ext,
    "rebuilt_at": datetime.datetime.now().isoformat(timespec="seconds"),
    "note": "由 rebuild_progress.py 从旁路文件重建（原文件因一次失败的 "
            "JSON 解析被写坏；权威数据为 gh_repos/forks/ 与合并文件）",
}
print(json.dumps(out, ensure_ascii=False))