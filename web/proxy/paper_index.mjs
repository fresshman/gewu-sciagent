// 论文索引（只读）
// 把「仓库里的 LaTeX 源 + 项目目录里的 PDF / 笔记 / 复现请求」汇总成两张视图：
//   ① 论文库    —— 一行一篇，含核查状态与推进度
//   ② 写作台    —— 从 main.tex 解析出带行号的大纲、表/图节点、资产计数
//
// 三条硬规则（不做就变成假数据）：
//   1. 每个字段要么指向磁盘上的具体文件/行号，要么留空降级，绝不猜、不补默认值；
//   2. 解析不出来的东西（例如正文没有编号公式）如实记为 0，不用「约」糊过去；
//   3. 同一份稿子存在两份内容不同的副本时，两份都列出来并标 sha256 不同 —— 藏起来最危险。

import { readFileSync, existsSync, readdirSync, statSync } from "node:fs";
import { createHash } from "node:crypto";
import { join, dirname, basename } from "node:path";

// ───────────────────────────── LaTeX 清洗 ─────────────────────────────

// 把一段 LaTeX 片段压成可显示的单行纯文本。
// 只做「去标记」，不改写内容：缩写、单位、数值一律保持原文。
export function cleanTex(input) {
  return String(input ?? "")
    .replace(/\\\\/g, " ")
    .replace(/\\(?:textit|texttt|textbf|textrm|textsc|emph|path)\s*\{([^{}]*)\}/g, "$1")
    .replace(/\\pm\b/g, "±")
    .replace(/\\times\b/g, "×")
    .replace(/\^2\b/g, "²")
    .replace(/\$/g, "")
    .replace(/\\%/g, "%")
    .replace(/\\_/g, "_")
    .replace(/\\&/g, "&")
    .replace(/\\[a-zA-Z]+\*?/g, " ")
    .replace(/[{}]/g, "")
    .replace(/~/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

// 从 src[start]（必须指向 '{'）读一个配平的括号组。
// 用来处理 \caption{... $10^{-5}$ ...} 这类嵌套花括号。
function readBraced(src, start) {
  if (src[start] !== "{") return null;
  let depth = 0;
  for (let i = start; i < src.length; i++) {
    const c = src[i];
    if (c === "\\") { i += 1; continue; }
    if (c === "{") depth += 1;
    else if (c === "}") {
      depth -= 1;
      if (depth === 0) return { text: src.slice(start + 1, i), end: i };
    }
  }
  return null;
}

// 取 \name{...} / \name*{...} 的参数（同一行内）
function cmdArg(line, name) {
  const re = new RegExp("\\\\" + name + "\\*?\\s*\\{");
  const m = re.exec(line);
  if (!m) return null;
  const r = readBraced(line, m.index + m[0].length - 1);
  return r ? r.text : null;
}

// ───────────────────────────── 结构解析 ─────────────────────────────

// 解析 main.tex：标题、日期、带行号的章节大纲、表/图/引用节点、资产计数。
// 行号是 1-based，与编辑器里看到的行号一致（可以直接跳过去核对）。
export function parseTexStructure(tex) {
  const src = String(tex ?? "");
  const lines = src.split(/\r?\n/);
  const outline = [];
  const assets = { equations: 0, tables: 0, figures: 0, bibitems: 0 };
  const orphans = [];

  let sec = 0;
  let sub = 0;
  let cur = null;
  let pending = null; // 正在等待 \caption 的浮动体 {kind, index, envLine}
  // figure 环境要额外记住「插的是哪个文件、有没有 \label」——图纸要按文件名和
  // 正文对起来，只靠「图 1 / 图 2」的顺序对不上（图表目录一改就错位）。
  let figOpen = null; // {file, texLabel, envLine, leaf}

  const pushLeaf = (node, leaf) => {
    if (node) node.leaves.push(leaf);
    else orphans.push(leaf);
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const ln = i + 1;
    const trimmed = line.trimStart();

    // 章节：\section*{} 与 \section{} 区分编号
    if (/^\\section\b/.test(trimmed)) {
      const starred = /^\\section\*/.test(trimmed);
      const title = cleanTex(cmdArg(trimmed, "section") ?? "");
      if (!starred) { sec += 1; sub = 0; }
      cur = {
        level: 0,
        num: starred ? "" : String(sec),
        title,
        line: ln,
        leaves: [],
        cites: [],
        citeLine: 0,
      };
      outline.push(cur);
      continue;
    }
    if (/^\\subsection\b/.test(trimmed)) {
      const title = cleanTex(cmdArg(trimmed, "subsection") ?? "");
      sub += 1;
      cur = {
        level: 1,
        num: sec ? `${sec}.${sub}` : String(sub),
        title,
        line: ln,
        leaves: [],
        cites: [],
        citeLine: 0,
      };
      outline.push(cur);
      continue;
    }

    // 资产计数：只数真正带编号的环境
    if (/\\begin\{equation\}/.test(line) || /\\begin\{align\}/.test(line) || /^\s*\\\[/.test(line)) {
      assets.equations += 1;
    }

    // 浮动体：\begin{table} → 等 \caption 拿标题
    const bt = line.match(/\\begin\{(table|figure)\*?\}/);
    if (bt) {
      const kind = bt[1] === "table" ? "tbl" : "fig";
      if (kind === "tbl") assets.tables += 1;
      else {
        assets.figures += 1;
        figOpen = { file: null, texLabel: null, envLine: ln, leaf: null };
      }
      pending = { kind, index: kind === "tbl" ? assets.tables : assets.figures, envLine: ln };
    }

    // figure 环境内部：\includegraphics 给文件名，\label{fig:*} 给交叉引用键
    if (figOpen) {
      const ig = line.match(/\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}/);
      if (ig && !figOpen.file) figOpen.file = ig[1].trim();
      const lb = line.match(/\\label\{([^}]+)\}/);
      if (lb && /^fig[:\-]/.test(lb[1].trim())) figOpen.texLabel = lb[1].trim();
    }

    if (line.includes("\\caption") && pending) {
      const cap = cmdArg(line, "caption");
      if (cap != null) {
        const leaf = {
          kind: pending.kind,
          num: pending.index,
          label: `${pending.kind === "tbl" ? "表" : "图"} ${pending.index}`,
          text: cleanTex(cap),
          line: ln,
          envLine: pending.envLine,
        };
        pushLeaf(cur, leaf);
        if (figOpen && pending.kind === "fig") figOpen.leaf = leaf;
      }
      pending = null;
    }

    if (/\\end\{figure\}/.test(line) && figOpen) {
      // caption 之后才出现的 \label 也算这张图的
      if (figOpen.leaf) {
        figOpen.leaf.file = figOpen.file;
        figOpen.leaf.texLabel = figOpen.texLabel;
      }
      figOpen = null;
    }

    // 引用：收集到当前章节，最后折成一个「引用」叶节点
    const citeRe = /\\cite\{([^}]*)\}/g;
    let cm;
    while ((cm = citeRe.exec(line))) {
      const ids = cm[1].split(",").map((s) => s.trim()).filter(Boolean);
      if (ids.length && cur) {
        if (!cur.citeLine) cur.citeLine = ln;
        for (const id of ids) if (!cur.cites.includes(id)) cur.cites.push(id);
      }
    }

    if (/\\begin\{thebibliography\}/.test(line)) {
      // 参考文献区之后不再累计引用
      cur = null;
    }

    const bi = line.match(/\\bibitem\{/g);
    if (bi) assets.bibitems += bi.length;
  }

  // 引用叶节点排在本章节图表之前
  for (const node of outline) {
    if (node.cites.length) {
      node.leaves.unshift({
        kind: "cite",
        num: 0,
        label: `引用 ${node.cites.join(" ")}`,
        text: "",
        line: node.citeLine,
      });
    }
    delete node.cites;
    delete node.citeLine;
  }

  const titleRaw = cmdArg(src, "title");
  return {
    title: titleRaw ? cleanTex(titleRaw) : "",
    date: cleanTex(cmdArg(src, "date") ?? ""),
    outline,
    assets,
    orphanLeaves: orphans,
  };
}

// ───────────────────────────── 参考文献 ─────────────────────────────

// 解析 \bibitem{id} ... —— 这是本稿实际引用的文献清单（不是外部库）。
// 字段规则（尽量少假设，错了宁可为空）：
//   期刊/会议 = 最后一个 \textit{...}；没有则为 arXiv（若带 arXiv 号）或 "—"
//   年份      = 正文里最后一个 19xx/20xx；仍无则用 arXiv 号前两位（YYMM）推年份
//   标识符    = DOI 优先，其次 arXiv 号
//   作者      = 仅当 bibitem 以「姓 首字母.」模式开头（如 "Ilse M., ..."），否则留空
export function parseBibItems(tex) {
  const src = String(tex ?? "");
  const env = src.match(/\\begin\{thebibliography\}([\s\S]*?)\\end\{thebibliography\}/);
  if (!env) return [];
  const body = env[1];
  const out = [];
  const re = /\\bibitem\{([^}]+)\}([\s\S]*?)(?=\\bibitem\{|$)/g;
  let m;
  while ((m = re.exec(body))) {
    out.push(splitBibItem(m[1].trim(), m[2]));
  }
  return out;
}

function splitBibItem(id, rawIn) {
  const raw = String(rawIn).replace(/\s+/g, " ").trim();

  const venues = [...raw.matchAll(/\\textit\{([^{}]*)\}/g)].map((x) => cleanTex(x[1]));
  let venue = venues.length ? venues[venues.length - 1] : "";

  const doiM = raw.match(/DOI:\s*([^\s;,]+)/i);
  const arxM = raw.match(/arXiv:\s*([\w.\-]+)/i);
  const doi = doiM ? doiM[1].replace(/\.$/, "") : "";
  const arxiv = arxM ? arxM[1].replace(/\.$/, "") : "";

  // 先摘掉标识符，否则 arXiv:1402.2062 里的 "2062" 会被当成出版年
  const stripped = raw
    .replace(/arXiv:\s*[\w.\-]+\.?/gi, " ")
    .replace(/DOI:\s*[^\s;,]+[;,]?/gi, " ")
    .replace(/\s+/g, " ")
    .trim();

  // 标题区：\textit 之前的部分（作者 + 标题），没有 \textit 时就是全部
  const vIdx = stripped.search(/\\textit\{/);
  let head = (vIdx >= 0 ? stripped.slice(0, vIdx) : stripped).replace(/\s+/g, " ").trim();

  let authors = "";
  const auM = head.match(/^([A-Z][A-Za-z\u00C0-\u024F]+ [A-Z]\.,[\s\S]*?\.)\s+(?=[A-Z0-9])/);
  if (auM) {
    authors = cleanTex(auM[1]);
    head = head.slice(auM[0].length).trim();
  }

  // 没有 \textit 时，「标题. 出版社, 年份.」的出版社要摘出来当来源，不能留在标题里
  if (!venue) {
    const pubM = head.match(/^(.+?)\.\s+([A-Z][A-Za-z&.\s]{0,24}?),?\s*((?:19|20)\d{2})\.?\s*$/);
    if (pubM) {
      head = pubM[1];
      venue = cleanTex(pubM[2]);
    }
  }

  const title = cleanTex(head).replace(/[.;]$/, "").trim();

  const years = [...stripped.matchAll(/\b(19\d{2}|20\d{2})\b/g)].map((x) => x[1]);
  let year = years.length ? years[years.length - 1] : "";
  if (!year && arxiv && /^\d{4}\./.test(arxiv)) {
    const yy = Number(arxiv.slice(0, 2));
    if (yy >= 90) year = String(1900 + yy);
    else if (yy <= 40) year = String(2000 + yy);
  }

  const identifier = doi ? doi : arxiv ? `arXiv:${arxiv}` : "";
  const src = venue || (arxiv ? "arXiv" : "—");

  return { id, title, src, authors, year, identifier, doi, arxiv };
}

// 统计正文里每个文献 id 被引次数（不含参考文献区）
export function countCitations(tex) {
  const src = String(tex ?? "");
  const cut = src.search(/\\begin\{thebibliography\}/);
  const body = cut >= 0 ? src.slice(0, cut) : src;
  const counts = {};
  const re = /\\cite\{([^}]*)\}/g;
  let m;
  while ((m = re.exec(body))) {
    for (const id of m[1].split(",").map((s) => s.trim()).filter(Boolean)) {
      counts[id] = (counts[id] || 0) + 1;
    }
  }
  return counts;
}

// ───────────────────────────── 论文库合成 ─────────────────────────────

const PROGRESS_STEPS = ["入库", "笔记", "复现", "引用", "成稿"];

// 推进度 = 五段流水线等分（每段 20 分）。规则写死在这里，
// 前端图例直接引用同一套定义，避免两处各说一套。
function progressOf(steps) {
  const hit = steps.filter(Boolean).length;
  return Math.round((hit / PROGRESS_STEPS.length) * 100);
}

function checkOf(ref) {
  if (!ref) return { t: "未核验", cls: "b-mut", sub: "不在核验清单" };
  if (ref.status === "verified") {
    const parts = [ref.method || "verified"];
    if (ref.confidence) parts.push(`置信 ${ref.confidence}`);
    return { t: "已核验", cls: "b-ok", sub: parts.join(" · ") };
  }
  return { t: "待核", cls: "b-warn", sub: ref.reason || ref.status || "未通过" };
}

// in: 已归一化的输入（便于单测）
//   bib      [{id,title,src,authors,year,identifier}]
//   pdfs     [{id,title,authors,doi,year,page_count,bytes}]
//   refs     refs_verified.json 对象或 null
//   notes    [paperId]
//   repro    {paperId: count}
//   cites    {paperId: count}
//   own      {id,title,src,year,texPath,texBytes,texSha,claimsPath,claimsCount,refsCount,tables,figures}
export function buildLibrary({ bib = [], pdfs = [], refs = null, notes = [], repro = {}, cites = {}, own = null } = {}) {
  const refMap = new Map((refs?.papers || []).map((x) => [x.id, x]));
  const noteSet = new Set(notes || []);
  const items = [];
  const seen = new Set();

  for (const b of bib) {
    if (seen.has(b.id)) continue;
    seen.add(b.id);
    const pdf = pdfs.find((x) => x.id === b.id);
    items.push({
      id: b.id,
      kind: "ext",
      label: "文献",
      title: b.title || b.id,
      src: b.src || (pdf?.authors ? pdf.authors : "—"),
      year: b.year || (pdf?.year ?? "—"),
      identifier: b.identifier || (pdf?.doi ? pdf.doi : "—"),
      tags: [],
      pdf: pdf ? { bytes: pdf.bytes, pages: pdf.page_count || 0 } : null,
      check: checkOf(refMap.get(b.id)),
      rel: {
        note: noteSet.has(b.id) ? 1 : 0,
        repro: repro[b.id] || 0,
        cite: cites[b.id] || 0,
      },
      prog: 0,
      lines: [],
    });
  }

  // 只在本机 PDF 里出现、正文没引用的（自己下载来读的）
  for (const pf of pdfs) {
    if (seen.has(pf.id)) continue;
    seen.add(pf.id);
    items.push({
      id: pf.id,
      kind: "ext",
      label: "文献",
      title: pf.title || pf.id,
      src: pf.authors || "本机 PDF",
      year: pf.year || "—",
      identifier: pf.doi || "—",
      tags: [],
      pdf: { bytes: pf.bytes, pages: pf.page_count || 0 },
      check: checkOf(refMap.get(pf.id)),
      rel: {
        note: noteSet.has(pf.id) ? 1 : 0,
        repro: repro[pf.id] || 0,
        cite: cites[pf.id] || 0,
      },
      prog: 0,
      lines: [],
    });
  }

  if (own) {
    items.unshift({
      id: own.id,
      kind: "own",
      label: "我的稿子",
      title: own.title || own.id,
      src: own.src || "本人",
      year: own.year || "—",
      // 自己的稿子没有 DOI/arXiv 号，标识符列留空 —— 指纹放明细里，不占据这一列
      identifier: "—",
      tags: [],
      pdf: null,
      check: own.claimsCount
        // 这里曾经写「已核」，依据只是 claims.json 里每条都有 source 字段。
        // 实测那 12 条一条都溯源不了（source 语法不符合引擎契约），于是列表页挂着
        // 一个绿色「已核」，点进去才发现全是未核验的。列表页不许替引擎下结论：
        // 只报「有 N 条等着核」，真正的判定在核查台（/api/writing/claims）。
        ? { t: "待核", cls: "b-warn", sub: `${own.claimsCount} 条声明 · 未跑溯源引擎` }
        : { t: "无声明", cls: "b-mut", sub: "没有 claims.json" },
      rel: { note: 0, repro: 0, cite: own.refsCount || 0 },
      prog: 0,
      lines: [],
      tex: own.texRelPath || "",
      claimsCount: own.claimsCount || 0,
    });
  }

  for (const it of items) {
    const steps = [
      Boolean(it.pdf) || it.kind === "own",
      it.rel.note > 0,
      it.rel.repro > 0,
      it.rel.cite > 0,
      it.kind === "own",
    ];
    it.steps = steps;
    it.prog = progressOf(steps);

    const lines = [];
    if (it.kind === "own") {
      lines.push(
        it.tex ? `源 ${it.tex}` : "未找到 main.tex",
        it.claimsCount ? `声明 ${it.claimsCount} 条 · 待溯源` : "无 claims.json",
        `参考文献 ${it.rel.cite} 条`,
      );
    } else {
      lines.push(it.pdf ? `${it.pdf.bytes} B · ${it.pdf.pages} 页` : "无本机 PDF（仅参考文献条目）");
      if (it.rel.note) lines.push("有阅读笔记");
      if (it.rel.repro) lines.push(`${it.rel.repro} 次复现请求`);
      if (it.rel.cite) lines.push(`本稿引用 ${it.rel.cite} 处`);
    }
    it.lines = lines;
  }

  const summary = {
    total: items.length,
    // 核验只统计外部文献。自己稿子的声明不在列表页判定——这里只数「有几条等着核」，
    // 判定权归 D2 引擎（核查台 /api/writing/claims）。
    verified: items.filter((x) => x.kind === "ext" && x.check.cls === "b-ok").length,
    ownWithClaims: items.filter((x) => x.kind === "own" && (x.claimsCount || 0) > 0).length,
    ownClaimCount: items.reduce((n, x) => n + (x.kind === "own" ? x.claimsCount || 0 : 0), 0),
    withNotes: items.filter((x) => x.rel.note > 0).length,
    withRepro: items.filter((x) => x.rel.repro > 0).length,
    missingPdf: items.filter((x) => x.kind === "ext" && !x.pdf).length,
  };
  return { items, summary, progressSteps: PROGRESS_STEPS };
}

// ───────────────────────────── 磁盘读取 ─────────────────────────────

function readTextSafe(p) {
  try { return readFileSync(p, "utf8"); } catch { return null; }
}
function sha256File(p) {
  try { return createHash("sha256").update(readFileSync(p)).digest("hex"); } catch { return ""; }
}
function sizeOf(p) {
  try { return statSync(p).size; } catch { return 0; }
}
function readJsonSafe(p) {
  const t = readTextSafe(p);
  if (!t) return null;
  try { return JSON.parse(t); } catch { return null; }
}

// 在 docs/paper/*/ 下找 main.tex（取最新修改的一份）
export function findRepoPaperTex(repoRoot) {
  const dir = join(repoRoot, "docs", "paper");
  if (!existsSync(dir)) return null;
  const cands = readdirSync(dir)
    .map((d) => join(dir, d, "main.tex"))
    .filter((f) => existsSync(f));
  if (!cands.length) return null;
  cands.sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs);
  return cands[0];
}

