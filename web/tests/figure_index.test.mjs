// web/proxy/figure_index.mjs 的行为测试
//
// 这个模块要解决一个很具体的问题：coal-thermal 项目里 3 张图散成 16 个文件
// （pdf 四处、png 两处，字节完全相同）。按文件列，一张图会变成 4 行；
// 按内容 sha256 合并成一条，才能回答「这张图在几个地方各有一份」。
//
// 守四条不变量：
//   ① 字节相同的副本必须合并成一条，不能因为目录不同就重复计数；
//   ② 正文引用必须落到「哪一节、第几行、有没有 \label」，对不上就留空；
//   ③ 没有出处旁文件就如实标无出处，不许编一个 tool 出来；
//   ④ 图纸 id 只能是自己生成的那种形状，别的字符串拿去拼路径要挡掉。
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  buildFigureIndex,
  figIdOf,
  isFigId,
  refsFromStructure,
} from "../proxy/figure_index.mjs";
import { parseTexStructure } from "../proxy/paper_index.mjs";

const SHA_A = "aaaaaaaa1111";
const SHA_B = "bbbbbbbb2222";
const SHA_PNG_A = "cccccccc3333";

function f(rel, format, bytes, sha256) {
  const base = rel.split("/").pop().replace(/\.[a-z0-9]+$/i, "");
  return { rel, abs: `/proj/${rel}`, base, format, bytes, sha256 };
}

const FILES = [
  // 图 A：pdf 在两处（字节相同），png 也在两处
  f("output/figures/fig_a_20261028.pdf", "pdf", 1000, SHA_A),
  f("output/figures/fig_a_20261028.png", "png", 5000, SHA_PNG_A),
  f("stages/5-paper/figures/fig_a_20261028.pdf", "pdf", 1000, SHA_A),
  f("stages/5-paper/figures/fig_a_20261028.png", "png", 5000, SHA_PNG_A),
  // 图 B：只有出图目录一份，且没有 png
  f("output/figures/fig_b_20261028.pdf", "pdf", 900, SHA_B),
];

const TEX = String.raw`\section{结果}
\subsection{主结果}
正文先引用文献 \cite{p1}。
\begin{figure}[htbp]
\centering
\includegraphics[width=0.8\textwidth]{fig_a_20261028.pdf}
\caption{五折 RMSE 对比}
\label{fig:rmse}
\end{figure}
`;

test("字节相同的副本合并成一条，不再按文件计数", () => {
  const { figures, summary } = buildFigureIndex({ files: FILES, refs: [] });
  assert.equal(figures.length, 2, "2 张图，不是 5 个文件");
  const a = figures.find((x) => x.base === "fig_a_20261028");
  assert.equal(a.copyCount, 4);
  assert.equal(a.dirCount, 2);
  assert.deepEqual(
    a.locations.map((l) => l.dir),
    ["output/figures", "stages/5-paper/figures"]
  );
  assert.deepEqual(a.locations[0].formats, ["pdf", "png"]);
  assert.equal(summary.files, 5);
  assert.equal(summary.total, 2);
  assert.equal(summary.multiCopy, 1);
});

test("id 走内容寻址：同一份 pdf 在哪个目录都是同一个 id", () => {
  const { figures } = buildFigureIndex({ files: FILES, refs: [] });
  assert.ok(figures.every((x) => x.fig_id === figIdOf(x.sha256)));
  assert.equal(figIdOf(SHA_A), "fig-aaaaaaaa");
  assert.equal(figures.find((x) => x.base === "fig_a_20261028").fig_id, "fig-aaaaaaaa");
});

test("正文引用按 includegraphics 的 basename 对上，带不带扩展名都行", () => {
  const st = parseTexStructure(TEX);
  const refs = refsFromStructure(st);
  assert.equal(refs.length, 1);
  assert.equal(refs[0].file, "fig_a_20261028.pdf");
  assert.equal(refs[0].texLabel, "fig:rmse");
  assert.equal(refs[0].sectionNum, "1.1");
  assert.equal(refs[0].sectionTitle, "主结果");

  const { figures } = buildFigureIndex({ files: FILES, refs });
  const a = figures.find((x) => x.base === "fig_a_20261028");
  assert.equal(a.referenced, true);
  assert.equal(a.refs[0].num, 1);
  assert.equal(a.refs[0].caption, "五折 RMSE 对比");
  assert.equal(a.refs[0].sectionNum, "1.1");
  assert.ok(a.refs[0].line > 0);
});

test("没被正文引用的图要标出来，且排在引用过的后面", () => {
  const refs = refsFromStructure(parseTexStructure(TEX));
  const { figures } = buildFigureIndex({ files: FILES, refs });
  const b = figures.find((x) => x.base === "fig_b_20261028");
  assert.equal(b.referenced, false);
  assert.equal(figures[0].referenced, true, "引用过的排前面");
  assert.ok(b.concerns.some((c) => c.code === "unreferenced"));
});

