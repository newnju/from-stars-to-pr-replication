# -*- coding: utf-8 -*-
"""
风险分层（危害导向）——聚焦「破坏性/凭证窃取能力」，而非普通命令执行
两级分类：
  DESTRUCTIVE（高危）：凭证窃取、数据销毁、提权、反弹shell/后门、恶意载荷、批量删除
  BENIGN（其余）：普通开发/内容生成技能（即便用 curl/token，属正常工具行为）
再分层检验 H2b（门槛随风险上移）、P1a（分离度随风险递增）、H2c（双峰）
"""
import json, os, re, statistics
from collections import Counter

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
SKILLDIR = os.path.join(DATA, "skillmd")

# 破坏性/凭证窃取能力（高危信号，高权重）
DESTRUCTIVE = [
    "rm -rf", "rm -fr", "del /f", "del /s /q", "drop table", "drop database",
    "truncate table", "format c:", "mkfs", "dd if=", "shred ", "wipe ",
    "credential", "credentials", "password", "passwd", "api_key", "api key",
    "access token", "auth token", "oauth", "private key", "ssh-keygen",
    "sudo ", "chmod 777", "chmod -R 777", "setuid", "privilege escalation",
    "reverse shell", "reverse_shell", "backdoor", "keylogger", "payload",
    "exfiltrat", "exfiltrate", "c2 server", "command and control",
    "impersonat", "spoof", "phish", "steal", "harvest credential",
    "browser cookie", "session hijack", "man-in-the-middle", "mitm",
    "keychain", "vault decrypt", "decrypt", "unlock", "bypass",
]
# 高危能力（即便正常工具，触碰凭证/破坏也计入）
HIGH = ["credential", "password", "api_key", "api key", "access token",
        "private key", "reverse shell", "backdoor", "keylogger", "exfiltrat",
        "rm -rf", "drop table", "drop database", "sudo ", "chmod 777",
        "session hijack", "phish", "decrypt", "bypass"]

def score_skill(content):
    if not content:
        return 0, 0
    c = content.lower()
    d = sum(1 for kw in DESTRUCTIVE if kw in c)
    h = sum(1 for kw in HIGH if kw in c)
    return d, h

def safe_fn(name):
    return name.replace("/", "__").replace("\\", "__") + ".json"

def q(vals, p):
    if not vals:
        return None
    i = min(int(len(vals) * p), len(vals) - 1)
    return vals[i]

