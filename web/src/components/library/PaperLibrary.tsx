import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import type { LibraryItem, LibraryResponse } from "../../types";
import { getPaperNotes } from "../../api/client";

type Filter = "all" | "own" | "notes" | "missing";
type SortKey = "title" | "year";

// 标题底色 = 推进度。只用 brand-soft，不引第三种颜色，避免和核查徽章抢注意力。
function heatStyle(p: number): CSSProperties {
  const a = Math.max(0, p - 5);
  const b = Math.min(100, p + 2);
  return {
    backgroundImage: `linear-gradient(90deg, var(--brand-soft) 0, var(--brand-soft) ${a}%, transparent ${b}%)`,
  };
}

function relHtml(it: LibraryItem) {
  const tip =
    it.kind === "own"
      ? `本稿引用外部文献 ${it.rel.cite} 篇`
      : `笔记 ${it.rel.note} 篇 · 复现请求 ${it.rel.repro} 次 · 被本稿引用 ${it.rel.cite} 处`;
  const f = (n: number, k: string) => (
    <span className={n ? "" : "zero"}>
      {k}
      <b>{n || 0}</b>
    </span>
  );
  return (
    <div className="pw-rel" title={tip}>
      {f(it.rel.note, "笔")}
      {f(it.rel.repro, "复")}
      {f(it.rel.cite, "引")}
    </div>
  );
}

