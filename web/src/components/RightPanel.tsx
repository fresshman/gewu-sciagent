// 右栏：项目仪表盘 + 案例数据面板（PC 全量常驻）
// 项目仪表盘来自 /api/projects/active —— 显示七阶段进度、指标、产出物
// 案例数据来自 /api/case —— 由 scripts/export_case_bundle.py 从本机真实课题导出，
// 仓库内不含任何实验数据副本；取不到时降级为占位提示，绝不用假数据顶替。
// 指标以 metrics_recomputed.json 为单一真源，且**同时标注两种口径**（逐折均值 / 合并 OOF），
// 避免 UI 与论文出现同一指标的两个不同数字。
import { useEffect, useState } from "react";
import { getCase, getActiveProject } from "../api/client";
import type { CaseBundle, CaseAblation, PairedTest } from "../types";
import { SpectrumChart } from "./SpectrumChart";
import { FoldBars } from "./FoldBars";
import { PredScatter } from "./PredScatter";
import { ProjectDashboard } from "./ProjectDashboard";

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

// 逐折配对检验：t 检验与 Wilcoxon 结论不一致时必须都摆出来，只报显著的那个是选择性报告
function PairedTestBlock({ t }: { t?: PairedTest }) {
  if (!t || !t.available) return null;
  const sig = t.p !== null && t.p < 0.05;
  return (
    <div className="case-stat">
      <div className="case-subhead">
        逐折配对检验 <span className="case-meta">n = {(t.df ?? 0) + 1} 折</span>
      </div>
      <div className="case-stat__row">
        <span>配对 t 检验</span>
        <code>
          t({t.df}) = {fmt(t.t, 4)}, p = {fmt(t.p, 4)}
        </code>
      </div>
      <div className="case-stat__row">
        <span>均值差 95% CI</span>
        <code>
          {t.ci95 ? `[${fmt(t.ci95[0])}, ${fmt(t.ci95[1])}]` : "—"} kcal/kg
        </code>
      </div>
      <div className="case-stat__row">
        <span>Wilcoxon 符号秩</span>
        <code>p = {fmt(t.wilcoxon_p, 4)}</code>
      </div>
      <div className={`case-note ${sig ? "case-note--warn" : ""}`}>
        {t.note ||
          "t 检验显著、Wilcoxon 受 n 限制不显著时，两者应同时报告。"}
      </div>
    </div>
  );
}

// 消融：组内比较才有意义，跨组（与最终配置）不可相减，caveat 常驻显示。
// 三组基准不同（347.55 / 347.55 / 215.75），故条形图必须**按组各自归一**，
// 否则跨组共用一条 vMax 会把「不同基准」画成「同一把尺子」。
function AblationBlock({ abl }: { abl?: CaseAblation | null }) {
  if (!abl || abl.status !== "available") return null;
  const groups: Array<{ title: string; items: CaseAblation["pooling"]; caveat: string }> = [
    { title: "池化策略对比", items: abl.pooling, caveat: abl.caveat },
    { title: "优化路径", items: abl.path, caveat: abl.caveat },
    { title: "组件级消融", items: abl.component ?? [], caveat: abl.component_caveat || abl.caveat },
  ].filter((s) => s.items.length > 0);
  if (!groups.length) return null;
  const total = groups.reduce((n, g) => n + g.items.length, 0);

  return (
    <div className="case-ablation">
      <div className="case-subhead">
        消融实验 <span className="case-meta">组内比较 · {total} 条</span>
      </div>
      {groups.map((g) => {
        const vMax = Math.max(...g.items.map((i) => i.rmse));
        return (
          <div key={g.title} className="case-ablation__group">
            <div className="case-meta">{g.title}</div>
            {g.items.map((it) => (
              <div className="case-ablation__row" key={it.id}>
                <span className="case-ablation__label" title={it.label}>
                  {it.label}
                </span>
                <code className="case-ablation__val">{fmt(it.rmse)}</code>
                <span className="case-ablation__bar">
                  <i style={{ width: `${Math.max(2, (it.rmse / vMax) * 100)}%` }} />
                </span>
              </div>
            ))}
            <div className="case-note case-note--warn">{g.caveat}</div>
          </div>
        );
      })}
    </div>
  );
}

