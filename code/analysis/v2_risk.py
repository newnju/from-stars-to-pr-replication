# -*- coding: utf-8 -*-
"""
v2_risk.py —— 风险属性的重新操作化与效度检验（替代关键词二分的单一口径）

既有做法的三处问题：
  1. 三套互不相同的风险口径（risk_strata.py 126/77；core.py 15/188；risk_classify.py 三档），
     论文只采用其中一套而未说明选择依据 → 研究者自由度。
  2. 关键词表含 decrypt / bypass / unlock / sudo / password / api_key，
     在正常开发技能中极为常见，测量的是「敏感词出现」而非「危害性」；
     实测高风险占比 62.1%，而外部审计的生态估计为 36.8%（Snyk，不同抽样框），
     缺口 25 个百分点即分类器过宽的直接证据。
  3. 以「任一关键词命中」作二分，未报告口径间一致性，也未报告剔除单一关键词的敏感性。

本模块的处置：
  A. 把「风险」拆成两个可分别测量的构念：
       敏感能力触达（capability reach）：技能调用凭证／破坏性／网络出站／
         远程执行／文件写入等能力的文本可观测程度（本容器不可审计真实行为）
       安全披露（disclosure）：是否声明权限范围、是否给出安全策略或沙箱说明
     二者不可混同：前者是风险暴露，后者是风险治理信号。
  B. 用分项计数与加权指数替代「任一命中」二分，并同时保留二分版本以对齐旧结果。
  C. 报告口径间一致性（Cohen's κ、Jaccard）、单关键词剔除敏感性、
     与「良性技术词」对照的误报地板，以及与外部审计估计的口径落差分析。

产出：data/results/v2_risk.json
"""
import json, os, re, itertools, statistics
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RES = os.path.join(DATA, "results")


def load(n):
    return json.load(open(os.path.join(DATA, n), encoding="utf-8"))


def _safe_fn(name):
    return name.replace("/", "__").replace("\\", "__") + ".json"


def read_skill(fname):
    fp = os.path.join(DATA, "skillmd", _safe_fn(fname))
    if not os.path.exists(fp) or os.path.getsize(fp) <= 2:
        return None
    try:
        obj = json.load(open(fp, encoding="utf-8"))
    except Exception:
        return None
    if isinstance(obj, dict) or not obj:
        return None
    return "\n".join(s.get("content") or "" for s in obj)


# ---------------- 关键词表（分类、可逐项审计） ----------------
FAMILIES = {
    "凭证与密钥": ["password", "passwd", "credential", "api_key", "api key", "apikey",
                   "access token", "secret key", "private key", "ssh key", "id_rsa",
                   ".env", "keychain", "cookie", "session token", "oauth"],
    "破坏性操作": ["rm -rf", "rm -fr", "drop table", "drop database", "truncate table",
                   "format c:", "mkfs", "dd if=", "shutil.rmtree"],
    "网络出站": ["curl ", "wget ", "requests.post", "fetch(", "http://", "https://",
                 "socket.", "netcat", "nc -", "webhook", "exfiltrat", "upload to"],
    "远程执行": ["reverse shell", "bind shell", "backdoor", "keylogger", "payload",
                 "meterpreter", "msfconsole", "powershell -enc", "eval(", "exec(",
                 "os.system", "subprocess"],
    "文件系统写入": ["chmod", "chown", "sudo ", "crontab", "launchctl", "systemd",
                     "registry", "hkml", "reg add", "write file", "overwrite"],
}
# 良性技术词对照（用于估计误报地板）
BENIGN = ["cache", "commit", "branch", "merge", "format", "token", "session", "shell",
          "network", "upload", "download", "request", "auth", "user"]

# 旧口径（risk_strata.py）：任一命中即高风险
OLD_HIGH = ["credential", "password", "api_key", "api key", "access token",
            "private key", "reverse shell", "backdoor", "keylogger", "exfiltrat",
            "rm -rf", "drop table", "drop database", "sudo ", "chmod 777",
            "session hijack", "phish", "decrypt", "bypass", "unlock"]
# 旧口径（core.py）：仅 topics 与 description
CORE_KW = ["security", "pen-test", "pentest", "exploit", "recon", "payload",
           "malware", "hack", "offensive", "vuln", "cve", "osint", "credential",
           "admin", "sudo", "shell", "network"]

DISCLOSURE = {
    "allowed_tools": [r"allowed[-_]tools", r"allowed[\s-]?commands"],
    "permission_scope": [r"permission", r"scope", r"最小权限", r"least privilege"],
    "security_note": [r"security", r"安全", r"threat model", r"risk"],
    "sandbox": [r"sandbox", r"沙箱", r"isolat", r"container"],
    "audit_badge": [r"audit", r"审计", r"verified", r"signed", r"signature", r"sbom"],
}