// 与 main.tex 同名的产物目录：先找同目录，再找 output/documents/<名>/
function findSiblingArtifact(repoRoot, texPath, file) {
  const own = join(dirname(texPath), file);
  if (existsSync(own)) return own;
  const byName = join(repoRoot, "output", "documents", basename(dirname(texPath)), file);
  if (existsSync(byName)) return byName;
  return null;
}

// 读本机 PDF 的 .meta.json（pdf_tool.py 产出，字段可能不全）
function readPdfs(projectPath) {
  const dir = join(projectPath, "papers");
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((f) => f.toLowerCase().endsWith(".pdf"))
    .map((f) => {
      const id = f.replace(/\.pdf$/i, "");
      const meta = readJsonSafe(join(dir, `${id}.meta.json`)) || {};
      const p = join(dir, f);
      const yearM = String(meta.year || meta.date || "").match(/\b(19\d{2}|20\d{2})\b/);
      return {
        id,
        title: meta.title || id,
        authors: meta.authors || "",
        doi: meta.doi || "",
        year: yearM ? yearM[1] : "",
        page_count: meta.page_count || 0,
        bytes: sizeOf(p),
      };
    });
}

function readNoteIds(projectPath) {
  const dir = join(projectPath, "stages", "2-literature", "notes");
  if (!existsSync(dir)) return [];
  return readdirSync(dir).filter((f) => f.endsWith(".md")).map((f) => f.replace(/\.md$/, ""));
}

