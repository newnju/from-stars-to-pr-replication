# Data

English | [中文](README.zh.md)

## Contents

| File | Description |
|---|---|
| `repos_meta.json` | Metadata for the 341-repository panel (stars, forks, created_at, description, topics) |
| `repos_discovered.json` | Same schema, earlier collection round |
| `topic_agent_skills_frame.json` | Census frame of 24,854 repositories, including `stargazers_count` and `forks_count` |
| `results/` | 76 result files; every number in the manuscript traces to one of these |

## Key files in `results/`

| File | Used for |
|---|---|
| `fig_input_p1_p2.json` | Input to Figures 2 and 4 |
| `fig_input_fork_hazard.json` | Input to Figure 3 |
| `mine_nobel_20261030.json` | P1 main test (Spearman, TOST, Granger, five-channel rank correlations) |
| `mine_comprehensive_20261029.json` | P2 and P4 main tests; event concentration |
| `copy_to_fork_20261031.json` | Supplementary copy-to-fork test |
| `near_recall_bound_20261031.json` | SimHash recall lower-bound rescan |
| `collected_20261024_summary.json` | Table 1 layer sizes and denominator definitions |
| `fork_prs_final_20261026.json` | P2 final values (6.33% / 6.67% / 3.95%) |
| `deep_what_data_shows_20261030.json` | Integrative analysis: NMI, dynamic coupling, GMM, concentration |

## Not included here

Raw crawl and API pull records are archived on Zenodo (about 2 GB):

- `skills_with_content.jsonl` — full text of 155,547 SKILL.md files
- `collected_20261024/` — PRs, reviews, comments, market data, near-duplicates, fork-to-PR records
- `forks_timestamps_full.json` — complete fork timestamps for 228 parent repositories
- `gh_discourse.json` — issue/PR/commit comments for 203 repositories

Third-party datasets (Gitskills, After the Party, and others) are cited by source rather than re-uploaded; see `docs/zh/数据来源全清单.md`.
