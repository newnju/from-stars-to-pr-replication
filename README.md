# From Stars to Pull Requests — Replication Package

[中文](README.zh.md)

Replication code and results for *From Stars to Pull Requests: Validity Boundaries along the Agent Skill Diffusion Chain*. The paper asks whether platform metrics (stars, installs, forks, pull requests) can stand in for one another along a diffusion chain. Two segments receive supported-tier tests (attention–installation; fork–PR), one mid-chain segment is tested on a different-source sample (copy–fork), and the remaining segments are reported as measurement descriptions.

- Data cut-off: 2026-10-24
- Package version: 2026-11-02
- Language split: **Chinese materials under `zh/`, English materials under `en/`**. Shared analysis code and data are language-neutral.

---

## 1. Structure

```
replication/
├── README.md                  this file (English)
├── README.zh.md               Chinese README
├── MANIFEST.csv               SHA-256 for every file in this repository
├── zenodo_MANIFEST.csv        SHA-256 for the 26 large files archived on Zenodo (1.84 GB)
├── requirements.txt
├── code/
│   ├── analysis/              106 analysis and figure scripts (shared by both language versions)
│   └── build/
│       ├── zh/                Chinese manuscript sources and generators
│       │   ├── content13.json         《新闻与传播研究》注释体例
│       │   ├── content14.json         《国际新闻界》著者-出版年制
│       │   └── generate_xwycbyj.js / generate_cjjc.js / generate_cover.js
│       └── en/                English manuscript source and generator
│           ├── ica_content.txt        ICA / APA 7 manuscript source
│           └── generate_ica.js
├── figures/
│   ├── zh/                    four journal figures, Chinese labels
│   └── en/                    four journal figures, English labels
├── data/                      shared: panel metadata, census frame, 76 result files
│   ├── README.md              data dictionary (English)
│   └── README.zh.md           data dictionary (Chinese)
└── docs/
    ├── zh/                    pipeline notes, data-source inventory, review memos
    └── en/                    data dictionary, variable list
```

Large files are not in this repository; see §2.

---

## 2. What is here and what is on Zenodo

Raw data total about 16 GB, and GitHub caps single files at 100 MB, so the package is split:

| Location | Contents | Size |
|---|---|---|
| **This repository** | all code, 76 result files, metadata, eight figures, documentation | about 20 MB |
| **Zenodo (DOI)** | raw crawls and API pull records | about 2 GB |

Zenodo archive:

| File | Contents | Size |
|---|---|---|
| `skills_with_content.jsonl` | full text of 155,547 SKILL.md files (content layer) | 1.39 GB |
| `collected_20261024/` | API pulls of 2026-10-24: PRs, reviews, comments, market, near-duplicates, fork-to-PR | 233 MB |
| `forks_timestamps_full.json` | complete fork timestamps for 228 parent repositories | 143 MB |
| `gh_discourse.json` | issue/PR/commit comments for 203 repositories | 120 MB |

Third-party datasets (Gitskills, After the Party, and others) are cited by source and not re-uploaded; see `docs/zh/数据来源全清单.md`.

---

## 3. Environment

```bash
# Python 3.12
pip install -r requirements.txt

# Node 22 (only for rebuilding the manuscripts)
node --version   # >= 18
```

### Path configuration (required for Python scripts)

Scripts in `code/analysis/` keep the absolute path constant used during the study:

```python
ROOT = r"E:\Skill扩散论文_可复现项目"
```

Change `ROOT` at the top of each script to your local project root. The values were deliberately left as they were: these scripts were rewritten many times during exploration, and the original paths record which copy of the data each run actually read. The Node generators under `code/build/` use relative paths and need no editing.

---

## 4. Reproduction paths (three levels)

### Level 1 — redraw figures and rebuild manuscripts (no raw data needed)

Every number in the four figures and four tables is in `data/results/`.

```bash
# Chinese figures
python code/analysis/make_fig1_framework.py       # Figure 1
python code/analysis/make_journal_figures.py      # Figures 2–4

# English figures
python code/analysis/make_figures_en.py           # all four, English labels
```

The Chinese scripts write to the system temp directory by default; copy the PNGs into `figures/zh/`. `make_figures_en.py` writes directly to `paper_figs/en/` in the project root — change its `OUT` constant to `figures/en/` if you run it inside this package.

Rebuild the manuscripts:

```bash
cd code/build/zh
npm install
node generate_xwycbyj.js      # reads content13.json -> out_正文.docx
node generate_cjjc.js         # reads content14.json -> out_国际新闻界体例.docx
node generate_cover.js        # -> out_投稿封面.docx

cd ../en
node generate_ica.js          # reads ica_content.txt -> out_ICA_manuscript.docx
```

All four generators were tested inside this package; they read figures from `figures/zh/` and `figures/en/` respectively.

