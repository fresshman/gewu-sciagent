// web/proxy/paper_index.mjs 的行为测试
// 重点不是「能跑」，而是三条不变量：
//   ① 论文库里每个数字都能指回磁盘（行号、字节、sha256），解析不出来就不编；
//   ② arXiv 号里的 "2062" 不能被当成出版年；
//   ③ 同一稿子存在内容不同的副本时必须被报出来，不能只留一份装作没事。
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  cleanTex,
  parseTexStructure,
  parseBibItems,
  countCitations,
  buildLibrary,
  parseReproRequestName,
  stripFrontMatter,
  collectLibrary,
  collectWriting,
} from "../proxy/paper_index.mjs";

const TEX = String.raw`\documentclass{ctexart}
\title{MIL + LIBS 热值预测\\5 折复现}
\date{2026-11-09}
\begin{document}
\section*{摘要}
本文给出 $214.57 \pm 25.71$ kcal/kg。
\section{引言}
已有工作\cite{p1,p2}，工具见\cite{p3}。
\section{方法}
\subsection{模型架构}
\begin{equation}
y = \beta x
\end{equation}
\subsection{结果}
\begin{table}[htbp]
\centering\caption{逐袋预测（kcal/kg）}
\begin{tabular}{cc} a & b \end{tabular}
\end{table}
\begin{figure}[htbp]
\includegraphics{a.pdf}
\caption{预测 vs 真实（$R^2=0.8786$）}
\end{figure}
\begin{thebibliography}{9}
\bibitem{p1} A model combining spectrum standardization.
\textit{Spectrochimica Acta Part B}, 2014. DOI: 10.1016/j.sab.2014.06.017; arXiv:1402.2062.
\bibitem{p2} The application of standardization. arXiv:1402.2060.
\bibitem{p3} Ilse M., Tomczak J., Welling M. Attention-based MIL.
\textit{ICML}, 2018. arXiv:1802.04712.
\end{thebibliography}
\end{document}`;

test("cleanTex 只去标记，不改写数值与单位", () => {
  assert.equal(cleanTex(String.raw`$R^2=0.8786$，RMSE$=218.6108$ kcal/kg`), "R²=0.8786，RMSE=218.6108 kcal/kg");
  assert.equal(cleanTex(String.raw`均值 $\pm$ 标准差`), "均值 ± 标准差");
  assert.equal(cleanTex(String.raw`\texttt{summary.json}`), "summary.json");
  assert.equal(cleanTex(String.raw`a\\b`), "a b");
  assert.equal(cleanTex(""), "");
});

test("parseTexStructure：编号、1-based 行号、图表归属到所在小节", () => {
  const st = parseTexStructure(TEX);
  assert.equal(st.title, "MIL + LIBS 热值预测 5 折复现");
  assert.equal(st.date, "2026-11-09");

  const heads = st.outline.map((n) => `${n.level}:${n.num}:${n.title}`);
  assert.deepEqual(heads, [
    "0::摘要", // \section* 不编号
    "0:1:引言",
    "0:2:方法",
    "1:2.1:模型架构",
    "1:2.2:结果",
  ]);

  // 行号必须与源文件对齐（可直接跳到编辑器同一行）
  const lines = TEX.split("\n");
  for (const n of st.outline) {
    assert.ok(lines[n.line - 1].includes(n.title.replace(/^摘要$/, "摘要")), `L${n.line} 应为 ${n.title}`);
  }

  const results = st.outline.find((n) => n.title === "结果");
  assert.deepEqual(results.leaves.map((l) => l.label), ["表 1", "图 1"]);
  assert.equal(results.leaves[0].text, "逐袋预测（kcal/kg）");
  assert.equal(results.leaves[1].text, "预测 vs 真实（R²=0.8786）");

  // 引用折成叶节点，排在本节图表之前
  const intro = st.outline.find((n) => n.title === "引言");
  assert.equal(intro.leaves[0].kind, "cite");
  assert.equal(intro.leaves[0].label, "引用 p1 p2 p3");

  assert.deepEqual(st.assets, { equations: 1, tables: 1, figures: 1, bibitems: 3 });
});

test("parseTexStructure：没有编号公式就如实记 0，不估不算", () => {
  const st = parseTexStructure("\\section{结论}\n行内 $a=b$ 不算编号公式。\n");
  assert.equal(st.assets.equations, 0);
  assert.equal(st.outline.length, 1);
});

