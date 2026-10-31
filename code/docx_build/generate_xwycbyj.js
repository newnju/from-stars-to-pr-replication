/* generate_xwycbyj.js —— 《新闻与传播研究》体例版
 * 版式：A4；每页 38 行、每行 41 字；正文五号宋体；注释体例（页下注、每页独立编号、①②③）；不设文末参考文献
 */
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  ImageRun, AlignmentType, HeadingLevel, WidthType, BorderStyle,
  Footer, PageNumber, FootnoteReferenceRun, FootnotePosition, NoteNumberRestart, NumberFormat,
} = require("docx");
const fs = require("fs");
const path = require("path");

const TMP = __dirname;   // 复现包：内容源与输出都在本目录
const C = JSON.parse(fs.readFileSync(path.join(TMP, "content13.json"), "utf-8"));
const FIGDIR = path.join(__dirname, "..", "..", "figures");
const OUT = path.join(__dirname, "out_正文.docx");

const NB = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const SONG = { ascii: "Times New Roman", eastAsia: "SimSun" };
const HEI = { ascii: "Times New Roman", eastAsia: "SimHei" };
const TNR = { ascii: "Times New Roman", eastAsia: "SimSun" };

const SZ_BODY = 21;    // 五号 10.5pt
const SZ_SMALL = 18;   // 小五 9pt
const SZ_H1 = 24;      // 小四 12pt
const SZ_TITLE = 32;   // 三号 16pt
const SZ_SUB = 28;     // 四号 14pt
const LINE = 367;      // 固定行距 18.4pt → 每页 38 行
const INDENT = 420;    // 首行缩进 2 字符（2 × 10.5pt）

function pngSize(buf) {
  return { w: buf.readUInt32BE(16), h: buf.readUInt32BE(20) };
}

// ---------- 脚注文本：*…* 解析为斜体 ----------
function noteRuns(text, size) {
  const out = [];
  const parts = String(text).split("*");
  for (let i = 0; i < parts.length; i++) {
    if (!parts[i]) continue;
    out.push(new TextRun({
      text: parts[i], size: size || SZ_SMALL, font: SONG,
      italics: i % 2 === 1, color: "000000",
    }));
  }
  return out;
}

const NOTES = C.refNotes || {};
function refNote(nums) {
  return nums.split(",").map((n) => NOTES[n.trim()] || "").filter(Boolean).join("；");
}

// ---------- 正文段：五号宋体，固定行距，首行缩进 2 字符 ----------
function bodyP(text) {
  const re = /\[\[(REF:[^\]]+|FN:[^\]]+)\]\]/;
  const children = [];
  let rest = String(text);
  while (true) {
    const m = re.exec(rest);
    if (!m) { if (rest) children.push(new TextRun({ text: rest, size: SZ_BODY, font: SONG })); break; }
    if (m.index > 0) children.push(new TextRun({ text: rest.slice(0, m.index), size: SZ_BODY, font: SONG }));
    const raw = m[1];
    const note = raw.startsWith("REF:") ? refNote(raw.slice(4)) : raw.slice(3);
    children.push(new FootnoteReferenceRun({
      children: [new Paragraph({
        spacing: { line: 240 },
        indent: { left: 0, hanging: 0 },
        children: noteRuns(note),
      })],
    }));
    rest = rest.slice(m.index + m[0].length);
  }
  return new Paragraph({
    alignment: AlignmentType.JUSTIFIED,
    indent: { firstLine: INDENT },
    spacing: { line: LINE, lineRule: "exact", before: 0, after: 0 },
    children,
  });
}

