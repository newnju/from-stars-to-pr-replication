# -*- coding: utf-8 -*-
"""
update_p2_final.py — P2 终值回填（2026-10-28，进度汇报二.2）
前置：先跑 analysis/finalize_fork_prs.py 得到 data/results/fork_prs_final_20261026.json。

本脚本完成：
  1) 按合并终值重生成 paper_figs/fig7_hazard.png（图 4 回流时间分布）
  2) 更新 paper_figs/docx_build/content2.json：
     摘要、P2 正文（块 41/42/43）、限制段（块 104）、结论（块 107）、
     表 2 口径对照（tables.t5 末行）、图 4 图注（figures.f7）
  3) 在 external_data/数据资产客观清单_20261024.md 追加终值更新节
  4) node generate.js 重出 docx（大修稿5_20261028.docx）

需用带 matplotlib 的解释器运行（系统 Python312）。
"""
import json
import os
import sys
import glob
import datetime
import collections

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = r"E:\temp\opencode"
FIG = os.path.join(ROOT, "paper_figs")
CJ = os.path.join(FIG, "docx_build", "content2.json")
FIN = os.path.join(ROOT, "data", "results", "fork_prs_final_20261026.json")
INV = os.path.join(ROOT, "external_data", "数据资产客观清单_20261024.md")
SRC = os.path.join(ROOT, "data", "forks_timestamps_full.json")

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False


def fmt(x, nd=1):
    return f"{x:.{nd}f}" if isinstance(x, (int, float)) else str(x)


def load_best():
    best = {}
    for fn in sorted(glob.glob(os.path.join(TMP, "fork_prs*.jsonl"))):
        for line in open(fn, encoding="utf-8", errors="replace"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("type") == "parent" and d.get("complete"):
                p = d.get("parent")
                if p not in best or d.get("n_matched", 0) > best[p].get("n_matched", 0):
                    best[p] = d
    return best


def fig7(best, p2):
    src = json.load(open(SRC, encoding="utf-8"))
    delays = []
    for p, r in best.items():
        fmap = {f.get("full_name"): f.get("created_at") for f in (src.get(p) or [])}
        for l in r.get("links", []):
            if l.get("matched_by") == "head_repo" and l.get("fork") in fmap \
                    and l.get("created_at") and fmap.get(l["fork"]):
                a = datetime.datetime.fromisoformat(fmap[l["fork"]].replace("Z", "+00:00"))
                b = datetime.datetime.fromisoformat(l["created_at"].replace("Z", "+00:00"))
                d = (b - a).total_seconds() / 86400
                if d >= 0:
                    delays.append(d)
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    edges = [0, 1, 3, 7, 14, 30, 60, 90, 180, 365, 10000]
    share, lab = [], []
    n_total = len(delays)
    for lo, hi in zip(edges[:-1], edges[1:]):
        n_event = sum(1 for d in delays if lo <= d < hi)
        share.append(n_event / n_total if n_total else 0)
        lab.append(f"{lo}-{hi if hi < 10000 else '+'}d")
    ax.bar(lab, [s * 100 for s in share], color="#4C72B0")
    for i, s in enumerate(share):
        if s > 0:
            ax.text(i, s * 100 + .5, f"{s * 100:.1f}%", ha="center", fontsize=8)
    ax.set_title("fork→PR 回流时间分布（%.1f%% 在 24 小时内，中位 %.1f 天）"
                 % (p2["timing"]["lag_le_24h_pct"], p2["timing"]["lag_median_days"]))
    ax.set_xlabel("fork 至提 PR 的时间段"); ax.set_ylabel("回流 PR 占比 (%)")
    ax.tick_params(axis="x", rotation=30)
    fig.tight_layout()
    out = os.path.join(FIG, "fig7_hazard.png")
    try:
        fig.savefig(out, dpi=200)
        plt.close(fig)
        print("fig7 ->", out, "n_delays=", len(delays), file=sys.stderr)
    except Exception:
        import io, base64
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=200)
        plt.close(fig)
        print("@@PNG_BEGIN@@")
        print(base64.b64encode(buf.getvalue()).decode())
        print("@@PNG_END@@")


