# -*- coding: utf-8 -*-
"""
交错双重差分（Staggered DID / Event-study） + 合成控制（Synthetic Control）
用真实采集数据估计 2026 上半年审计冲击对 Skill 采纳增速的因果效应。

设计（对应论文表8 阶段①，见 自动化推进交接文档 三、识别策略）：
  A. 事件研究式 DID（风险暴露为处理强度）：
       处理组 = 含高风险能力文本的仓库（DESTRUCTIVE，126 个）
       对照组 = 其余仓库（BENIGN，77 个）
       断点 = 2026-02-03（ClawHavoc 首披，冲击簇起点）
       结果变量 = 周度新增 star 的对数 log(1+stars_w)
       设定 = 双向固定效应（仓库 FE + 周 FE）+ 处理×断点后 交互项
       标准误 = 仓库层面聚类
       → 识别「风险暴露更高的仓库在冲击后增速是否相对放缓」。
  B. 合成控制（SCM）：
       处理单元 = anthropics/skills（官方核心仓库，声誉暴露最直接）
       捐赠池 = 其余干净样本仓库（冲击前有完整时段的）
       结果变量 = 周度新增 star
       反事实 = 以冲击前 MSE 最小化为目标的非负权重凸组合
       断点 = 2026-03-24（Silverfort 排名可操纵，可见性信号可信度冲击）
       → 报告冲击后实际 vs 反事实的缺口（gap），及 pre/post RMSPE 比值。
产出：data/results/did_synthetic.json + data/results/figs/scm_gap.png
"""
import json, os, datetime, statistics
import numpy as np

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

def load(name):
    return json.load(open(os.path.join(DATA, name), encoding="utf-8"))

def daily_series(hist):
    out = []
    for w in hist:
        base = datetime.datetime.fromtimestamp(w["week"], datetime.timezone.utc)
        for i, c in enumerate(w["days"]):
            out.append(((base + datetime.timedelta(days=i)).strftime("%Y-%m-%d"), c))
    out.sort()
    return out

def weekly_series(hist, origin="2025-10-01", n_weeks=53):
    """每日 → 周度 [(week_index, weekly_sum)]，week 0 = origin 所在周"""
    daily = dict(daily_series(hist))
    o = datetime.date.fromisoformat(origin)
    out = {}
    for d, c in daily.items():
        dd = datetime.date.fromisoformat(d)
        wi = (dd - o).days // 7
        out[wi] = out.get(wi, 0) + c
    return sorted(out.items())