def main():
    meta = json.load(open(os.path.join(DATA, "repos_meta.json"), encoding="utf-8"))
    sh = json.load(open(os.path.join(DATA, "star_history.json"), encoding="utf-8"))
    forks = json.load(open(os.path.join(DATA, "forks_timestamps.json"), encoding="utf-8"))
    clean = json.load(open(os.path.join(DATA, "results", "clean_sample.json"), encoding="utf-8"))
    clean_repos = set(clean["clean_repos"])

    # 风险评分
    repo_risk = {}
    for k in clean_repos:
        fp = os.path.join(SKILLDIR, safe_fn(k))
        d_total, h_total, n_skills = 0, 0, 0
        if os.path.exists(fp):
            try:
                data = json.load(open(fp, encoding="utf-8"))
            except Exception:
                data = []
            if isinstance(data, dict):
                data = []
            for s in data:
                d, h = score_skill(s.get("content", ""))
                d_total += d; h_total += h; n_skills += 1
        repo_risk[k] = {"d": d_total, "h": h_total, "n": n_skills}

    # 两级：DESTRUCTIVE = h>=1（含凭证/破坏/提权/后门），BENIGN = 其余
    destructive = [k for k in clean_repos if repo_risk[k]["h"] >= 1]
    benign = [k for k in clean_repos if repo_risk[k]["h"] == 0]

    print("=" * 70)
    print("危害导向风险分层（DESTRUCTIVE vs BENIGN）")
    print("=" * 70)
    print(f"DESTRUCTIVE（含凭证/破坏/提权/后门能力）: {len(destructive)} ({len(destructive)/len(clean_repos)*100:.1f}%)")
    print(f"BENIGN（其余）: {len(benign)} ({len(benign)/len(clean_repos)*100:.1f}%)")

    # ---------- 风险分层下的 fork/star 转化率（采纳空转在风险维度） ----------
    def ratio_stats(repos):
        rs = []
        for k in repos:
            m = meta.get(k)
            if isinstance(m, dict) and m.get("stars"):
                rs.append(m["forks"] / m["stars"])
        return rs

    d_ratios = ratio_stats(destructive)
    b_ratios = ratio_stats(benign)
    print(f"\n【采纳空转 × 风险】fork/star 转化率")
    print(f"  DESTRUCTIVE: 中位数={statistics.median(d_ratios)*100:.2f}%  均值={statistics.mean(d_ratios)*100:.2f}%  (n={len(d_ratios)})")
    print(f"  BENIGN:      中位数={statistics.median(b_ratios)*100:.2f}%  均值={statistics.mean(b_ratios)*100:.2f}%  (n={len(b_ratios)})")

    # ---------- 贡献门槛 θ(D) 风险分层（H2b） ----------
    def theta_D(repos):
        def daily(hist):
            out = []
            for w in hist:
                import datetime
                base = datetime.datetime.fromtimestamp(w["week"], datetime.timezone.utc)
                for i, c in enumerate(w["days"]):
                    out.append(((base + datetime.timedelta(days=i)).strftime("%Y-%m-%d"), c))
            out.sort(); return out
        def cum_at(cum, ds):
            best = None
            for d, v in cum:
                if d <= ds: best = v
                else: break
            return best
        vals = []
        for k in repos:
            hist = sh.get(k)
            if not hist or k not in forks:
                continue
            ds = daily(hist)
            cum, run = [], 0
            for d, c in ds:
                run += c; cum.append((d, run))
            for f in forks[k] if isinstance(forks[k], list) else []:
                fd = f.get("created_at", "")[:10]
                v = cum_at(cum, fd)
                if v is not None:
                    vals.append(v)
        return vals

    td_d = theta_D(destructive)
    td_b = theta_D(benign)
    print(f"\n【贡献门槛 θ(D) × 风险】（H2b：门槛随风险上移）")
    print(f"  DESTRUCTIVE: 中位数={statistics.median(td_d):.0f}  均值={statistics.mean(td_d):.0f}  (n={len(td_d):,})")
    print(f"  BENIGN:      中位数={statistics.median(td_b):.0f}  均值={statistics.mean(td_b):.0f}  (n={len(td_b):,})")

    # ---------- 分离度 Δ × 风险（P1a） ----------
    # 注意力门槛 θ(L) 近零，Δ ≈ θ(D)
    # 用 Mann-Whitney U 检验两组 θ(D) 差异
    try:
        from scipy import stats as st
        mw = st.mannwhitneyu(td_d, td_b, alternative="two-sided")
        print(f"\n【Mann-Whitney U 检验】θ(D) 风险分层差异")
        print(f"  U={mw.statistic:.1f}  p={mw.pvalue:.3e}  {'显著' if mw.pvalue<0.05 else '不显著'}")
        # 双峰检验（H2c）：高风险仓库 θ(D) 分布形态
        from scipy.stats import gaussian_kde
        import numpy as np
        td_d_sorted = sorted(td_d)
        # 用 dip test 近似：双峰性通过直方图峰谷比
        hist_counts, edges = np.histogram(td_d, bins=30)
        # 峰谷比（简单）：找局部极大
        peaks = []
        for i in range(1, len(hist_counts)-1):
            if hist_counts[i] > hist_counts[i-1] and hist_counts[i] > hist_counts[i+1]:
                peaks.append(i)
        print(f"\n【H2c 双峰检验】高风险 θ(D) 直方图局部峰数: {len(peaks)}")
        print(f"  （峰数>=2 支持双峰；峰数=1 支持单峰）")
    except ImportError:
        print("  (scipy 不可用，跳过检验)")

    # 保存
    out = {
        "n_destructive": len(destructive), "n_benign": len(benign),
        "ratio_d_median": statistics.median(d_ratios) if d_ratios else None,
        "ratio_b_median": statistics.median(b_ratios) if b_ratios else None,
        "theta_D_d_median": statistics.median(td_d) if td_d else None,
        "theta_D_b_median": statistics.median(td_b) if td_b else None,
        "theta_D_d_mean": statistics.mean(td_d) if td_d else None,
        "theta_D_b_mean": statistics.mean(td_b) if td_b else None,
    }
    os.makedirs(os.path.join(DATA, "results"), exist_ok=True)
    json.dump(out, open(os.path.join(DATA, "results", "risk_strata_test.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"\n  结果已保存 data/results/risk_strata_test.json")
    print("=" * 70)

if __name__ == "__main__":
    main()
