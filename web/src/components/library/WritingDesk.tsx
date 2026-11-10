import { useEffect, useMemo, useRef, useState } from "react";
import type { WritingLeaf, WritingNode, WritingResponse } from "../../types";

type Sel =
  | { kind: "sec"; index: number }
  | { kind: "leaf"; index: number; leaf: number }
  | { kind: "asset"; key: "claims" | "equations" | "refs" };

const ICON: Record<WritingLeaf["kind"], string> = { tbl: "▦", fig: "◨", cite: "❝" };

// 写作台：左大纲（行号可核对）、中源码（就是磁盘上那份 tex）、右详情。
// 中间不放 PDF 骨架页 —— 那只能看个形状；放源码才能验证「大纲 L78」确实指向表 1。
export function WritingDesk({ data, onToast }: { data: WritingResponse | null; onToast: (m: string) => void }) {
  const [sel, setSel] = useState<Sel>({ kind: "sec", index: 0 });
  const lineRefs = useRef(new Map<number, HTMLDivElement>());
  const srcRef = useRef<HTMLDivElement>(null);

  const outline = data?.outline || [];
  const selNode: WritingNode | null = useMemo(() => {
    if (!outline.length) return null;
    if (sel.kind === "sec") return outline[sel.index] || null;
    if (sel.kind === "leaf") {
      const n = outline[sel.index];
      return n && n.leaves[sel.leaf] ? n : null;
    }
    return null;
  }, [outline, sel]);

  const targetLine = useMemo(() => {
    if (sel.kind === "sec") return outline[sel.index]?.line ?? null;
    if (sel.kind === "leaf") return outline[sel.index]?.leaves[sel.leaf]?.line ?? null;
    return null;
  }, [outline, sel]);

  // 自己算 scrollTop：scrollIntoView 在嵌套滚动容器里会把外层一起带走，
  // 而且行为随浏览器不同；这里只滚 .pw-src 自己，目标行落在视口 1/3 处。
  useEffect(() => {
    const box = srcRef.current;
    if (!targetLine || !box) return;
    const el = lineRefs.current.get(targetLine);
    if (!el) return;
    const top = el.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop;
    box.scrollTo({ top: Math.max(0, top - box.clientHeight / 3), behavior: "smooth" });
  }, [targetLine]);

  const lines = useMemo(() => (data?.tex?.source || "").split(/\r?\n/), [data?.tex?.source]);

  // 大纲涉及的所有行：章节行 + 表/图/引用行，用来在源码里区分「结构行」和正文
  const markLines = useMemo(() => {
    const sec = new Set<number>();
    const leaf = new Set<number>();
    for (const n of outline) {
      sec.add(n.line);
      for (const l of n.leaves) leaf.add(l.line);
    }
    return { sec, leaf };
  }, [outline]);

  if (!data) {
    return <div className="pw-view"><div className="pw-empty">正在解析 main.tex…</div></div>;
  }
  if (!data.available || !data.tex || !data.assets) {
    return (
      <div className="pw-view">
        <div className="pw-empty">
          <p>{data.reason || "没有可解析的稿子"}</p>
          {data.hint && <p><code>{data.hint}</code></p>}
        </div>
      </div>
    );
  }

  const a = data.assets;

  return (
    <div className="pw-view">
      <nav className="pw-outline" aria-label="稿子结构">
        <div className="pw-olh">结构（行号对应该 tex 文件）</div>
        {outline.map((n, i) => (
          <div key={`${n.line}-${n.title}`}>
            <button
              className={`pw-node s${n.level}`}
              aria-selected={sel.kind === "sec" && sel.index === i}
              title={`${n.num ? `${n.num} ` : ""}${n.title}　L${n.line}`}
              onClick={() => setSel({ kind: "sec", index: i })}
            >
              <span className="tx">{n.num ? `${n.num}　${n.title}` : n.title}</span>
              <span className="ln">L{n.line}</span>
            </button>
            {n.leaves.map((l, j) => (
              <button
                key={`${l.kind}-${l.num}-${l.line}`}
                className="pw-node leaf"
                aria-selected={sel.kind === "leaf" && sel.index === i && sel.leaf === j}
                title={`${l.label}　L${l.line}`}
                onClick={() => setSel({ kind: "leaf", index: i, leaf: j })}
              >
                <span className="ic">{ICON[l.kind]}</span>
                <span className="tx">{l.label}</span>
                <span className="ln">L{l.line}</span>
              </button>
            ))}
          </div>
        ))}

        <div className="pw-olsplit" />
        <div className="pw-olh">资产</div>
        <button
          className="pw-node s1"
          aria-selected={sel.kind === "asset" && sel.key === "claims"}
          onClick={() => setSel({ kind: "asset", key: "claims" })}
        >
          <span className="ic">#</span>
          <span className="tx">核查声明 {a.claims.n}</span>
          <span className="ln">{a.claims.withSource}</span>
        </button>
        <button
          className="pw-node s1"
          aria-selected={sel.kind === "asset" && sel.key === "equations"}
          onClick={() => setSel({ kind: "asset", key: "equations" })}
        >
          <span className="ic">#</span>
          <span className="tx">编号公式 {a.equations.n}</span>
        </button>
        <button
          className="pw-node s1"
          aria-selected={sel.kind === "asset" && sel.key === "refs"}
          onClick={() => setSel({ kind: "asset", key: "refs" })}
        >
          <span className="ic">#</span>
          <span className="tx">参考文献 {a.refs.n}</span>
          <span className="ln">{a.refs.verified}</span>
        </button>
      </nav>

      <div className="pw-src" ref={srcRef}>
        <div className="pw-srchead">
          <b>{data.tex.path}</b>
          <span>·</span>
          <span>{data.tex.lines} 行 · {data.tex.bytes} B</span>
          <span>·</span>
          <span className="pw-mono">sha {data.tex.sha256.slice(0, 12)}</span>
          <span style={{ marginLeft: "auto" }}>
            {data.pdf ? `编译产物 ${data.pdf.path} · ${(data.pdf.bytes / 1024).toFixed(0)} KB` : "未找到编译产物 main.pdf"}
          </span>
        </div>
        <pre className="pw-code">
          {lines.map((text, i) => {
            const ln = i + 1;
            const cls = ln === targetLine ? (sel.kind === "leaf" ? "is-leaf" : "is-sec") : "";
            return (
              <div
                key={ln}
                className={`pw-line ${cls}`}
                ref={(el) => {
                  if (el) lineRefs.current.set(ln, el);
                  else lineRefs.current.delete(ln);
                }}
              >
                <span className="no">{ln}</span>
                <span className="src">{text || " "}</span>
              </div>
            );
          })}
        </pre>
      </div>

      <aside className="pw-detail" aria-live="polite">
        {sel.kind === "sec" && selNode && (
          <SectionDetail node={selNode} texPath={data.tex.path} onToast={onToast} />
        )}
        {sel.kind === "leaf" && selNode && (
          <LeafDetail
            node={selNode}
            leaf={selNode.leaves[sel.leaf]}
            texPath={data.tex.path}
            refItems={a.refs.items}
            onToast={onToast}
          />
        )}
        {sel.kind === "asset" && <AssetDetail data={data} which={sel.key} />}
      </aside>
    </div>
  );
}

