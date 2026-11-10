// Markdown 渲染器的结构测试。
//
// 为什么要测：这份渲染器输出的是 React 元素树，肉眼只能看出「大概像」；
// 而真会让用户踩到的是边界——代码块里的星号不该变粗体、表格少一列不能错位、
// 流式半截围栏不能把后面的正文吞掉。这些用字符串断言最省事。
//
// 实现方式：markdown.tsx 是 TSX，node 直接 import 不了。这里用 esbuild 现场
// 转成 JS 落到 node_modules/.gw-test/（在项目内，裸模块名才解析得到），再 import。

import { test } from "node:test";
import assert from "node:assert";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, join } from "node:path";
import { transformSync } from "esbuild";
import { renderToStaticMarkup } from "react-dom/server";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = join(HERE, "..");
const SRC = join(WEB, "src", "lib", "markdown.tsx");
const OUT_DIR = join(WEB, "node_modules", ".gw-test");
const OUT = join(OUT_DIR, "markdown.mjs");

mkdirSync(OUT_DIR, { recursive: true });
const code = transformSync(readFileSync(SRC, "utf8"), {
  loader: "tsx",
  format: "esm",
  jsx: "automatic",
  target: "es2022",
}).code;
writeFileSync(OUT, code, "utf8");

const { renderMarkdown } = await import(pathToFileURL(OUT).href);

/** 渲染成 HTML 字符串，省得在断言里遍历元素树 */
const html = (src) => renderToStaticMarkup(renderMarkdown(src));

test("标题按层级降级，气泡里不会出现 h1", () => {
  assert.match(html("# 一级"), /<h3[^>]*>一级<\/h3>/);
  assert.match(html("### 三级"), /<h5[^>]*>三级<\/h5>/);
  assert.strictEqual(html("####### 七个井号").includes("<h"), false);
});

test("粗体先于斜体，不把 **x** 拆成两个斜体", () => {
  const out = html("这是**重点**内容");
  assert.match(out, /<strong>重点<\/strong>/);
  assert.strictEqual(out.includes("<em>"), false);
});

test("行内代码里的星号与竖线原样保留", () => {
  const out = html("用 `a**b**c` 表示");
  assert.match(out, /<code class="md-code">a\*\*b\*\*c<\/code>/);
});

test("围栏代码块内不做任何行内解析", () => {
  const out = html("```python\nx = **not bold**\n```");
  assert.match(out, /class="md-pre"/);
  assert.match(out, /\*\*not bold\*\*/);
  assert.strictEqual(out.includes("<strong>"), false);
  // 注意不能用 includes("<p")：<pre> 也以 <p 开头
  assert.strictEqual(out.includes('<p class="md-p"'), false);
});

test("流式未闭合的围栏把剩余内容都当代码，不吞成正文", () => {
  const out = html("说明如下：\n```bash\nrsync -av a b");
  assert.match(out, /rsync -av a b/);
  assert.strictEqual(out.includes("md-code"), false);
});

test("表格列数按表头对齐，缺列补空", () => {
  const out = html("| 模型 | RMSE |\n|---|---|\n| MIL | 214.6 |\n| PLSR |");
  assert.match(out, /<th>模型<\/th>/);
  assert.match(out, /<th>RMSE<\/th>/);
  // 第二行只有一列，第二格应补成空 td 而不是错位
  assert.strictEqual((out.match(/<td>/g) || []).length, 4);
});

test("无序与有序列表各自成组，不混成一个", () => {
  const ul = html("- 甲\n- 乙");
  assert.match(ul, /<ul class="md-ul">/);
  assert.strictEqual((ul.match(/<li>/g) || []).length, 2);

  const ol = html("1. 一\n2. 二");
  assert.match(ol, /<ol class="md-ol" start="1">/);
});

test("引用块合并连续行", () => {
  const out = html("> 第一行\n> 第二行");
  assert.match(out, /<blockquote class="md-quote">/);
});

test("引用指针渲染成可点击 pill，并按类型着色", () => {
  const reg = html("见 registry:our_hybrid 一栏");
  assert.match(reg, /md-pill--reg/);
  assert.match(reg, />our_hybrid</);

  const paper = html("依据 paper:ilse2018");
  assert.match(paper, /md-pill--paper/);
  assert.match(paper, />ilse2018</);
});

test("pill 只取 id，不把后续标点带进去", () => {
  const out = html("来自 registry:our_hybrid，以及 paper:ilse2018。");
  assert.match(out, />our_hybrid</);
  assert.match(out, />ilse2018</);
  assert.strictEqual(out.includes("our_hybrid，"), false);
});

test("只放行 http(s)/mailto 链接，javascript: 降级成纯文本", () => {
  assert.match(html("[站点](https://example.org)"), /href="https:\/\/example.org"/);
  const bad = html("[点我](javascript:alert(1))");
  assert.strictEqual(bad.includes("href"), false);
  assert.match(bad, /点我/);
});

test("渲染结果不拼原始 HTML：<script> 只会变成文本", () => {
  const out = html("<script>alert(1)</script>");
  assert.strictEqual(out.includes("<script>"), false);
  assert.match(out, /&lt;script&gt;/);
});

test("空输入不产出空段落", () => {
  assert.strictEqual(html(""), "");
  assert.strictEqual(html("   \n\n  "), "");
});

test("行内公式源码被单独标出，不会与正文混排", () => {
  // 没引 KaTeX，所以只做「视觉隔离」，不假装渲染。\b 在 JS 里是退格，必须转义。
  const out = html("超参 $\\beta$ 可学习");
  assert.match(out, /class="md-math"/);
  assert.match(out, /\\beta/);
  assert.strictEqual(out.includes("$"), false, "两侧的 $ 应被剥掉");
});

test("单个 $ 不会被当成公式，避免吞掉后半句", () => {
  const out = html("成本约 100$ 左右，后面还有话");
  assert.strictEqual(out.includes("md-math"), false);
  assert.match(out, /后面还有话/);
});

test("同样输入连解析两次结果一致（缓存不串味）", () => {
  const src = "| a | b |\n|---|---|\n| 1 | 2 |";
  assert.strictEqual(html(src), html(src));
});
