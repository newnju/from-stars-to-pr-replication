# -*- coding: utf-8 -*-
"""v3_mechanism.py —— 把「信号竞争」操作化为两个可观测维度并直接检验

回应第四轮评审意见（一）与（二）3：
  意见（一）：「信号竞争」目前只是解释性标签，未被直接测量；建议至少操作化为
      维度一 决策时点信号可得性（Level 1 元数据中安全字段占比）
      维度二 信号读取成本（文本长度、结构化字段比例）
  意见（二）3：同日星标与分叉无法确定先后，须补滞后分析展示时序方向。

本模块产出：
  A. 决策时点信号可得性编码（frontmatter 字段构成、安全字段占比、Level-1 令牌数）
  B. 读取成本不对称（Level-2 正文长度 / Level-1 元数据长度）
  C. 机制模型：注意力方程（星标）与转化方程（分叉）对上述变量的反应差异
  D. 滞后事件分析：t 日星标 → t+1／t+7 日分叉；t 日分叉 → t+1 日星标

产出：data/results/v3_mechanism.json
"""
import json, os, re, sys, math, datetime, statistics
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RES = os.path.join(DATA, "results")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from v2_hazard import build_panel, add_bins  # 复用完备窗口面板

# 安全相关字段：在决策时点即 Level 1 可得的、与风险治理有关的字段
SAFETY_FIELDS = {"allowed-tools", "allowed_tools", "permissions", "permission",
                 "license", "sandbox", "security", "credentials"}


def load(n):
    return json.load(open(os.path.join(DATA, n), encoding="utf-8"))


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


def approx_tokens(s):
    """粗略令牌估计：英文按空白切分，中日韩字符按字计。"""
    if not s:
        return 0
    cjk = len(re.findall(r"[\u4e00-\u9fff\u3040-\u30ff]", s))
    latin = len(re.findall(r"[A-Za-z0-9_\-]+", s))
    return cjk + latin


def frontmatter_features(txt):
    """从 SKILL.md 文本抽取 Level-1 可得性特征。"""
    out = {"has_skillmd": txt is not None, "has_fm": False, "n_fields": 0,
           "safety_fields": 0, "safety_any": 0, "fm_tokens": 0,
           "l1_tokens": 0, "safe_tokens": 0, "body_tokens": 0,
           "desc_tokens": 0, "name_tokens": 0}
    if not txt:
        return out
    out["body_tokens"] = approx_tokens(txt)
    m = re.match(r"\s*---\s*\n(.*?)\n---", txt, flags=re.S)
    if not m:
        return out
    fm = m.group(1)
    out["has_fm"] = True
    # 逐字段抽取（含缩进块：以顶格 key: 切分）
    blocks = re.split(r"\n(?=[A-Za-z][A-Za-z0-9_\-]*\s*:)", fm)
    keys, safe_tok, all_tok = [], 0, 0
    for b in blocks:
        km = re.match(r"([A-Za-z][A-Za-z0-9_\-]*)\s*:\s*(.*)", b, flags=re.S)
        if not km:
            continue
        k = km.group(1).lower()
        v = km.group(2) or ""
        keys.append(k)
        tk = approx_tokens(v)
        all_tok += tk
        if k in SAFETY_FIELDS:
            safe_tok += tk
        if k == "description":
            out["desc_tokens"] = tk
        if k == "name":
            out["name_tokens"] = tk
    out["n_fields"] = len(set(keys))
    out["safety_fields"] = len([k for k in set(keys) if k in SAFETY_FIELDS])
    out["safety_any"] = 1 if out["safety_fields"] > 0 else 0
    out["fm_tokens"] = all_tok
    out["safe_tokens"] = safe_tok
    # Level 1 = 决策时点唯一被加载的部分 = name + description
    out["l1_tokens"] = out["desc_tokens"] + out["name_tokens"]
    return out


