// 极简 Markdown 渲染器（零依赖，输出 React 元素而不是 HTML 字符串）。
//
// 为什么自己写而不引 marked/react-markdown：
//   ① 聊天流是增量追加的，每次 token 都要重渲染。这里的解析是纯函数 + 记忆化，
//      且只认科研对话里真会出现的子集，比通用实现快得多；
//   ② 输出 React 元素、永不走 dangerouslySetInnerHTML —— agent 的输出是模型生成的
//      不可信文本，一旦拼成 HTML 就多了个 XSS 面。元素树天然免疫。
//
// 支持的子集（够用即止，不支持的一律按纯文本显示，绝不吞内容）：
//   标题 # ## ###      粗体 **x**      斜体 *x*      行内代码 `x`
//   围栏代码块 ```lang  无序/有序列表   引用 >        表格 | a | b |
//   分隔线 ---         链接 [t](u)     引用指针 registry:x / paper:y
//
// 引用指针不是装饰：源文件里的 `registry:our_hybrid` 点了能跳到核查卡，
// 让「这句话的数字从哪来」在聊天里就能顺着走，而不是只能去论文库翻。

import type { ReactNode } from "react";

type Block =
  | { t: "h"; level: number; text: string }
  | { t: "p"; text: string }
  | { t: "code"; lang: string; code: string }
  | { t: "ul"; items: string[] }
  | { t: "ol"; items: string[]; start: number }
  | { t: "quote"; text: string }
  | { t: "table"; head: string[]; rows: string[][] }
  | { t: "hr" };

const FENCE = /^\s*```(\S*)\s*$/;
const HEADING = /^(#{1,6})\s+(.*)$/;
const UL = /^\s*[-*+]\s+(.*)$/;
const OL = /^\s*(\d+)[.)]\s+(.*)$/;
const QUOTE = /^\s*>\s?(.*)$/;
const HR = /^\s*(?:---|\*\*\*|___)\s*$/;
const TBL_SEP = /^\s*\|?[\s:-]*-[-\s:|]*\|?\s*$/;

function splitRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((c) => c.trim());
}

function parseBlocks(src: string): Block[] {
  const lines = (src || "").split(/\r?\n/);
  const out: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) {
      i++;
      continue;
    }

    // 围栏代码块：流式时可能还没收到闭合围栏，那就把剩下的都当代码
    const fence = FENCE.exec(line);
    if (fence) {
      const lang = fence[1] || "";
      const buf: string[] = [];
      i++;
      while (i < lines.length && !FENCE.test(lines[i])) {
        buf.push(lines[i]);
        i++;
      }
      i++; // 跳过闭合围栏（若已到末尾也安全）
      out.push({ t: "code", lang, code: buf.join("\n") });
      continue;
    }

    const h = HEADING.exec(line);
    if (h) {
      out.push({ t: "h", level: h[1].length, text: h[2].trim() });
      i++;
      continue;
    }

    if (HR.test(line)) {
      out.push({ t: "hr" });
      i++;
      continue;
    }

    // 表格：本行含 |，下一行是分隔行
    if (line.includes("|") && i + 1 < lines.length && TBL_SEP.test(lines[i + 1]) && lines[i + 1].includes("-")) {
      const head = splitRow(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) {
        rows.push(splitRow(lines[i]));
        i++;
      }
      out.push({ t: "table", head, rows });
      continue;
    }

    if (UL.test(line)) {
      const items: string[] = [];
      while (i < lines.length && UL.test(lines[i])) {
        items.push(UL.exec(lines[i])![1]);
        i++;
      }
      out.push({ t: "ul", items });
      continue;
    }

    if (OL.test(line)) {
      const items: string[] = [];
      const start = Number(OL.exec(line)![1]) || 1;
      while (i < lines.length && OL.test(lines[i])) {
        items.push(OL.exec(lines[i])![2]);
        i++;
      }
      out.push({ t: "ol", items, start });
      continue;
    }

    if (QUOTE.test(line)) {
      const buf: string[] = [];
      while (i < lines.length && QUOTE.test(lines[i])) {
        buf.push(QUOTE.exec(lines[i])![1]);
        i++;
      }
      out.push({ t: "quote", text: buf.join("\n") });
      continue;
    }

    // 段落：连续非空、且不是别的块起始
    const buf: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !FENCE.test(lines[i]) &&
      !HEADING.test(lines[i]) &&
      !HR.test(lines[i]) &&
      !UL.test(lines[i]) &&
      !OL.test(lines[i]) &&
      !QUOTE.test(lines[i])
    ) {
      buf.push(lines[i]);
      i++;
    }
    out.push({ t: "p", text: buf.join("\n") });
  }

  return out;
}

// 顺序有意义：先吃 code span（里面的星号不该变粗体），再粗体（先于斜体，
// 否则 **x** 会先被单星号规则吃掉一半），最后才是公式与引用指针。
const INLINE = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\*[^*\n]+\*)|(\[[^\]\n]+\]\([^)\s]+\))|(\$[^$\n]{1,80}\$)|((?:registry|paper):[A-Za-z0-9_.:#\[\]-]+)/g;

function pillFor(raw: string, key: string): ReactNode {
  const isPaper = raw.startsWith("paper:");
  const id = raw.slice(isPaper ? 6 : 9);
  if (!id) return <span key={key}>{raw}</span>;
  return (
    <button
      key={key}
      type="button"
      className={`md-pill ${isPaper ? "md-pill--paper" : "md-pill--reg"}`}
      title={
        isPaper
          ? `文献溯源指针 · 点击到核查台看它是否在已核验集合内`
          : `注册表指针 · 点击到核查台看这个实验的数值是否对得上`
      }
      onClick={() => {
        // 只带 id，不带整个 raw —— 核查台的 q 用来高亮匹配，id 足够定位
        if (typeof location !== "undefined") {
          location.hash = `#claims?q=${encodeURIComponent(id)}`;
        }
      }}
    >
      <span className="md-pill__ic">{isPaper ? "❝" : "◇"}</span>
      {id}
    </button>
  );
}

