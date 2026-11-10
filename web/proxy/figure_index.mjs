/**
 * 图纸索引——把「一张图」从文件系统碎片里拼回来。
 *
 * 现状（2026-11 实测，coal-thermal 项目）：
 *   同 3 张图，pdf 散在 output/figures、output/documents/coal_report、
 *   stages/5-paper/figures、stages/5-paper/draft 四处，png 两处，sha256 完全相同。
 *   前端按文件列，就会看到 3 张图变成 10 行；写作台说「图 2」，没人知道是哪个文件。
 *
 * 所以这里做的是**内容寻址的合并**：
 *   1. 按 pdf 的 sha256（没有 pdf 就用 png）给一张图一个 id：fig-<sha8>；
 *   2. 逐字节相同的副本合成一条，只列「还散落在哪几个目录」；
 *   3. 挂两样东西——正文里的引用位置（§小节 / 图 N / 行号 / \label），
 *      以及出图时写的旁文件（fig_meta：哪个工具、什么数据指纹）。
 *
 * 尺度说明：`\includegraphics{a.pdf}` 与 `a.pdf` 是同一条，按 basename 对；
 * 不解析 \graphicspath（本稿用的是同目录相对名，真出现多路径时宁可对不上也不猜）。
 */
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { basename, join, relative } from "node:path";

import { parseTexStructure } from "./paper_index.mjs";

/** 扫描目录（相对项目根）＋给用户看的说明 */
export const FIG_SCAN_DIRS = [
  ["output/figures", "出图目录"],
  ["stages/5-paper/figures", "写作阶段抄件"],
  ["stages/5-paper/draft", "草稿目录"],
  ["output/documents", "成稿目录"],
];

const IMG_EXT = new Set([".pdf", ".png"]);

export function sha256OfFile(p) {
  return createHash("sha256").update(readFileSync(p)).digest("hex");
}

/** 图纸 id：内容寻址，同一份图在任何目录下都是同一个 id */
export function figIdOf(sha) {
  return `fig-${String(sha).slice(0, 8)}`;
}

/** 预览/下载路由用：只接受本模块生成的 id 形状，别的直接拒（防路径拼接） */
export function isFigId(s) {
  return typeof s === "string" && /^fig-[0-9a-f]{8}$/.test(s);
}

/** 从 tex 结构里捞出全部图引用（含孤儿——不在任何小节下的图） */
export function refsFromStructure(st) {
  const all = [];
  for (const node of st.outline || []) {
    for (const leaf of node.leaves || []) {
      if (leaf.kind === "fig") {
        all.push({
          num: leaf.num,
          caption: leaf.text,
          line: leaf.line,
          envLine: leaf.envLine || leaf.line,
          file: leaf.file || "",
          texLabel: leaf.texLabel || "",
          sectionNum: node.num || "",
          sectionTitle: node.title || "",
        });
      }
    }
  }
  for (const leaf of st.orphanLeaves || []) {
    if (leaf.kind === "fig") {
      all.push({
        num: leaf.num,
        caption: leaf.text,
        line: leaf.line,
        envLine: leaf.envLine || leaf.line,
        file: leaf.file || "",
        texLabel: leaf.texLabel || "",
        sectionNum: "",
        sectionTitle: "",
      });
    }
  }
  return all.sort((a, b) => a.num - b.num);
}

/** 把文件副本按目录归并，返回 [{dir, formats, bytes}] */
function groupLocations(copies) {
  const m = new Map();
  for (const c of copies) {
    const dir = c.rel.split("/").slice(0, -1).join("/");
    if (!m.has(dir)) m.set(dir, { dir, formats: [], bytes: 0 });
    const g = m.get(dir);
    if (!g.formats.includes(c.format)) g.formats.push(c.format);
    g.bytes += c.bytes;
  }
  return [...m.values()]
    .map((g) => ({ ...g, formats: g.formats.sort() }))
    .sort((a, b) => a.dir.localeCompare(b.dir));
}

/**
 * 目录扫描结果 → 一条一条图纸。
 *
 * @param {object} p
 * @param {Array} p.files    [{rel, abs, base, format, bytes, sha256, mtime}]
 * @param {Array} p.refs     refsFromStructure 的结果
 * @param {Function} p.readMeta (base, rel) => {path, data}|null  读旁文件
 */