// 来源标注：快照模式必须显眼，避免把「仓库内快照」误读成「本机实测」
function ModeNote({ data }: { data: CaseBundle }) {
  if (!data.mode_label) return null;
  const snap = data.mode === "repo_snapshot";
  return (
    <div className={`case-note ${snap ? "case-note--warn" : ""}`}>
      <span className={`case-badge case-badge--${snap ? "pending" : "verified"}`}>
        {snap ? "快照" : "本机"}
      </span>{" "}
      {data.mode_label}
    </div>
  );
}

function CaseBody({ data }: { data: CaseBundle }) {
  const m = data.metrics;
  const hyb = m?.hybrid.summary;
  const pls = m?.plsr_baseline.summary;
  const pooledPct = m?.improvement_pct_pooled;
  const refs = data.references_summary;

  return (
    <>
      <ModeNote data={data} />
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
                value={`−${fmt(m.improvement_pct, 2)}%`}
                sub={
                  pooledPct == null
                    ? "逐折均值口径"
                    : `逐折均值口径 · 合并 OOF ${fmt(pooledPct, 2)}%`
                }
                tone="muted"
              />
            </div>
            <FoldBars hybrid={m.hybrid.per_fold} baseline={m.plsr_baseline.per_fold} />
            {m.scatter?.y_true?.length ? (
              <PredScatter
                yTrue={m.scatter.y_true}
                yPred={m.scatter.hybrid}
                unit={m.scatter.unit}
              />
            ) : null}
            <PairedTestBlock t={m.paired_test} />
            <AblationBlock abl={data.ablation} />
            <div className="case-meta">{m.convention}</div>
            {data.provenance?.metrics ? (
              <div className="case-meta">
                真源：<code>{data.provenance.metrics}</code>
              </div>
            ) : null}
          </>
        ) : (
          <div className="right__placeholder">暂无指标数据。</div>
        )}
      </div>

      <div className="right__block">
        <h4>文献与产出物</h4>
        {refs ? (
          <div className="case-meta">
            论文引用 {refs.n_papers} 篇 · D1 核验{" "}
            <span className={`case-badge case-badge--${refs.verdict === "PASS" ? "verified" : "pending"}`}>
              {refs.verdict}
            </span>{" "}
            幻觉率 {fmt(refs.hallucination_rate, 1)}
            {refs.checked_at ? ` · ${refs.checked_at}` : ""}
          </div>
        ) : null}
        {data.papers?.length ? (
          <ul className="case-list">
            {data.papers.map((p) => (
              <li key={p.key || p.doi || p.title}>
                <div className="case-list__title">{p.title}</div>
                <div className="case-meta">
                  {[p.venue, p.year].filter(Boolean).join(" ")}
                  {p.doi ? (
                    <>
                      {" "}
                      · <code>{p.doi}</code>
                    </>
                  ) : p.arxiv ? (
                    <>
                      {" "}
                      · <code>arXiv:{p.arxiv}</code>
                    </>
                  ) : null}
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
            <div className="case-meta">
              阶段产出物 {data.artifacts.length} 项
              {(() => {
                const repo = data.artifacts.filter((a) => a.scope === "repo").length;
                const ext = data.artifacts.length - repo;
                return repo || ext ? `（仓库内 ${repo} · 外部课题 ${ext}）` : "";
              })()}
            </div>
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
  const [project, setProject] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getCase()
      .then((d) => alive && setData(d))
      .catch((e) => alive && setErr(String(e)));
    getActiveProject()
      .then((p) => alive && setProject(p))
      .catch(() => { /* 无活跃项目时静默 */ });
    return () => {
      alive = false;
    };
  }, []);

  if (variant === "mobile") {
    return (
      <div className="settings" style={{ padding: "var(--space-4)" }}>
        <ProjectDashboard project={project} />
        <div style={{ borderTop: "1px dashed var(--border)", margin: "var(--space-4) 0" }} />
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
    <aside className="right" aria-label="项目与数据面板">
      <div className="right__title">
        项目概览
      </div>
      <ProjectDashboard project={project} />
      <div className="right__title" style={{ borderTop: "1px dashed var(--border)", paddingTop: "var(--space-4)" }}>
        案例数据
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