test("没有旁文件 → 明确无出处，不猜 tool", () => {
  const { figures } = buildFigureIndex({ files: FILES, refs: [] });
  const a = figures.find((x) => x.base === "fig_a_20261028");
  assert.equal(a.provenance, null);
  assert.equal(a.provenancePath, "");
  const c = a.concerns.find((x) => x.code === "no-provenance");
  assert.ok(c, "必须有一条「无出处」提示");
  assert.match(c.text, /无法回溯/);
});

test("有旁文件 → 原样带上，并给出旁文件相对路径", () => {
  const meta = { schema: 1, tool: "plot_bar", fig_id: "fig-aaaaaaaa", draw: { digest: "d1" } };
  const { figures } = buildFigureIndex({
    files: FILES,
    refs: [],
    readMeta: (base, rel) =>
      base === "fig_a_20261028" && rel.startsWith("output/figures/")
        ? { path: "output/figures/fig_a_20261028.meta.json", data: meta }
        : null,
  });
  const a = figures.find((x) => x.base === "fig_a_20261028");
  assert.equal(a.provenance.tool, "plot_bar");
  assert.equal(a.provenancePath, "output/figures/fig_a_20261028.meta.json");
  assert.ok(!a.concerns.some((c) => c.code === "no-provenance"));
});

test("只有 pdf 的图要提示缺 png 预览，且 master 是 pdf", () => {
  const { figures } = buildFigureIndex({ files: FILES, refs: [] });
  const b = figures.find((x) => x.base === "fig_b_20261028");
  assert.equal(b.masterFormat, "pdf");
  assert.equal(b.formats.png, undefined);
  assert.ok(b.concerns.some((c) => c.code === "no-preview"));
});

test("图纸 id 形状校验：路径拼接类输入一律拒绝", () => {
  assert.equal(isFigId("fig-76a19f42"), true);
  assert.equal(isFigId("fig-76A19F42"), false, "大写不是本模块生成的");
  assert.equal(isFigId("fig-76a19f4"), false, "7 位不够");
  assert.equal(isFigId("../../etc/passwd"), false);
  assert.equal(isFigId("fig-76a19f42/../../etc"), false);
  assert.equal(isFigId(""), false);
  assert.equal(isFigId(null), false);
});

test("引用写的是绝对路径或不存在的文件时，不抛错，只是对不上", () => {
  const refs = [
    { num: 1, caption: "x", line: 10, file: "/abs/path/fig_x.pdf", sectionNum: "1", sectionTitle: "s", texLabel: "" },
    { num: 2, caption: "y", line: 20, file: "", sectionNum: "1", sectionTitle: "s", texLabel: "" },
  ];
  const { figures, summary } = buildFigureIndex({ files: FILES, refs });
  assert.equal(summary.referenced, 0);
  assert.ok(figures.every((x) => !x.referenced));
});

test("同一个 base 既在出图目录又在成稿目录，只算一张图", () => {
  const files = [
    f("output/figures/x_1.pdf", "pdf", 100, SHA_A),
    f("output/documents/report/x_1.pdf", "pdf", 100, SHA_A),
  ];
  const { figures, summary } = buildFigureIndex({ files, refs: [] });
  assert.equal(figures.length, 1);
  assert.equal(figures[0].dirCount, 2);
  assert.equal(summary.rowsBeforeMerge, 2);
});

test("文件名里带点号时 base 不被截断（只去掉最后一个扩展名）", () => {
  const files = [f("output/figures/fig.v2_20261028.pdf", "pdf", 10, SHA_A)];
  const { figures } = buildFigureIndex({ files, refs: [] });
  assert.equal(figures[0].base, "fig.v2_20261028");
});

test("tex 里 \label 写在 \caption 之后也能收到", () => {
  const tex = String.raw`\section{A}
\begin{figure}
\includegraphics{a.pdf}
\caption{图注}
\label{fig:late}
\end{figure}
`;
  const refs = refsFromStructure(parseTexStructure(tex));
  assert.equal(refs[0].texLabel, "fig:late");
  assert.equal(refs[0].file, "a.pdf");
});

test("图没有 \label 时要提示无法交叉引用", () => {
  const tex = String.raw`\section{A}
\begin{figure}
\includegraphics{a.pdf}
\caption{图注}
\end{figure}
`;
  const refs = refsFromStructure(parseTexStructure(tex));
  const files = [f("output/figures/a.pdf", "pdf", 10, SHA_A)];
  const { figures } = buildFigureIndex({ files, refs });
  assert.ok(figures[0].concerns.some((c) => c.code === "no-label"));
});
