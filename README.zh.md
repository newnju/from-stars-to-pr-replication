# 从星标到 PR——Agent Skill 扩散链上的效度边界

[English](README.md)

本仓库是论文《从星标到 PR——Agent Skill 扩散链上的效度边界》的复现代码与结果。论文检验平台指标（星标、安装、fork、PR）能否在扩散链上互相代理：在「注意—安装」与「fork—PR」两处完成支持档检验，在「复制—fork」补做一处不同源检验，其余环节作测量描述。

- 数据截止：2026-10-24
- 复现包版本：2026-11-02
- 语言分层：**中文材料在 `zh/` 下，英文材料在 `en/` 下**；分析代码与数据为两稿共用，不分语言。

---

## 一、目录结构

```
replication/
├── README.md                  英文说明
├── README.zh.md               本文件
├── MANIFEST.csv               本仓库文件的 SHA-256 清单
├── zenodo_MANIFEST.csv        Zenodo 大文件（26 个，1.84 GB）的 SHA-256 清单
├── requirements.txt           Python 依赖
├── code/
│   ├── analysis/              106 个分析与画图脚本（中英两稿共用）
│   └── build/
│       ├── zh/                中文稿源与生成器
│       │   ├── content13.json        《新闻与传播研究》注释体例
│       │   ├── content14.json        《国际新闻界》著者-出版年制
│       │   └── generate_xwycbyj.js / generate_cjjc.js / generate_cover.js
│       └── en/                英文稿源与生成器
│           ├── ica_content.txt        ICA / APA 7 稿源
│           └── generate_ica.js
├── figures/
│   ├── zh/                    中文标注四图（300 dpi，灰度安全）
│   └── en/                    英文标注四图
├── data/                      共享：面板元数据、普查框架、76 个结果文件
│   ├── README.md              数据字典（英文）
│   └── README.zh.md           数据字典（中文）
└── docs/
    ├── zh/                    管线说明、数据来源清单、评审意见存档
    └── en/                    英文数据字典与变量表
```

**大文件不在本仓库**，见第二节。

---

## 二、数据分层：哪些在本仓库，哪些在 Zenodo

原始数据约 16 GB，GitHub 单文件上限 100 MB，故分两处：

| 位置 | 内容 | 体量 |
|---|---|---|
| **本仓库（GitHub）** | 全部代码、76 个结果文件、元数据、八张图、文档 | 约 20 MB |
| **Zenodo 归档（DOI）** | 抓取原文与 API 拉取记录 | 约 2 GB |

Zenodo 归档包含：

| 文件 | 说明 | 体量 |
|---|---|---|
| `skills_with_content.jsonl` | 155,547 份 SKILL.md 全文（内容层） | 1.39 GB |
| `collected_20261024/` | 2026-10-24 一批 API 拉取（PR、审查、评论、市场、近重复、fork→PR） | 233 MB |
| `forks_timestamps_full.json` | 228 父仓全量 fork 时间戳 | 143 MB |
| `gh_discourse.json` | 203 仓的 issue/PR/commit 评论 | 120 MB |

**第三方数据集不重复上传**，按来源引用：

- Gitskills 数据集（`gitskills_parquet/`、`skillmd_138k/train.parquet`）：见 `docs/zh/数据来源全清单.md`
- After the Party 等复现项目材料：同上

---

## 三、环境

```bash
# Python 3.12
pip install -r requirements.txt

# Node 22（仅用于重排正文与封面）
node --version   # >= 18
```

### 路径配置（Python 脚本必读）

`code/analysis/` 下的脚本保留了研究时的绝对路径常量：

```python
ROOT = r"E:\Skill扩散论文_可复现项目"
```

在别处复现时，把每个脚本首部的 `ROOT` 改为本地项目根目录即可。之所以没有统一改成相对路径，是因为这些脚本在探索过程中反复改写过路径，保留原值可以核对当时读的到底是哪一份数据。`code/build/` 下的 Node 生成器已改为相对路径，无需修改。

---

## 四、复现路径（三级）

### 级别 1：从结果文件重画图表、重排正文（最快，无需原始数据）

论文四张图与四张表所需的数字全部在 `data/results/` 中。

```bash
# 中文图
python code/analysis/make_fig1_framework.py       # 图 1
python code/analysis/make_journal_figures.py      # 图 2—4

# 英文图
python code/analysis/make_figures_en.py           # 四图，英文标注
```

中文脚本默认写系统临时目录，运行后需把 PNG 拷回 `figures/zh/`。`make_figures_en.py` 默认写到项目根目录的 `paper_figs/en/`，若在本包内运行，把 `OUT` 常量改为 `figures/en/`。

重排正文：

```bash
cd code/build/zh
npm install
node generate_xwycbyj.js      # 读 content13.json，输出 out_正文.docx
node generate_cjjc.js         # 读 content14.json，输出 out_国际新闻界体例.docx
node generate_cover.js        # 输出 out_投稿封面.docx

cd ../en
node generate_ica.js          # 读 ica_content.txt，输出 out_ICA_manuscript.docx
```

