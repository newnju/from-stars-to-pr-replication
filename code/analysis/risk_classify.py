# -*- coding: utf-8 -*-
"""
基于 SKILL.md 实际内容的风险分级（高风险技能识别）
数据：data/skillmd/*.json（每仓库 SKILL.md 列表）
方法：安全敏感关键词 + 权限/命令特征 加权评分，产出每仓库 risk_score 与风险等级
用于 H1d / H2b / H2c / P1a 的风险分层
"""
import json, os, re
from collections import Counter

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
SKILLDIR = os.path.join(DATA, "skillmd")

# 高风险信号词（命令执行 / 凭证 / 网络 / 文件系统写 / 提权）
RISK_KW = [
    "rm -rf", "sudo", "chmod 777", "chmod -R", "curl ", "wget ", "eval(",
    "exec(", "subprocess", "os.system", "shell=True", "bash -c", "sh -c",
    "credential", "password", "api_key", "api key", "secret", "token",
    "ssh ", "ssh-key", "private key", "scp ", "rsync", "git push",
    "delete", "remove all", "drop table", "truncate", "format",
    "poweroff", "reboot", "shutdown", "kill -9", "pkill",
    "write file", "overwrite", "sed -i", "dd if=", "mkfs",
    "payload", "backdoor", "reverse shell", "exfiltration", "keylogger",
    "access token", "auth", "login", "impersonate", "spoof",
]
# 权重：更强的信号词
STRONG_KW = ["rm -rf", "sudo", "shell=True", "os.system", "eval(", "exec(",
             "subprocess", "bash -c", "credential", "api_key", "private key",
             "reverse shell", "exfiltration", "keylogger", "drop table",
             "truncate", "dd if=", "mkfs", "backdoor", "payload"]

def score_skill(content):
    """对单个 SKILL.md 内容评分"""
    if not content:
        return 0
    c = content.lower()
    hits = 0
    for kw in RISK_KW:
        if kw in c:
            hits += 1
    strong = 0
    for kw in STRONG_KW:
        if kw in c:
            strong += 1
    # 命令块数量（```bash 等）
    cmd_blocks = len(re.findall(r"```(bash|sh|shell|zsh|powershell|cmd)", c))
    return hits + strong * 2 + cmd_blocks

def safe_fn(name):
    return name.replace("/", "__").replace("\\", "__") + ".json"

def main():
    meta = json.load(open(os.path.join(DATA, "repos_meta.json"), encoding="utf-8"))
    clean = json.load(open(os.path.join(DATA, "results", "clean_sample.json"), encoding="utf-8"))
    clean_repos = set(clean["clean_repos"])

    repo_risk = {}   # repo -> {score, n_skills, max_score, mean_score, n_risky}
    for k in clean_repos:
        fp = os.path.join(SKILLDIR, safe_fn(k))
        if not os.path.exists(fp):
            repo_risk[k] = {"score": 0, "n_skills": 0, "max": 0, "mean": 0, "n_risky": 0}
            continue
        try:
            data = json.load(open(fp, encoding="utf-8"))
        except Exception:
            data = []
        if isinstance(data, dict):  # _error
            data = []
        scores = []
        for s in data:
            sc = score_skill(s.get("content", ""))
            scores.append(sc)
        n_risky = sum(1 for sc in scores if sc >= 3)
        repo_risk[k] = {
            "score": sum(scores),
            "n_skills": len(scores),
            "max": max(scores) if scores else 0,
            "mean": (sum(scores)/len(scores)) if scores else 0,
            "n_risky": n_risky,
        }

    # 分级：high = 存在风险技能（n_risky>=1）或 max>=5
    high, mid, low = [], [], []
    for k, r in repo_risk.items():
        if r["n_risky"] >= 1 or r["max"] >= 5:
            high.append(k)
        elif r["max"] >= 2:
            mid.append(k)
        else:
            low.append(k)

    out = {
        "risk_by_repo": repo_risk,
        "high": high, "mid": mid, "low": low,
        "n_high": len(high), "n_mid": len(mid), "n_low": len(low),
    }
    os.makedirs(os.path.join(DATA, "results"), exist_ok=True)
    json.dump(out, open(os.path.join(DATA, "results", "risk_class.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    print("=" * 70)
    print("SKILL.md 内容风险分级")
    print("=" * 70)
    print(f"高风险仓库: {len(high)}  ({len(high)/len(clean_repos)*100:.1f}%)")
    print(f"中风险仓库: {len(mid)}  ({len(mid)/len(clean_repos)*100:.1f}%)")
    print(f"低风险仓库: {len(low)}  ({len(low)/len(clean_repos)*100:.1f}%)")
    print(f"\n高风险仓库示例（前20）:")
    for k in high[:20]:
        r = repo_risk[k]
        print(f"  {k:<45} score={r['score']:>3} n_risky={r['n_risky']} max={r['max']} skills={r['n_skills']}")
    print(f"\n结果已保存 data/results/risk_class.json")
    print("=" * 70)

if __name__ == "__main__":
    main()