// 一级标题：小四黑体，左对齐
function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    alignment: AlignmentType.LEFT,
    spacing: { before: 150, after: 80, line: LINE, lineRule: "exact" },
    keepNext: true,
    children: [new TextRun({ text, bold: true, size: SZ_H1, font: HEI, color: "000000" })],
  });
}
// 二级标题：五号黑体，左对齐
function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    alignment: AlignmentType.LEFT,
    spacing: { before: 90, after: 50, line: LINE, lineRule: "exact" },
    keepNext: true,
    children: [new TextRun({ text, bold: true, size: SZ_BODY, font: HEI, color: "000000" })],
  });
}

function figure(fid) {
  const f = C.figures[fid];
  const buf = fs.readFileSync(path.join(FIGDIR, f.file));
  const { w, h } = pngSize(buf);
  const maxW = 565;                       // 版心 15.19cm ≈ 574px
  const dw = Math.min(maxW, w);
  const dh = Math.round(dw * (h / w));
  return [
    new Paragraph({
      keepNext: true, alignment: AlignmentType.CENTER,
      spacing: { before: 80, after: 40, line: 240 },
      children: [new ImageRun({ data: buf, transformation: { width: dw, height: dh }, type: "png" })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER, spacing: { before: 0, after: f.note ? 20 : 120, line: 260 },
      children: [new TextRun({ text: f.caption, size: SZ_SMALL, font: SONG, color: "000000" })],
    }),
    ...(f.note ? [new Paragraph({
      alignment: AlignmentType.JUSTIFIED, spacing: { before: 0, after: 120, line: 240 },
      children: [new TextRun({ text: f.note, size: SZ_SMALL, font: SONG, color: "000000" })],
    })] : []),
  ];
}

function threeLine(tid) {
  const t = C.tables[tid];
  const widths = t.widths || t.header.map(() => Math.floor(100 / t.header.length));
  const mk = (text, bold, isHeader, idx, isLast) => new TableCell({
    borders: isHeader
      ? { top: NB, left: NB, right: NB, bottom: { style: BorderStyle.SINGLE, size: 2, color: "000000" } }
      : { top: NB, left: NB, right: NB, bottom: NB },
    margins: { top: 50, bottom: 50, left: 70, right: 70 },
    width: { size: widths[idx], type: WidthType.PERCENTAGE },
    children: [new Paragraph({
      alignment: (t.aligns && t.aligns[idx] === "left") ? AlignmentType.LEFT
        : (t.aligns && t.aligns[idx] === "right") ? AlignmentType.RIGHT : AlignmentType.CENTER,
      spacing: { line: 220 }, keepNext: !isLast,
      children: [new TextRun({ text: String(text), bold: !!bold, size: SZ_SMALL, font: SONG, color: "000000" })],
    })],
  });
  return [
    new Paragraph({
      keepNext: true, alignment: AlignmentType.CENTER,
      spacing: { before: 140, after: 50, line: 260 },
      children: [new TextRun({ text: t.caption, size: SZ_SMALL, bold: true, font: SONG, color: "000000" })],
    }),
    new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      borders: {
        top: { style: BorderStyle.SINGLE, size: 4, color: "000000" },
        bottom: { style: BorderStyle.SINGLE, size: 4, color: "000000" },
        left: NB, right: NB, insideHorizontal: NB, insideVertical: NB,
      },
      rows: [
        new TableRow({ tableHeader: true, cantSplit: true,
          children: t.header.map((x, i) => mk(x, true, true, i, false)) }),
        ...t.rows.map((r, ri) => new TableRow({ cantSplit: true,
          children: r.map((x, i) => mk(x, false, false, i, ri === t.rows.length - 1)) })),
      ],
    }),
    new Paragraph({ spacing: { after: t.note ? 10 : 40, line: 240 }, children: [] }),
    ...(t.note ? [new Paragraph({
      alignment: AlignmentType.JUSTIFIED, spacing: { before: 0, after: 120, line: 240 },
      children: [new TextRun({ text: t.note, size: SZ_SMALL, font: SONG, color: "000000" })],
    })] : []),
  ];
}