export function buildFigureIndex({ files = [], refs = [], readMeta = () => null } = {}) {
  // 1) 先按 basename 聚合：一个 base 的 pdf + png 是同一张图的两种格式
  //
  // 同一格式可能在多个目录各有一份（字节相同）。哪一份当「母版」必须是确定的：
  // 这里取**扫描顺序里第一个**，而扫描顺序是 FIG_SCAN_DIRS 的声明顺序
  // （output/figures 在最前），所以母版永远是出图目录那份。
  const byBase = new Map();
  for (const f of files) {
    if (!byBase.has(f.base)) byBase.set(f.base, { base: f.base, formats: {}, copies: [] });
    const g = byBase.get(f.base);
    if (!g.formats[f.format]) g.formats[f.format] = f;
    g.copies.push(f);
  }

  // 2) 再按 master 的内容 sha 合并不同目录里的同一个 base
  //    master = pdf（矢量母版）；没有 pdf 就退回 png
  const bySha = new Map();
  for (const g of byBase.values()) {
    const master = g.formats.pdf || g.formats.png;
    if (!master) continue;
    const key = master.sha256;
    if (!bySha.has(key)) {
      bySha.set(key, {
        fig_id: figIdOf(key),
        sha256: key,
        base: g.base,
        formats: {},
        copies: [],
      });
    }
    const item = bySha.get(key);
    for (const [fmt, f] of Object.entries(g.formats)) {
      if (!item.formats[fmt]) item.formats[fmt] = f;
    }
    item.copies.push(...g.copies);
  }

  // 3) 挂正文引用：按 includegraphics 的 basename 对（含扩展名与不带扩展名两种写法）
  const refByKey = new Map();
  for (const r of refs) {
    const f = String(r.file || "");
    if (!f) continue;
    const key = basename(f).replace(/\.(pdf|png|jpg|jpeg|eps)$/i, "");
    if (!refByKey.has(key)) refByKey.set(key, []);
    refByKey.get(key).push(r);
  }

  const figures = [];
  for (const item of bySha.values()) {
    const masterFmt = item.formats.pdf ? "pdf" : "png";
    const master = item.formats[masterFmt];
    const hits = refByKey.get(item.base) || [];

    // 一份图可能被正文引用多次（不同小节复用同一张图）；这里全列出来
    const refsOut = hits.map((r) => ({
      num: r.num,
      caption: r.caption,
      line: r.line,
      sectionNum: r.sectionNum,
      sectionTitle: r.sectionTitle,
      texLabel: r.texLabel,
    }));

    // 旁文件优先取母版那一份；同 base 的副本即使各自带旁文件也只认母版的
    const mp = readMeta(item.base, master.rel);
    const meta = mp?.data ?? null;

    const concerns = [];
    if (!meta) {
      concerns.push({
        level: "warn",
        code: "no-provenance",
        text: "无出处记录：这张图旁边没有 .meta.json，无法回溯用哪个工具、哪份数据画的",
      });
    }
    if (!refsOut.length) {
      concerns.push({ level: "info", code: "unreferenced", text: "正文未引用（\u005cincludegraphics 里没有它）" });
    }
    if (!item.formats.pdf) {
      concerns.push({ level: "warn", code: "raster-only", text: "只有位图，没有矢量 pdf（投稿通常要矢量）" });
    }
    if (!item.formats.png) {
      concerns.push({ level: "info", code: "no-preview", text: "没有 png，页面上无法直接预览" });
    }
    if (refsOut.length && !refsOut.some((r) => r.texLabel)) {
      concerns.push({
        level: "info",
        code: "no-label",
        text: "正文里没有 \\label{fig:*}，无法交叉引用（只能写死「图 N」）",
      });
    }

    figures.push({
      fig_id: item.fig_id,
      base: item.base,
      sha256: item.sha256,
      masterFormat: masterFmt,
      bytes: master.bytes,
      formats: Object.fromEntries(
        Object.entries(item.formats).map(([k, f]) => [k, { rel: f.rel, bytes: f.bytes, sha256: f.sha256 }])
      ),
      // copies 是「文件」，locations 是「目录」——用户想知道的是「这张图在几个地方各有一份」
      copies: item.copies
        .map((c) => ({ rel: c.rel, format: c.format, bytes: c.bytes, dir: c.rel.split("/").slice(0, -1).join("/") }))
        .sort((a, b) => a.rel.localeCompare(b.rel)),
      locations: groupLocations(item.copies),
      copyCount: item.copies.length,
      dirCount: groupLocations(item.copies).length,
      provenance: meta,
      provenancePath: mp?.path || "",
      refs: refsOut,
      referenced: refsOut.length > 0,
      concerns,
    });
  }

  figures.sort((a, b) => {
    // 正文引用过的排前面，按图号；其余按生成时间倒序（新的在前）
    if (a.referenced !== b.referenced) return a.referenced ? -1 : 1;
    if (a.referenced) return (a.refs[0]?.num || 0) - (b.refs[0]?.num || 0);
    return a.base.localeCompare(b.base);
  });

  const summary = {
    /** 合并后的图纸数（不是文件数） */
    total: figures.length,
    /** 磁盘上的图片文件数 */
    files: files.length,
    referenced: figures.filter((f) => f.referenced).length,
    unreferenced: figures.filter((f) => !f.referenced).length,
    withProvenance: figures.filter((f) => f.provenance).length,
    /** 散落在 2 个以上目录的图有几张（这些是最容易「改了一份、另一份还是旧的」的） */
    multiCopy: figures.filter((f) => f.dirCount > 1).length,
    /** 合并前如果按文件列会有多少行 */
    rowsBeforeMerge: files.length,
  };

  return { figures, summary };
}

