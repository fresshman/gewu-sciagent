import { useState } from "react";
import { figurePdfUrl, figurePreviewUrl } from "../../api/client";
import type { FigureItem } from "../../types";

// 一张图纸的卡片。合并前它是 4–8 个文件；这里只出现一次。
//
// 信息的排列顺序按「写论文时真正会问的问题」来：
//   这张图长什么样 → 它被哪一节引用 → 还剩几个地方有它的副本 → 它到底是怎么画出来的。
// 最后一条没有就写「无出处」，不写「未登记」这种含糊话，也不假装有。

export function kindLabel(kind: string): string {
  // 名字要贴着画布上真实的东西：柱状图的误差棒帽是 Line2D，叫「曲线」会被读成折线
  const m: Record<string, string> = {
    line: "线",
    patch: "矩形",
    image: "位图",
    LineCollection: "线段组",
    PolyCollection: "多边形",
    PathCollection: "散点",
  };
  return m[kind] || kind;
}

function kb(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function shortTime(iso: string): string {
  // 2026-11-10T11:15:08+08:00 → 11-10 11:15
  const m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  return m ? `${m[2]}-${m[3]} ${m[4]}:${m[5]}` : iso;
}

export function FigureCard({
  fig,
  compact = false,
  onToast,
}: {
  fig: FigureItem;
  compact?: boolean;
  onToast?: (m: string) => void;
}) {
  const [openCopies, setOpenCopies] = useState(false);
  const hasPng = Boolean(fig.formats.png);
  const ref = fig.refs[0];
  const p = fig.provenance;
  const warnRest = fig.concerns.filter((c) => c.level === "warn" && c.code !== "no-provenance");

  return (
    <article className={`fx-card ${compact ? "is-compact" : ""}`}>
      <div className="fx-thumb">
        {hasPng ? (
          <img src={figurePreviewUrl(fig.fig_id)} alt={ref?.caption || fig.base} loading="lazy" />
        ) : (
          <div className="fx-thumb-none">只有矢量 pdf，没有 png 预览</div>
        )}
        {fig.referenced && <span className="fx-num">图 {ref?.num}</span>}
      </div>

      <div className="fx-body">
        <div className="fx-head">
          <code className="fx-id" title="内容寻址 id：同一份图在任何目录下都是这个 id">
            {fig.fig_id}
          </code>
          {!fig.referenced && <span className="pw-badge b-mut">未引用</span>}
          {fig.dirCount > 1 && (
            <span className="pw-badge b-mut" title="同一份图在多个目录各存一份">
              {fig.dirCount} 处
            </span>
          )}
        </div>

        <div className="fx-title" title={ref?.caption || fig.base}>
          {ref?.caption || fig.base}
        </div>

        <div className="fx-meta">
          {ref ? (
            <span>
              §{ref.sectionNum || "—"}　{ref.sectionTitle}　L{ref.line}
            </span>
          ) : (
            <span>正文未引用</span>
          )}
          <span className="fx-dot">·</span>
          <span>{fig.masterFormat.toUpperCase()} {kb(fig.bytes)}</span>
          {ref?.texLabel && (
            <>
              <span className="fx-dot">·</span>
              <span className="pw-mono">{ref.texLabel}</span>
            </>
          )}
        </div>

        {/* 出处：有就摊开，没有就明说没有 */}
        {p ? (
          <div className="fx-prov">
            <div className="fx-prov-h">
              <span className="fx-ok">出处已记录</span>
              <span className="pw-mono">{p.tool}()</span>
              <span className="fx-sub">{shortTime(p.created_at)}</span>
            </div>
            <div className="fx-prov-rows">
              {p.draw?.series?.length > 0 && (
                /* 只报「哪几类元素、各几个」：patch 的 min–max 是矩形几何（x/y/w/h）而不是
                   数据本身，摆出来会被当成数值范围读错。真正的数据指纹在下一行。 */
                <div>
                  画了 {p.draw.series.length} 组元素：
                  {p.draw.series.slice(0, 5).map((s, i) => (
                    <span key={i} className="fx-serie">
                      {kindLabel(s.kind)}×{s.n ?? "?"}
                    </span>
                  ))}
                </div>
              )}
              {p.args?.values?.sha256 && (
                <div>
                  数据指纹 <code>{p.args.values.sha256}</code>
                  {p.args.values.shape ? `　shape ${p.args.values.shape.join("×")}` : ""}
                </div>
              )}
              {p.args?.title?.value != null && <div>标题「{String(p.args.title.value)}」</div>}
              <div className="fx-prov-foot">
                重绘校验 <code>{p.draw?.digest || "—"}</code>
                {p.gewu?.git && <>　gewu {p.gewu.git}</>}
                {p.errors?.length ? <span className="fx-warn">　指纹有 {p.errors.length} 处读取失败</span> : null}
              </div>
            </div>
          </div>
        ) : (
          <div className="fx-noprov">
            无出处记录：这张图旁边没有 <code>.meta.json</code>，不知道是哪个工具、用哪份数据画的。
            {fig.provenancePath === "" && "（当前 sci_plot 才开始写出处，老图补不回来）"}
          </div>
        )}

        {/* 副本：合并了但要能翻出来 */}
        <div className="fx-copies">
          <button className="fx-copies-btn" onClick={() => setOpenCopies((v) => !v)}>
            {openCopies ? "▾" : "▸"} {fig.copyCount} 个文件在 {fig.dirCount} 个目录
          </button>
          {openCopies && (
            <ul className="fx-copies-list">
              {fig.locations.map((l) => (
                <li key={l.dir}>
                  <code>{l.dir}/</code>
                  <span className="fx-sub">{l.formats.join(" + ")}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="fx-actions">
          {hasPng && (
            <a
              className="pw-btn pw-btn--sm"
              href={figurePreviewUrl(fig.fig_id)}
              target="_blank"
              rel="noreferrer"
            >
              原图
            </a>
          )}
          {fig.formats.pdf && (
            <a
              className="pw-btn pw-btn--sm"
              href={figurePdfUrl(fig.fig_id)}
              target="_blank"
              rel="noreferrer"
              title="矢量版，投稿用"
            >
              矢量 PDF
            </a>
          )}
          <button
            className="pw-btn pw-btn--sm"
            onClick={() => {
              navigator.clipboard?.writeText(fig.fig_id);
              onToast?.("已复制图纸 id");
            }}
            title="复制 id，在对话里可以直接指这张图"
          >
            复制 id
          </button>
        </div>

        {/* no-provenance 已经在上面单独占一块，别在这里再说一遍 */}
        {warnRest.length > 0 && !compact && (
          <ul className="fx-concerns">
            {warnRest.map((c) => (
              <li key={c.code}>{c.text}</li>
            ))}
          </ul>
        )}
      </div>
    </article>
  );
}