function renderInline(text: string, keyBase: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0;
  let n = 0;
  // 必须每次新建实例：renderInline 会为粗体/斜体递归调用自己，
  // 共用模块级 /g 正则时内层会把 lastIndex 改掉，外层循环随即从错位置继续。
  const re = new RegExp(INLINE.source, "g");

  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    const token = m[0];
    const k = `${keyBase}-${n++}`;

    if (token.startsWith("`")) {
      nodes.push(<code key={k} className="md-code">{token.slice(1, -1)}</code>);
    } else if (token.startsWith("**")) {
      nodes.push(<strong key={k}>{renderInline(token.slice(2, -2), k)}</strong>);
    } else if (token.startsWith("*")) {
      nodes.push(<em key={k}>{renderInline(token.slice(1, -1), k)}</em>);
    } else if (token.startsWith("$")) {
      // 没有 KaTeX：不假装渲染公式，只把源码单独标出来，
      // 免得 `\beta` 混在正文里看着像乱码。剥掉两侧的 $ 显示。
      nodes.push(
        <span key={k} className="md-math" title="行内公式源码（未渲染）">{token.slice(1, -1)}</span>
      );
    } else if (token.startsWith("[")) {
      const close = token.indexOf("](");
      const label = token.slice(1, close);
      const href = token.slice(close + 2, -1);
      // 只放行 http(s)/mailto：javascript: 之类的一律降级为纯文本
      if (/^(https?:|mailto:)/i.test(href)) {
        nodes.push(
          <a key={k} href={href} target="_blank" rel="noreferrer noopener">{label}</a>
        );
      } else {
        nodes.push(label);
      }
    } else {
      nodes.push(pillFor(token, k));
    }
    last = m.index + token.length;
  }

  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

// 流式场景下同一段文本会被连续解析多次（每次多几个 token）。
// 缓存最近 64 个结果，命中率极高，且避免长对话的历史消息反复重算。
const CACHE = new Map<string, Block[]>();
const CACHE_MAX = 64;

function blocksOf(src: string): Block[] {
  const hit = CACHE.get(src);
  if (hit) return hit;
  const parsed = parseBlocks(src);
  if (CACHE.size >= CACHE_MAX) {
    const first = CACHE.keys().next().value;
    if (first !== undefined) CACHE.delete(first);
  }
  CACHE.set(src, parsed);
  return parsed;
}

export function renderMarkdown(src: string): ReactNode {
  const blocks = blocksOf(src);
  return blocks.map((b, i) => {
    const k = `b${i}`;
    switch (b.t) {
      case "h": {
        const Tag = (`h${Math.min(b.level + 2, 6)}`) as "h3";
        return <Tag key={k} className="md-h">{renderInline(b.text, k)}</Tag>;
      }
      case "code":
        return (
          <pre key={k} className="md-pre">
            {b.lang && <span className="md-pre__lang">{b.lang}</span>}
            <code>{b.code}</code>
          </pre>
        );
      case "ul":
        return (
          <ul key={k} className="md-ul">
            {b.items.map((it, j) => <li key={`${k}-${j}`}>{renderInline(it, `${k}-${j}`)}</li>)}
          </ul>
        );
      case "ol":
        return (
          <ol key={k} className="md-ol" start={b.start}>
            {b.items.map((it, j) => <li key={`${k}-${j}`}>{renderInline(it, `${k}-${j}`)}</li>)}
          </ol>
        );
      case "quote":
        return <blockquote key={k} className="md-quote">{renderInline(b.text, k)}</blockquote>;
      case "table":
        return (
          <div key={k} className="md-tablewrap">
            <table className="md-table">
              <thead>
                <tr>{b.head.map((c, j) => <th key={j}>{renderInline(c, `${k}h${j}`)}</th>)}</tr>
              </thead>
              <tbody>
                {b.rows.map((r, j) => (
                  <tr key={j}>
                    {b.head.map((_, c) => <td key={c}>{renderInline(r[c] ?? "", `${k}r${j}c${c}`)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      case "hr":
        return <hr key={k} className="md-hr" />;
      default:
        return <p key={k} className="md-p">{renderInline(b.text, k)}</p>;
    }
  });
}
