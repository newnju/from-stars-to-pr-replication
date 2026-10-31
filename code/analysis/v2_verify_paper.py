# -*- coding: utf-8 -*-
"""v2_verify_paper.py —— 独立复核：检查正文报告数值与结果文件是否一致。

只读取 data/ 与 data/results/，不修改任何文件。用于投稿前的数值自检。
"""
import json, os, re, datetime, statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RES = os.path.join(DATA, "results")
DOCX = os.path.join(ROOT, "Skill何以扩散：信息与工具同体条件下AI Agent技能的信号结构与采纳空转.docx")


def load(p):
    return json.load(open(p, encoding="utf-8"))


def docx_text():
    import zipfile
    from xml.etree import ElementTree as ET
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(DOCX) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    return "".join(t.text or "" for t in root.iter(ns + "t"))


def main():
    h = load(os.path.join(RES, "v2_hazard.json"))
    th = load(os.path.join(RES, "v2_threshold.json"))
    rk = load(os.path.join(RES, "v2_risk.json"))
    dy = load(os.path.join(RES, "v2_dynamics.json"))
    sg = load(os.path.join(RES, "v2_signal.json"))
    pn = load(os.path.join(RES, "v2_panel.json"))
    scm_doc = load(os.path.join(RES, "v2_scm_refit.json"))
    scm = scm_doc["scm"] if isinstance(scm_doc, dict) and "scm" in scm_doc else scm_doc
    rb = load(os.path.join(RES, "v2_robustness.json"))
    txt = docx_text()

    checks = []

    def chk(label, needle, ok=None):
        # 正文使用 Unicode 减号（U+2212），结果文件用 ASCII 连字符，先归一化
        norm = str.maketrans({"\u2212": "-", "\u2013": "-", "\u2014": "-"})
        present = str(needle).translate(norm) in txt.translate(norm)
        checks.append((label, str(needle), present))

    # 核心数值是否出现在正文
    conv = h["conversion_by_bin"]
    chk("转化率最低组", f"{conv['0']['conv_per_100']:.2f}")
    chk("转化率最高组", f"{conv['9']['conv_per_100']:.2f}")
    chk("转化率均值", "9.38")
    chk("似然比统计量", "510.8")
    chk("仓库—日面板规模", f"{h['design']['n_rows']:,}")
    chk("事件级模型系数", "+0.281")
    chk("仓库FE系数", "+0.128")
    chk("首次分叉门槛中位", str(th["first_fork_threshold"]["median_point"]))
    chk("完整分叉记录仓库数", str(th["first_fork_threshold"]["n_complete_fork_records"]))
    chk("≤10星标占比", f"{th['first_fork_threshold']['share_at_or_below_10']*100:.1f}")
    chk("旧口径同口径比值", f"{th['legacy_reproduction']['like_for_like_ratio']:.1f}倍")
    chk("左侧截断仓库数", str(pn["meta"]["n_fork_records_truncated"]))
    chk("分叉记录保留份额", f"{pn['meta']['fork_retained_share_overall']*100:.1f}")
    chk("allowed-tools声明率", f"{rk['disclosure_desc']['by_item']['allowed_tools']*100:.1f}")
    chk("五类披露齐备率", f"{rk['disclosure_desc']['share_all5']*100:.1f}")
    chk("旧口径高风险数", str(rk["classifiers"]["old_any_kw"]["n_high"]))
    chk("口径间kappa", f"{rk['agreement']['kappa_old_core']:.3f}")
    chk("可见性系数", f"{abs(sg['models']['B3_rate_full']['coef']['vis_resid']):.2f}")
    chk("可见性系数（年龄分层）", f"{abs(sg['robustness']['C3_agebin_vis']['coef']['vis_resid']):.2f}")
    chk("SCM冲击前RMSE", f"{scm['pre_rmse']:,.0f}")
    chk("SCM冲击后RMSE", f"{scm['post_rmse']:,.0f}")
    chk("风险分层旧口径IRR", f"{th['repo_level_models']['M1_old_kw']['irr']['old_kw']:.3f}")
    chk("风险分层触达口径IRR", f"{th['repo_level_models']['M3_reach2']['irr']['reach2']:.3f}")
    chk("风险分层话题口径IRR", f"{th['repo_level_models']['M5_core_kw']['irr']['core_kw']:.3f}")

    # 新增：等价检验、超级节点、混淆矩阵、窗口代表性
    eq = rb["equivalence"]["repo_fe"]
    chk("单侧95%上界", f"{eq['ci95_upper_factor']:.2f}倍")
    chk("MDE功效", f"{eq['mde_80power_factor']:.2f}倍")
    chk("朴素曲线最高最低比", f"{rb['equivalence']['naive_curve']['max_min_ratio']:.2f}")
    chk("TOST边际p值", f"{eq['tost']['2.0x/decade']['p_upper']:.3f}")
    sn = rb["supernode"]
    chk("剔除前1%系数", f"{sn['excl_top1pct']['beta']:.3f}")
    chk("剔除官方仓库系数", f"{sn['excl_official']['beta']:.3f}")
    cp = rb["risk_confusion"]["pairs"]
    chk("关键词与触达一致kappa", f"{cp['old_kw_vs_reach']['kappa']:.3f}")
    chk("话题口径嵌套双高", str(cp["old_kw_vs_core_topic"]["both_high"]))
    wr = rb["window"]
    chk("截断组窗口日中位", str(int(wr["trunc_win_days_median"])))
    chk("窗口起点星标相关", f"{wr['spearman_winlo_stars']['rho']:.3f}")

    # 第五轮新增：机制测量、滞后分析、推断加固、分类器效度
    try:
        mech = load(os.path.join(RES, "v3_mechanism.json"))
        inf = load(os.path.join(RES, "v3_inference.json"))
        val = load(os.path.join(RES, "v3_validation.json"))
        fm = mech["frontmatter"]
        chk("安全字段可得率", f"{fm['share_safety_any']*100:.1f}")
        chk("Level-1令牌中位", f"{fm['median_l1_tokens']:.0f}")
        chk("正文令牌中位", f"{fm['median_body_tokens']:,.0f}")
        chk("读取成本比", f"{fm['median_cost_ratio']:.0f}倍")
        chk("元数据字段中位", f"{fm['median_fields']:.0f}")
        chk("机制-安全字段系数p", f"{mech['models']['conv_safety']['p']['safety_any']:.2f}")
        chk("同日星标分叉相关", f"{mech['same_day_within_corr_median']:.3f}")
        chk("分叉→次日星标", f"+{mech['lag_models']['forks_t_to_stars_t+1']['forks_t']:.3f}")
        chk("过度离散", f"{inf['inference']['cross_repo']['overdispersion_pearson']:.2f}")
        chk("随机化推断p", f"{inf['inference']['cross_repo']['p_randomization']:.3f}")
        chk("类别+可见性系数", f"+{inf['category_models']['plus_vis']['beta']:.4f}")
        chk("样本最小星标", str(inf["left_truncation"]["min_in_sample"]))
        chk("未入样本最小星标", str(inf["left_truncation"]["min_candidate_out"]))
        chk("SESOI上界", f"{inf['sesoi']['upper_bound_factor_onesided']:.2f}倍")
        main_s = val["schemes"]["主口径：敏感能力触达≥2族"]
        chk("主口径精确率", f"{main_s['precision']:.3f}")
        chk("主口径召回率", f"{main_s['recall']:.3f}")
        chk("主口径F1", f"{main_s['f1']:.3f}")
        chk("人工判定高触达占比", f"{val['manual_positive_share']*100:.1f}")
        chk("话题口径召回率", f"{val['schemes']['话题／描述匹配口径']['recall']:.3f}")
    except Exception as e:
        print(f"  [警告] v3 结果文件读取失败: {e}")

    # 不应再出现的旧表述（以肯定语气出现才算问题）
    forbidden = [
        "2027年3月", "预期贡献", "预注册形式登记", "强有力地支持",
        "注意力门槛坍缩至近零", "每100次星标事件的转化率",
        "右侧截断构成", "回溯值为下界",
    ]
    print("=" * 74)
    print("正文数值一致性复核")
    print("=" * 74)
    bad = 0
    for label, val, ok in checks:
        flag = "OK " if ok else "缺失"
        if not ok:
            bad += 1
        print(f"  [{flag}] {label:<24} {val}")
    print()
    print("旧表述残留检查：")
    for f in forbidden:
        hit = f in txt
        if hit:
            bad += 1
        print(f"  [{'残留' if hit else 'OK '}] {f}")

    # 图表编号连续性：同时检查编号集合与「连续整数」条件
    tabs = sorted(set(int(m) for m in re.findall(r"表(\d+)", txt)))
    figs = sorted(set(int(m) for m in re.findall(r"图(\d+)", txt)))
    # 表格标题（形如「表7　…」）必须构成 1..N
    tab_titles = sorted(set(int(m) for m in re.findall(r"表(\d+)　", txt)))
    fig_titles = sorted(set(int(m) for m in re.findall(r"图(\d+)　", txt)))
    print(f"\n  表编号出现（含引用）：{tabs}")
    print(f"  表标题编号：{tab_titles}")
    print(f"  图标题编号：{fig_titles}")
    if tab_titles != list(range(1, len(tab_titles) + 1)):
        print("  [警告] 表标题编号不连续")
        bad += 1
    if fig_titles != list(range(1, len(fig_titles) + 1)):
        print("  [警告] 图标题编号不连续")
        bad += 1
    if not set(tabs) <= set(tab_titles):
        print(f"  [警告] 存在指向不存在表格的引用：{sorted(set(tabs) - set(tab_titles))}")
        bad += 1
    if not set(figs) <= set(fig_titles):
        print(f"  [警告] 存在指向不存在插图的引用：{sorted(set(figs) - set(fig_titles))}")
        bad += 1

    print(f"\n  文档字数（含标点）：{len(txt):,}")
    print(f"  问题数：{bad}")
    print("=" * 74)


if __name__ == "__main__":
    main()