四个生成器均已在本包内实测跑通，图分别从 `figures/zh/`、`figures/en/` 读取。

### 级别 2：从中间数据重算统计量

| 论文结论 | 脚本 | 输入 | 输出 |
|---|---|---|---|
| P1 分层敏感性、中间环节试算 | `compute_mid_chain.py` | `collected_20261024/market_full.jsonl` 等 | 终端输出 |
| 复制→fork 补充检验 | `compute_copy_fork_full.py` | `collected_20261024/near_duplicates.jsonl` + Zenodo 元数据 | `data/results/copy_to_fork_20261031.json` |
| SimHash 召回下界 | `near_recall_bound.py` | `skills_with_content.jsonl` | `data/results/near_recall_bound_20261031.json` |
| P1 主检验与 TOST | `mine_nobel_methods.py` | `data/` | `data/results/mine_nobel_20261030.json` |
| P2 风险模型 | `mine_comprehensive.py` | `collected_20261024/` | `data/results/mine_comprehensive_20261029.json` |
| 整合分析（NMI、动态耦合） | `deep_what_data_shows.py` | `star_history_v2.json`、`fork_prs*.jsonl` | `data/results/deep_what_data_shows_20261030.json` |

### 级别 3：从原始数据全链路

需要先跑 `fetch_*.py` 系列重新采集（需要 GitHub Token，写入 `external_data/_cache/gh_token.txt`），再跑聚合脚本。采集窗口与查询词见 `docs/zh/数据来源全清单.md`。

> 全链路复现约需 6—8 小时（GitHub API 限流 + skills.sh 逐仓查询）。

---

## 五、脚本与论文的对应

| 论文位置 | 脚本 | 结果文件 |
|---|---|---|
| 表 1 数据分层 | `fetch_fork_prs.py`、`fetch_market_full.py` 等采集脚本 | `collected_20261024_summary.json` |
| 表 2 四个核心概念 | 人工整理 | — |
| 表 3 贡献作者结构 | `mine_comprehensive.py` | `mine_comprehensive_20261029.json` |
| 表 4 证据分层 | 汇总自 P1—P5 | 见各检验结果 |
| 图 1 三要件框架 | `make_fig1_framework.py`（中）/ `make_figures_en.py`（英） | — |
| 图 2 P1 | `make_journal_figures.py` / `make_figures_en.py` | `fig_input_p1_p2.json` |
| 图 3 P2 | 同上 | `fig_input_fork_hazard.json` |
| 图 4 P4 | 同上 | `fig_input_p1_p2.json` |
| P1 主检验 | `mine_nobel_methods.py` | `mine_nobel_20261030.json` |
| P1 等价界敏感性 | `compute_mid_chain.py` | 终端输出 |
| P2 首次回流风险 | `mine_comprehensive.py` | `mine_comprehensive_20261029.json` |
| 复制→fork 补充检验 | `compute_copy_fork_full.py` | `copy_to_fork_20261031.json` |
| SimHash 召回下界 | `near_recall_bound.py` | `near_recall_bound_20261031.json` |

其余脚本（`mine_*.py`、`deep*.py`）为历轮探索性挖掘，结果保留在 `data/results/`，论文未全部采用，但构成完整的分析路径。

---

## 六、关键口径（复现前必读）

1. **样本非概率**：341 面板仓是按平台可见性优先纳入的判定样本，占生态扫描 35,947 仓的 0.95%，比率不外推长尾。
2. **安装量口径**：skills.sh 搜索接口返回的 `installs` 字段，按 `source` 等于仓库全名精确匹配后求和；平台未公布统计窗口与去重规则，本文按单一计数处理。
3. **172 个安装命中**：为 `market_full`（146）与 `market_retry`（26）两批合并所得；`market_extra` 的 3 个仓未计入，三批合并为 175。
4. **复制→fork 的样本与 P1、P2 不同源**：取自 2,001 个有跨仓复制边的仓，非 341 面板，故在表 4 中列为「补充」而非「支持档」。
5. **缺失不置零**：安装、审查、fork 时间戳的缺失均按缺失处理，报告中给出覆盖数。

---

## 七、已知限制

- 图 2—4 的输入是中间聚合文件（`fig_input_*.json`），不是从 raw 直接算。
- 表 1—4 的数字未自动回填：改动 `data/results/` 后需手工同步 `content13.json`、`content14.json`、`ica_content.txt` 的表格字段。
- Python 脚本默认写系统临时目录（沙箱限制），运行后需手工拷回。
- `make_journal_figures.py` 中原有的旧版图 1 代码已停用，图 1 只由 `make_fig1_framework.py`（中）或 `make_figures_en.py`（英）生成。

---

## 八、许可与引用

- **代码**：建议 MIT（作者确认后填入 `LICENSE`）
- **数据**：建议 CC BY 4.0
- **引用格式**：待论文正式发表后补充 DOI

复现包版本 2026-11-02。任何数字若有出入，以 `MANIFEST.csv` 所列文件为准。
