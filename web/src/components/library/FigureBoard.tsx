import { useMemo, useState } from "react";
import type { FigureIndexResponse } from "../../types";
import { FigureCard } from "./FigureCard";

type Filter = "all" | "ref" | "orphan" | "noprov";

// 图纸页：把散在各目录、各格式的图片文件，按内容合并成「一张图 = 一张卡片」。
//
// 页头那行数字是这一页存在的理由：16 个文件 → 3 张图。不合并的话，
// 用户看到的行数比图多 5 倍，写论文时根本不知道「图 2」对应哪个文件。
export function FigureBoard({
  data,
  onToast,
}: {
  data: FigureIndexResponse | null;
  onToast: (m: string) => void;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const figs = data?.figures || [];
  const s = data?.summary;

  const list = useMemo(() => {
    if (filter === "ref") return figs.filter((f) => f.referenced);
    if (filter === "orphan") return figs.filter((f) => !f.referenced);
    if (filter === "noprov") return figs.filter((f) => !f.provenance);
    return figs;
  }, [figs, filter]);

  if (!data) {
    return <div className="pw-view"><div className="pw-empty">正在扫描出图目录…</div></div>;
  }
  if (!data.available) {
    return (
      <div className="pw-view">
        <div className="pw-empty">
          <p>{data.reason || "没有可扫描的图纸"}</p>
          {data.hint && <p><code>{data.hint}</code></p>}
        </div>
      </div>
    );
  }

  return (
    <div className="pw-view pw-view--figures">
      <div className="fx-bar">
        <div className="fx-sum">
          <b>{s?.files ?? 0}</b> 个图片文件
          <span className="fx-arrow">→</span>
          <b>{s?.total ?? 0}</b> 张图
          <span className="fx-sub">（按内容 sha256 合并）</span>
        </div>
        <div className="fx-chips" role="tablist" aria-label="图纸筛选">
          <button className="fx-chip" aria-selected={filter === "all"} onClick={() => setFilter("all")}>
            全部 {s?.total ?? 0}
          </button>
          <button className="fx-chip" aria-selected={filter === "ref"} onClick={() => setFilter("ref")}>
            正文引用 {s?.referenced ?? 0}
          </button>
          <button className="fx-chip" aria-selected={filter === "orphan"} onClick={() => setFilter("orphan")}>
            未引用 {s?.unreferenced ?? 0}
          </button>
          <button className="fx-chip" aria-selected={filter === "noprov"} onClick={() => setFilter("noprov")}>
            无出处 {s ? s.total - s.withProvenance : 0}
          </button>
        </div>
      </div>

      {s && s.withProvenance === 0 && (
        <div className="pw-bar-note pw-bar-note--warn">
          这 {s.total} 张图都没有出处记录：出图工具是从本次改动才开始写 <code>.meta.json</code> 的，
          之前画的图只有文件名和时间戳。下面每张卡片的「无出处记录」是真的缺，不是没读到。
        </div>
      )}

      {list.length === 0 ? (
        <div className="pw-empty">这个筛选下没有图</div>
      ) : (
        <div className="fx-grid">
          {list.map((f) => (
            <FigureCard key={f.fig_id} fig={f} onToast={onToast} />
          ))}
        </div>
      )}

      <div className="fx-foot">
        扫描目录：
        {(data.dirs || []).map((d) => (
          <span key={d.dir} className="fx-dir">
            <code>{d.dir}</code>
            <span className={d.exists ? "" : "fx-warn"}>{d.exists ? `${d.files} 个文件` : "不存在"}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
