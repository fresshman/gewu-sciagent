// 右栏：工具 / 数据面板（PC 全量常驻）
// 注意：按用户要求，目前仅占位骨架，不接入任何光谱/案例内容。
// 待整体框架与测试案例就绪后再实现 SpectrumChart / MetricCard 等。
export function RightPanel({ variant = "desktop" }: { variant?: "desktop" | "mobile" }) {
  if (variant === "mobile") {
    return (
      <div className="settings" style={{ padding: "var(--space-4)" }}>
        <div className="right__empty-note">
          工具与数据面板（光谱查看器 / 5 折 CV 指标 / 文献产出物）将在接入测试案例后启用。
        </div>
      </div>
    );
  }
  return (
    <aside className="right" aria-label="工具与数据面板">
      <div className="right__title">工具 / 数据</div>
      <div className="right__block">
        <h4>光谱查看器</h4>
        <div className="right__placeholder">
          接入 LIBS 光谱后，此处常驻 uPlot 折线（波长 × 强度）。
        </div>
      </div>
      <div className="right__block">
        <h4>5 折交叉验证指标</h4>
        <div className="right__placeholder">RMSE · R² · MAE 等指标卡，接入 sci_compute 后展示。</div>
      </div>
      <div className="right__block">
        <h4>文献与产出物</h4>
        <div className="right__placeholder">论文检索结果与阶段产出物列表，接入 paper-search-mcp 后展示。</div>
      </div>
    </aside>
  );
}
