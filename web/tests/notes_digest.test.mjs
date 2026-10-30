// web/shared/notes_digest.mjs 的行为测试：node --test tests/（零依赖，用 Node 标准库）
// 重点是「不裁断」的三条不变量：数值句整句保留或整块降级、段头不在数字中间收尾、
// 结构（目录）永远完整。
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  stripFrontMatter,
  splitSections,
  toUnits,
  extractKeyLines,
  buildNotesDigest,
} from "../shared/notes_digest.mjs";

const LONG_NOTE = `---
paper: 2406.05975
updated: 2026-10-29T03:52:18.446Z
---

# 研究问题
 LIBS 单颗粒光谱直接回归热值时，采样点漂移让模型学到的是颗粒位置而不是煤质。本文把「一袋煤」当成一个 bag，光谱是 instance，标签只在 bag 级。这里的关键假设是袋内光谱分布足以线性表征热值分布。

# 方法
 模型是 ResNet1D 编码器 + TransMIL 注意力聚合，再用 FiLM 把灰分/水分两个协变量注入每层。消融实验对比 mean-pooling 与 attention 两种聚合。数据集 130 个 bag，每袋 110 个颗粒，光谱统一裁剪到 820 个通道。
训练按 5 折交叉验证，seed=42，早停 patience=30，学习率 1e-3。

# 主要结果
| bag | gt_MJ_kg | hybrid_MJ_kg |
| 1 | 25.716 | 25.381 |
| 2 | 25.716 | 24.838 |

混合模型在 val 上的整体指标：RMSE=214.5699±25.7094 kcal/kg，MAE=176.3 kcal/kg，R²=0.93。plsr 基线 RMSE=414.9 kcal/kg，即 MIL 残差修正把误差压低约 48%。

# 结论
结论是注意力聚合显著优于 mean-pooling，说明袋内光谱的稀疏信息点位比均值更值得信。创新点在于把 FiLM 条件调制用到煤质协变量上。

# 局限与待验证
局限是没有跨矿区的迁移实验，样本只来自单一矿区。待验证：1) 单颗粒信噪比对袋级预测的敏感度；2) instance 数量 K 对 RMSE 的影响。无法复现的部分是作者未公开的 4 个训练超参。
`;

test("stripFrontMatter 拿走 YAML 头，正文完整保留", () => {
  const { frontMatter, body } = stripFrontMatter(LONG_NOTE);
  assert.match(frontMatter, /paper: 2406\.05975/);
  assert.doesNotMatch(body, /^---/m);
  assert.match(body, /hybrid_MJ_kg/);
});

test("splitSections 按标题切段，前言段 level=0", () => {
  const { body } = stripFrontMatter(LONG_NOTE);
  const secs = splitSections(body);
  assert.deepEqual(
    secs.map((s) => s.heading),
    ["研究问题", "方法", "主要结果", "结论", "局限与待验证"]
  );
  assert.ok(secs.every((s) => s.chars === s.text.trim().length));
});

