# Data Dictionary (English)

This file defines the variables and result keys used in the manuscript. Chinese counterpart: `docs/zh/图表与排版管线说明.md` and `data/README.zh.md`.

---

## 1. Panel metadata — `data/repos_meta.json`

Keyed by repository full name (`owner/name`).

| Field | Type | Definition |
|---|---|---|
| `stars` | int | Stargazers at collection time (2026-10-24) |
| `forks` | int | Fork count at collection time |
| `created_at` | ISO date | Repository creation date |
| `description` | string | Repository description, as published |
| `topics` | list | GitHub topics |
| `archived` | bool | Whether the repository is archived |

## 2. Census frame — `data/topic_agent_skills_frame.json`

A list of 24,854 repositories discovered by two rounds of topic- and search-based collection, each carrying `full_name`, `stargazers_count`, `forks_count`, `created_at`, `topics`, `description`. The ecosystem-scan layer of Table 1 (35,947 repositories) is the deduplicated union of this frame and the search-based collection; the frame is the subset for which metadata were retrievable.

## 3. Measures

| Measure | Definition | Used in |
|---|---|---|
| Attention | Stars. Treated as the platform's visibility signal, not as adoption | P1 |
| Install | Sum of `installs` over skills returned by the skills.sh search API whose `source` equals the repository full name exactly | P1 |
| Copy out-degree | Number of distinct SHA-256 document hashes of a repository that appear as copies in other repositories | Copy→fork test |
| Fork conversion | Return PRs divided by forks, per parent repository | P2 |
| First return | The first fork→PR event observed for a given fork, censored at the data cut-off | P2 |
| Contribution rate | Return PR events per repository, quartile-discretized for the integrative analysis | Section 5.1 |
| Visibility | Five-channel indicator (stars, skills.sh, ClawHub, release downloads, npm) reduced to a rank | Section 5.1 |

## 4. Key result keys

### `data/results/mine_nobel_20261030.json` (P1)

| Key | Meaning |
|---|---|
| `rho` | Spearman rank correlation between stars and installs (n = 172) |
| `ci95` / `ci90` | Confidence intervals; 90% is the TOST reporting convention, 95% is descriptive |
| `tost.p` | One-sided p for the equivalence test against \|ρ\| = .50 |
| `star_quartiles`, `age_tertiles` | Within-stratum point estimates and intervals |

### `data/results/fig_input_fork_hazard.json` (P2)

| Key | Meaning |
|---|---|
| `curve.times_h` | Hours since fork |
| `curve.cum_pct` | Kaplan–Meier cumulative first-return incidence, in percent |
| `hazard_bins[].bin` | Interval label (`<1h`, `1–24h`, `1–7d`, `7–30d`, `30–90d`, `90–365d`, `>365d`) |
| `hazard_bins[].hazard_pct` | Interval hazard rate, in percent |
| `n_forks` | Denominator forks for the stratum (`overall`, `list`, `non_list`) |

### `data/results/deep_what_data_shows_20261030.json` (integrative)

| Key | Meaning |
|---|---|
| `D1_conversion_mixture` | GMM fit (k = 1–4) on logit and log₁₀ conversion; BIC, KDE modes, bimodality coefficient |
| `D2_regime_coupling.low` / `.high` | Within-repository weekly Spearman correlation between star increments and PR events, split by conversion regime; `median_rho`, `share_sig_p05`, `elasticity_within_repo` |
| `D3_mutual_information.normalized_mi` | Normalized mutual information between quartile-discretized repository variables; `perm_p` gives 500-permutation p-values |
| `D8_concentration_baseline` | Top-5 parent event share, author concentration, conversion with head exclusions |

### `data/results/copy_to_fork_20261031.json`

| Key | Meaning |
|---|---|
| `n_out_gt0_fork_gt0` | Repositories with both copy out-degree and forks above zero (n = 784) |
| `rho` | Spearman correlation between copy out-degree and forks |
| `tost_vs_0.5` | One-sided p for the equivalence test against \|ρ\| = .50 |
| `control_fork_to_stars` | Self-check: fork–star correlation in the same batch |

## 5. Denominators that are easy to confuse

| Figure | Value | Denominator |
|---|---|---|
| 6.33% | Ever-return proportion | 117,169 / 1,851,928 (all forks) |
| 6.36% | One-year Kaplan–Meier incidence | All forks, with censoring weights |
| 6.67% | Fork-layer return rate | 122,235 / 1,832,187 (forks of the 225 fully parsed parents) |
| 87.8% | Share of first returns within 24 hours | Returners only |
| 37.0% | Share of all PR events within 24 hours of return | All PR events of return forks — a different quantity |

These five are not interchangeable. Any comparison across them is a denominator error.
