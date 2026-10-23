// 右栏：工具 / 数据面板（PC 全量常驻）
// 数据来自 /api/case —— 由 scripts/export_case_bundle.py 从本机真实课题导出，
// 仓库内不含任何实验数据副本；取不到时降级为占位提示，绝不用假数据顶替。
import { useEffect, useState } from "react";
import { getCase } from "../api/client";
import type { CaseBundle } from "../types";
import { SpectrumChart } from "./SpectrumChart";
import { FoldBars } from "./FoldBars";
import { PredScatter } from "./PredScatter";

const fmt = (v: number | null | undefined, d = 2) =>
  v === null || v === undefined ? "—" : v.toFixed(d);

function MetricCard({
  label,
  value,
  sub,
  tone = "brand",
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "brand" | "muted";
}) {
  return (
    <div className={`case-card case-card--${tone}`}>
      <div className="case-card__label">{label}</div>
      <div className="case-card__value">{value}</div>
      {sub && <div className="case-card__sub">{sub}</div>}
    </div>
  );
}

function CaseBody({ data }: { data: CaseBundle }) {
  const m = data.metrics;
  const hyb = m?.hybrid.summary;
  const pls = m?.plsr_baseline.summary;

  return (
    <>
      <div className="right__block">
        <h4>光谱查看器</h4>
        {data.spectrum ? (
          <SpectrumChart spec={data.spectrum} />
        ) : (
          <div className="right__placeholder">本机未生成光谱预览（缺少原始 CSV）。</div>
        )}
      </div>

      <div className="right__block">
        <h4>5 折交叉验证指标</h4>
        {m && hyb && pls ? (
          <>
            <div className="case-cards">
              <MetricCard
                label="RMSE"
                value={fmt(hyb.rmse.mean)}
                sub={`± ${fmt(hyb.rmse.std)} (基线 ${fmt(pls.rmse.mean)})`}
              />
              <MetricCard
                label="R²"
                value={fmt(hyb.r2.mean, 4)}
                sub={`± ${fmt(hyb.r2.std, 4)} (基线 ${fmt(pls.r2.mean, 4)})`}
              />
              <MetricCard
                label="MAE"
                value={fmt(hyb.mae.mean)}
                sub={`± ${fmt(hyb.mae.std)} (基线 ${fmt(pls.mae.mean)})`}
              />
              <MetricCard
                label="相对基线"
                value={`−${fmt(m.improvement_pct, 1)}%`}
                sub="合并 RMSE 降幅"
                tone="muted"
              />
            </div>
            <FoldBars hybrid={m.hybrid.per_fold} baseline={m.plsr_baseline.per_fold} />
            <PredScatter yTrue={m.scatter.y_true} yPred={m.scatter.hybrid} unit={m.scatter.unit} />
            <div className="case-meta">{m.convention}</div>
          </>
        ) : (
          <div className="right__placeholder">暂无指标数据。</div>
        )}
      </div>

      <div className="right__block">
        <h4>文献与产出物</h4>
        {data.papers?.length ? (
          <ul className="case-list">
            {data.papers.map((p) => (
              <li key={p.doi}>
                <div className="case-list__title">{p.title}</div>
                <div className="case-meta">
                  {p.venue} {p.year} · <code>{p.doi}</code>
                  <span className={`case-badge case-badge--${p.status}`}>{p.status}</span>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <div className="right__placeholder">暂无已核验文献。</div>
        )}
        {data.artifacts?.length ? (
          <div className="case-artifacts">
            <div className="case-meta">阶段产出物 {data.artifacts.length} 项</div>
            <ul className="case-list case-list--tight">
              {data.artifacts.slice(0, 12).map((a) => (
                <li key={a.rel}>
                  <span className="case-tag">{a.kind}</span> {a.name}
                  <span className="case-meta"> {a.size_kb} KB</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </>
  );
}

export function RightPanel({ variant = "desktop" }: { variant?: "desktop" | "mobile" }) {
  const [data, setData] = useState<CaseBundle | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getCase()
      .then((d) => alive && setData(d))
      .catch((e) => alive && setErr(String(e)));
    return () => {
      alive = false;
    };
  }, []);

  if (variant === "mobile") {
    return (
      <div className="settings" style={{ padding: "var(--space-4)" }}>
        {data?.available ? (
          <CaseBody data={data} />
        ) : (
          <div className="right__empty-note">
            {data === null
              ? err || "加载中…"
              : `未接入真实案例：${data.reason || ""}${data.hint ? ` 生成：${data.hint}` : ""}`}
          </div>
        )}
      </div>
    );
  }

  return (
    <aside className="right" aria-label="工具与数据面板">
      <div className="right__title">
        工具 / 数据
        {data?.available && data.generated_at ? (
          <span className="case-stamp">{data.generated_at}</span>
        ) : null}
      </div>
      {data === null ? (
        <>
          <div className="right__block">
            <h4>光谱查看器</h4>
            <div className="right__placeholder">加载中…</div>
          </div>
          <div className="right__block">
            <h4>5 折交叉验证指标</h4>
            <div className="right__placeholder">加载中…</div>
          </div>
          <div className="right__block">
            <h4>文献与产出物</h4>
            <div className="right__placeholder">加载中…</div>
          </div>
        </>
      ) : data.available ? (
        <CaseBody data={data} />
      ) : (
        <>
          <div className="right__block">
            <h4>光谱查看器</h4>
            <div className="right__placeholder">
              接入 LIBS 光谱后，此处常驻折线（波长 × 强度）。
            </div>
          </div>
          <div className="right__block">
            <h4>5 折交叉验证指标</h4>
            <div className="right__placeholder">
              {data.reason || "未接入真实案例。"}
              {data.hint ? ` 生成：${data.hint}` : ""}
            </div>
          </div>
          <div className="right__block">
            <h4>文献与产出物</h4>
            <div className="right__placeholder">论文检索结果与阶段产出物列表。</div>
          </div>
        </>
      )}
    </aside>
  );
}