function SectionDetail({
  node,
  texPath,
  onToast,
}: {
  node: WritingNode;
  texPath: string;
  onToast: (m: string) => void;
}) {
  const tbls = node.leaves.filter((l) => l.kind === "tbl");
  const figs = node.leaves.filter((l) => l.kind === "fig");
  const cite = node.leaves.find((l) => l.kind === "cite");
  return (
    <>
      <h3>{node.num ? `${node.num}　${node.title}` : node.title}</h3>
      <div className="d-kind">章节 · {texPath} 第 {node.line} 行</div>
      <div className="pw-kv"><span className="k">层级</span><span className="v">{node.level === 0 ? "章" : "节"}</span></div>
      <div className="pw-kv">
        <span className="k">图表</span>
        <span className="v">{tbls.length} 表 · {figs.length} 图</span>
      </div>
      <div className="pw-kv">
        <span className="k">引用</span>
        <span className="v">{cite ? cite.label.replace(/^引用\s*/, "") : "本节无引用"}</span>
      </div>
      {node.leaves.length > 0 && (
        <div className="pw-sec">
          <div className="pw-sec-h">下级节点</div>
          {node.leaves.map((l) => (
            <div className="pw-refrow" key={`${l.kind}-${l.num}-${l.line}`}>
              <span className="rid">{ICON[l.kind]}</span>
              <span className="rtx">{l.kind === "cite" ? l.label : `${l.label}　${l.text}`}</span>
              <span className="pw-sub">L{l.line}</span>
            </div>
          ))}
        </div>
      )}
      <button
        className="pw-btn"
        style={{ marginTop: 12 }}
        onClick={() => {
          navigator.clipboard?.writeText(`${node.num ? node.num + "　" : ""}${node.title}`);
          onToast("已复制章节标题");
        }}
      >
        复制标题
      </button>
    </>
  );
}

