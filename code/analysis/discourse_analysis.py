# -*- coding: utf-8 -*-
"""话语层数据分析（analysis/fetch_discourse.py 的产物 data/gh_discourse.json）。

第一节先验证一个决定全部结论可否采信的口径问题：
  GitHub issues 端点默认按 number 升序返回，MAX_PAGES 封顶意味着
  触顶仓库贡献的是最旧的一段 —— 若属实，任何时间趋势都不可读。
第二节起才是实质分析。只读。
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = r"E:\Skill扩散论文_可复现项目"
SRC = os.path.join(ROOT, "data", "gh_discourse.json")
PER_PAGE, MAX_PAGES = 100, 10
LINE = "=" * 94

if not os.path.exists(SRC):
    # 合并文件只在采集收尾时写出；若被中断，直接读旁路缓存（内容等价）
    SIDE = os.path.join(ROOT, "external_data", "_cache", "gh_discourse")
    if not os.path.isdir(SIDE):
        print("尚未产出 %s，旁路缓存也不存在（采集未启动）" % SRC)
        sys.exit(0)
    print("合并文件不存在，改读旁路缓存 %s" % SIDE)
    repos = {}
    for kind in ("issues", "comments"):
        d = os.path.join(SIDE, kind)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".json"):
                continue
            repo = fn[:-5].replace("__", "/")
            o = json.load(open(os.path.join(d, fn), encoding="utf-8"))
            repos.setdefault(repo, {})[kind] = o["rows"]
            if o.get("truncated"):
                repos[repo][kind + "_truncated"] = True
    D = {"repos": repos, "source": "sidecar"}
else:
    D = json.load(open(SRC, encoding="utf-8"))
repos = D["repos"]
n_repo = len(repos)

print("载入 %d 个仓库的语料" % n_repo)
print()

# ---------------------------------------------------------------- 0 覆盖
iss_all = [(r, i) for r, v in repos.items() for i in v.get("issues", [])]
com_all = [(r, c) for r, v in repos.items() for c in v.get("comments", [])]
n_iss = len(iss_all)
n_pr = sum(1 for _, i in iss_all if i.get("is_pr"))
capped = [r for r, v in repos.items()
          if v.get("issues_truncated") or v.get("comments_truncated")]

print(LINE)
print("零、覆盖与截断")
print(LINE)
print("  仓库        %d" % n_repo)
print("  issue+PR    %s 条（其中 PR %s，纯 issue %s）"
      % ("{:,}".format(n_iss), "{:,}".format(n_pr), "{:,}".format(n_iss - n_pr)))
print("  commit 评论 %s 条" % "{:,}".format(len(com_all)))
print("  触顶仓库    %d 个（%.1f%%），其 issues 已被 MAX_PAGES=%d 截断"
      % (len(capped), 100 * len(capped) / max(1, n_repo), MAX_PAGES))

# ---------------------------------------------------------------- 1 截断方向
print()
print(LINE)
print("一、截断方向实证（决定时间趋势可否读）")
print(LINE)
capped_iss = [(r, i) for r, i in iss_all if r in set(capped)]
uncapped = [r for r in repos if r not in set(capped)]
print("  判据必须用**落盘原始顺序**：若先按 number 排序再测单调性，必然单调，等于没测。")
print("  本节 2026-10-17 就是这样错过一次，此处已改为直接读未排序的 rows。")
print()
print("  %-36s %11s %-11s %s" % ("触顶仓库", "首条->末条", "首条日期", "原始顺序是否递减"))
raw_desc_all = True
for r in sorted(capped)[:6]:
    its = repos[r]["issues"]          # 不排序
    nums = [x["number"] for x in its if x.get("number")]
    dates = [x["created_at"][:10] for x in its if x.get("created_at")]
    if len(nums) < 2:
        continue
    desc = all(nums[i] >= nums[i + 1] for i in range(len(nums) - 1))
    raw_desc_all &= desc
    print("  %-36s %5d->%-5d %-11s %s"
          % (r[:36], nums[0], nums[-1], dates[0] if dates else "-", desc))
print()
print("  触顶份数 %d，原始顺序全部递减 = %s" % (len(capped), raw_desc_all))

# 全体触顶仓库的日期上界分布
top_dates = Counter()
for r, i in capped_iss:
    if i.get("created_at"):
        top_dates[i["created_at"][:4]] += 1
print()
print("  触顶仓库贡献条目的年份分布（若集中在早年，说明截断偏向最旧一段）:")
for y in sorted(top_dates):
    print("      %s  %8s 条" % (y, "{:,}".format(top_dates[y])))

unc_dates = Counter()
for r, i in iss_all:
    if r in set(uncapped) and i.get("created_at"):
        unc_dates[i["created_at"][:4]] += 1
print("  未触顶仓库贡献条目的年份分布（对照）:")
for y in sorted(unc_dates):
    print("      %s  %8s 条" % (y, "{:,}".format(unc_dates[y])))

print()
if raw_desc_all and capped:
    print("  >> 结论（2026-10-17 实测）：issues 端点**倒序返回**，触顶仓库贡献的是其**最新的**")
    print("  >> %d 条，缺的是**早期历史** —— 与直觉相反。验证点：Observal/Observal 第 1 页首条"
          % (PER_PAGE * MAX_PAGES))
    print("  >> number=1897 恰等于其已采最大号，随后向后取到 888。")
    print("  >> 影响：触顶仓的**早期讨论不在语料内**；凡按仓库生命周期计算的比率"
          "（如\"存续期平均 issue 数\"）")
    print("  >> 须只用未触顶子集，或对触顶仓按 created 正序补采前段。按日历时间的近期分析不受影响。")
else:
    print("  >> 结论：当前无触顶仓库，截断方向问题在本语料不适用。")

# ---------------------------------------------------------------- 2 AI 提及
print()
print(LINE)
print("二、话语中的 AI 助手提及（与 §2.2.1 的尾注数据对照）")
print(LINE)
AI_RX = re.compile(r"\b(claude|chatgpt|openai|gpt-?\d|copilot|cursor|gemini|codex|"
                   r"anthropic|deepseek|qwen|kimi|mistral|grok|devin|"
                   r"ai assistant|llm|large language model)\b", re.I)
BOT_RX = re.compile(r"\[bot\]$|[-_]bot\b", re.I)
hit_ai = 0
ai_names = Counter()
by_type = Counter()
for r, i in iss_all:
    txt = "%s\n%s" % (i.get("title") or "", i.get("body") or "")
    by_type[i.get("user_type") or "unknown"] += 1
    m = AI_RX.findall(txt)
    if m:
        hit_ai += 1
        for x in m:
            ai_names[x.lower()] += 1
print("  条目总数 %s" % "{:,}".format(n_iss))
print("  正文或标题命中 AI 名称的 %s 条，占 %.2f%%"
      % ("{:,}".format(hit_ai), 100 * hit_ai / max(1, n_iss)))
print()
print("  命中最多的 AI 名称 top 15:")
for k, v in ai_names.most_common(15):
    print("      %-24s %7d" % (k[:24], v))
print()
print("  发布者类型分布:")
for k, v in by_type.most_common():
    print("      %-24s %8s   %5.2f%%" % (k[:24], "{:,}".format(v), 100 * v / max(1, n_iss)))

# ---------------------------------------------------------------- 2.5 issue/PR 分层
print()
print(LINE)
print("二·补、按 issue 与 PR 分层（PR 占 70.6%，合并计算会被模板正文主导）")
print(LINE)
def ai_rate(rows):
    n = len(rows)
    if not n:
        return 0, 0, 0.0
    h = sum(1 for i in rows
            if AI_RX.search("%s\n%s" % (i.get("title") or "", i.get("body") or "")))
    return n, h, 100.0 * h / n

iss_rows = [i for _, i in iss_all if not i.get("is_pr")]
pr_rows = [i for _, i in iss_all if i.get("is_pr")]
human_rows = [i for _, i in iss_all if i.get("user_type") == "User"]
bot_rows = [i for _, i in iss_all if i.get("user_type") == "Bot"]
rows_capped = [i for r, i in iss_all if r in set(capped)]
rows_uncap = [i for r, i in iss_all if r not in set(capped)]

print("  %-30s %8s %9s %8s" % ("切分", "条数", "命中 AI", "命中率"))
for nm, grp in (("纯 issue", iss_rows), ("PR", pr_rows),
                ("发布者=User", human_rows), ("发布者=Bot", bot_rows),
                ("触顶仓", rows_capped), ("未触顶仓", rows_uncap)):
    n, h, p = ai_rate(grp)
    print("  %-30s %8s %9s %7.2f%%" % (nm, "{:,}".format(n), "{:,}".format(h), p))

print()
print("  说明：PR 与 issue 的命中率若差距大，则 45.27% 这一总体值")
print("        不能作为\"讨论中 AI 出现频率\"的单一表述，须分层报告。")

# ---------------------------------------------------------------- 3 集中度
print()
print(LINE)
print("三、参与集中度与 issue/PR 结构")
print(LINE)
per_repo = Counter(r for r, _ in iss_all)
print("  每仓条目数：中位 %d，最大 %d，零条目的仓库 %d 个"
      % (sorted(per_repo.values())[len(per_repo) // 2] if per_repo else 0,
         max(per_repo.values()) if per_repo else 0,
         n_repo - len(per_repo)))
top5 = per_repo.most_common(5)
print("  条目最多的 5 个仓:")
for r, c in top5:
    print("      %-46s %7d" % (r[:46], c))
share = 100 * sum(c for _, c in top5) / max(1, n_iss)
print("  前 5 仓占全部条目的 %.1f%%" % share)
authors = Counter(i.get("user") for _, i in iss_all if i.get("user"))
print()
print("  发布者去重 %d 人；top 8:" % len(authors))
for k, v in authors.most_common(8):
    print("      %-30s %7d   %s" % (str(k)[:30], v, "（bot）" if k and BOT_RX.search(k) else ""))

print()
print(LINE)
print("四、必须随结论说明的限制")
print(LINE)
print("""  1. 触顶仓库贡献的是最旧一段（见第一节），跨时间趋势只能用未触顶子集。
  2. 语料只覆盖 203 个面板仓库，而 §2.7.1 已测出该面板 star 中位数落在
     总体第 99.55 百分位 —— 话语层同样不代表技能仓库总体。
  3. AI 名称命中是关键词法，无法区分「讨论 AI」与「用 AI 生成的正文被讨论」。
  4. body 截断至 8,000 字符，长讨论的后半段不在语料内。""")
