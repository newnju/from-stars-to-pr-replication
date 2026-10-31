# -*- coding: utf-8 -*-
"""
GitSkills 外部数据两件事（《数据来源全清单》第八节第 1 项）：
  (1) 分位数/Gini 对照：把本文 203 个干净样本放进 GitSkills 282,200 仓库的
      星标总体分布，回答“样本是否系统性偏向高注意力仓库”；
  (2) file_sha 替换测量：按 SKILL.md 文件的 git blob SHA 统计同一内容出现在
      多少个仓库（独立于 GitHub forks 端点的扩散测量，且不受 500 条截断影响）。
      严格按字节相同判定，是对“精确复制”的下界估计。
  (3) 第二来源交叉验证：skillmd_138k 的 content_hash 复制计数。

输入：
  external_data/gitskills_parquet/repos/*.parquet      (282,200)
  external_data/gitskills_parquet/artifacts/*.parquet  (31 片, 3,797,117)
  external_data/skillmd_138k/train.parquet             (138,133)
  data/results/clean_sample.json / data/repos_meta.json / data/forks_timestamps.json
输出：
  data/results/gitskills_external.json
"""
import json
import os
import glob
import sys
import datetime

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
GK = os.path.join(HERE, "external_data", "gitskills_parquet")
OUT = os.path.join(DATA, "results", "gitskills_external.json")


def gini(x):
    """标准基尼系数，x 升序；返回 0..1。"""
    x = np.sort(np.asarray(x, dtype=np.float64))
    n = len(x)
    s = x.sum()
    if n == 0 or s <= 0:
        return None
    idx = np.arange(1, n + 1, dtype=np.float64)
    return float((2.0 * (idx * x).sum()) / (n * s) - (n + 1.0) / n)


def pctile_summary(x):
    x = np.asarray(x, dtype=np.float64)
    q = np.percentile(x, [10, 25, 50, 75, 90, 95, 99])
    return {
        "mean": float(x.mean()),
        "p10": float(q[0]), "p25": float(q[1]), "p50": float(q[2]),
        "p75": float(q[3]), "p90": float(q[4]), "p95": float(q[5]),
        "p99": float(q[6]),
        "gini": gini(x),
    }


def percentile_of(v, sorted_arr):
    """v 在升序总体中的分位（<=v 的比例）。"""
    return float(np.searchsorted(sorted_arr, v, side="right") / len(sorted_arr))


