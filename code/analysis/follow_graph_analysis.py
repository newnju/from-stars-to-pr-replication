# -*- coding: utf-8 -*-
"""
follow_graph_analysis.py —— 关注图子图分析（analysis/fetch_follow_graph.py 的产物）

对应研究设计 §4.3 / RQ2「是否存在意见领袖」。

核心判据：761 个 out-degree>=20 的高分叉行动者，其 following 边有多少指向
**同样高分叉的行动者**（in-sample）？

  - 若 in-sample 占比远高于随机基线 -> 他们互相关注成团，属同侪聚类；
    「少数桥 -> 多数一次性采纳者」的两极流动须重新审视（聚类不等于意见领袖）。
  - 若绝大多数指向圈外 -> 支持"桥"的读法。

随机基线取 761 / GitHub 账号量级（数量级估算，非精确实测，文中会标注【估】）。
只读。
"""
import json
import os
import sys
from collections import Counter, defaultdict

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = r"E:\Skill扩散论文_可复现项目"
SRC = os.path.join(ROOT, "data", "follow_graph_subgraph.json")
LINE = "=" * 94

if not os.path.exists(SRC):
    print("尚未产出 %s" % SRC)
    sys.exit(0)

D = json.load(open(SRC, encoding="utf-8"))
A = D["actors"]
N = len(A)
sample = set(A)

print("载入 %d 个行动者（min_degree=%s，记录值校验=%s）"
      % (N, D.get("min_degree"), D.get("expect_n")))
print()

# ------------------------------------------------------------ 0 覆盖与截断
print(LINE)
print("零、覆盖与截断")
print(LINE)
n_fol = n_sta = 0
trunc_f = trunc_s = 0
for a, v in A.items():
    f = v.get("following", [])
    s = v.get("starred", [])
    n_fol += len(f)
    n_sta += len(s)
    if v.get("following_truncated"):
        trunc_f += 1
    if v.get("starred_truncated"):
        trunc_s += 1

print("  actor            %d" % N)
print("  following 边     %s   （人均 %.1f）" % ("{:,}".format(n_fol), n_fol / N))
print("  starred   边     %s   （人均 %.1f）" % ("{:,}".format(n_sta), n_sta / N))
print("  following 触顶   %d 个（%.1f%%，封顶 300）" % (trunc_f, 100 * trunc_f / N))
print("  starred   触顶   %d 个（%.1f%%，封顶 300）" % (trunc_s, 100 * trunc_s / N))
print()
print("  >> 触顶者的 following/starred 计数是**下界**，不是真值；")
print("  >> 下方所有边统计同样只在已采到的 300 条内成立。")

# ------------------------------------------------------------ 1 内部边
print()
print(LINE)
print("一、同侪聚类检验（in-sample following 边占比）")
print(LINE)
targets = Counter()
for a, v in A.items():
    for t in v.get("following", []):
        targets[t.lower()] += 1

distinct_targets = len(targets)
in_sample_hits = sum(c for t, c in targets.items() if t in {x.lower() for x in sample})
in_sample_targets = sum(1 for t in targets if t in {x.lower() for x in sample})

print("  去重后的 following 目标     %s 个" % "{:,}".format(distinct_targets))
print("  其中属于 761 样本的         %d 个（占样本的 %.1f%%）"
      % (in_sample_targets, 100 * in_sample_targets / N))
print("  in-sample 边数（按出现次数）%s / %s = **%.4f%%**"
      % ("{:,}".format(in_sample_hits), "{:,}".format(n_fol),
         100 * in_sample_hits / max(1, n_fol)))
print()
print("  随机基线【估】：若目标随机来自 GitHub 账号池，")
print("      样本占比 = 761 / 账号量级。GitHub 账号量级按 1e7–1e8 计【估】：")
print("        1e7 -> 0.00761%    1e8 -> 0.000761%")
if in_sample_hits:
    obs = 100 * in_sample_hits / max(1, n_fol)
    # 用 1e7 这一端（基线更大 -> 放大倍数更小 -> 更保守）
    base_conservative = 100 * N / 1e7
    print("      实测 %.4f%%  ->  相对 1e7 基线放大 **%.0f 倍**（保守端）；"
          % (obs, obs / base_conservative))
    print("               ->  相对 1e8 基线放大 %.0f 倍【同为估，仅数量级】"
          % (obs / (100 * N / 1e8)))
    print("      注意：放大倍数大**不等于**同侪聚类强 —— 绝对占比仍仅 %.2f%%，"
          % obs)
    print("      即 %.2f%% 的关注边指向圈外。基线效应与效应量是两件事。"
          % (100 - obs))

