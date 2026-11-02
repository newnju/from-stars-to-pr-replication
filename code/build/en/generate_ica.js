// generate_ica.js — 生成 ICA 投稿英文稿（APA 7 排版）
// 输入：ica_content.txt（自定义分隔符）+ ../jfig*.png
// 输出：../../ICA_FromStarsToPR_manuscript.docx
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, AlignmentType, BorderStyle,
  Table, TableRow, TableCell, WidthType, ImageRun, Header, Footer,
  PageNumber, TabStopType, TabStopPosition, VerticalAlign, LineRuleType,
} = require("docx");

const DIR = __dirname;
const ROOT = path.join(DIR, "..", "..", "..");   // replication/
const FONT = "Times New Roman";
const BODY = 24;      // 12pt
const SMALL = 20;     // 10pt
const TBL = 18;       // 9pt，表体与表注
const LINE = 480;     // double
const SINGLE = 240;

function runs(text, opts = {}) {
  // *italic* 标记 → 斜体
  const out = [];
  const parts = text.split(/(\*[^*]+\*)/g).filter(Boolean);
  for (const p of parts) {
    const it = p.startsWith("*") && p.endsWith("*") && p.length > 2;
    out.push(new TextRun({
      text: it ? p.slice(1, -1) : p,
      italics: it || opts.italics,
      bold: opts.bold,
      font: FONT,
      size: opts.size || BODY,
    }));
  }
  return out;
}

function bodyP(text, opts = {}) {
  return new Paragraph({
    alignment: AlignmentType.LEFT,
    spacing: { line: LINE, before: 0, after: 0 },
    indent: opts.noIndent ? undefined : { firstLine: 720 },
    children: runs(text, opts),
  });
}

const lines = fs.readFileSync(path.join(DIR, "ica_content.txt"), "utf8")
  .split(/\r?\n/).filter((l) => l.trim().length);

const body = [];
let i = 0;
let runHead = "";
let inAbstract = false;

while (i < lines.length) {
  const line = lines[i];
  const bar = line.indexOf("|");
  const tag = bar < 0 ? "P" : line.slice(0, bar);
  const val = bar < 0 ? line : line.slice(bar + 1);

  if (tag === "TITLE") {
    body.push(new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { line: LINE, before: 0, after: 240 },
      children: [new TextRun({ text: val, bold: true, font: FONT, size: BODY })],
    }));
  } else if (tag === "AUTH") {
    for (const name of val.split(";")) {
      if (!name.trim()) continue;
      body.push(new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { line: LINE, before: 0, after: 0 },
        children: [new TextRun({ text: name.trim(), font: FONT, size: BODY })],
      }));
    }
  } else if (tag === "AFF") {
    body.push(new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { line: LINE, before: 0, after: 200 },
      children: [new TextRun({ text: val, italics: true, font: FONT, size: BODY })],
    }));
  } else if (tag === "RUN") {
    runHead = val;
  } else if (tag === "H1") {
    inAbstract = (val === "Abstract");
    body.push(new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { line: LINE, before: 240, after: 120 },
      keepNext: true,
      children: [new TextRun({ text: val, bold: true, font: FONT, size: BODY })],
    }));
  } else if (tag === "H2") {
    body.push(new Paragraph({
      alignment: AlignmentType.LEFT,
      spacing: { line: LINE, before: 240, after: 60 },
      keepNext: true,
      children: [new TextRun({ text: val, bold: true, font: FONT, size: BODY })],
    }));
  } else if (tag === "P") {
    body.push(bodyP(val, { noIndent: inAbstract }));
  } else if (tag === "KWD") {
    body.push(new Paragraph({
      alignment: AlignmentType.LEFT,
      spacing: { line: LINE, before: 240, after: 0 },
      children: [
        new TextRun({ text: "Keywords: ", italics: true, font: FONT, size: BODY }),
        ...runs(val),
      ],
    }));
  } else if (tag === "R") {
    body.push(new Paragraph({
      alignment: AlignmentType.LEFT,
      spacing: { line: LINE, before: 0, after: 0 },
      indent: { left: 720, hanging: 720 },
      children: runs(val),
    }));
  } else if (tag === "NOTE") {
    const txt = val.replace(/^Note\.\s*/, "");
    body.push(new Paragraph({
      alignment: AlignmentType.LEFT,
      spacing: { line: SINGLE, before: 80, after: 200 },
      children: [
        new TextRun({ text: "Note. ", italics: true, font: FONT, size: TBL }),
        ...runs(txt, { size: TBL }),
      ],
    }));
  } else if (tag === "FIG") {
    const [file, ...rest] = val.split("|");
    const cap = rest.join("|");
    const p = path.join(ROOT, "figures", "en", path.basename(file));
    const buf = fs.readFileSync(p);
    const dim = pngSize(buf);
    const maxW = 600;
    const w = Math.min(maxW, dim.w);
    const h = Math.round(dim.h * (w / dim.w));
    body.push(new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { line: SINGLE, before: 200, after: 80 },
      keepNext: true,
      children: [new ImageRun({ data: buf, transformation: { width: w, height: h }, type: "png" })],
    }));
    body.push(new Paragraph({
      alignment: AlignmentType.LEFT,
      spacing: { line: SINGLE, before: 0, after: 240 },
      children: captionRuns(cap),
    }));
  } else if (tag === "TBL") {
    const cap = val;
    const rows = [];
    i++;
    while (i < lines.length && lines[i].startsWith("ROW|")) {
      rows.push(lines[i].slice(4).split("|"));
      i++;
    }
    if (i < lines.length && lines[i] === "ENDTBL") { /* skip */ }
    body.push(...tableBlock(cap, rows));
  }
  i++;
}