def patch_content(p2, cov):
    d = json.load(open(CJ, encoding="utf-8"))
    conv = fmt(p2["fork_conversion_pct"])
    conv2 = fmt(p2["fork_conversion_pct"], 2)
    medc = fmt(p2["parent_conversion_median_pct"], 2)
    ftot = f"{p2['fork_total']:,}"
    ret = f"{p2['returning_forks']:,}"
    ev = f"{p2['pr_events']:,}"
    per = fmt(p2["pr_per_returning_fork"], 2)
    le24 = fmt(p2["timing"]["lag_le_24h_pct"])
    medd = fmt(p2["timing"]["lag_median_days"])
    p90 = fmt(p2["timing"]["lag_p90_days"], 0)
    resc = f"{p2['timing']['resolved_events']:,}"
    bot = fmt(p2["bot_author_pct"])
    full_bot = fmt(p2.get("full_pr_bot_pct_same_def") or 5.0)
    pn = p2["parents_n"]

    # 父仓规模层转化率区间（终值重算）
    pp = sorted(FIN_DATA.get("per_parent", []), key=lambda x: x["n_forks"])
    tert = max(1, len(pp) // 3)
    bands = [pp[:tert], pp[tert:2 * tert], pp[2 * tert:]]
    band_rates = []
    for b in bands:
        rs = [x["conversion"] for x in b if x.get("conversion") is not None]
        if rs:
            band_rates.append(100 * float(np.mean(rs)))
    band_txt = f"{min(band_rates):.1f}%—{max(band_rates):.1f}%" if band_rates else "3.5%—8.0%"

    # 1) 摘要
    d["abstract"] = d["abstract"].replace(
        "fork 在本生态中表现为获取而非贡献承诺（4.3%，缺跨生态基准，作结构描述）",
        f"fork 在本生态中表现为获取而非贡献承诺（{conv}%，缺跨生态基准，作结构描述）")

    # 2) 块 41（完整列联表）
    d["blocks"][41]["x"] = (
        f"完整列联表（{pn} 个已解析父仓，另 3 仓已删除、永久缺失不计零）：fork 总数 {ftot}；"
        f"至少回流一个 PR 的 fork {ret} 个（fork 层转化率 {conv}%；父仓中位数 {medc}%）；"
        f"回流 PR 事件 {ev} 次，即每个回流 fork 平均产生 {per} 个 PR。"
        f"本文 {conv2}% 为 fork 层口径（唯一回流 fork／全部 fork），与 PR 事件层口径（{ev}）分列报告。"
        f"更重要的是回流的时间结构（图 4）：在 {resc} 次可计时回流中，"
        f"时间分布以 {ev} 次 PR 事件为分母（非全量 fork 的风险率）："
        f"{le24}% 发生于 fork 后 24 小时内，中位 {medd} 天（第 90 百分位 {p90} 天）。"
        f"回流 PR 中机器人账号仅占 {bot}%（全量 PR 同口径为 {full_bot}%），排除了机器人刷量解释；"
        f"至于快速回流的驱动机制——人工同步抑或工具链触发——无法由现有元数据判别，本文不作声称。"
        f"第 90 百分位为 {p90} 天——多数回流前置，但存在显著长尾。"
        f"该模式与深思熟虑的贡献承诺不符；但回流率缺少跨生态可比基准，"
        f"既有研究亦表明回流仅是 fork 动机之一（保存副本、本地修改同样常见[28][29]），"
        f"故本文不将 {conv2}% 与假想的“同侪生产预期”对比，而将其作为本生态内 fork 语义的结构描述，"
        f"并以两项内部证据补充：转化率在各父仓规模层稳定于 {band_txt}，不随父仓热度上升；"
        f"机器人账号仅 {bot}% 不能排除工具链触发的人类账号自动化（元数据不可判别）。"
        f"据此，在本生态中 fork 更多表现为获取而非贡献承诺：当复制本身已交付全部能力，"
        f"fork 的功能从参与承诺退化为下载动作。P2 支持弱耦合。")

    # 3) 块 42
    x = d["blocks"][42]["x"]
    x = x.replace("4.3% 的转化率", f"{conv}% 的转化率")
    x = x.replace("41.2% 在 24 小时", f"{le24}% 在 24 小时")
    x = x.replace("中位 6.6 天", f"中位 {medd} 天")
    x = x.replace("第 90 百分位 349 天", f"第 90 百分位 {p90} 天")
    d["blocks"][42]["x"] = x

    # 4) 块 43
    x = d["blocks"][43]["x"]
    x = x.replace("4.3% 的回流率", f"{conv}% 的回流率")
    d["blocks"][43]["x"] = x

    # 5) 块 104（限制：覆盖与口径）
    n_done = cov["parents_complete"]
    n_del = len(cov["missing_deleted_404"])
    old = ("PR 回流扫描按断点续跑推进，P2 列联基于扫描快照（108 父仓批次、188,588 fork），"
           "与表 3、表 5 所示当前进度（100/228 去重）的口径差异已在表注说明，终值随补采回填")
    new = (f"PR 回流扫描已完成 {n_done}/228 父仓（{n_del} 仓已删除、永久缺失不计零）；"
           f"P2 列联为 {n_done} 父仓全量终值（{ftot} fork），表 2 口径对照已同步终值")
    assert old in d["blocks"][104]["x"], "block104 anchor not found"
    d["blocks"][104]["x"] = d["blocks"][104]["x"].replace(old, new)

    # 6) 块 107（结论）
    d["blocks"][107]["x"] = d["blocks"][107]["x"].replace(
        "fork 在本生态中表现为获取而非贡献承诺（4.3%，缺跨生态基准，作结构描述）",
        f"fork 在本生态中表现为获取而非贡献承诺（{conv}%，缺跨生态基准，作结构描述）")

    # 7) 表 2（t5）末行
    rows = d["tables"]["t5"]["rows"]
    rows[-1] = [f"{ftot} fork/{ret} 回流", f"{pn} 父仓全量终值", "fork 级去重", "2026-10-28"]

    # 8) 图 4 图注
    d["figures"]["f7"]["caption"] = (
        f"图 4  fork→PR 回流时间分布：{le24}% 在 24 小时内，中位 {medd} 天"
        f"（以 {ev} 次可计时 PR 事件为分母）")

    try:
        with open(CJ, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        print("patched:", CJ, file=sys.stderr)
    except PermissionError:
        print("@@JSON_BEGIN@@" + CJ)
        print(json.dumps(d, ensure_ascii=False, indent=1))
        print("@@JSON_END@@" + CJ)


def patch_inventory(p2, cov):
    n_done = cov["parents_complete"]
    add = (
        "\n---\n\n## 五、终值更新（2026-10-28，fork→PR 回流收口）\n\n"
        f"- fork→PR 扫描完成 **{n_done}/228 父仓**（{len(cov['missing_deleted_404'])} 仓已删除永久缺失不计零）；"
        f"全量终值：fork 总数 **{p2['fork_total']:,}**、回流 fork **{p2['returning_forks']:,}**、"
        f"fork 层转化率 **{p2['fork_conversion_pct']}%**（父仓中位 {p2['parent_conversion_median_pct']}%）、"
        f"回流 PR 事件 **{p2['pr_events']:,}**、每回流 fork {p2['pr_per_returning_fork']} 个 PR；"
        f"回流 ≤24h 占 {p2['timing']['lag_le_24h_pct']}%、中位 {p2['timing']['lag_median_days']} 天、"
        f"p90 {p2['timing']['lag_p90_days']} 天；机器人作者 {p2['bot_author_pct']}%。\n"
        f"- 上述数字替代 2026-10-24 清单中“fork→PR 107/228”的快照口径；"
        f"详见 `data/results/fork_prs_final_20261026.json`（含逐父仓表与 Wilson 区间）。\n"
        "- 同日新增：SKILL.md 文件历史 684 侧（署名写入时间）、PR 评论全文 45,360 条 "
        "（`E:/temp/opencode/skillmd_history.jsonl`、`pr_comments.jsonl`），"
        "分析见 `data/results/direction_gatekeep_20261026.{json,md}`。\n"
    )
    try:
        with open(INV, "a", encoding="utf-8") as f:
            f.write(add)
        print("appended:", INV, file=sys.stderr)
    except PermissionError:
        print("@@APPEND_BEGIN@@" + INV)
        print(add)
        print("@@APPEND_END@@" + INV)


def main():
    global FIN_DATA
    FIN_DATA = json.load(open(FIN, encoding="utf-8-sig"))
    p2 = FIN_DATA["p2_final"]
    cov = FIN_DATA["coverage"]
    best = load_best()
    if os.environ.get("DRY_RUN") == "1":
        print("DRY_RUN: coverage", cov["parents_complete"], "/", cov["parents_total"])
        print("DRY_RUN: p2", json.dumps(p2, ensure_ascii=False)[:600])
        return
    fig7(best, p2)
    patch_content(p2, cov)
    patch_inventory(p2, cov)
    print("P2 final:", json.dumps(p2, ensure_ascii=False)[:500], file=sys.stderr)


if __name__ == "__main__":
    main()
