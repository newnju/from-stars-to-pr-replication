# -*- coding: utf-8 -*-
"""
样本构造：从 341 候选仓库筛选「Agent Skill 时代」真实技能仓库
判据：
  1) created_at >= 2025-09-22（Agent Skills 首个公开仓库 anthropics/skills 创建日）
  2) 至少含一个 skill 相关 topic（agent-skills / skills / claude-skills / codex / claude-code 等）
排除：2011-2024 的通用 awesome-list / 老牌项目（非 Skill 时代产物）
产出：data/results/clean_sample.json（仓库清单 + 元数据），并给出样本量统计
"""
import json, os, datetime

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
SKILL_TOPICS = {"agent-skills", "skills", "claude-skills", "codex",
                "claude-code", "claude-code-skills", "skill", "skillsets",
                "agent-skill", "claude-skill", "codex-skills", "cursor-skills",
                "opencode-skills"}

def main():
    meta = json.load(open(os.path.join(DATA, "repos_meta.json"), encoding="utf-8"))
    disc = json.load(open(os.path.join(DATA, "repos_discovered.json"), encoding="utf-8"))

    CUTOFF = "2025-09-22"
    clean = {}
    excluded_old = []
    excluded_topic = []
    for k, m in meta.items():
        if not isinstance(m, dict):
            continue
        ca = m.get("created_at", "")
        topics = set(m.get("topics", []) or [])
        d_topics = set(disc.get(k, {}).get("topics", []) or [])
        all_topics = topics | d_topics
        if ca < CUTOFF:
            excluded_old.append((k, ca))
            continue
        # skill 相关 topic 判定
        if not (all_topics & SKILL_TOPICS):
            excluded_topic.append((k, ca, list(all_topics)[:5]))
            continue
        clean[k] = m

    print("=" * 70)
    print("样本构造：Agent Skill 时代技能仓库")
    print("=" * 70)
    print(f"原始候选: {len(meta)}")
    print(f"  排除（创建于 {CUTOFF} 之前，非 Skill 时代）: {len(excluded_old)}")
    print(f"  排除（无 skill 相关 topic）: {len(excluded_topic)}")
    print(f"  干净样本: {len(clean)}")

    # 干净样本统计
    stars = [m["stars"] for m in clean.values() if "stars" in m]
    fks = [m["forks"] for m in clean.values() if "forks" in m]
    import statistics
    print(f"\n干净样本描述统计:")
    print(f"  总 star: {sum(stars):,}  总 fork: {sum(fks):,}")
    print(f"  star 中位数: {statistics.median(stars):.0f}  均值: {statistics.mean(stars):.0f}")
    print(f"  fork 中位数: {statistics.median(fks):.0f}  均值: {statistics.mean(fks):.0f}")
    ratio = sum(fks)/sum(stars) if sum(stars) else 0
    print(f"  整体 fork/star 转化率: {ratio*100:.2f}%")
    med_ratio = statistics.median(m["forks"]/m["stars"] if m.get("stars") else 0 for m in clean.values())
    print(f"  fork/star 转化率中位数: {med_ratio*100:.2f}%")

    # 语言分布
    from collections import Counter
    langs = Counter(m.get("language") for m in clean.values())
    print(f"  语言分布: {dict(langs.most_common(8))}")

    # created_at 月份分布
    months = Counter((m.get('created_at','')[:7]) for m in clean.values())
    print(f"  创建月份分布:")
    for mo in sorted(months):
        print(f"    {mo}: {months[mo]}")

    os.makedirs(os.path.join(DATA, "results"), exist_ok=True)
    json.dump({
        "cutoff": CUTOFF,
        "n_original": len(meta),
        "n_excluded_old": len(excluded_old),
        "n_excluded_topic": len(excluded_topic),
        "n_clean": len(clean),
        "clean_repos": sorted(clean.keys()),
        "excluded_old": excluded_old,
    }, open(os.path.join(DATA, "results", "clean_sample.json"), "w", encoding="utf-8"),
       ensure_ascii=False, indent=2)
    print(f"\n  结果已保存 data/results/clean_sample.json")
    print("=" * 70)

if __name__ == "__main__":
    main()