def counts(text, kws):
    return {k: text.count(k) for k in kws}


def main():
    meta = load("repos_meta.json")
    clean = load(os.path.join("results", "clean_sample.json"))["clean_repos"]

    recs = {}
    for k in clean:
        m = meta.get(k) or {}
        txt = read_skill(k)
        low = (txt or "").lower()
        rec = {"has_skillmd": txt is not None}
        if txt is None:
            rec.update({"reach_index": None, "reach_binary": None,
                        "families": None, "family_hits": None, "disclosure": None,
                        "disclosure_index": None, "any_old_kw": None, "n_old_kw": None,
                        "core_kw_hit": None, "text_len": 0, "n_code_blocks": 0,
                        "benign_hits": 0})
            recs[k] = rec
            continue
        fam_counts, fam_hits = {}, {}
        for fam, kws in FAMILIES.items():
            c = counts(low, kws)
            fam_counts[fam] = int(sum(c.values()))
            fam_hits[fam] = int(sum(1 for v in c.values() if v > 0))
        # 加权触达指数：五个能力族各占 1 分（族内饱和），另加族内强度对数项
        reach = sum(1 for v in fam_hits.values() if v > 0)
        strength = sum(np.log1p(v) for v in fam_counts.values())
        rec["families"] = fam_counts
        rec["family_hits"] = fam_hits
        rec["reach_index"] = float(reach + 0.2 * strength)
        rec["reach_binary"] = int(reach >= 2)   # 至少两个能力族被触达
        disc = {}
        for name, pats in DISCLOSURE.items():
            disc[name] = int(any(re.search(p, low) for p in pats))
        rec["disclosure"] = disc
        rec["disclosure_index"] = float(sum(disc.values()))
        rec["any_old_kw"] = int(any(kw in low for kw in OLD_HIGH))
        rec["n_old_kw"] = int(sum(low.count(kw) for kw in OLD_HIGH))
        desc_topics = " ".join(m.get("topics") or []).lower() + " " + (m.get("description") or "").lower()
        rec["core_kw_hit"] = int(any(kw in desc_topics for kw in CORE_KW))
        rec["text_len"] = len(txt)
        rec["n_code_blocks"] = txt.count("```")
        # 良性词对照：估计「敏感词=风险」口径的误报地板
        rec["benign_sensitive_overlap"] = int(sum(
            1 for b in BENIGN if any(b in kw for kw in OLD_HIGH)))
        rec["benign_hits"] = int(sum(low.count(b) for b in BENIGN))
        recs[k] = rec

    def arr(field, cond=lambda r: True):
        return [r[field] for r in recs.values() if cond(r) and r[field] is not None]

    with_md = [k for k, r in recs.items() if r["has_skillmd"]]
    old_hi = [k for k, r in recs.items() if r["any_old_kw"] == 1]
    new_hi = [k for k, r in recs.items() if r["reach_binary"] == 1]
    core_hi = [k for k, r in recs.items() if r["core_kw_hit"] == 1]

    def jac(a, b):
        A, B = set(a), set(b)
        return len(A & B) / len(A | B) if (A | B) else None

    # Cohen's kappa（两两口径）
    def kappa(a, b):
        keys = sorted(set(recs))
        va = np.array([1 if k in set(a) else 0 for k in keys])
        vb = np.array([1 if k in set(b) else 0 for k in keys])
        po = (va == vb).mean()
        pe = ((va.mean() * vb.mean()) + ((1 - va.mean()) * (1 - vb.mean())))
        return (po - pe) / (1 - pe) if pe < 1 else None

    # 单关键词剔除敏感性（旧口径）
    drop_sens = {}
    for kw in OLD_HIGH:
        keep = [k for k, r in recs.items()
                if r["has_skillmd"] and any(x in (read_skill(k) or "").lower()
                                            for x in OLD_HIGH if x != kw)]
        drop_sens[kw] = len(keep)

    # 旧口径关键词在样本中的出现仓库数
    kw_prev = {}
    for kw in OLD_HIGH:
        kw_prev[kw] = sum(1 for k in with_md if kw in (read_skill(k) or "").lower())

    n_md = len(with_md)
    out = {
        "n_clean": len(recs),
        "n_with_skillmd": n_md,
        "n_without_skillmd": len(recs) - n_md,
        "classifiers": {
            "old_any_kw": {"n_high": len(old_hi),
                           "share_of_all": len(old_hi) / len(recs),
                           "share_of_with_md": len(old_hi) / n_md if n_md else None},
            "new_reach2": {"n_high": len(new_hi),
                           "share_of_all": len(new_hi) / len(recs),
                           "share_of_with_md": len(new_hi) / n_md if n_md else None},
            "core_desc_kw": {"n_high": len(core_hi),
                             "share_of_all": len(core_hi) / len(recs)},
        },
        "agreement": {
            "jaccard_old_new": jac(old_hi, new_hi),
            "jaccard_old_core": jac(old_hi, core_hi),
            "jaccard_new_core": jac(new_hi, core_hi),
            "kappa_old_new": kappa(old_hi, new_hi),
            "kappa_old_core": kappa(old_hi, core_hi),
            "kappa_new_core": kappa(new_hi, core_hi),
        },
        "keyword_prevalence_old": kw_prev,
        "drop_one_sensitivity_old": drop_sens,
        "reach_index_desc": {
            "median": statistics.median(arr("reach_index")),
            "mean": statistics.mean(arr("reach_index")),
            "p10": float(np.percentile(arr("reach_index"), 10)),
            "p90": float(np.percentile(arr("reach_index"), 90)),
        },
        "disclosure_desc": {
            "median": statistics.median(arr("disclosure_index")) if arr("disclosure_index") else None,
            "share_zero": sum(1 for r in recs.values()
                              if r.get("disclosure_index") == 0) / max(n_md, 1),
            "share_all5": sum(1 for r in recs.values()
                              if r.get("disclosure_index") == 5) / max(n_md, 1),
            "by_item": {it: sum(1 for r in recs.values()
                                if (r.get("disclosure") or {}).get(it) == 1) / max(n_md, 1)
                        for it in DISCLOSURE},
        },
        "external_benchmark": {
            "snyk_severe_share": 0.134, "snyk_all_severity_share": 0.3682,
            "note": "Snyk 的 36.82% 是在 ClawHub/skills.sh 市场 3,984 个技能上的审计判定；"
                    "本文样本为 GitHub 仓库且以文本可观测性为代理，两者抽样框不同，"
                    "不可直接相减，但 62.1% 与 36.8% 的落差说明关键词口径明显偏宽。",
        },
        "repos": {k: {kk: vv for kk, vv in r.items() if kk != "families"}
                  for k, r in recs.items()},
    }
    json.dump(out, open(os.path.join(RES, "v2_risk.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2, default=float)

    print("=" * 78)
    print("v2 风险属性操作化与效度检验")
    print("=" * 78)
    print(f"  干净样本 {len(recs)}；有 SKILL.md {n_md}；无 SKILL.md {len(recs)-n_md}")
    print(f"  旧口径（任一敏感词）高风险: {len(old_hi)}  ({len(old_hi)/len(recs)*100:.1f}% of all, "
          f"{len(old_hi)/n_md*100:.1f}% of with-md)")
    print(f"  新口径（≥2 能力族）高风险: {len(new_hi)}  ({len(new_hi)/len(recs)*100:.1f}%)")
    print(f"  旧 core.py 口径（topics/desc）: {len(core_hi)}")
    print(f"  口径一致性 Jaccard: old~new={out['agreement']['jaccard_old_new']:.3f}  "
          f"old~core={out['agreement']['jaccard_old_core']:.3f}  "
          f"new~core={out['agreement']['jaccard_new_core']:.3f}")
    print(f"  Cohen's κ: old~new={out['agreement']['kappa_old_new']:.3f}  "
          f"old~core={out['agreement']['kappa_old_core']:.3f}")
    print("\n  旧口径关键词在样本中的出现仓库数（降序）:")
    for kw, c in sorted(kw_prev.items(), key=lambda x: -x[1]):
        print(f"    {kw:<18} {c:>4} 仓库   ({c/max(len(with_md),1)*100:.1f}%)")
    print("\n  单关键词剔除后的高风险仓库数（旧口径，基线 %d）:" % len(old_hi))
    for kw, c in sorted(drop_sens.items(), key=lambda x: x[1]):
        print(f"    剔除 {kw:<18} → {c}")
    print(f"\n  触达指数: 中位数 {out['reach_index_desc']['median']:.2f}  "
          f"均值 {out['reach_index_desc']['mean']:.2f}")
    print(f"  披露指数: 中位数 {out['disclosure_desc']['median']:.0f}  "
          f"零披露占比 {out['disclosure_desc']['share_zero']*100:.1f}%  "
          f"五项齐全 {out['disclosure_desc']['share_all5']*100:.1f}%")
    print("  产出: data/results/v2_risk.json")
    print("=" * 78)


if __name__ == "__main__":
    main()