# ------------------------------------------------------------ 2 互相度
print()
print(LINE)
print("二、双向关系与样本内连通性")
print(LINE)
# 大小写归一必须贯穿始终：GitHub login 大小写不敏感但显示保留大小写，
# 样本键来自 fork owner（如 DotWasi、SyxonQ-Dev 为混合大小写）。
# 2026-10-17 实测：此前 `if b in sample` 用原始大小写比对已 lowercase 的目标，
# 会漏匹配并把互相关注数压成假 0 —— 故此处统一用 sample_lc / 小写键。
sample_lc = {x.lower() for x in sample}
folset = {}
for a, v in A.items():
    folset.setdefault(a.lower(), set()).update(x.lower() for x in v.get("following", []))

pairs = set()
for a, s in folset.items():
    for b in s:
        if b in sample_lc and a != b:
            pairs.add((a, b))
mutual = sum(1 for a, b in pairs if a in folset.get(b, set()))

n_out = sum(1 for a, s in folset.items() if s & sample_lc)

print("  样本内有向边（去重，大小写归一）  %d 条" % len(pairs))
print("  其中双向（互相关注）            %d 条（%.1f%%）" % (mutual, 100 * mutual / max(1, len(pairs))))
print("  有出边连到样本内的 actor         %d / %d（%.1f%%）" % (n_out, N, 100 * n_out / N))

# 交叉核对：与第一节的 in-sample 边数（按出现次数）应一致
edge_with_mult = sum(1 for a, s in folset.items() for b in s
                     if b in sample_lc and a != b)
print("  交叉核对（按出现次数计）        %d 条  -> 应等于第一节的 in-sample 边数"
      % edge_with_mult)

# 出度分布（样本内）
in_deg = Counter()
for a, s in folset.items():
    for b in s:
        if b in sample_lc and a != b:
            in_deg[b] += 1
if in_deg:
    vals = sorted(in_deg.values())
    print()
    print("  样本内 in-degree：有入边者 %d 个，最大 %d，中位 %d"
          % (len(in_deg), vals[-1], vals[len(vals) // 2]))
    top5 = in_deg.most_common(5)
    print("  样本内被关注最多的 5 个（候选意见领袖）：")
    tot_fol = {k.lower(): len(v.get("following", [])) for k, v in A.items()}
    for k, v in top5:
        print("      %-30s 样本内入度 %4d   该actor总出度 %s"
              % (k[:30], v, tot_fol.get(k, "?")))
else:
    print()
    print("  >> 样本内**没有任何**互相 following 关系。")

# ------------------------------------------------------------ 3 star 同质性
print()
print(LINE)
print("三、注意力同质性（starred 重叠）")
print(LINE)
star_targets = Counter()
for a, v in A.items():
    for t in v.get("starred", []):
        star_targets[t.lower()] += 1
ds = len(star_targets)
shared = sum(1 for t, c in star_targets.items() if c >= 2)
top_star = star_targets.most_common(8)
print("  去重 starred 仓库      %s 个" % "{:,}".format(ds))
print("  被 >=2 个样本 actor 星标 %s 个（%.2f%%）"
      % ("{:,}".format(shared), 100 * shared / max(1, ds)))
print("  样本共同星标最多的 8 个：")
for k, c in top_star:
    print("      %-52s %3d 个 actor" % (k[:52], c))

# ------------------------------------------------------------ 4 限制
print()
print(LINE)
print("四、必须随结论说明的限制")
print(LINE)
print("""  1. following/starred 各封顶 300 条，%d/%d（%.1f%%）的 actor 触顶，
     其边数是下界；截断只取回一端，可能系统性漏掉样本内边。
  2. following 与 starred 都是**当前快照**，无时序，无法区分
     「因同质而关注」与「因关注而同质」——本表只能支持关联，不能支持因果。
  3. 随机基线的账号量级为【估】量级值，放大倍数只可读作数量级。
  4. 子图只覆盖 out-degree>=20 的 761 人，占全部 258,558 个 actor 的
     0.29%%；面向总体的意见领袖推断须另行加权。
  5. GitHub 关注关系不含强度（无时间、无互动频次），SAOM 所需的
     滞后结构无法由本表单独构造。""" % (trunc_f, N, 100 * trunc_f / N))
