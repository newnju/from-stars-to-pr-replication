# -*- coding: utf-8 -*-
"""patch_bimodal.py — 给块 41 补双峰分布说明（2026-10-29）"""
import json

P = r"E:\Skill扩散论文_可复现项目\paper_figs\docx_build\content2.json"
d = json.load(open(P, encoding="utf-8-sig"))
x = d["blocks"][41]["x"]
x = x.replace("不 能排除", "不能排除")
old = "转化率在各父仓规模层稳定于 6.5%—7.5%，不随父仓热度上升；"
new = ("转化率在各父仓规模层均值稳定于 6.5%—7.5%，不随父仓热度上升"
       "（层内高度异质、呈双峰：父仓中位数仅 3.95%，个别同步流水线仓达 40% 以上，"
       "而十万 fork 量级聚合仓低于 0.1%——回流集中于少数自动化管道，"
       "与其“深思熟虑的贡献承诺”语义恰相反）；")
if old in x:
    d["blocks"][41]["x"] = x.replace(old, new)
    print("patched")
else:
    print("anchor not found; block41 head:", x[:120])
print(json.dumps(d, ensure_ascii=False, indent=1))