### Level 2 — recompute statistics from intermediate data

| Claim | Script | Input | Output |
|---|---|---|---|
| P1 stratified sensitivity, mid-chain trial | `compute_mid_chain.py` | `collected_20261024/market_full.jsonl` and others | console |
| Copy-to-fork supplementary test | `compute_copy_fork_full.py` | `collected_20261024/near_duplicates.jsonl` plus Zenodo metadata | `data/results/copy_to_fork_20261031.json` |
| SimHash recall lower bound | `near_recall_bound.py` | `skills_with_content.jsonl` | `data/results/near_recall_bound_20261031.json` |
| P1 main test and TOST | `mine_nobel_methods.py` | `data/` | `data/results/mine_nobel_20261030.json` |
| P2 hazard model | `mine_comprehensive.py` | `collected_20261024/` | `data/results/mine_comprehensive_20261029.json` |
| Integrative NMI and dynamic coupling | `deep_what_data_shows.py` | `star_history_v2.json`, `fork_prs*.jsonl` | `data/results/deep_what_data_shows_20261030.json` |

### Level 3 — full pipeline from raw data

Re-run the `fetch_*.py` series first (a GitHub token is required, written to `external_data/_cache/gh_token.txt`), then the aggregation scripts. Collection windows and query terms are documented in `docs/zh/数据来源全清单.md`.

> A full re-run takes about 6–8 hours, dominated by GitHub API rate limits and per-repository queries to skills.sh.

---

## 5. Script-to-paper map

| Paper element | Script | Result file |
|---|---|---|
| Table 1 data layers | `fetch_fork_prs.py`, `fetch_market_full.py` and other collectors | `collected_20261024_summary.json` |
| Table 2 four concepts | manual | — |
| Table 3 contributor structure | `mine_comprehensive.py` | `mine_comprehensive_20261029.json` |
| Table 4 evidence tiers | summary of P1–P5 | see individual result files |
| Figure 1 framework | `make_fig1_framework.py` (zh) / `make_figures_en.py` (en) | — |
| Figure 2 P1 | `make_journal_figures.py` / `make_figures_en.py` | `fig_input_p1_p2.json` |
| Figure 3 P2 | same | `fig_input_fork_hazard.json` |
| Figure 4 P4 | same | `fig_input_p1_p2.json` |
| P1 main test | `mine_nobel_methods.py` | `mine_nobel_20261030.json` |
| P1 equivalence-bound sensitivity | `compute_mid_chain.py` | console |
| P2 first-return hazard | `mine_comprehensive.py` | `mine_comprehensive_20261029.json` |
| Copy-to-fork supplementary test | `compute_copy_fork_full.py` | `copy_to_fork_20261031.json` |
| SimHash recall lower bound | `near_recall_bound.py` | `near_recall_bound_20261031.json` |

The remaining scripts (`mine_*.py`, `deep*.py`) are exploratory rounds; their outputs are kept in `data/results/`. The paper does not use all of them, but they document the full analytic path.

---

## 6. Definitions that must be read before reproducing

1. **Non-probability sample.** The 341-repository panel is an adjudication sample prioritized by platform visibility, 0.95% of the 35,947-repository ecosystem scan. Ratios are not extrapolated to the long tail.
2. **Install counts.** The `installs` field returned by the skills.sh search API, summed after exact matching on `source` equal to the repository full name. The platform does not publish its statistical window or deduplication rule, so the value is treated as a single count.
3. **172 install hits.** The merge of `market_full` (146) and `market_retry` (26). The three repositories in `market_extra` are excluded; all three batches together would give 175.
4. **Copy-to-fork uses a different sample.** It draws on repositories with cross-repository copying edges, not the 341 panel, and is therefore labelled supplementary rather than supported in Table 4.
5. **Missing is not zero.** Missing installs, reviews, and fork timestamps are treated as missing; coverage counts are reported.

---

## 7. Known limitations

- Inputs to Figures 2–4 are intermediate aggregates (`fig_input_*.json`), not computed directly from raw data.
- Numbers in Tables 1–4 are not auto-populated: after changing `data/results/`, the `tables` field of `content13.json` / `content14.json` / `ica_content.txt` must be updated by hand.
- Python scripts write to the system temp directory by default; outputs must be copied back manually.
- The legacy Figure 1 code inside `make_journal_figures.py` is disabled; Figure 1 comes only from `make_fig1_framework.py` (zh) or `make_figures_en.py` (en).

---

## 8. License and citation

- **Code**: MIT recommended (to be confirmed by the author in `LICENSE`)
- **Data**: CC BY 4.0 recommended
- **Citation**: DOI to be added after publication

Package version 2026-11-02. If any number disagrees, the files listed in `MANIFEST.csv` are authoritative.
