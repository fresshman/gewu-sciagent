// 结构化提问块的解析测试。
//
// 这块的风险不在「能不能渲染」，而在「渲染错了会怎样」：
// 一个解析得太宽松的实现，会把模型写的普通代码块当成问卷，于是一段示例 JSON
// 变成用户必须回答的问题；一个解析得太严的，又会让 agent 提的问悄悄退回散文。
// 所以两头都钉住：合法的必须认出来，可疑的必须原样放过。

import { test } from "node:test";
import assert from "node:assert";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, join } from "node:path";
import { transformSync } from "esbuild";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = join(HERE, "..");
const OUT_DIR = join(WEB, "node_modules", ".gw-test");
const OUT = join(OUT_DIR, "ask.mjs");

mkdirSync(OUT_DIR, { recursive: true });
writeFileSync(
  OUT,
  transformSync(readFileSync(join(WEB, "src", "lib", "ask.ts"), "utf8"), {
    loader: "ts",
    format: "esm",
    target: "es2022",
  }).code
);
const { parseAsk, stripAsk, answerText } = await import(pathToFileURL(OUT).href);

const fence = (obj) => "```ask\n" + JSON.stringify(obj, null, 2) + "\n```";

const ok = {
  question: "第 5 折的 OOF 预测按哪种口径复算？",
  why: "两种口径的 RMSE 差 3.1%，选错结论会反号",
  options: [
    { label: "合并 OOF", desc: "70 条预测一次性算" },
    { label: "5 折均值" },
  ],
};

test("合法块：问题、解释、选项、单选默认关闭多选", () => {
  const b = parseAsk("正文\n\n" + fence(ok));
  assert.ok(b);
  assert.strictEqual(b.question, ok.question);
  assert.strictEqual(b.why, ok.why);
  assert.strictEqual(b.options.length, 2);
  assert.strictEqual(b.options[0].desc, "70 条预测一次性算");
  assert.strictEqual(b.options[1].desc, undefined);
  assert.strictEqual(b.multi, false);
});

test("multi 只在显式为 true 时生效（字符串 'true' 不算）", () => {
  assert.strictEqual(parseAsk(fence({ ...ok, multi: true })).multi, true);
  assert.strictEqual(parseAsk(fence({ ...ok, multi: "true" })).multi, false);
});

test("没有 ask 围栏的正文不碰", () => {
  assert.strictEqual(parseAsk("就是一段话"), null);
  assert.strictEqual(parseAsk("```python\nprint(1)\n```"), null);
  assert.strictEqual(parseAsk(""), null);
  assert.strictEqual(parseAsk(undefined), null);
});

test("JSON 坏了就当没有：不抛异常，也不猜", () => {
  assert.strictEqual(parseAsk("```ask\n{不是 json}\n```"), null);
  assert.strictEqual(parseAsk("```ask\n```"), null);
});

test("围栏没闭合（流式输出到一半）先不渲染，等闭合再说", () => {
  assert.strictEqual(parseAsk("```ask\n" + JSON.stringify(ok)), null);
});

test("少于两个选项不算问卷", () => {
  assert.strictEqual(parseAsk(fence({ ...ok, options: [{ label: "只有一个" }] })), null);
  assert.strictEqual(parseAsk(fence({ ...ok, options: [] })), null);
  assert.strictEqual(parseAsk(fence({ question: ok.question })), null);
});

test("没有 question 的块不算问卷", () => {
  assert.strictEqual(parseAsk(fence({ options: ok.options })), null);
  assert.strictEqual(parseAsk(fence({ ...ok, question: "   " })), null);
});

test("坏选项被跳过，但剩下的够两个就还能用", () => {
  const b = parseAsk(fence({
    question: "选一个",
    options: [{ label: "" }, { label: "A" }, { nolabel: 1 }, { label: " B " }],
  }));
  assert.deepStrictEqual(b.options.map((o) => o.label), ["A", "B"]);
});

test("选项上限 8：再多就不是一页一题了", () => {
  const many = Array.from({ length: 12 }, (_, i) => ({ label: `选项${i}` }));
  assert.strictEqual(parseAsk(fence({ question: "选", options: many })).options.length, 8);
});

test("stripAsk 只摘围栏，正文原样留着", () => {
  const text = "先给结论：**214.57** kcal/kg。\n\n" + fence(ok) + "\n\n剩下的补充说明。";
  const b = parseAsk(text);
  const body = stripAsk(text, b);
  assert.ok(body.includes("**214.57**"));
  assert.ok(body.includes("剩下的补充说明"));
  assert.ok(!body.includes("```ask"));
  assert.ok(!body.includes("合并 OOF"));
});

test("stripAsk 传 null 时原样返回（解析失败不能吞正文）", () => {
  const text = "```ask\n坏掉的\n```";
  assert.strictEqual(stripAsk(text, null), text);
});

test("answerText：单选取标签本身，多选用顿号连，越界忽略", () => {
  const b = parseAsk(fence(ok));
  assert.strictEqual(answerText(b, [0]), "合并 OOF");
  assert.strictEqual(answerText(b, [1]), "5 折均值");
  assert.strictEqual(answerText({ ...b, multi: true }, [0, 1]), "合并 OOF、5 折均值");
  assert.strictEqual(answerText(b, [99]), "");
  assert.strictEqual(answerText(b, []), "");
});

test("复选时按点击顺序而不是选项顺序拼（用户看到的就是他点的顺序）", () => {
  const b = { ...parseAsk(fence(ok)), multi: true };
  assert.strictEqual(answerText(b, [1, 0]), "5 折均值、合并 OOF");
});