def main():
    sh = load("star_history.json")
    meta = load("repos_meta.json")
    clean = load("results/clean_sample.json")
    risk = load("results/risk_class.json")          # high/mid/low 分级
    clean_repos = set(clean["clean_repos"])

    high_set = set(risk.get("high", []))
    low_set = set(risk.get("low", []))
    mid_set = set(risk.get("mid", []))

    results = {}

    # ================= A. 事件研究式 DID =================
    # 处理组 = high（高风险），对照组 = low（低风险，最"干净"）；mid 舍弃以增强对照
    treated = [k for k in clean_repos if k in high_set]
    control = [k for k in clean_repos if k in low_set]

    BREAK_WEEK = (datetime.date.fromisoformat("2026-02-03") - datetime.date.fromisoformat("2025-10-01")).days // 7

    # 构建面板：[(repo_id, week, treat, post, y)]
    panel = []
    repo_id = {}
    for k in treated + control:
        ws = weekly_series(sh.get(k, []))
        if not ws:
            continue
        rid = len(repo_id)
        repo_id[k] = rid
        treat = 1 if k in high_set else 0
        for wi, v in ws:
            post = 1 if wi >= BREAK_WEEK else 0
            panel.append((rid, wi, treat, post, np.log1p(v)))

    panel = np.array(panel, dtype=float)
    n_obs = panel.shape[0]
    n_repo = len(repo_id)
    weeks = sorted(set(int(w) for w in panel[:, 1]))
    n_week = len(weeks)
    week_map = {w: i for i, w in enumerate(weeks)}

    # 设计矩阵：截距 + repo FE + week FE + treat×post
    # 去掉一个 repo FE 与一个 week FE 作基准
    n_cols = 1 + (n_repo - 1) + (n_week - 1) + 1
    X = np.zeros((n_obs, n_cols))
    y = panel[:, 4]
    X[:, 0] = 1.0
    col = 1
    for r in range(1, n_repo):
        X[:, col] = (panel[:, 0] == r).astype(float); col += 1
    for i, w in enumerate(weeks[1:]):
        X[:, col] = (panel[:, 1] == w).astype(float); col += 1
    # treat×post 交互
    X[:, col] = (panel[:, 2] * panel[:, 3])

    try:
        import statsmodels.api as sm
        model = sm.OLS(y, X).fit(cov_type="cluster", cov_kwds={"groups": panel[:, 0].astype(int)})
        did_coef = model.params[col]
        did_se = model.bse[col]
        did_p = model.pvalues[col]
        did = {
            "treated_n_repo": len(repo_id),
            "n_obs": int(n_obs),
            "n_week": n_week,
            "break_week": BREAK_WEEK,
            "break_date": "2026-02-03",
            "outcome": "log1p(weekly_new_stars)",
            "treat_x_post_coef": float(did_coef),
            "treat_x_post_se": float(did_se),
            "treat_x_post_p": float(did_p),
            "r2": float(model.rsquared),
        }
        # 简单 pre/post 组均值（便于解释方向）
        treat_pre = np.mean(panel[(panel[:, 2] == 1) & (panel[:, 3] == 0), 4])
        treat_post = np.mean(panel[(panel[:, 2] == 1) & (panel[:, 3] == 1), 4])
        ctrl_pre = np.mean(panel[(panel[:, 2] == 0) & (panel[:, 3] == 0), 4])
        ctrl_post = np.mean(panel[(panel[:, 2] == 0) & (panel[:, 3] == 1), 4])
        did["did_in_means"] = float((treat_post - treat_pre) - (ctrl_post - ctrl_pre))
        did["treat_pre_mean"] = float(treat_pre); did["treat_post_mean"] = float(treat_post)
        did["ctrl_pre_mean"] = float(ctrl_pre); did["ctrl_post_mean"] = float(ctrl_post)
        results["A_did"] = did
        print("=" * 70)
        print("A. 事件研究式 DID（处理=高风险仓库，对照=低风险仓库）")
        print(f"  仓库: {len(repo_id)}  观测: {n_obs}  周数: {n_week}")
        print(f"  treat×post 系数 = {did_coef:+.4f}  SE={did_se:.4f}  p={did_p:.3e}")
        print(f"  DID in means = {did['did_in_means']:+.4f}")
        print(f"  组均值: 处理 pre={treat_pre:.3f} post={treat_post:.3f} | 对照 pre={ctrl_pre:.3f} post={ctrl_post:.3f}")
    except Exception as e:
        results["A_did"] = {"error": str(e)}
        print(f"A DID 失败: {e}")

    # ================= B. 合成控制 =================
    try:
        treated_repo = "anthropics/skills"
        # 捐赠池：干净样本中除处理单元外、冲击前(2025-10-01~2026-03-23)有完整周度数据的仓库
        pre_start_wi = 0
        pre_end_wi = (datetime.date.fromisoformat("2026-03-24") - datetime.date.fromisoformat("2025-10-01")).days // 7 - 1
        post_end_wi = (datetime.date.fromisoformat("2026-10-05") - datetime.date.fromisoformat("2025-10-01")).days // 7

        def repo_weekly(k):
            return dict(weekly_series(sh.get(k, [])))

        yt = repo_weekly(treated_repo)
        donors = []
        for k in clean_repos:
            if k == treated_repo:
                continue
            wk = repo_weekly(k)
            # 冲击前须覆盖全部周
            pre = [wk.get(wi, 0.0) for wi in range(pre_start_wi, pre_end_wi + 1)]
            if len(pre) > 0 and sum(1 for v in pre if v == 0) / len(pre) < 0.5:
                donors.append(k)
        donors = donors[:120]  # 控制规模

        J = len(donors)
        T0 = pre_end_wi - pre_start_wi + 1
        Y_pre_treat = np.array([yt.get(wi, 0.0) for wi in range(pre_start_wi, pre_end_wi + 1)])
        D_pre = np.array([[repo_weekly(k).get(wi, 0.0) for wi in range(pre_start_wi, pre_end_wi + 1)] for k in donors])

        # 约束最小二乘求权重：min ||Y_pre_treat - D_pre^T w||, s.t. sum(w)=1, w>=0
        from scipy.optimize import minimize
        def obj(w):
            return np.sum((Y_pre_treat - D_pre.T @ w) ** 2)
        cons = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
        bounds = [(0, 1)] * J
        w0 = np.full(J, 1.0 / J)
        res = minimize(obj, w0, method="SLSQP", bounds=bounds, constraints=cons)
        w = res.x
        w = np.where(w < 1e-4, 0, w)
        w = w / w.sum() if w.sum() > 0 else w

        # 反事实轨迹
        def synth_series():
            post = [yt.get(wi, 0.0) for wi in range(pre_start_wi, post_end_wi + 1)]
            synth = []
            for wi in range(pre_start_wi, post_end_wi + 1):
                s = sum(w[j] * repo_weekly(donors[j]).get(wi, 0.0) for j in range(J))
                synth.append(s)
            return post, synth

        post, synth = synth_series()
        pre_rmse = np.sqrt(np.mean((Y_pre_treat - D_pre.T @ w) ** 2))
        post_gap = np.array(post[T0 + 1:]) - np.array(synth[T0 + 1:])
        post_rmse = np.sqrt(np.mean(post_gap ** 2))
        ratio = post_rmse / pre_rmse if pre_rmse > 0 else None

        scm = {
            "treated": treated_repo,
            "n_donors": J,
            "n_positive_weights": int(np.sum(w > 1e-4)),
            "pre_period": ["2025-10-01", "2026-03-23"],
            "post_period": ["2026-03-24", "2026-10-04"],
            "pre_rmse": float(pre_rmse),
            "post_rmse": float(post_rmse),
            "rmspe_ratio": float(ratio) if ratio is not None else None,
            "mean_gap_post": float(np.mean(post_gap)),
            "total_gap_post": float(np.sum(post_gap)),
            "top_weights": [[donors[j], round(float(w[j]), 4)] for j in np.argsort(-w)[:10] if w[j] > 1e-4],
        }
        results["B_scm"] = scm
        print("=" * 70)
        print("B. 合成控制（处理=anthropics/skills，断点=2026-03-24）")
        print(f"  捐赠池: {J}  正权重单元: {scm['n_positive_weights']}")
        print(f"  pre RMSE={pre_rmse:.2f}  post RMSE={post_rmse:.2f}  RMSPE ratio={ratio:.2f}")
        print(f"  冲击后平均 gap={np.mean(post_gap):+.2f} star/周")
        print(f"  主要权重: {scm['top_weights'][:5]}")

        # 图：实际 vs 合成
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Noto Sans SC", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        figdir = os.path.join(DATA, "results", "figs")
        os.makedirs(figdir, exist_ok=True)
        weeks_idx = list(range(pre_start_wi, post_end_wi + 1))
        dates = [datetime.date.fromisoformat("2025-10-01") + datetime.timedelta(weeks=wi) for wi in weeks_idx]
        plt.figure(figsize=(9, 4.5))
        plt.plot(dates, post, color="#1f77b4", lw=1.6, label="实际 anthropics/skills")
        plt.plot(dates, synth, color="#d62728", lw=1.6, ls="--", label="合成控制（反事实）")
        bd = datetime.date.fromisoformat("2026-03-24")
        plt.axvline(bd, color="gray", ls=":", lw=1, alpha=0.8)
        plt.text(bd, max(post) * 0.9, "Silverfort\n(2026-03-24)", rotation=0, fontsize=8, color="gray")
        plt.title("合成控制：anthropics/skills 周度新增星标（实际 vs 反事实）")
        plt.xlabel("日期"); plt.ylabel("周度新增 star")
        plt.legend(); plt.grid(alpha=0.3); plt.tight_layout()
        plt.savefig(os.path.join(figdir, "scm_gap.png"), dpi=150)
        plt.close()
        print("  图已保存 data/results/figs/scm_gap.png")
    except Exception as e:
        results["B_scm"] = {"error": str(e)}
        print(f"B SCM 失败: {e}")

    os.makedirs(os.path.join(DATA, "results"), exist_ok=True)
    json.dump(results, open(os.path.join(DATA, "results", "did_synthetic.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("=" * 70)
    print("结果已保存 data/results/did_synthetic.json")

if __name__ == "__main__":
    main()
