/* generate_cover.js — 《新闻与传播研究》投稿封面 */
const { Document, Packer, Paragraph, TextRun, AlignmentType } = require("docx");
const fs = require("fs");
const path = require("path");
const C = JSON.parse(fs.readFileSync(path.join(__dirname, "content13.json"), "utf-8"));
const OUT = path.join(__dirname, "out_投稿封面.docx");
const SONG = { ascii: "Times New Roman", eastAsia: "SimSun" };
const HEI = { ascii: "Times New Roman", eastAsia: "SimHei" };
const TNR = { ascii: "Times New Roman", eastAsia: "SimSun" };

const p = (text, opt = {}) => new Paragraph({
  alignment: opt.center ? AlignmentType.CENTER : AlignmentType.JUSTIFIED,
  indent: opt.center ? undefined : { firstLine: 420 },
  spacing: { line: 300, before: opt.before || 0, after: opt.after || 80 },
  children: [new TextRun({
    text, bold: !!opt.bold, size: opt.size || 21,
    font: opt.hei ? HEI : (opt.tnr ? TNR : SONG), color: "000000",
  })],
});

const doc = new Document({
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    children: [
      p(C.title, { center: true, bold: true, size: 32, hei: true, before: 200, after: 60 }),
      p(C.subtitle, { center: true, bold: true, size: 28, hei: true, after: 160 }),
      p("作者姓名：＿＿＿＿＿＿　＿＿＿＿＿＿　＿＿＿＿＿＿", { center: true, size: 24, after: 200 }),
      p("内容提要：" + C.abstract, { size: 21 }),
      p("关键词：" + C.keywords, { size: 21, after: 160 }),
      p(C.title_en, { center: true, bold: true, size: 24, tnr: true, before: 160, after: 100 }),
      p("Abstract: " + C.abstract_en, { size: 21, tnr: true }),
      p("Key words: " + C.keywords_en, { size: 21, tnr: true, after: 200 }),
      p("作者简介：姓名＿＿＿＿；出生年月＿＿＿＿；性别＿＿；民族＿＿；籍贯＿＿＿＿；学历＿＿＿＿；研究方向＿＿＿＿＿＿；职务＿＿＿＿；职称＿＿＿＿。", { size: 21 }),
      p("联系方式：手机＿＿＿＿＿＿＿＿＿＿；电子信箱＿＿＿＿＿＿＿＿＿＿；样刊邮寄地址＿＿＿＿＿＿＿＿＿＿＿＿；邮政编码＿＿＿＿＿＿。", { size: 21 }),
      p("基金项目：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿（无则不填）。", { size: 21 }),
      p("作者声明：本文专投《新闻与传播研究》，未一稿多投。", { size: 21, after: 200 }),
      p("说明：正文文件已匿名化，未出现作者信息；本页仅供投稿系统与编辑部联系使用。", { size: 18 }),
    ],
  }],
});
Packer.toBuffer(doc).then(buf => { fs.writeFileSync(OUT, buf); console.log("WROTE", OUT, buf.length); });
