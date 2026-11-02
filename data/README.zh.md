# 数据说明

## 本目录内容

| 文件 | 说明 |
|---|---|
| `repos_meta.json` | 341 面板仓元数据（stars、forks、created_at、description、topics） |
| `repos_discovered.json` | 同上，早期采集版本 |
| `topic_agent_skills_frame.json` | 24,854 仓普查框架，字段含 `stargazers_count`、`forks_count` |
| `results/` | 76 个结果文件，论文全部数字来源 |

## results/ 中的关键文件

| 文件 | 对应论文 |
|---|---|
| `fig_input_p1_p2.json` | 图 2、图 4 的输入 |
| `fig_input_fork_hazard.json` | 图 3 的输入 |
| `mine_nobel_20261030.json` | P1 主检验（Spearman、TOST、Granger、五渠道秩相关） |
| `mine_comprehensive_20261029.json` | P2、P4 主检验与事件集中度 |
| `copy_to_fork_20261031.json` | 复制→fork 补充检验 |
| `near_recall_bound_20261031.json` | SimHash 召回下界重扫 |
| `collected_20261024_summary.json` | 表 1 各层规模与口径汇总 |
| `fork_prs_final_20261026.json` | P2 终值口径（6.33%/6.67%/3.95%） |

## 未在本目录的数据

原始抓取与 API 拉取记录在 Zenodo 归档（约 2 GB），包括：

- `skills_with_content.jsonl` — 155,547 份 SKILL.md 全文
- `collected_20261024/` — PR、审查、评论、市场、近重复、fork→PR
- `forks_timestamps_full.json` — 228 父仓全量 fork 时间戳
- `gh_discourse.json` — 203 仓的 issue/PR/commit 评论

第三方数据集（Gitskills、After the Party 等）按来源引用，不重复上传，见 `docs/数据来源全清单.md`。