// ---------- 题名、摘要、关键词 ----------
const front = [
  new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { before: 0, after: 100, line: 400 },
    children: [new TextRun({ text: C.title, bold: true, size: SZ_TITLE, font: HEI, color: "000000" })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { after: 220, line: 340 },
    children: [new TextRun({ text: C.subtitle, bold: true, size: SZ_SUB, font: HEI, color: "000000" })],
  }),
  new Paragraph({
    alignment: AlignmentType.JUSTIFIED, indent: { firstLine: 0 },
    spacing: { line: 260, after: 60 },
    children: [
      new TextRun({ text: "摘要：", bold: true, size: SZ_BODY, font: HEI }),
      new TextRun({ text: C.abstract, size: SZ_BODY, font: SONG }),
    ],
  }),
  new Paragraph({
    alignment: AlignmentType.JUSTIFIED, indent: { firstLine: 0 },
    spacing: { line: 260, after: 160 },
    children: [
      new TextRun({ text: "关键词：", bold: true, size: SZ_BODY, font: HEI }),
      new TextRun({ text: C.keywords, size: SZ_BODY, font: SONG }),
    ],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { before: 80, after: 60, line: 300 },
    children: [new TextRun({ text: C.title_en || "", bold: true, size: SZ_BODY, font: TNR, color: "000000" })],
  }),
  new Paragraph({
    alignment: AlignmentType.JUSTIFIED, indent: { firstLine: 0 },
    spacing: { line: 260, after: 40 },
    children: [
      new TextRun({ text: "Abstract: ", bold: true, size: SZ_BODY, font: TNR }),
      new TextRun({ text: C.abstract_en, size: SZ_BODY, font: TNR }),
    ],
  }),
  new Paragraph({
    alignment: AlignmentType.JUSTIFIED, indent: { firstLine: 0 },
    spacing: { line: 260, after: 200 },
    children: [
      new TextRun({ text: "Key words: ", bold: true, size: SZ_BODY, font: TNR }),
      new TextRun({ text: C.keywords_en, size: SZ_BODY, font: TNR }),
    ],
  }),
];

const body = [];
for (const b of C.blocks) {
  if (b.t === "h1") body.push(h1(b.x));
  else if (b.t === "h2") body.push(h2(b.x));
  else if (b.t === "h3") body.push(h2(b.x));
  else if (b.t === "p") body.push(bodyP(b.x));
  else if (b.t === "ref") body.push(new Paragraph({
    alignment: AlignmentType.JUSTIFIED,
    indent: { left: 480, hanging: 480 },
    spacing: { line: LINE, lineRule: "exact", before: 0, after: 0 },
    children: [new TextRun({ text: b.x, size: SZ_SMALL, font: SONG, color: "000000" })],
  }));
  else if (b.t === "fig") body.push(...figure(b.id));
  else if (b.t === "table") body.push(...threeLine(b.id));
}

const doc = new Document({
  styles: {
    default: {
      document: {
        run: { font: SONG, size: SZ_BODY, color: "000000" },
        paragraph: { spacing: { line: LINE, lineRule: "exact" } },
      },
      footnoteText: { run: { font: SONG, size: SZ_SMALL }, paragraph: { spacing: { line: 220 } } },
    },
  },
  sections: [{
    properties: {
      page: {
        size: { width: 11906, height: 16838 },                 // A4
        margin: { top: 1440, bottom: 1440, left: 1645, right: 1645, footer: 500, header: 500 },
      },
      footnoteProperties: {
        position: FootnotePosition.PAGE_BOTTOM,
        numberFormat: { type: NumberFormat.DECIMAL_ENCLOSED_CIRCLE },
        restart: NoteNumberRestart.EACH_PAGE,
      },
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ children: [PageNumber.CURRENT], size: SZ_SMALL, font: SONG })],
        })],
      }),
    },
    children: [...front, ...body],
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(OUT, buf);
  console.log("WROTE", OUT, buf.length, "bytes");
});