// repro_request_<paperId>_<ISO 时间戳>.json —— 从文件名反解 paperId
export function parseReproRequestName(name) {
  const m = String(name).match(/^repro_request_(.+)\.json$/);
  if (!m) return null;
  return m[1].replace(/_\d{4}-\d{2}-\d{2}T[\d\-]+Z$/, "");
}

function readReproCounts(projectPath) {
  const dir = join(projectPath, "handoffs");
  const out = {};
  if (!existsSync(dir)) return out;
  for (const f of readdirSync(dir)) {
    const id = parseReproRequestName(f);
    if (!id) continue;
    out[id] = (out[id] || 0) + 1;
  }
  return out;
}

// 阅读笔记正文（去掉 front-matter）
export function stripFrontMatter(raw) {
  const m = String(raw ?? "").match(/^---\n[\s\S]*?\n---\n\n?([\s\S]*)$/);
  return (m ? m[1] : String(raw ?? "")).trim();
}

export function readNoteText(projectPath, paperId) {
  const p = join(projectPath, "stages", "2-literature", "notes", `${paperId}.md`);
  const raw = readTextSafe(p);
  return raw == null ? null : { text: stripFrontMatter(raw), path: p };
}

// ── 对外：论文库 ──
export function collectLibrary({ projectPath, repoRoot, projectName }) {
  const texPath = findRepoPaperTex(repoRoot);
  const tex = texPath ? readTextSafe(texPath) : null;

  let own = null;
  let bib = [];
  let cites = {};
  let claimsCount = 0;
  if (tex) {
    const st = parseTexStructure(tex);
    bib = parseBibItems(tex);
    cites = countCitations(tex);
    const claimsPath = findSiblingArtifact(repoRoot, texPath, "claims.json");
    const claims = claimsPath ? readJsonSafe(claimsPath) : null;
    claimsCount = Array.isArray(claims) ? claims.length : Array.isArray(claims?.claims) ? claims.claims.length : 0;
    own = {
      id: basename(dirname(texPath)),
      title: st.title || basename(dirname(texPath)),
      src: "复现报告 · 本人",
      year: (st.date.match(/\b(19\d{2}|20\d{2})\b/) || [])[1] || "",
      texName: "main.tex",
      texRelPath: texPath.slice(repoRoot.length + 1).replace(/\\/g, "/"),
      texSha: sha256File(texPath),
      texBytes: sizeOf(texPath),
      claimsCount,
      refsCount: bib.length,
      tables: st.assets.tables,
      figures: st.assets.figures,
    };
  }

  const refsPath = texPath ? findSiblingArtifact(repoRoot, texPath, "refs_verified.json") : null;
  const refs = refsPath ? readJsonSafe(refsPath) : null;

  const base = buildLibrary({
    bib,
    pdfs: readPdfs(projectPath),
    refs,
    notes: readNoteIds(projectPath),
    repro: readReproCounts(projectPath),
    cites,
    own,
  });

  return {
    available: Boolean(tex) || base.items.length > 0,
    project: projectName,
    reason: tex ? "" : "仓库内未找到 docs/paper/*/main.tex",
    hint: tex ? "" : "把 LaTeX 源放到 docs/paper/<稿名>/main.tex",
    ...base,
  };
}

