# -*- coding: utf-8 -*-
"""v3_validate.py —— 风险分类器的人工复核效度检验

复核协议（可复现）：
  1. 从 203 个干净样本中随机抽取 120 个（种子 20261006）；
  2. 逐条读取 SKILL.md 全文与命中上下文，判定该技能是否**真实具备**
     ≥2 个敏感能力族（凭证与密钥／破坏性操作／网络出站／远程执行／文件系统写入）；
  3. 判定规则（统一适用）：
       · 计入：技能在其功能中实际执行或指示执行该能力（如真的调用 API、真的写文件、
         真的执行 shell、真的管理密钥）；
       · 不计入：禁令式提及（"never store credentials"）、安全审查语境
         （"检查代码中是否有 eval()"）、文档与外链（https://github.com/...）、
         数据结构名（registry 指状态机或标签表）、英文词巧合
         （"auto-curl" 命中 "curl "、"payload" 指消息体、"credentials" 指资历）、
         纯安装说明。
  4. 以人工判定为参照标准，计算三套自动口径的精确率、召回率、F1 与准确率。

局限：单一编码者，未计算编码者间信度；样本 120 个，指标的标准误见输出。

产出：data/results/v3_validation.json
"""
import json, os, math

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "data", "results")

# 人工复核判定：真实具备 ≥2 敏感能力族的仓库索引（0-based，对应 v3_audit_evidence.json 顺序）
MANUAL_TRUE = [
    2, 7, 8, 9, 10, 12, 13, 14, 16, 17, 19, 21, 22, 23, 27, 31, 33, 34, 35, 37,
    40, 43, 44, 46, 47, 49, 50, 53, 54, 57, 58, 61, 63, 65, 70, 71, 74, 80, 81,
    82, 83, 85, 88, 90, 91, 92, 93, 97, 101, 103, 104, 105, 110, 111,
]


def metrics(auto, manual):
    tp = sum(1 for a, m in zip(auto, manual) if a == 1 and m == 1)
    fp = sum(1 for a, m in zip(auto, manual) if a == 1 and m == 0)
    fn = sum(1 for a, m in zip(auto, manual) if a == 0 and m == 1)
    tn = sum(1 for a, m in zip(auto, manual) if a == 0 and m == 0)
    prec = tp / (tp + fp) if (tp + fp) else float("nan")
    rec = tp / (tp + fn) if (tp + fn) else float("nan")
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else float("nan")
    acc = (tp + tn) / len(auto)
    # 精确率与召回率的近似标准误（二项）
    se_prec = math.sqrt(prec * (1 - prec) / (tp + fp)) if (tp + fp) else float("nan")
    se_rec = math.sqrt(rec * (1 - rec) / (tp + fn)) if (tp + fn) else float("nan")
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": prec, "recall": rec,
            "f1": f1, "accuracy": acc, "se_precision": se_prec, "se_recall": se_rec,
            "n_pos_manual": tp + fn, "n_pos_auto": tp + fp}


def main():
    ev = json.load(open(os.path.join(RES, "v3_audit_evidence.json"), encoding="utf-8"))
    risk = json.load(open(os.path.join(RES, "v2_risk.json"), encoding="utf-8"))["repos"]

    manual = [1 if i in set(MANUAL_TRUE) else 0 for i in range(len(ev))]
    schemes = {
        "主口径：敏感能力触达≥2族": [r["auto_reach_binary"] for r in ev],
        "旧关键词口径（任一命中）": [int(risk.get(r["repo"], {}).get("any_old_kw") or 0) for r in ev],
        "话题／描述匹配口径": [int(risk.get(r["repo"], {}).get("core_kw_hit") or 0) for r in ev],
    }

    print("=" * 78)
    print("v3 风险分类器人工复核（n=%d，单一编码者）" % len(ev))
    print("=" * 78)
    print("人工判定为真实高触达者: %d (%.1f%%)" % (sum(manual), sum(manual) / len(manual) * 100))

    out = {"n_sample": len(ev), "manual_positive": int(sum(manual)),
           "manual_positive_share": float(sum(manual) / len(manual)),
           "protocol": "随机抽样120；统一判定规则见脚本docstring；单一编码者",
           "schemes": {}}
    for name, auto in schemes.items():
        m = metrics(auto, manual)
        out["schemes"][name] = m
        print("\n【%s】" % name)
        print("  混淆矩阵: TP=%d FP=%d FN=%d TN=%d" % (m["tp"], m["fp"], m["fn"], m["tn"]))
        print("  精确率=%.3f (SE %.3f)  召回率=%.3f (SE %.3f)  F1=%.3f  准确率=%.3f"
              % (m["precision"], m["se_precision"], m["recall"], m["se_recall"],
                 m["f1"], m["accuracy"]))
        print("  自动判为高触达 %d 个，其中 %d 个为误报（假阳性率 %.1f%%）"
              % (m["n_pos_auto"], m["fp"], m["fp"] / m["n_pos_auto"] * 100 if m["n_pos_auto"] else 0))

    # 逐条列出主口径的误报与漏报，供读者核验
    main_name = "主口径：敏感能力触达≥2族"
    auto_main = schemes[main_name]
    fp_list = [ev[i]["repo"] for i in range(len(ev)) if auto_main[i] == 1 and manual[i] == 0]
    fn_list = [ev[i]["repo"] for i in range(len(ev)) if auto_main[i] == 0 and manual[i] == 1]
    out["main_false_positives"] = fp_list
    out["main_false_negatives"] = fn_list
    print("\n【主口径误报 %d 例（自动判高、人工判否）】" % len(fp_list))
    for r in fp_list[:40]:
        print("   ·", r)
    print("\n【主口径漏报 %d 例（自动判低、人工判是）】" % len(fn_list))
    for r in fn_list:
        print("   ·", r)

    json.dump(out, open(os.path.join(RES, "v3_validation.json"), "w",
                        encoding="utf-8"), ensure_ascii=False, indent=2, default=float)
    print("\n  产出: data/results/v3_validation.json")
    print("=" * 78)


if __name__ == "__main__":
    main()