export function PaperLibrary({
  data,
  onToast,
  onOpenPaper,
  onRetry,
}: {
  data: LibraryResponse | null;
  onToast: (msg: string) => void;
  onOpenPaper?: (paperId: string) => void;
  onRetry: () => void;
}) {
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 } | null>(null);
  const [selId, setSelId] = useState<string | null>(null);
  const [peekId, setPeekId] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string | null>>({});
  const [scrolling, setScrolling] = useState(false);
  const peekTimer = useRef<number | undefined>(undefined);
  const scrollTimer = useRef<number | undefined>(undefined);

  const items = data?.items || [];

  const rows = useMemo(() => {
    const kw = q.trim().toLowerCase();
    let list = items.filter((it) => {
      if (filter === "own" && it.kind !== "own") return false;
      if (filter === "notes" && it.rel.note === 0) return false;
      if (filter === "missing" && (it.kind !== "ext" || it.pdf)) return false;
      if (!kw) return true;
      return [it.title, it.src, it.identifier, it.year, ...(it.tags || [])]
        .join(" ")
        .toLowerCase()
        .includes(kw);
    });
    if (sort) {
      list = [...list].sort((a, b) => {
        const va = sort.key === "year" ? a.year : a.title;
        const vb = sort.key === "year" ? b.year : b.title;
        return String(va).localeCompare(String(vb), "zh") * sort.dir;
      });
    }
    return list;
  }, [items, q, filter, sort]);

  const sel = selId || items[0]?.id || null;
  const activeId = peekId || sel;
  const active = items.find((x) => x.id === activeId) || null;

  // 笔记按需拉：几百字节的 md，点了才读；读不到就是"没有"，不编造
  useEffect(() => {
    if (!activeId) return;
    if (notes[activeId] !== undefined) return;
    let alive = true;
    getPaperNotes(activeId)
      .then((r) => alive && setNotes((p) => ({ ...p, [activeId]: r.notes || "" })))
      .catch(() => alive && setNotes((p) => ({ ...p, [activeId]: null })));
    return () => {
      alive = false;
    };
  }, [activeId, notes]);

  useEffect(
    () => () => {
      window.clearTimeout(peekTimer.current);
      window.clearTimeout(scrollTimer.current);
    },
    []
  );

  const hover = (id: string) => {
    if (peekId === id) return;
    window.clearTimeout(peekTimer.current);
    peekTimer.current = window.setTimeout(() => setPeekId(id), 180);
  };

  const copy = (text: string, label: string) => {
    if (!text || text === "—") return;
    navigator.clipboard?.writeText(text).then(
      () => onToast(`已复制${label}`),
      () => onToast("复制失败（浏览器未授权剪贴板）")
    );
  };

  const onScroll = () => {
    setScrolling(true);
    window.clearTimeout(scrollTimer.current);
    scrollTimer.current = window.setTimeout(() => setScrolling(false), 450);
  };

  if (!data) {
    return <div className="pw-view"><div className="pw-empty">正在读取论文索引…</div></div>;
  }
  if (!data.available) {
    return (
      <div className="pw-view">
        <div className="pw-empty">
          <p>{data.reason || "没有可索引的论文数据"}</p>
          {data.hint && <p><code>{data.hint}</code></p>}
          <button className="pw-ghost" onClick={onRetry}>重试</button>
        </div>
      </div>
    );
  }

  const s = data.summary;

  return (
    <div className="pw-view">
      <div className={`pw-lib ${scrolling ? "pw-lib--scrolling" : ""}`}>
        <div className="pw-libbar">
          <div className="pw-search">
            <span className="ic">⌕</span>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="搜索标题、来源、标识符、年份…"
              aria-label="搜索论文"
            />
          </div>
          <div className="pw-chips">
            {(
              [
                ["all", `全部 ${s.total}`],
                ["own", `我的稿子 ${items.filter((x) => x.kind === "own").length}`],
                ["notes", `有笔记 ${s.withNotes}`],
                ["missing", `缺 PDF ${s.missingPdf}`],
              ] as [Filter, string][]
            ).map(([k, label]) => (
              <button
                key={k}
                className="pw-chip"
                aria-pressed={filter === k}
                onClick={() => setFilter(k)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="pw-legend">
            <i />
            标题底色 = 推进度（{data.progressSteps.join("→")}）
          </div>
        </div>

        <div className="pw-tablewrap" onScroll={onScroll}>
          <table className="pw-table">
            <colgroup className="pw-cols">
              <col style={{ width: "29%" }} />
              <col style={{ width: "13%" }} />
              <col style={{ width: "6%" }} />
              <col style={{ width: "14%" }} />
              <col style={{ width: "9%" }} />
              <col style={{ width: "16%" }} />
              <col style={{ width: "13%" }} />
            </colgroup>
            <thead>
              <tr>
                <th>
                  <button
                    className="pw-th"
                    data-on={sort?.key === "title"}
                    onClick={() =>
                      setSort((p) =>
                        p?.key === "title" ? { key: "title", dir: p.dir === 1 ? -1 : 1 } : { key: "title", dir: 1 }
                      )
                    }
                  >
                    标题 <span className="so">{sort?.key === "title" ? (sort.dir === 1 ? "▲" : "▼") : "▲▼"}</span>
                  </button>
                </th>
                <th><span className="pw-th">来源 / 作者</span></th>
                <th>
                  <button
                    className="pw-th"
                    data-on={sort?.key === "year"}
                    onClick={() =>
                      setSort((p) =>
                        p?.key === "year" ? { key: "year", dir: p.dir === 1 ? -1 : 1 } : { key: "year", dir: 1 }
                      )
                    }
                  >
                    年份 <span className="so">{sort?.key === "year" ? (sort.dir === 1 ? "▲" : "▼") : "▲▼"}</span>
                  </button>
                </th>
                <th><span className="pw-th">核查状态</span></th>
                <th><span className="pw-th">标签</span></th>
                <th><span className="pw-th">标识符</span></th>
                <th><span className="pw-th">关联</span></th>
              </tr>
            </thead>
            <tbody onMouseLeave={() => setPeekId(null)}>
              {rows.map((it) => (
                <tr
                  key={it.id}
                  aria-selected={sel === it.id}
                  onClick={() => setSelId(it.id)}
                  onMouseEnter={() => hover(it.id)}
                >
                  <td>
                    <button
                      className="pw-cell"
                      onDoubleClick={(e) => {
                        e.stopPropagation();
                        copy(it.title, "标题");
                      }}
                      title={`${it.title}\n双击复制`}
                    >
                      <div className="pw-tmain">
                        <span className={`pw-kind ${it.kind === "own" ? "pw-kind--own" : ""}`}>{it.label}</span>
                        <span className="pw-heat" style={heatStyle(it.prog)} title={`推进度 ${it.prog}%`}>
                          {it.title}
                        </span>
                      </div>
                    </button>
                  </td>
                  <td>
                    <button
                      className="pw-cell"
                      onDoubleClick={(e) => {
                        e.stopPropagation();
                        copy(it.src, "来源");
                      }}
                      title={it.src}
                    >
                      <span className="pw-sub">{it.src}</span>
                    </button>
                  </td>
                  <td><span className="pw-sub pw-mono">{it.year || "—"}</span></td>
                  <td>
                    <span className={`pw-badge ${it.check.cls}`}>{it.check.t}</span>
                    <div className="pw-sub">{it.check.sub}</div>
                  </td>
                  <td>
                    {it.tags && it.tags.length ? (
                      <div className="pw-tags">
                        {it.tags.map((t) => (
                          <span key={t} className="pw-tag">{t}</span>
                        ))}
                      </div>
                    ) : (
                      <span className="pw-sub" title=".meta.json 里没有标签字段，索引不编造">
                        —
                      </span>
                    )}
                  </td>
                  <td>
                    <button
                      className="pw-cell"
                      onDoubleClick={(e) => {
                        e.stopPropagation();
                        copy(it.identifier, "标识符");
                      }}
                      title={it.identifier}
                    >
                      <span className="pw-idf">{it.identifier}</span>
                    </button>
                  </td>
                  <td>{relHtml(it)}</td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={7} style={{ padding: 24, color: "var(--text-tertiary)", textAlign: "center" }}>
                    没有匹配的条目
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="pw-foot">
          <span>{s.total} 篇</span>
          <span className="sep">·</span>
          <span>{s.verified} 篇文献已核验</span>
          <span className="sep">·</span>
          <span>{s.withNotes} 篇有笔记</span>
          <span className="sep">·</span>
          <span>{s.withRepro} 篇有复现请求</span>
          <span className="sep">·</span>
          <span>{s.missingPdf} 篇缺本机 PDF</span>
          {s.ownChecked > 0 && (
            <>
              <span className="sep">·</span>
              <span>本稿声明已核 {s.ownChecked}</span>
            </>
          )}
          <span className="hint">单击选中，双击任意单元格复制</span>
        </div>
      </div>

      <aside className="pw-peek" aria-live="polite">
        {active ? (
          <Peek item={active} note={notes[active.id]} steps={data.progressSteps} onOpenPaper={onOpenPaper} />
        ) : (
          <div className="pw-empty" style={{ margin: 0 }}>选中一行查看明细</div>
        )}
      </aside>
    </div>
  );
}

function Peek({
  item,
  note,
  steps,
  onOpenPaper,
}: {
  item: LibraryItem;
  note: string | null | undefined;
  steps: string[];
  onOpenPaper?: (paperId: string) => void;
}) {
  return (
    <>
      <h3>{item.title}</h3>
      <div className="p-meta">
        {item.src} · {item.year || "—"}
      </div>

      <div className="pw-sec-h">推进</div>
      <div className="pw-pbar">
        {item.steps.map((on, i) => (
          <i key={i} className={on ? "on" : ""} title={`${steps[i]}${on ? " 已完成" : " 未开始"}`} />
        ))}
      </div>
      <div className="pw-plab">
        {steps.map((n, i) => (
          <span key={n} className={item.steps[i] ? "on" : ""}>{n}</span>
        ))}
      </div>

      <div className="pw-sec">
        <div className="pw-sec-h">核查</div>
        <div className="pw-sec-v">
          <span className={`pw-badge ${item.check.cls}`}>{item.check.t}</span> {item.check.sub}
        </div>
      </div>

      <div className="pw-sec">
        <div className="pw-sec-h">标识符</div>
        <div className="pw-sec-v pw-mono">{item.identifier}</div>
      </div>

      <div className="pw-sec">
        <div className="pw-sec-h">明细</div>
        <div className="pw-sec-v">
          {item.lines.map((l) => (
            <div key={l}>· {l}</div>
          ))}
        </div>
      </div>

      <div className="pw-sec">
        <div className="pw-sec-h">笔记</div>
        {note === undefined ? (
          <div className="pw-sec-v">读取中…</div>
        ) : note ? (
          <div className="pw-note">{note}</div>
        ) : (
          <div className="pw-sec-v" style={{ color: "var(--text-tertiary)" }}>无笔记</div>
        )}
      </div>

      {item.kind === "ext" && (
        <div className="pw-actions">
          <button
            className="pw-btn"
            disabled={!item.pdf || !onOpenPaper}
            title={item.pdf ? "在阅读器中打开" : "本机没有这篇的 PDF，先导入才能读"}
            onClick={() => onOpenPaper?.(item.id)}
          >
            {item.pdf ? "打开阅读器" : "缺 PDF"}
          </button>
        </div>
      )}
    </>
  );
}
