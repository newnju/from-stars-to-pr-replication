# -*- coding: utf-8 -*-
"""
recover_content2.py — 从最终 docx 反构 content2.json（2026-10-29 应急恢复）
源 content2.json 被意外清空；最新 docx（大修稿5_20261028.docx）内容完整。
按 generate.js 渲染契约逆向提取：
  front: 标题/副标题/摘要/关键词/EN 摘要
  blocks: h1/h2/p/fig/table（按文档顺序）
  endmatter: 带粗体标签的文末声明段
  references: [n] 条目
  figures: 图注→文件映射（按图注关键词识别）
  tables: 表注+单元格（id 按出现顺序重编，块引用一致即可）
输出：content2 JSON 打到 stdout（文件写入被安全软件拦截时走 shell 落盘）。
"""
import json
import sys

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

DOCX = r"E:\Skill扩散论文_可复现项目\扩散的弱耦合_大修稿5_20261028.docx"

FIGMAP = [
    ("复制结构", "fig1_copy_structure.png"),
    ("字段保留率", "fig2_retention.png"),
    ("洛伦兹", "fig3_attention.png"),
    ("五渠道可见性", "fig4_visibility.png"),
    ("创建月队列", "fig5_lifecycle.png"),
    ("治理三联", "fig6_governance.png"),
    ("回流时间分布", "fig7_hazard.png"),
    ("技能类型学", "fig8_typology.png"),
    ("复制网络", "fig9_copy_network.png"),
    ("安全披露", "fig10_event_window.png"),
]


def iter_blocks(doc):
    for child in doc.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            yield Paragraph(child, doc)
        elif tag == "tbl":
            yield Table(child, doc)


def has_image(p):
    x = p._element.xml
    return "<w:drawing" in x or "<pic:pic" in x


def runs_text(p):
    return "".join(r.text or "" for r in p.runs)


def main():
    doc = Document(DOCX)
    items = list(iter_blocks(doc))

    out = {"title": "", "subtitle": "", "abstract": "", "keywords": "",
           "blocks": [], "tables": {}, "figures": {}, "references": [],
           "abstract_en": "", "keywords_en": "", "endmatter": []}

    # 识别各区域
    idx_first_h1 = None
    idx_refs_h1 = None
    for i, it in enumerate(items):
        if isinstance(it, Paragraph):
            st = it.style.name or ""
            tx = runs_text(it).strip()
            if st.startswith("Heading 1") and idx_first_h1 is None and tx != "参考文献":
                idx_first_h1 = i
            if st.startswith("Heading 1") and tx == "参考文献":
                idx_refs_h1 = i
                break
    assert idx_first_h1 is not None and idx_refs_h1 is not None, "结构定位失败"

    # ---- front ----
    for it in items[:idx_first_h1]:
        if not isinstance(it, Paragraph):
            continue
        tx = runs_text(it)
        st = it.style.name or ""
        if not out["title"] and st.startswith("Heading") is False and tx.strip() and not out["title"]:
            # 第一段为标题（居中加粗大字），第二段为副标题
            if not out["title"]:
                out["title"] = tx.strip()
                continue
        if out["title"] and not out["subtitle"] and tx.strip() and "摘" not in tx[:3] and "Abstract" not in tx[:9]:
            out["subtitle"] = tx.strip()
            continue
        if tx.startswith("摘　要：") or tx.startswith("摘要："):
            out["abstract"] = tx.split("：", 1)[1].strip()
        elif tx.startswith("关键词："):
            out["keywords"] = tx.split("：", 1)[1].strip()
        elif tx.startswith("Abstract: "):
            out["abstract_en"] = tx[len("Abstract: "):].strip()
        elif tx.startswith("Keywords: "):
            out["keywords_en"] = tx[len("Keywords: "):].strip()

    # ---- body + endmatter + refs ----
    table_seq = 0
    fig_seq = 0
    mode = "body"          # body -> end -> refs
    pend_caption = None    # (kind, text)
    ref_no = 1
    for it in items[idx_first_h1:idx_refs_h1]:
        if isinstance(it, Table):
            table_seq += 1
            tid = f"xt{table_seq}"
            rows = [[c.text.strip() for c in r.cells] for r in it.rows]
            caption = pend_caption[1] if pend_caption and pend_caption[0] == "table" else f"表 {table_seq}"
            out["tables"][tid] = {"caption": caption, "header": rows[0], "rows": rows[1:]}
            out["blocks"].append({"t": "table", "id": tid})
            pend_caption = None
            continue

        tx = runs_text(it)
        st = it.style.name or ""
        bold0 = bool(it.runs) and bool(it.runs[0].bold)

        if has_image(it):
            pend_caption = ("fig", None)
            continue

        if pend_caption and pend_caption[0] == "fig":
            # 图注段
            fig_seq += 1
            cap = tx.strip()
            fname = next((f for kw, f in FIGMAP if kw in cap), f"fig{fig_seq}.png")
            fid = f"xf{fig_seq}"
            out["figures"][fid] = {"file": fname, "caption": cap}
            out["blocks"].append({"t": "fig", "id": fid})
            pend_caption = None
            continue

        if st.startswith("Heading 1"):
            out["blocks"].append({"t": "h1", "x": tx.strip()})
            continue
        if st.startswith("Heading 2"):
            out["blocks"].append({"t": "h2", "x": tx.strip()})
            continue

        # 表注：加粗居中短段（后随 Table）
        if bold0 and len(tx.strip()) < 80 and tx.strip().startswith("表"):
            pend_caption = ("table", tx.strip())
            continue

        # 文末声明：首 run 粗体且以：结尾
        if it.runs and it.runs[0].bold and (it.runs[0].text or "").endswith("：") and len(it.runs) >= 2:
            label = (it.runs[0].text or "")[:-1]
            body = "".join((r.text or "") for r in it.runs[1:])
            out["endmatter"].append([label, body])
            continue

        if tx.strip():
            out["blocks"].append({"t": "p", "x": tx})

    # ---- references ----
    for it in items[idx_refs_h1:]:
        if not isinstance(it, Paragraph):
            continue
        tx = runs_text(it).strip()
        if tx == "参考文献":
            continue
        if tx.startswith(f"[{ref_no}]"):
            out["references"].append(tx[len(f"[{ref_no}]"):].strip())
            ref_no += 1
        elif tx.startswith("["):
            # 连续编号容错
            try:
                n = int(tx[1:tx.index("]")])
                out["references"].append(tx[tx.index("]") + 1:].strip())
                ref_no = n + 1
            except Exception:
                pass

    print(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"# recovered: blocks={len(out['blocks'])} tables={len(out['tables'])} "
          f"figs={len(out['figures'])} refs={len(out['references'])} "
          f"endmatter={len(out['endmatter'])}", file=sys.stderr)


if __name__ == "__main__":
    main()