test("parseBibItems：arXiv 号不被当成出版年，出版社从句尾剥离", () => {
  const items = parseBibItems(TEX);
  const byId = Object.fromEntries(items.map((x) => [x.id, x]));

  assert.equal(byId.p1.year, "2014", "DOI/arXiv 里的数字不能污染年份");
  assert.equal(byId.p1.src, "Spectrochimica Acta Part B");
  assert.equal(byId.p1.identifier, "10.1016/j.sab.2014.06.017");
  assert.equal(byId.p1.title, "A model combining spectrum standardization");

  // 无年份时用 arXiv 号 YYMM 推年份
  assert.equal(byId.p2.year, "2014");
  assert.equal(byId.p2.src, "arXiv");

  assert.equal(byId.p3.authors, "Ilse M., Tomczak J., Welling M.");
  assert.equal(byId.p3.title, "Attention-based MIL", "标题尾部的句号要去掉");
  assert.equal(byId.p3.src, "ICML");
});

test("parseBibItems：无 \\textit 时「标题. 出版社, 年份.」要拆开", () => {
  const tex = String.raw`\begin{thebibliography}{9}
\bibitem{x} Coal Analysis by Laser-Induced Breakdown Spectroscopy.
Wiley, 2021. DOI: 10.1002/abc.
\end{thebibliography}`;
  const [it] = parseBibItems(tex);
  assert.equal(it.title, "Coal Analysis by Laser-Induced Breakdown Spectroscopy");
  assert.equal(it.src, "Wiley");
  assert.equal(it.year, "2021");
});

test("countCitations 只数正文，不数参考文献区", () => {
  const counts = countCitations(TEX);
  assert.deepEqual(counts, { p1: 1, p2: 1, p3: 1 });
});

test("buildLibrary：推进度按五段等分，核验口径只算外部文献", () => {
  const { items, summary, progressSteps } = buildLibrary({
    bib: [
      { id: "a", title: "A", src: "arXiv", year: "2020", identifier: "arXiv:1" },
      { id: "b", title: "B", src: "arXiv", year: "2021", identifier: "arXiv:2" },
    ],
    pdfs: [{ id: "c", title: "C", authors: "X", year: "2019", page_count: 3, bytes: 100 }],
    refs: { papers: [{ id: "a", status: "verified", method: "arxiv", confidence: "high" }] },
    notes: ["c"],
    repro: { c: 2 },
    cites: { b: 1 },
    own: { id: "mine", title: "我的稿子", claimsCount: 5, refsCount: 2 },
  });

  assert.deepEqual(progressSteps, ["入库", "笔记", "复现", "引用", "成稿"]);
  const g = (id) => items.find((x) => x.id === id);
  assert.equal(g("mine").prog, 60, "入库+引用+成稿 = 3/5");
  assert.equal(g("a").prog, 0, "只在核验清单里，五段都没走");
  assert.equal(g("b").prog, 20, "只有引用");
  assert.equal(g("c").prog, 60, "入库+笔记+复现");
  assert.equal(g("a").check.cls, "b-ok");
  assert.equal(g("b").check.cls, "b-mut", "不在核验清单");
  // 这里原先是 assert.equal(g("mine").check.t, "已核")。那条断言把「claims.json 里
  // 每条都有 source 字段」锁成了「已核」——实测那 12 条一条都溯源不了。
  // 列表页只能报「待核」，判定权归 D2 引擎（核查台）。
  assert.equal(g("mine").check.t, "待核");
  assert.equal(g("mine").check.cls, "b-warn", "自己稿子的声明没跑过引擎，不能标绿");

  // 自己稿子的「已核」不能混进「几篇文献已核验」；
  // 而且列表页根本不该给结论 —— 只数「有几条待核」，判定归核查台。
  assert.equal(summary.verified, 1);
  assert.equal(summary.ownWithClaims, 1);
  assert.equal(summary.ownClaimCount, 5);
  assert.equal(summary.total, 4);
  assert.equal(summary.missingPdf, 2);
  assert.equal(summary.withNotes, 1);
  assert.equal(summary.withRepro, 1);
});

test("parseReproRequestName 能反解带下划线的 paperId", () => {
  assert.equal(parseReproRequestName("repro_request_test_paper_2026-10-29T04-18-33-644Z.json"), "test_paper");
  assert.equal(parseReproRequestName("repro_request_p1_2026-10-29T04-18-33-644Z.json"), "p1");
  assert.equal(parseReproRequestName("handoff_1_direction.json"), null);
});

test("stripFrontMatter 去掉 YAML 头，正文原样", () => {
  assert.equal(stripFrontMatter("---\npaper: x\nupdated: y\n---\n\n正文"), "正文");
  assert.equal(stripFrontMatter("没有头"), "没有头");
});