function LeafDetail({
  node,
  leaf,
  texPath,
  refItems,
  onToast,
}: {
  node: WritingNode;
  leaf: WritingLeaf;
  texPath: string;
  refItems: { id: string; title: string; identifier: string; status: string; method: string }[];
  onToast: (m: string) => void;
}) {
  if (leaf.kind === "cite") {
    const ids = leaf.label.replace(/^引用\s*/, "").split(/\s+/).filter(Boolean);
    const byId = new Map(refItems.map((r) => [r.id, r]));
    return (
      <>
        <h3>{node.num ? `${node.num}　${node.title}` : node.title}　· 引用</h3>
        <div className="d-kind">引用节点 · {texPath} 第 {leaf.line} 行</div>
        <div className="pw-kv"><span className="k">条数</span><span className="v">{ids.length}</span></div>
        <div className="pw-sec">
          <div className="pw-sec-h">本节引用</div>
          {ids.map((id) => {
            const r = byId.get(id);
            return (
              <div className="pw-refrow" key={id}>
                <span className="rid">{id}</span>
                <span className="rtx" title={r?.title || ""}>{r?.title || "参考文献里找不到这个 id"}</span>
                <span className={`pw-badge ${r?.status === "verified" ? "b-ok" : "b-mut"}`}>
                  {r?.status === "verified" ? "已核" : "未核"}
                </span>
              </div>
            );
          })}
        </div>
        <div className="pw-warnbox">
          引用计数来自正文 \cite{"{…}"} 的实际展开；点开参考文献资产可看每条的核验方式与命中标识符。
        </div>
      </>
    );
  }

  const isTable = leaf.kind === "tbl";
  return (
    <>
      <h3>{leaf.label}</h3>
      <div className="d-kind">{isTable ? "表" : "图"}环境 · {texPath} 第 {leaf.line} 行</div>
      <div className="pw-kv"><span className="k">题注</span><span className="v">{leaf.text || "（无题注）"}</span></div>
      <div className="pw-kv"><span className="k">所属</span><span className="v">{node.num ? `${node.num}　${node.title}` : node.title}</span></div>
      <div className="pw-kv"><span className="k">数据源</span><span className="v">未登记</span></div>
      <div className="pw-warnbox">
        tex 里这个{isTable ? "表" : "图"}没有 \label，也没有指向 registry / predictions.json 的指针，
        所以「这一{isTable ? "行" : "点"}数字从哪来」目前只能靠题注和文件名推断。
        要变成可核资产，得给它一个 \label 并在 claims 里挂来源。
      </div>
      <button
        className="pw-btn"
        style={{ marginTop: 12 }}
        onClick={() => {
          navigator.clipboard?.writeText(`${leaf.label}　${leaf.text}`);
          onToast("已复制题注");
        }}
      >
        复制题注
      </button>
    </>
  );
}

function AssetDetail({ data, which }: { data: WritingResponse; which: "claims" | "equations" | "refs" }) {
  const a = data.assets!;
  if (which === "claims") {
    return (
      <>
        <h3>核查声明 {a.claims.n}</h3>
        <div className="d-kind">{a.claims.path || "未找到 claims.json"}</div>
        <div className="pw-kv"><span className="k">带来源</span><span className="v">{a.claims.withSource} / {a.claims.n}</span></div>
        <div className="pw-kv"><span className="k">格式</span><span className="v">text · metric · value · source</span></div>
        <div className="pw-warnbox">
          本页只统计「有没有来源指针」，不判定失效。要判失效得拿每条 source 回 registry
          重算并比对数值——那一步尚未接进这个视图，所以这里不写「0 条失效」。
        </div>
      </>
    );
  }
  if (which === "equations") {
    return (
      <>
        <h3>编号公式 {a.equations.n}</h3>
        <div className="d-kind">{a.equations.n === 0 ? "全文没有独立编号公式" : `${a.equations.n} 条 equation/align 环境`}</div>
        <div className="pw-kv"><span className="k">统计口径</span><span className="v">\begin{"{equation}"} / \begin{"{align}"} / \[ … \]</span></div>
        <div className="pw-kv"><span className="k">资产</span><span className="v">{a.equations.n} 条</span></div>
        <div className="pw-warnbox">
          {a.equations.n === 0
            ? "这是真缺口：公式全部写在行内 $…$，没有编号，也没有符号表。实现里的超参（例如 β）改了，没人能被提醒「公式没跟着改」。"
            : "公式已编号，但还没有与实现参数互锁的检查。"}
        </div>
      </>
    );
  }
  const r = a.refs;
  return (
    <>
      <h3>参考文献 {r.n}</h3>
      <div className="d-kind">{r.path || "未找到 refs_verified.json"}</div>
      <div className="pw-kv"><span className="k">结论</span><span className="v">{r.verdict || "—"}</span></div>
      <div className="pw-kv"><span className="k">已核验</span><span className="v">{r.verified} / {r.n}</span></div>
      {r.hallucinationRate != null && (
        <div className="pw-kv"><span className="k">幻觉率</span><span className="v">{r.hallucinationRate}</span></div>
      )}
      <div className="pw-kv"><span className="k">核验日</span><span className="v">{r.checkedAt || "—"}</span></div>
      <div className="pw-sec">
        <div className="pw-sec-h">逐条</div>
        {r.items.map((it) => (
          <div className="pw-refrow" key={it.id}>
            <span className="rid">{it.id}</span>
            <span className="rtx" title={it.title}>{it.title}</span>
            <span className={`pw-badge ${it.status === "verified" ? "b-ok" : "b-mut"}`}>
              {it.status === "verified" ? it.method || "已核" : it.status}
            </span>
          </div>
        ))}
      </div>
      <div className="pw-warnbox">
        核验只证明「这篇文献存在且标识符对得上」，不证明「本稿引用它是对的」。
        后者要看正文那句说法，属于引用恰当性，这页不管。
      </div>
    </>
  );
}