// ───────────────────────────── 读盘 ─────────────────────────────

function walkImages(dirAbs, projectPath) {
  const out = [];
  if (!existsSync(dirAbs)) return out;
  const stack = [dirAbs];
  let guard = 0;
  while (stack.length) {
    const d = stack.pop();
    let ents = [];
    try {
      ents = readdirSync(d, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const e of ents) {
      const p = join(d, e.name);
      if (e.isDirectory()) {
        if (++guard > 4000) break;
        stack.push(p);
        continue;
      }
      const m = e.name.match(/\.([a-z0-9]+)$/i);
      if (!m) continue;
      const fmt = m[1].toLowerCase();
      if (!IMG_EXT.has(`.${fmt}`)) continue;
      if (e.name.endsWith(".meta.json")) continue;
      let st;
      try {
        st = statSync(p);
      } catch {
        continue;
      }
      out.push({
        abs: p,
        rel: relative(projectPath, p).split(/[\\/]/).join("/"),
        base: e.name.replace(/\.[a-z0-9]+$/i, ""),
        format: fmt,
        bytes: st.size,
        sha256: sha256OfFile(p),
        mtime: st.mtime.toISOString(),
      });
    }
  }
  return out;
}

/**
 * 项目内所有图片 → 台账。
 * 旁文件只在出图目录里找（母版同目录），找不到就当「无出处」，不跨目录猜。
 */
export function collectFigures({ projectPath, repoRoot, projectName, texPath }) {
  if (!projectPath || !existsSync(projectPath)) {
    return {
      available: false,
      project: projectName,
      reason: "项目目录不存在",
      hint: "先在格物里建一个课题",
      figures: [],
      summary: null,
    };
  }

  const files = [];
  const scans = [];
  for (const [rel, label] of FIG_SCAN_DIRS) {
    const abs = join(projectPath, rel);
    const got = walkImages(abs, projectPath);
    scans.push({ dir: rel, label, exists: existsSync(abs), files: got.length });
    files.push(...got);
  }

  const tex = texPath && existsSync(texPath) ? readFileSync(texPath, "utf8") : "";
  const st = tex ? parseTexStructure(tex) : { outline: [], orphanLeaves: [] };
  const refs = refsFromStructure(st);

  const readMeta = (base, rel) => {
    // 旁文件与母版同目录：<base>.meta.json
    const dir = rel.split("/").slice(0, -1).join("/");
    const abs = join(projectPath, dir, `${base}.meta.json`);
    if (!existsSync(abs)) return null;
    try {
      const d = JSON.parse(readFileSync(abs, "utf8"));
      if (!d || typeof d !== "object") return null;
      return { path: `${dir}/${base}.meta.json`, data: d };
    } catch {
      return null; // 坏 json 当没有，不猜
    }
  };

  const { figures, summary } = buildFigureIndex({ files, refs, readMeta });

  return {
    available: true,
    project: projectName,
    dirs: scans,
    texPath: texPath ? relative(repoRoot, texPath).split(/[\\/]/).join("/") : "",
    figures,
    summary,
  };
}