// ── 端到端：临时目录造一个「仓库 + 项目」，验证两份不同的稿子会被同时报出来 ──
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "gewu-pi-"));
  const repo = join(root, "repo");
  const proj = join(root, "proj");
  mkdirSync(join(repo, "docs", "paper", "report"), { recursive: true });
  mkdirSync(join(repo, "output", "documents", "report"), { recursive: true });
  mkdirSync(join(proj, "papers"), { recursive: true });
  mkdirSync(join(proj, "stages", "2-literature", "notes"), { recursive: true });
  mkdirSync(join(proj, "handoffs"), { recursive: true });
  mkdirSync(join(proj, "output", "documents", "report"), { recursive: true });

  writeFileSync(join(repo, "docs", "paper", "report", "main.tex"), TEX);
  writeFileSync(join(repo, "output", "documents", "report", "claims.json"), JSON.stringify([
    { text: "c1", value: 1, source: "registry:x" },
    { text: "c2", value: 2, source: "registry:y" },
  ]));
  writeFileSync(join(repo, "output", "documents", "report", "refs_verified.json"), JSON.stringify({
    verdict: "PASS",
    hallucination_rate: 0,
    papers: [
      { id: "p1", status: "verified", method: "crossref", confidence: "high" },
      { id: "p2", status: "verified", method: "arxiv", confidence: "high" },
    ],
    _meta: { checked_at: "2026-11-01" },
  }));
  // 项目里那份是残缺副本
  writeFileSync(join(proj, "output", "documents", "report", "main.tex"), "\\section{摘要}\n短版\n");
  writeFileSync(join(proj, "papers", "downloaded.meta.json"), JSON.stringify({
    title: "Downloaded", authors: "Some One", page_count: 7, year: "2022",
  }));
  writeFileSync(join(proj, "papers", "downloaded.pdf"), "%PDF-fake");
  writeFileSync(join(proj, "stages", "2-literature", "notes", "downloaded.md"), "---\npaper: downloaded\n---\n\n我的笔记正文");
  writeFileSync(join(proj, "handoffs", "repro_request_downloaded_2026-10-01T00-00-00-000Z.json"), "{}");
  return { root, repo, proj };
}

test("collectLibrary：仓库参考文献 + 本机 PDF + 笔记 + 复现请求合成一张表", () => {
  const { repo, proj } = fixture();
  const lib = collectLibrary({ projectPath: proj, repoRoot: repo, projectName: "demo" });

  assert.equal(lib.available, true);
  const ids = lib.items.map((x) => x.id);
  assert.deepEqual(ids, ["report", "p1", "p2", "p3", "downloaded"]);

  const own = lib.items[0];
  assert.equal(own.kind, "own");
  assert.equal(own.check.sub, "2 条声明 · 未跑溯源引擎");
  assert.equal(own.rel.cite, 3, "正文引用 3 条参考文献");
  assert.equal(own.identifier, "—", "自己的稿子没有 DOI，不该编一个");

  const dl = lib.items.find((x) => x.id === "downloaded");
  assert.equal(dl.pdf.pages, 7);
  assert.equal(dl.rel.note, 1);
  assert.equal(dl.rel.repro, 1);
  assert.equal(dl.check.cls, "b-mut");
  assert.equal(dl.prog, 60);
});

test("collectWriting：大纲带行号，两份不同的 main.tex 同时报出", () => {
  const { repo, proj } = fixture();
  const w = collectWriting({ projectPath: proj, repoRoot: repo, projectName: "demo" });

  assert.equal(w.available, true);
  assert.equal(w.tex.path, join("docs", "paper", "report", "main.tex").replace(/\\/g, "/"));
  assert.equal(w.outline.length, 5);
  assert.equal(w.assets.claims.n, 2);
  assert.equal(w.assets.claims.withSource, 2);
  assert.equal(w.assets.equations.n, 1);
  assert.equal(w.assets.refs.n, 3);
  assert.equal(w.assets.refs.verified, 2);
  assert.equal(w.assets.refs.verdict, "PASS");
  assert.equal(w.pdf, null, "没编出 PDF 就报 null，不假装有");

  assert.equal(w.duplicates.length, 1);
  assert.equal(w.duplicates[0].same, false, "副本内容不同必须标 false");
  assert.equal(w.duplicates[0].bytes > 0, true);
});

test("collectWriting：找不到 tex 时降级为 available:false，不返回空壳数据", () => {
  const root = mkdtempSync(join(tmpdir(), "gewu-pi-empty-"));
  const repo = join(root, "repo");
  const proj = join(root, "proj");
  mkdirSync(repo, { recursive: true });
  mkdirSync(proj, { recursive: true });
  const w = collectWriting({ projectPath: proj, repoRoot: repo, projectName: "demo" });
  assert.equal(w.available, false);
  assert.ok(w.reason.includes("main.tex"));
  assert.equal(w.outline, undefined);
});