test("extractKeyLines：数值句整句原样，一条都不能丢（limit=Infinity 全文扫）", () => {
  const { body } = stripFrontMatter(LONG_NOTE);
  const { matched } = extractKeyLines(body, Infinity);
  const joined = matched.map((k) => k.text).join("\n");
  for (const probe of [
    "RMSE=214.5699±25.7094 kcal/kg", // 核心指标串必须整块出现
    "R²=0.93",
    "seed=42",
    "130 个 bag",
    "| 1 | 25.716 | 25.381 |", // 表格行也是数值单元
  ]) {
    assert.ok(joined.includes(probe), `数值句丢失：${probe}`);
  }
  // 主张句也被收进来（结论/创新/局限/待验证/无法复现）
  assert.ok(matched.some((k) => k.kind.includes("主张") && /创新点/.test(k.text)));
  assert.ok(matched.some((k) => /无法复现的部分/.test(k.text)));
  // 整句保留：没有一条是被截断的（原文里能整句找到）
  for (const k of matched) assert.ok(body.includes(k.text), `非整句保留：${k.text}`);
  // 标题行不进数值句清单（目录里已经有了）
  assert.ok(!matched.some((k) => /^#/.test(k.text)));
});

test("短笔记整篇原样内联：装得下就别做摘要（实测摘要比旧截断更亏）", () => {
  const d = buildNotesDigest(LONG_NOTE);
  assert.equal(d.mode, "full_verbatim");
  const { body } = stripFrontMatter(LONG_NOTE);
  assert.equal(d.text, body.trim());
  assert.ok(d.source_chars <= 4000);
  assert.ok(d.key_lines_total > 5, "整篇内联时也要如实报出这篇有数值句");
  assert.match(d.text, /RMSE=214\.5699±25\.7094 kcal\/kg/);
});

test("buildNotesDigest：预算内联完全部数值句，且总量远小于 4000 硬截断", () => {
  const d = buildNotesDigest(LONG_NOTE, { inlineMax: 0, budget: 2400 });
  assert.equal(d.mode, "digest");
  assert.equal(d.key_lines_status, "inline");
  assert.doesNotMatch(JSON.stringify(d), /2026-10-29T03:52/, "front-matter 的更新时间戳不该进摘要");
  const inlineText = d.key_lines.join("") + d.outline.map((s) => s.head || "").join("");
  assert.ok(inlineText.length <= 2400, `内联文本超预算：${inlineText.length}`);
  assert.ok(d.key_lines.some((s) => s.includes("RMSE=214.5699±25.7094 kcal/kg")));
  // 目录永远完整：五段都在，且带各自字符数
  assert.equal(d.outline.length, 5);
  assert.ok(d.outline.every((s) => s.chars > 0));
});

test("数值句先占预算：预算吃紧时先让散文段头出局，数值句一条不丢", () => {
  // 12 段散文 + 3 条数值句，预算 900 只够数值句和头几段段头
  const prose = (t) => `${t} This section discusses bag-level MIL motivation and cites no numbers at all. `;
  const md = [
    ...Array.from({ length: 12 }, (_, i) => [`# 讨论 ${i + 1}`, prose(`第 ${i + 1} 节只是铺垫，没有可引用的数字。`)]).flat(),
    "# 结果", "RMSE=214.5699 kcal/kg。MAE=176.3 kcal/kg。R²=0.93。",
  ].join("\n");
  const d = buildNotesDigest(md, { inlineMax: 0, budget: 900, sectionHead: 200 });
  assert.equal(d.key_lines_status, "inline", "数值句不该因为预算紧就被整块降级");
  assert.equal(d.key_lines.length, 3);
  assert.ok(d.key_lines.some((s) => s.includes("RMSE=214.5699 kcal/kg")));
  assert.ok(d.outline.filter((s) => s.head === null && s.head_omitted === "budget").length >= 5,
    "预算耗尽后段头应让位并如实标注原因");
  assert.equal(d.outline.length, 13, "目录永远完整，哪怕段头被挤掉");
});

test("段头只在句子/空白边界收尾，绝不落在半个数字上", () => {
  const d = buildNotesDigest(LONG_NOTE, { inlineMax: 0, budget: 2400, sectionHead: 40 });
  for (const s of d.outline) {
    if (!s.head) continue;
    assert.doesNotMatch(s.head, /\d$/, `${s.heading}：段头以数字结尾，疑似切断数值`);
    assert.ok(LONG_NOTE.includes(s.head.replace(/ …$/, "")), `${s.heading}：段头不是原文子串`);
  }
});

test("没有安全边界时宁可不给段头，也不在数字中间切", () => {
  // 400 字符连续无空格无句号的「数字流」：任何切法都会切断数字
  const hell = "数据序列1234567890" + "1".repeat(400);
  const md = `# 附录\n${hell}\n`;
  const d = buildNotesDigest(md, { inlineMax: 0, budget: 2000, keyBudget: 1600, sectionHead: 50 });
  const sec = d.outline[0];
  assert.equal(sec.head, null);
  assert.equal(sec.head_omitted, "no_safe_boundary");
});

test("同形行折叠：只差数字的表格行不配吃掉整块预算", () => {
  const rows = Array.from({ length: 120 }, (_, i) => `| bag ${i} | ${(25 + i / 100).toFixed(3)} | ${(24.9 + i / 100).toFixed(3)} |`).join("\n");
  const md = `# 全部逐袋结果\n${rows}\n\n整体 RMSE=214.5699±25.7094 kcal/kg。\n`;
  const d = buildNotesDigest(md, { inlineMax: 0, budget: 2400, keyBudget: 600 });
  assert.equal(d.key_lines_folded, 115, "同形状只留前 5 条");
  assert.ok(d.key_lines_folded_hint.includes("读全文") || d.key_lines_folded_hint.includes("见全文"));
  // 关键收益：折叠后，唯一的结论句还有预算可用（不折叠时它会被 120 行表格挤出去）
  assert.ok(d.key_lines.some((s) => s.includes("RMSE=214.5699±25.7094 kcal/kg")));
  assert.equal(d.key_lines_status, "inline_with_folds");
  assert.equal(d.key_lines_total, d.key_lines.length + d.key_lines_folded);
});

test("数值句吃紧预算：内联的是「按文档顺序的完整前缀」，剩余如实计数并指向全文", () => {
  // 每行形状都不同（尾列汉字唯一），同形折叠不生效 → 真正装不下的那些要如实报数
  const rows = Array.from({ length: 120 }, (_, i) =>
    `| bag | ${(25 + i / 100).toFixed(3)} | 样品${String.fromCharCode(0x4e00 + i)} |`).join("\n");
  const md = `# 全部逐袋结果\n${rows}\n`;
  const d = buildNotesDigest(md, { inlineMax: 0, budget: 2400, keyBudget: 600 });
  assert.equal(d.key_lines_status, "partial_read_full_text");
  assert.ok(d.key_lines.length > 0, "前缀一条都不给等于没摘要");
  assert.ok(d.key_lines_uninlined > 0 && d.key_lines_uninlined_chars > 0);
  assert.equal(d.key_lines_folded, 0);
  assert.equal(d.key_lines_total, d.key_lines.length + d.key_lines_uninlined + d.long_lines_uninlined);
  // 铁律：内联的每一条都是原文里的整行，不是切半的
  for (const line of d.key_lines) {
    const text = line.replace(/^(数值\+主张|数值|主张)｜/, "");
    assert.ok(md.includes(text), `非整句内联：${text}`);
    assert.match(text, /样品./, "必须完整收尾，不能停在数字中间");
  }
  assert.ok(d.inline_chars <= 2400);
});

test("长句（>500 字符）只登记指纹，不整句内联也不切半句", () => {
  // 整句无句末标点，520+ 字符，含核心指标——切它会切断数值，整句内联会撑爆预算
  const long = "结论：本方法的总体误差为 RMSE=214.5699±25.7094 kcal/kg " + "补充说明".repeat(120);
  const d = buildNotesDigest(`# 超长结论\n${long}\n`, { inlineMax: 0, budget: 2400 });
  assert.equal(d.long_lines_uninlined, 1);
  assert.ok(d.long_lines_hint[0].includes("读原文"));
  assert.ok(d.long_lines_hint[0].includes("整句 " + long.length + " 字符"));
  assert.deepEqual(d.key_lines, []);
  // 唯一那条数值句是长句，进不了内联，但状态不能谎报成「没有数值」
  assert.equal(d.key_lines_status, "read_full_text");
  assert.equal(d.key_lines_total, 1);
});

test("重复数值句去重，保序", () => {
  const md = "# A\nRMSE=214.5699 kcal/kg\n\n# B\nRMSE=214.5699 kcal/kg\n";
  const d = buildNotesDigest(md, { inlineMax: 0 });
  assert.equal(d.key_lines.filter((s) => s.includes("214.5699")).length, 1);
});

test("空笔记/纯空白不炸", () => {
  for (const input of ["", "   \n  ", "---\npaper: x\n---\n\n"]) {
    const d = buildNotesDigest(input);
    assert.equal(d.source_chars, 0);
    assert.deepEqual(d.outline, []);
    assert.equal(d.key_lines_status, "none");
  }
});

test("toUnits：列表行/表格行整体成单元，普通行按句切", () => {
  const units = toUnits("- 创新点是 FiLM 调制。它把灰分当条件。\n| 1 | 25.716 |");
  assert.deepEqual(units, ["- 创新点是 FiLM 调制。它把灰分当条件。", "| 1 | 25.716 |"]);
  assert.deepEqual(toUnits("第一句。第二句！第三句？"), ["第一句。", "第二句！", "第三句？"]);
});
