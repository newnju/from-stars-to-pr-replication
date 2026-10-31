# -*- coding: utf-8 -*-
"""v3_audit_sample.py —— 导出主口径分类的人工复核证据样本

评审意见要求：至少人工标注 100—200 个技能，报告精确率、召回率与 F1。
本脚本按冻结样本清单导出「每仓库被命中的能力族 + 命中词 + 最小上下文」，
供逐条复核；复核结果由 v3_validate.py 汇总为混淆矩阵与指标。

样本清单：analysis/v3_audit_sample_list.json（120 个仓库，顺序即人工判定索引）。
原实现为固定种子随机抽样，已改为冻结清单——原因见 main() 内注释。

产出：data/results/v3_audit_evidence.json（含待复核样本与证据）
"""
import json, os, re, random

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RES = os.path.join(DATA, "results")

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


def safe_fn(name):
    return name.replace("/", "__").replace("\\", "__") + ".json"


def read_skill(repo):
    fp = os.path.join(DATA, "skillmd", safe_fn(repo))
    if not os.path.exists(fp) or os.path.getsize(fp) <= 2:
        return None
    try:
        obj = json.load(open(fp, encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(obj, list) or not obj:
        return None
    return "\n".join(s.get("content") or "" for s in obj)


def main():
    risk = json.load(open(os.path.join(RES, "v2_risk.json"), encoding="utf-8"))["repos"]
    panel = json.load(open(os.path.join(RES, "v2_panel.json"), encoding="utf-8"))["repos"]

    # ---- 抽样框冻结（重要，勿回退到下面这行原实现）-------------------------
    # 原实现：random.seed(20261006); sample = random.sample(sorted(pool), 120)
    # 其中 pool = 203 个干净样本中能读到非空 SKILL.md 的仓库。
    #
    # 随机抽样对池子构成极其敏感：只要补采到一个此前为空的 SKILL.md，池子一变，
    # 同样的种子就会抽出完全不同的样本（实测 120 个里换掉 34 个）。
    # 而 v3_validate.py 的人工判定是按「证据文件中的位置索引」写死的（MANUAL_TRUE），
    # 样本一变，判定会张冠李戴地落到另一批仓库上，混淆矩阵随即静默失效。
    #
    # 因此把已复核的 120 个仓库连同顺序固化为 analysis/v3_audit_sample_list.json：
    # 人工判定永远对应同一批仓库；池子变化只影响自动标签，不再改变抽样。
    # 注：本文件记录的是当时抽样框（182 个含 SKILL.md 仓库）中的 120 个，
    #     人工判定以仓库为单位有效，不因抽样框补采到 185 而失效。
    sample = json.load(open(os.path.join(
        ROOT, "analysis", "v3_audit_sample_list.json"), encoding="utf-8"))
    if len(sample) != 120 or len(set(sample)) != 120:
        raise SystemExit("冻结样本应为互不重复的 120 个，实际 %d（去重后 %d）"
                         % (len(sample), len(set(sample))))
    out_of_panel = [k for k in sample if k not in panel]
    if out_of_panel:
        raise SystemExit("冻结样本不在 203 干净样本内: %s" % out_of_panel[:3])
    no_skill = [k for k in sample if not read_skill(k)]
    if no_skill:
        raise SystemExit("冻结样本读不到 SKILL.md: %s" % no_skill[:3])

    records = []
    for repo in sample:
        txt = read_skill(repo) or ""
        low = txt.lower()
        fam_hits, evid = {}, {}
        for fam, kws in FAMILIES.items():
            hits = sorted({kw for kw in kws if kw in low})
            if hits:
                fam_hits[fam] = hits
                # 每个命中词给一个最小上下文
                ctx = {}
                for kw in hits[:3]:
                    i = low.find(kw)
                    ctx[kw] = txt[max(0, i - 55):i + 55].replace("\n", " ")
                evid[fam] = ctx
        rr = risk.get(repo, {})
        records.append({
            "repo": repo,
            "auto_families": fam_hits,
            "auto_n_families": len(fam_hits),
            "auto_reach_binary": int(rr.get("reach_binary") or 0),
            "auto_reach_index": rr.get("reach_index"),
            "evidence": evid,
            "len": len(txt),
        })

    json.dump(records, open(os.path.join(RES, "v3_audit_evidence.json"), "w",
                            encoding="utf-8"), ensure_ascii=False, indent=2, default=float)

    n_pos = sum(1 for r in records if r["auto_reach_binary"] == 1)
    print("样本 %d 个仓库；主口径判为高触达（≥2族）: %d，低触达: %d" %
          (len(records), n_pos, len(records) - n_pos))
    print("证据已写入 data/results/v3_audit_evidence.json")


if __name__ == "__main__":
    main()
