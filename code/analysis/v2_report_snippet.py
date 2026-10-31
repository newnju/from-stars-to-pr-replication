# -*- coding: utf-8 -*-
"""v2_report_snippet.py —— 供正文核对：按分位组的流量/存量结构。"""
import json, os
R = r"C:\Users\diamond\Downloads\Skill扩散论文_可复现项目\data\results"
h = json.load(open(os.path.join(R, "v2_hazard.json"), encoding="utf-8"))
c = h["conversion_by_bin"]
print("bin  mean_cum   stars   forks  per100   p_fork_day  p_star_day  ratio")
for b in map(str, range(10)):
    v = c[b]
    print("%-4s %10.0f %9.0f %7.0f %7.2f   %.4f      %.4f     %.3f" % (
        b, v["mean_cum_stars"], v["new_stars"], v["forks"], v["conv_per_100"],
        v["p_fork_day"], v["p_star_day"], v["prob_ratio"]))
print()
print("rate_model:", json.dumps(h["rate_model"], ensure_ascii=False, indent=1))
print("bin_joint_test:", h.get("bin_joint_test"))
print("risk_interaction:", json.dumps(h.get("risk_interaction"), ensure_ascii=False))