function captionRuns(text) {
  // "Figure 1. xxx" → Figure 1. 加粗，其余常规
  const m = text.match(/^(Figure \d+\.)\s*(.*)$/);
  if (!m) return runs(text, { size: SMALL });
  return [
    new TextRun({ text: m[1] + " ", bold: true, font: FONT, size: SMALL }),
    ...runs(m[2], { size: SMALL }),
  ];
}

function tableBlock(caption, rows) {
  const m = caption.match(/^(Table \d+\.)\s*(.*)$/);
  const num = m ? m[1] : caption;
  const title = m ? m[2] : "";
  const out = [];
  out.push(new Paragraph({
    spacing: { line: SINGLE, before: 240, after: 0 },
    keepNext: true,
    children: [new TextRun({ text: num, bold: true, font: FONT, size: BODY })],
  }));
  out.push(new Paragraph({
    spacing: { line: SINGLE, before: 0, after: 80 },
    keepNext: true,
    children: [new TextRun({ text: title, italics: true, font: FONT, size: BODY })],
  }));

  const ncol = Math.max(...rows.map((r) => r.length));
  const weights = [];
  for (let c = 0; c < ncol; c++) {
    weights.push(Math.max(...rows.map((r) => (r[c] || "").length), 6) + 4);
  }
  const total = 9360;
  const sum = weights.reduce((a, b) => a + b, 0);
  const widths = weights.map((w) => Math.max(700, Math.round((total * w) / sum)));

  const trs = rows.map((cells, ri) => {
    const isHead = ri === 0;
    return new TableRow({
      tableHeader: isHead,
      children: cells.map((cell, ci) => new TableCell({
        width: { size: widths[ci], type: WidthType.DXA },
        margins: { top: 50, bottom: 50, left: 80, right: 80 },
        verticalAlign: VerticalAlign.TOP,
        borders: isHead
          ? { bottom: { style: BorderStyle.SINGLE, size: 6, color: "000000" } }
          : undefined,
        children: [new Paragraph({
          spacing: { line: SINGLE, before: 0, after: 0 },
          children: runs(cell, { size: TBL, bold: isHead }),
        })],
      })),
    });
  });

  out.push(new Table({
    rows: trs,
    width: { size: total, type: WidthType.DXA },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 8, color: "000000" },
      bottom: { style: BorderStyle.SINGLE, size: 8, color: "000000" },
      left: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      right: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      insideHorizontal: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      insideVertical: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
    },
  }));
  out.push(new Paragraph({ spacing: { line: SINGLE, before: 0, after: 0 }, children: [] }));
  return out;
}

function pngSize(buf) {
  return { w: buf.readUInt32BE(16), h: buf.readUInt32BE(20) };
}

const header = new Header({
  children: [new Paragraph({
    tabStops: [{ type: TabStopType.RIGHT, position: 9360 }],
    spacing: { line: SINGLE, before: 0, after: 0 },
    children: [
      new TextRun({ text: runHead, font: FONT, size: 18, color: "000000" }),
      new TextRun({ text: "\t", font: FONT, size: 18 }),
      new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 18 }),
    ],
  })],
});

const doc = new Document({
  creator: "Anonymous",
  title: "From Stars to Pull Requests",
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440, header: 720 },
      },
    },
    headers: { default: header },
    children: body,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  const out = path.join(DIR, "out_ICA_manuscript.docx");
  fs.writeFileSync(out, buf);
  console.log("written", out, buf.length, "bytes");
});
