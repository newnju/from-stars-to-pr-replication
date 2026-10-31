# -*- coding: utf-8 -*-
"""
analysis/export_203_forks.py —— 把 BigQuery 上的 GH Archive ForkEvent 查询结果
一键导出到 E 盘 data/（CSV + JSON），用于补全 forks_timestamps.json 的 500 条截断。

前置（二选一）：
  A) 已装 gcloud 并登录：  gcloud auth application-default login
     然后直接：            python analysis/export_203_forks.py
  B) 没装 gcloud：在 BigQuery 网页跑 analysis/bigquery_203_forks.sql，
     结果 Save→CSV 下载，再把文件改名放到 data/ 即可，本脚本可跳过。

依赖：google-cloud-bigquery  —— pip install google-cloud-bigquery
查询定义：与 analysis/bigquery_203_forks.sql 完全一致（203 仓库 + 观察窗口）。
"""
import os, sys, csv, json, re

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQL_PATH = os.path.join(BASE, "analysis", "bigquery_203_forks.sql")
OUT_CSV = os.path.join(BASE, "data", "gharchive_forks_203.csv")
OUT_JSON = os.path.join(BASE, "data", "gharchive_forks_203.json")


def main():
    if not os.path.exists(SQL_PATH):
        print("缺少", SQL_PATH)
        return
    sql = open(SQL_PATH, encoding="utf-8").read()
    # 去掉末尾分号与 ORDER BY（导出时排序非必需，且大结果集 ORDER BY 会加成本）
    sql = re.sub(r";\s*$", "", sql.strip())
    try:
        from google.cloud import bigquery
        from google.oauth2 import credentials
    except ImportError:
        print("未装依赖：pip install google-cloud-bigquery")
        return

    # 优先用 ADC；否则回退到 gcloud application-default 凭据
    try:
        client = bigquery.Client()
        client.get_project()          # 触发认证，失败会抛
    except Exception as ex:
        print("认证失败，请先执行：gcloud auth application-default login")
        print("（细节）", type(ex).__name__, ex)
        return

    print("查询中（扫描 2025-09-21~2026-10-04 的 ForkEvent，仅 203 仓库）……")
    rows = list(client.query(sql).result())
    print(f"返回 {len(rows):,} 行")

    cols = [f.name for f in rows[0].keys()] if rows else []
    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c) for c in cols])
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump([{c: str(r.get(c)) for c in cols} for r in rows], f,
                  ensure_ascii=False, indent=1)

    print("已导出：")
    print("  ", OUT_CSV)
    print("  ", OUT_JSON)
    print("下一步：核对行数与仓库数（应覆盖 203 仓库），再把该文件接入 "
          "analysis/v2_panel.py 等脚本替换 forks_timestamps.json。")


if __name__ == "__main__":
    main()