def main():
    res = {"generated_at": datetime.datetime.now().isoformat(timespec="seconds")}

    # ---------------- 输入 ----------------
    clean = json.load(open(os.path.join(DATA, "results", "clean_sample.json"), encoding="utf-8"))
    sample = list(clean["clean_repos"])
    cutoff = str(clean.get("cutoff", "2025-09-22"))[:10]
    meta = json.load(open(os.path.join(DATA, "repos_meta.json"), encoding="utf-8"))
    forks_ts = json.load(open(os.path.join(DATA, "forks_timestamps.json"), encoding="utf-8"))
    truncated = {k for k in sample if meta.get(k, {}).get("forks", 0) > 500 and k in forks_ts}

    # ================= (1) 282,200 总体分布中的位置 =================
    repos = pd.read_parquet(sorted(glob.glob(os.path.join(GK, "repos", "*.parquet")))[0])
    stars_all = repos["stars"].to_numpy(dtype=np.float64)
    valid_stars = np.isfinite(stars_all)          # repos 表存在空星标（元数据未回填）
    created = pd.to_datetime(repos["created_at"], errors="coerce", utc=True)
    era_mask = ((created >= pd.Timestamp(cutoff, tz="UTC")).to_numpy()) & valid_stars

    matched = repos["full_name"].isin(sample)
    sample_rows = repos[matched]
    stars_sorted = np.sort(stars_all[valid_stars])
    era_sorted = np.sort(stars_all[era_mask])

    # 星标快照一致性（GitSkills 挖掘约 2026-08 vs 本文 2026-10-04 快照）
    meta_stars = pd.Series(
        {k: meta[k]["stars"] for k in sample if k in meta}, name="meta"
    )
    gs_stars = sample_rows.set_index("full_name")["stars"]
    common_idx = meta_stars.index.intersection(gs_stars.index)
    spearman = (
        float(meta_stars[common_idx].corr(gs_stars[common_idx], method="spearman"))
        if len(common_idx) >= 3 else None
    )

    sample_pct_all = [percentile_of(s, stars_sorted) for s in sample_rows["stars"]]
    era_pct = [percentile_of(s, era_sorted) for s in sample_rows["stars"]]

    res["population"] = {
        "n_repos": int(len(repos)),
        "n_stars_valid": int(valid_stars.sum()),
        "stars_all": pctile_summary(stars_all[valid_stars]),
        "era_cutoff": cutoff,
        "n_same_era": int(era_mask.sum()),
        "stars_same_era": pctile_summary(stars_all[era_mask]),
        "sample": {
            "n_clean": len(sample),
            "hit_in_gitskills": int(matched.sum()),
            "hit_rate": float(matched.sum() / len(sample)),
            "stars_median_matched": float(sample_rows["stars"].median(skipna=True)),
            "stars_p25_matched": float(sample_rows["stars"].quantile(0.25, interpolation="linear")),
            "stars_p75_matched": float(sample_rows["stars"].quantile(0.75, interpolation="linear")),
            "star_pctile_median_all": float(np.median(sample_pct_all)),
            "star_pctile_p25_all": float(np.percentile(sample_pct_all, 25)),
            "star_pctile_p75_all": float(np.percentile(sample_pct_all, 75)),
            "star_pctile_median_same_era": float(np.median(era_pct)),
            "share_in_pop_top10pct": float(np.mean(np.asarray(sample_pct_all) >= 0.90)),
            "share_in_pop_top1pct": float(np.mean(np.asarray(sample_pct_all) >= 0.99)),
            "is_fork_share_sample": float(sample_rows["is_fork"].mean()),
            "is_fork_share_same_era_pop": float(
                repos.loc[era_mask, "is_fork"].mean()
            ),
            "stars_spearman_vs_repos_meta": spearman,
        },
        "missed_sample_repos": sorted(set(sample) - set(sample_rows["full_name"])),
    }

    # ================= (2) file_sha 内容复制计数 =================
    shards = sorted(glob.glob(os.path.join(GK, "artifacts", "*.parquet")))
    parts = []
    for i, f in enumerate(shards):
        parts.append(
            pd.read_parquet(
                f, columns=["repo_full_name", "file_sha", "dedup_primary",
                            "content_sha_ok", "first_commit_at", "path"]
            )
        )
        if (i + 1) % 10 == 0:
            print(f"  读取 artifacts {i + 1}/{len(shards)}")
    art = pd.concat(parts, ignore_index=True)
    del parts
    n_art = len(art)

    art["first_commit_at"] = pd.to_datetime(art["first_commit_at"], errors="coerce", utc=True)
    repo_codes, repo_uniques = pd.factorize(art["repo_full_name"])
    sha_codes, sha_uniques = pd.factorize(art["file_sha"])
    n_unique_sha = int((sha_uniques != "").sum()) if hasattr(sha_uniques, "__len__") else 0
    has_sha = sha_codes >= 0  # factorize 把 NaN 记为 -1

    # 样本行：留 path 做 top 列表
    sample_id_map = {r: i for i, r in enumerate(repo_uniques)}
    sample_ids = np.array([sample_id_map[r] for r in sample if r in sample_id_map], dtype=np.int64)
    repo_is_sample = np.isin(repo_codes, sample_ids)
    sample_row_df = pd.DataFrame({
        "sha": sha_codes[repo_is_sample & has_sha],
        "repo": repo_codes[repo_is_sample & has_sha],
        "path": art.loc[repo_is_sample & has_sha, "path"].to_numpy(),
    })

    # 每个 sha 出现在多少个不同仓库（只按字节相同判定）
    pairs = pd.DataFrame({"sha": sha_codes[has_sha], "repo": repo_codes[has_sha]}).drop_duplicates()
    n_repos_per_sha = pairs.groupby("sha", sort=False).size()

    # 行级加权：全体 / dedup_primary / content_sha_ok 三个口径的复制占比
    def copied_share(mask_sha):
        """mask_sha 内、且内容出现在 >=2 仓库的行占比（相对全体行）。"""
        rc = np.asarray(n_repos_per_sha.reindex(sha_codes[mask_sha]).fillna(0))
        return float((rc >= 2).sum() / max(mask_sha.sum(), 1))

    valid = has_sha
    primary = has_sha & (art["dedup_primary"].to_numpy() == 1)
    sha_ok = has_sha & (art["content_sha_ok"].to_numpy() == 1)

    counts = np.bincount(sha_codes[has_sha], minlength=len(sha_uniques))
    rc_arr = n_repos_per_sha.reindex(np.arange(len(sha_uniques))).fillna(0).to_numpy()

    share_of = lambda thr, arr: float((arr >= thr).sum() / max(len(arr), 1))
    uniq_mask = np.arange(len(sha_uniques))[counts > 0]

    copy_summary = {
        "n_artifacts": int(n_art),
        "n_unique_file_sha": int(len(uniq_mask)),
        "inflation_artifacts_per_sha": float(n_art / max(len(uniq_mask), 1)),
        "sha_in_1_repo_share": float((rc_arr[uniq_mask] == 1).sum() / len(uniq_mask)),
        "sha_in_ge2_repo_share": float((rc_arr[uniq_mask] >= 2).sum() / len(uniq_mask)),
        "sha_in_ge5_repo_share": float((rc_arr[uniq_mask] >= 5).sum() / len(uniq_mask)),
        "sha_in_ge10_repo_share": float((rc_arr[uniq_mask] >= 10).sum() / len(uniq_mask)),
        "max_repo_count_per_sha": int(rc_arr[uniq_mask].max()),
        "artifact_share_copied_ge2": copied_share(valid),
        "artifact_share_copied_ge2_primary": copied_share(primary),
        "artifact_share_copied_ge2_sha_ok": copied_share(sha_ok),
        "median_repos_per_copied_sha": float(
            np.median(rc_arr[uniq_mask][rc_arr[uniq_mask] >= 2])
        ) if (rc_arr[uniq_mask] >= 2).any() else None,
    }

    # ---- 样本内：每个仓库的复制深度 ----
    srow = sample_row_df.copy()
    srow["n_repos"] = n_repos_per_sha.reindex(srow["sha"]).fillna(0).to_numpy()
    srow["other"] = srow["n_repos"] - 1
    per_repo = srow.groupby("repo").agg(
        n_skills=("sha", "count"),
        copied_skills=("other", lambda x: int((x >= 1).sum())),
        max_other=("other", "max"),
        median_other=("other", "median"),
    )
    per_repo.index = [repo_uniques[i] for i in per_repo.index]

    # 复制传播时长：被复制的样本技能，其同一 SHA 在各仓库的最早提交时间跨度
    sample_shas = np.unique(srow.loc[srow["other"] >= 1, "sha"].to_numpy())
    is_sample_sha = np.isin(sha_codes, sample_shas) & has_sha
    tl = pd.DataFrame({
        "sha": sha_codes[is_sample_sha],
        "t": art.loc[is_sample_sha, "first_commit_at"].to_numpy(),
    }).dropna()
    span = (tl.groupby("sha")["t"].max() - tl.groupby("sha")["t"].min()).dt.days

    # 触顶仓库（元数据 forks>500，分叉列表被截断）能否用内容复制补
    trunc_list = sorted(truncated)
    trunc_copy = sum(
        1 for r in trunc_list
        if r in per_repo.index and per_repo.loc[r, "copied_skills"] >= 1
    )

    top = (
        srow[srow["other"] >= 1]
        .drop_duplicates(subset=["repo", "sha"])
        .nlargest(10, "n_repos")
    )
    top_list = [
        {
            "sample_repo": repo_uniques[r],
            "skill_path": p,
            "n_repos_with_same_content": int(n),
            "other_repos": int(n - 1),
        }
        for r, p, n in zip(top["repo"], top["path"], top["n_repos"])
    ]

    copy_summary["sample"] = {
        "n_sample_in_artifacts": int(len(per_repo)),
        "repos_with_exact_copy": int((per_repo["copied_skills"] >= 1).sum()),
        "share_with_exact_copy": float((per_repo["copied_skills"] >= 1).mean()),
        "median_skills_per_repo": float(per_repo["n_skills"].median()),
        "median_copied_skills_per_repo": float(per_repo["copied_skills"].median()),
        "median_max_other_repos": float(per_repo["max_other"].median()),
        "p90_max_other_repos": float(per_repo["max_other"].quantile(0.9)),
        "truncated_repos": len(trunc_list),
        "truncated_with_exact_copy": trunc_copy,
        "copied_skill_span_days_median": float(span.median()) if len(span) else None,
        "copied_skill_n_sha": int(len(span)),
        "top_copied": top_list,
    }
    res["copy_by_file_sha"] = copy_summary
    del art, pairs, srow, sample_row_df, tl

    # ================= (3) skillmd_138k 交叉验证 =================
    try:
        tr = pd.read_parquet(
            sorted(glob.glob(os.path.join(HERE, "external_data", "skillmd_138k", "*.parquet")))[0],
            columns=["content_hash", "repo"],
        )
        tr["repo"] = tr["repo"].astype(str)
        p2 = tr.drop_duplicates(subset=["content_hash", "repo"])
        rc2 = p2.groupby("content_hash", sort=False).size()
        n_h = len(rc2)
        res["skillmd_138k"] = {
            "note": "该语料按唯一内容构建（138,133 行哈希全部唯一），"
                    "复制率为 0 属构造使然，不具备复制计数信息量；仅作样本覆盖参考。",
            "n_artifacts": int(len(tr)),
            "n_unique_content_hash": int(n_h),
            "hash_in_1_repo_share": float((rc2 == 1).sum() / n_h),
            "hash_in_ge2_repo_share": float((rc2 >= 2).sum() / n_h),
            "hash_in_ge5_repo_share": float((rc2 >= 5).sum() / n_h),
            "max_repo_count_per_hash": int(rc2.max()),
            "sample_hit": int(tr.loc[tr["repo"].isin(sample), "repo"].nunique()),
        }
    except Exception as e:  # 交叉验证失败不阻断主结果
        res["skillmd_138k"] = {"error": str(e)}

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)

    # ---------------- 摘要 ----------------
    p = res["population"]["sample"]
    c = res["copy_by_file_sha"]
    print("\n== (1) 样本在 282,200 总体中的位置 ==")
    print(f"  命中 {p['hit_in_gitskills']}/{p['n_clean']}  "
          f"星标分位中位(全体) {p['star_pctile_median_all']:.3f}  "
          f"(同代) {p['star_pctile_median_same_era']:.3f}  "
          f"落 top10% 占比 {p['share_in_pop_top10pct']:.1%}")
    print(f"  总体 Gini(星标) {res['population']['stars_all']['gini']:.3f}  "
          f"同代 Gini {res['population']['stars_same_era']['gini']:.3f}  "
          f"与 repos_meta 星标 Spearman {p['stars_spearman_vs_repos_meta']}")
    print("\n== (2) file_sha 内容复制 ==")
    print(f"  产物 {c['n_artifacts']:,}  唯一SHA {c['n_unique_file_sha']:,}  "
          f"膨胀 {c['inflation_artifacts_per_sha']:.2f}×")
    print(f"  SHA 跨仓库复制: >=2 {c['sha_in_ge2_repo_share']:.1%}  "
          f">=5 {c['sha_in_ge5_repo_share']:.1%}  "
          f"行级(>=2仓库) {c['artifact_share_copied_ge2']:.1%}")
    s = c["sample"]
    print(f"  样本 {s['n_sample_in_artifacts']} 仓库中 {s['repos_with_exact_copy']} "
          f"({s['share_with_exact_copy']:.1%}) 存在精确内容复制；"
          f"触顶 {s['truncated_with_exact_copy']}/{s['truncated_repos']}")
    print(f"  复制传播跨度中位 {s['copied_skill_span_days_median']} 天")
    print("\n== (3) skillmd_138k 交叉验证 ==")
    k = res["skillmd_138k"]
    if "error" not in k:
        print(f"  唯一 content_hash {k['n_unique_content_hash']:,}  "
              f"跨仓库 >=2 {k['hash_in_ge2_repo_share']:.1%}")
    print(f"\n输出 -> {OUT}")


if __name__ == "__main__":
    main()
