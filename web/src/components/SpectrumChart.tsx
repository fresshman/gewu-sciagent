// 光谱预览：零依赖内联 SVG 折线（波长 × 强度）
// 说明：真实 LIBS 单条击打光谱，等间隔抽样后绘制；不引入 uPlot 等外部图表库。
import type { SpectrumPreview } from "../types";

const W = 320;
const H = 104;
const PAD_L = 4;
const PAD_R = 4;
const PAD_T = 8;
const PAD_B = 16;

export function SpectrumChart({ spec }: { spec: SpectrumPreview }) {
  const { wavelength, intensity } = spec;
  if (!wavelength.length || !intensity.length) return null;

  const wlMin = wavelength[0];
  const wlMax = wavelength[wavelength.length - 1];
  const yMin = Math.min(...intensity);
  const yMax = Math.max(...intensity);
  const span = yMax - yMin || 1;

  const plotW = W - PAD_L - PAD_R;
  const plotH = H - PAD_T - PAD_B;
  const pts = wavelength.map((wl, i) => {
    const x = PAD_L + ((wl - wlMin) / (wlMax - wlMin || 1)) * plotW;
    const y = PAD_T + plotH - ((intensity[i] - yMin) / span) * plotH;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  // 标出强度最高的点（通常是 C 247.8nm 附近的强峰或基体线）
  let peakIdx = 0;
  for (let i = 1; i < intensity.length; i++) {
    if (intensity[i] > intensity[peakIdx]) peakIdx = i;
  }
  const peakX = PAD_L + ((wavelength[peakIdx] - wlMin) / (wlMax - wlMin || 1)) * plotW;
  const peakY = PAD_T + plotH - ((intensity[peakIdx] - yMin) / span) * plotH;

  return (
    <div className="case-spectrum">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="LIBS 光谱预览" preserveAspectRatio="none">
        <line
          x1={PAD_L}
          y1={H - PAD_B}
          x2={W - PAD_R}
          y2={H - PAD_B}
          stroke="var(--border)"
          strokeWidth="1"
        />
        <polyline
          points={pts.join(" ")}
          fill="none"
          stroke="var(--brand)"
          strokeWidth="1.2"
          strokeLinejoin="round"
        />
        <circle cx={peakX} cy={peakY} r="2.4" fill="var(--accent-violet)" />
        <text x={peakX} y={Math.max(10, peakY - 4)} className="case-svg-label" textAnchor="middle">
          {wavelength[peakIdx].toFixed(1)} nm
        </text>
        <text x={PAD_L} y={H - 4} className="case-svg-axis">
          {wlMin.toFixed(0)} nm
        </text>
        <text x={W - PAD_R} y={H - 4} className="case-svg-axis" textAnchor="end">
          {wlMax.toFixed(0)} nm
        </text>
      </svg>
      <div className="case-meta">
        {spec.bag_id} · 第 1/{spec.n_shots} 次击打 · 原始 {spec.n_raw} 点（预览 {spec.n_points} 点）
      </div>
    </div>
  );
}