// ── 对外：写作台 ──
export function collectWriting({ projectPath, repoRoot, projectName }) {
  const texPath = findRepoPaperTex(repoRoot);
  if (!texPath) {
    return {
      available: false,
      project: projectName,
      reason: "仓库内未找到 docs/paper/*/main.tex",
      hint: "把 LaTeX 源放到 docs/paper/<稿名>/main.tex",
    };
  }

  const tex = readTextSafe(texPath) || "";
  const st = parseTexStructure(tex);
  const bib = parseBibItems(tex);

  const claimsPath = findSiblingArtifact(repoRoot, texPath, "claims.json");
  const claimsRaw = claimsPath ? readJsonSafe(claimsPath) : null;
  const claims = Array.isArray(claimsRaw) ? claimsRaw : Array.isArray(claimsRaw?.claims) ? claimsRaw.claims : [];
  const claimsWithSource = claims.filter((c) => c && (c.source || c.registry)).length;

  const refsPath = findSiblingArtifact(repoRoot, texPath, "refs_verified.json");
  const refs = refsPath ? readJsonSafe(refsPath) : null;

  const pdfPath = join(dirname(texPath), "main.pdf");
  const name = basename(dirname(texPath));

  // 同一份稿子在项目目录下还有一份副本吗？内容一致就合并，不一致就并列报出来。
  const dupPath = join(projectPath, "output", "documents", name, "main.tex");
  const duplicates = [];
  if (existsSync(dupPath)) {
    const mainSha = sha256File(texPath);
    const dupSha = sha256File(dupPath);
    duplicates.push({
      path: dupPath.slice(projectPath.length + 1).replace(/\\/g, "/"),
      bytes: sizeOf(dupPath),
      sha256: dupSha,
      same: dupSha === mainSha,
      lines: (readTextSafe(dupPath) || "").split(/\r?\n/).length,
      tables: (readTextSafe(dupPath) || "").match(/\\begin\{table\}/g)?.length || 0,
    });
  }

  return {
    available: true,
    project: projectName,
    tex: {
      path: texPath.slice(repoRoot.length + 1).replace(/\\/g, "/"),
      bytes: sizeOf(texPath),
      sha256: sha256File(texPath),
      lines: tex.split(/\r?\n/).length,
      title: st.title,
      date: st.date,
      mtime: statSync(texPath).mtime.toISOString(),
      // 源码全文：写作台中间栏显示的就是它（按行号渲染），
      // 大纲里的 L### 因此可以直接对到具体一行，不用另开接口。
      source: tex,
    },
    outline: st.outline,
    assets: {
      claims: {
        n: claims.length,
        withSource: claimsWithSource,
        path: claimsPath ? claimsPath.slice(repoRoot.length + 1).replace(/\\/g, "/") : "",
      },
      equations: { n: st.assets.equations },
      refs: {
        n: bib.length,
        verified: (refs?.papers || []).filter((x) => x.status === "verified").length,
        verdict: refs?.verdict || "",
        checkedAt: refs?._meta?.checked_at || "",
        hallucinationRate: refs?.hallucination_rate ?? null,
        path: refsPath ? refsPath.slice(repoRoot.length + 1).replace(/\\/g, "/") : "",
        items: bib.map((b) => {
          const r = (refs?.papers || []).find((x) => x.id === b.id);
          return {
            id: b.id,
            title: b.title,
            identifier: b.identifier,
            status: r?.status || "unverified",
            method: r?.method || "",
          };
        }),
      },
      tables: st.assets.tables,
      figures: st.assets.figures,
      bibitems: st.assets.bibitems,
    },
    pdf: existsSync(pdfPath)
      ? { path: pdfPath.slice(repoRoot.length + 1).replace(/\\/g, "/"), bytes: sizeOf(pdfPath) }
      : null,
    duplicates,
    // 项目内 5-paper/draft 的产出（如果存在），用于说明「哪一份才是源」
    projectDraft: existsSync(join(projectPath, "stages", "5-paper", "draft", "main.tex"))
      ? {
          path: "stages/5-paper/draft/main.tex",
          bytes: sizeOf(join(projectPath, "stages", "5-paper", "draft", "main.tex")),
          sha256: sha256File(join(projectPath, "stages", "5-paper", "draft", "main.tex")),
        }
      : null,
  };
}