def main():
    print("=" * 78)
    print("v3 机制直测：决策时点信号可得性与读取成本")
    print("=" * 78)

    panel = load(os.path.join(RES, "v2_panel.json"))["repos"]
    risk = load(os.path.join(RES, "v2_risk.json"))["repos"]
    meta = load("repos_meta.json")

    # ---------- A. 编码 ----------
    rows = []
    for repo, r in sorted(panel.items()):
        txt = read_skill(repo)
        f = frontmatter_features(txt)
        f["repo"] = repo
        rows.append(f)
    fm = pd.DataFrame(rows).set_index("repo")
    print("\n【A 决策时点信号可得性】")
    has = fm[fm["has_skillmd"]]
    print("  有 SKILL.md 文本: %d / %d" % (len(has), len(fm)))
    print("  含 frontmatter: %d (%.1f%%)" % (has["has_fm"].sum(),
                                            has["has_fm"].mean() * 100))
    print("  安全字段≥1 的仓库: %d (%.1f%%)" % (has["safety_any"].sum(),
                                               has["safety_any"].mean() * 100))
    print("  字段数中位: %.0f  仅 name+description(≤2字段)占比: %.1f%%" %
          (has["n_fields"].median(), (has["n_fields"] <= 2).mean() * 100))
    print("  Level-1 令牌数中位: %.0f（p10=%.0f, p90=%.0f）" %
          (has["l1_tokens"].median(), has["l1_tokens"].quantile(.1),
           has["l1_tokens"].quantile(.9)))

    # ---------- B. 读取成本不对称 ----------
    has = has.copy()
    has["cost_ratio"] = has["body_tokens"] / has["l1_tokens"].clip(lower=1)
    print("\n【B 读取成本不对称】")
    print("  Level-2 正文令牌中位: %.0f" % has["body_tokens"].median())
    print("  正文/元数据 成本比中位: %.1f 倍（p10=%.1f, p90=%.1f）" %
          (has["cost_ratio"].median(), has["cost_ratio"].quantile(.1),
           has["cost_ratio"].quantile(.9)))

    # ---------- C. 机制模型 ----------
    # 仓库级：以窗口内日均星标（注意力）与每百星标分叉数（共现）为结果
    d = []
    for repo, r in panel.items():
        if not r["win_stars"]:
            continue
        rr = risk.get(repo, {})
        f = fm.loc[repo].to_dict() if repo in fm.index else {}
        d.append({
            "repo": repo,
            "stars_per_day": r["win_stars"] / max(r["win_days"], 1),
            "conv": r["win_forks"] / r["win_stars"] * 100,
            "forks": r["win_forks"], "stars_ev": r["win_stars"],
            "win_days": r["win_days"],
            "l1_tokens": f.get("l1_tokens", 0) or 0,
            "body_tokens": f.get("body_tokens", 0) or 0,
            "cost_ratio": (f.get("body_tokens", 0) or 0) / max(f.get("l1_tokens", 1) or 1, 1),
            "safety_any": f.get("safety_any", 0) or 0,
            "n_fields": f.get("n_fields", 0) or 0,
            "safety_fields": f.get("safety_fields", 0) or 0,
            "total_stars": r["total_stars"],
            "age": (datetime.date(2026, 10, 4) -
                    datetime.date.fromisoformat(r["created"])).days,
            "vis_resid": math.log10(r["total_stars"] + 10) - math.log10(41964 + 10),
        })
    d = pd.DataFrame(d)
    d["log_l1"] = np.log10(d["l1_tokens"] + 10)
    d["log_body"] = np.log10(d["body_tokens"] + 10)
    d["log_cost"] = np.log10(d["cost_ratio"] + 1)
    d["log_age"] = np.log10(d["age"] + 10)
    d = d[d["l1_tokens"] > 0].copy()      # 需要 Level-1 可得才有机制可言
    print("\n  进入机制模型的仓库: %d" % len(d))

    models = {}
    specs = {
        # 注意力方程：Level-1 信号越"丰满"，吸引的注意力越多？
        "att_l1": ("stars_per_day ~ log_l1 + log_age", None),
        "att_safety": ("stars_per_day ~ safety_any + log_l1 + log_age", None),
        # 共现方程：同样的信号是否提高单位注意力的意图产出？
        "conv_l1": ("forks ~ log_l1 + log_age", "stars_ev"),
        "conv_safety": ("forks ~ safety_any + log_l1 + log_age", "stars_ev"),
        "conv_cost": ("forks ~ log_cost + log_age", "stars_ev"),
        "conv_fields": ("forks ~ n_fields + log_age", "stars_ev"),
    }
    for tag, (f, off) in specs.items():
        try:
            if off is None:
                m = smf.glm(f, data=d, family=sm.families.Poisson()).fit(cov_type="HC1")
                fam = "Poisson(计数=日均星标)"
            else:
                m = smf.glm(f, data=d, family=sm.families.Poisson(),
                            offset=np.log(d[off])).fit(cov_type="HC1")
                fam = "Poisson(offset=log星标事件)"
            keys = [k for k in m.params.index if k in
                    ("log_l1", "safety_any", "log_cost", "n_fields")]
            models[tag] = {"formula": f, "family": fam, "n": int(m.nobs),
                           "coef": {k: float(m.params[k]) for k in keys},
                           "se": {k: float(m.bse[k]) for k in keys},
                           "p": {k: float(m.pvalues[k]) for k in keys},
                           "irr": {k: float(np.exp(m.params[k])) for k in keys}}
            print("\n  %s: %s  [%s, n=%d]" % (tag, f, fam, int(m.nobs)))
            for k in keys:
                print("    %-12s β=%+.4f (SE=%.4f, p=%.4f)  IRR=%.3f%s" %
                      (k, m.params[k], m.bse[k], m.pvalues[k], np.exp(m.params[k]),
                       "  ***" if m.pvalues[k] < .05 else ""))
        except Exception as e:
            models[tag] = {"error": str(e)}
            print("  %s 失败: %s" % (tag, e))

    # ---------- D. 滞后事件分析 ----------
    print("\n" + "=" * 78)
    print("D 滞后事件分析（同时性与时序方向）")
    print("=" * 78)
    df, _ = build_panel()
    df = add_bins(df)
    lags = []
    for repo, g in df.groupby("repo"):
        g = g.sort_values("date").reset_index(drop=True)
        s = g["new_stars"].values
        fk = g["forks"].values
        n = len(g)
        rec = {"repo": repo, "date": g["date"].values}
        for L in (1, 3, 7):
            rec["stars_lag%d" % L] = np.concatenate([[np.nan] * L, s[:-L]]) if n > L else np.full(n, np.nan)
            rec["forks_lag%d" % L] = np.concatenate([[np.nan] * L, fk[:-L]]) if n > L else np.full(n, np.nan)
        # 前瞻：明天的分叉、七天的分叉
        for L in (1, 7):
            rec["forks_lead%d" % L] = np.concatenate([fk[L:], [np.nan] * L]) if n > L else np.full(n, np.nan)
            rec["stars_lead%d" % L] = np.concatenate([s[L:], [np.nan] * L]) if n > L else np.full(n, np.nan)
        rec["stars_t"] = s
        rec["forks_t"] = fk
        rec["cum"] = g["cum"].values
        rec["pct"] = g["pct"].values
        rec["age"] = g["age"].values
        lags.append(pd.DataFrame(rec))
    L = pd.concat(lags, ignore_index=True)
    L["log_cum"] = np.log10(L["cum"] + 10)
    L["ym"] = pd.to_datetime(L["date"]).dt.strftime("%Y-%m")

    lag_models = {}
    # (1) 今日星标 → 明日／七日后分叉（正向时序）
    for lead in (1, 7):
        sub = L[(L["stars_t"] > 0) & L["forks_lead%d" % lead].notna()].copy()
        if len(sub) < 100:
            continue
        sub["expo"] = np.log(sub["stars_t"])
        try:
            m = smf.glm("forks_lead%d ~ log_cum + C(ym)" % lead, data=sub,
                        family=sm.families.Poisson(), offset=sub["expo"]).fit(
                cov_type="cluster", cov_kwds={"groups": sub["repo"]})
            lag_models["stars_t_to_forks_t+%d" % lead] = {
                "n": int(m.nobs), "log_cum": float(m.params["log_cum"]),
                "se": float(m.bse["log_cum"]), "p": float(m.pvalues["log_cum"])}
            print("\n  今日星标 → %d 日后分叉（offset=log今日星标, n=%d）" % (lead, int(m.nobs)))
            print("    log_cum β=%+.4f (SE=%.4f, p=%.4f)" %
                  (m.params["log_cum"], m.bse["log_cum"], m.pvalues["log_cum"]))
        except Exception as e:
            print("  星标→分叉(lead=%d) 失败: %s" % (lead, e))
    # (2) 今日分叉 → 明日星标（反向时序）
    sub = L[(L["forks_t"] >= 0) & L["stars_lead1"].notna()].copy()
    sub = sub[sub["forks_t"] > 0]
    if len(sub) > 100:
        try:
            m = smf.glm("stars_lead1 ~ forks_t + log_cum + C(ym)", data=sub,
                        family=sm.families.Poisson()).fit(
                cov_type="cluster", cov_kwds={"groups": sub["repo"]})
            lag_models["forks_t_to_stars_t+1"] = {
                "n": int(m.nobs), "forks_t": float(m.params["forks_t"]),
                "se": float(m.bse["forks_t"]), "p": float(m.pvalues["forks_t"])}
            print("\n  今日分叉 → 明日星标（n=%d）" % int(m.nobs))
            print("    forks_t β=%+.4f (SE=%.4f, p=%.4f)" %
                  (m.params["forks_t"], m.bse["forks_t"], m.pvalues["forks_t"]))
        except Exception as e:
            print("  分叉→星标 失败: %s" % e)

    # (3) 同时性诊断：同日星标与同日分叉的相关系数（仓库内）
    within = []
    for repo, g in df.groupby("repo"):
        if len(g) > 5 and g["new_stars"].std() > 0 and g["forks"].std() > 0:
            within.append(np.corrcoef(g["new_stars"], g["forks"])[0, 1])
    within = [w for w in within if np.isfinite(w)]
    print("\n  同日星标—分叉的仓库内相关：中位 %.3f（n=%d 仓库，p25=%.3f, p75=%.3f）" %
          (np.median(within), len(within), np.percentile(within, 25),
           np.percentile(within, 75)))

    out = {
        "frontmatter": {
            "n_with_skillmd": int(len(has)), "n_has_fm": int(has["has_fm"].sum()),
            "share_safety_any": float(has["safety_any"].mean()),
            "median_fields": float(has["n_fields"].median()),
            "share_minimal_fields": float((has["n_fields"] <= 2).mean()),
            "median_l1_tokens": float(has["l1_tokens"].median()),
            "median_body_tokens": float(has["body_tokens"].median()),
            "median_cost_ratio": float(has["cost_ratio"].median()),
            "p10_cost_ratio": float(has["cost_ratio"].quantile(.1)),
            "p90_cost_ratio": float(has["cost_ratio"].quantile(.9)),
            "field_prevalence": {k: int(v) for k, v in
                                 has["n_fields"].value_counts().sort_index().items()},
        },
        "models": models,
        "lag_models": lag_models,
        "same_day_within_corr_median": float(np.median(within)),
        "same_day_within_corr_p25": float(np.percentile(within, 25)),
        "same_day_within_corr_p75": float(np.percentile(within, 75)),
        "n_repos_mechanism": int(len(d)),
    }
    json.dump(out, open(os.path.join(RES, "v3_mechanism.json"), "w",
                        encoding="utf-8"), ensure_ascii=False, indent=2, default=float)
    print("\n  产出: data/results/v3_mechanism.json")
    print("=" * 78)


if __name__ == "__main__":
    main()
