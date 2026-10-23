// 逐折指标对比：混合模型 vs PLSR 基线（零依赖内联 SVG 分组柱图）
import type { FoldMetric } from "../types";

const W = 320;
const H = 92;
const PAD_B = 18;
const PAD_T = 6;

export function FoldBars({
  hybrid,
  baseline,
  metric = "rmse",
  unit = "kcal/kg",
}: {
  hybrid: FoldMetric[];
  baseline: FoldMetric[];
  metric?: "rmse" | "mae";
  unit?: string;
}) {
  if (!hybrid.length || !baseline.length) return null;
  const vals = [...hybrid, ...baseline].map((m) => m[metric] ?? 0);
  const vMax = Math.max(...vals) * 1.08 || 1;
  const n = hybrid.length;
  const groupW = (W - 8) / n;
  const barW = Math.min(11, groupW / 2.6);
  const plotH = H - PAD_T - PAD_B;

  return (
    <div className="case-folds">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="逐折 RMSE 对比">
        <line x1={4} y1={H - PAD_B} x2={W - 4} y2={H - PAD_B} stroke="var(--border)" strokeWidth="1" />
        {hybrid.map((m, i) => {
          const gx = 4 + i * groupW;
          const hv = m[metric] ?? 0;
          const pv = baseline[i]?.[metric] ?? 0;
          const hh = (hv / vMax) * plotH;
          const ph = (pv / vMax) * plotH;
          const cx = gx + groupW / 2;
          return (
            <g key={i}>
              <rect
                x={cx - barW - 1}
                y={H - PAD_B - ph}
                width={barW}
                height={ph}
                fill="var(--text-tertiary)"
                rx="1.5"
              />
              <rect
                x={cx + 1}
                y={H - PAD_B - hh}
                width={barW}
                height={hh}
                fill="var(--brand)"
                rx="1.5"
              />
              <text x={cx} y={H - 5} className="case-svg-axis" textAnchor="middle">
                f{i}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="case-legend">
        <span>
          <i className="dot" style={{ background: "var(--brand)" }} />
          混合模型
        </span>
        <span>
          <i className="dot" style={{ background: "var(--text-tertiary)" }} />
          PLSR 基线
        </span>
        <span className="case-legend__unit">{unit}</span>
      </div>
    </div>
  );
}
