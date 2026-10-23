// 预测值 vs 真实值散点（零依赖内联 SVG）：含 y=x 参考线
export function PredScatter({
  yTrue,
  yPred,
  unit = "kcal/kg",
}: {
  yTrue: number[];
  yPred: number[];
  unit?: string;
}) {
  const n = Math.min(yTrue.length, yPred.length);
  if (n === 0) return null;
  const W = 320;
  const H = 128;
  const PAD = 14;

  const lo = Math.min(...yTrue, ...yPred);
  const hi = Math.max(...yTrue, ...yPred);
  const pad = (hi - lo) * 0.05 || 1;
  const loV = lo - pad;
  const hiV = hi + pad;
  const sx = (v: number) => PAD + ((v - loV) / (hiV - loV)) * (W - PAD * 2);
  const sy = (v: number) => H - PAD - ((v - loV) / (hiV - loV)) * (H - PAD * 2);

  return (
    <div className="case-scatter">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="预测值 vs 真实值">
        <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="var(--border)" strokeWidth="1" />
        <line x1={PAD} y1={PAD} x2={PAD} y2={H - PAD} stroke="var(--border)" strokeWidth="1" />
        {/* y = x 参考线 */}
        <line
          x1={sx(loV)}
          y1={sy(loV)}
          x2={sx(hiV)}
          y2={sy(hiV)}
          stroke="var(--danger)"
          strokeWidth="1"
          strokeDasharray="3 3"
          opacity="0.55"
        />
        {Array.from({ length: n }, (_, i) => (
          <circle
            key={i}
            cx={sx(yTrue[i])}
            cy={sy(yPred[i])}
            r="2.1"
            fill="var(--accent-teal)"
            opacity="0.75"
          />
        ))}
        <text x={W - PAD} y={H - 3} className="case-svg-axis" textAnchor="end">
          真实值 ({unit})
        </text>
        <text x={2} y={PAD - 3} className="case-svg-axis">
          预测值
        </text>
      </svg>
      <div className="case-meta">5 折合并 n={n} · 虚线为 y=x</div>
    </div>
  );
}
