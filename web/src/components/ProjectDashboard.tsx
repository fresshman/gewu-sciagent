// 项目仪表盘：显示七阶段进度、关键指标、产出物
import { useEffect, useState } from "react";

interface StageStatus {
  status: "pending" | "in_progress" | "completed" | "partial";
  started_at: string | null;
  completed_at: string | null;
  note?: string;
}

interface ProjectDetails {
  project_name: string;
  display_name: string;
  domain: string;
  research_question: string;
  hypothesis: string;
  stages: Record<string, StageStatus>;
  metrics: Record<string, any>;
  outputs: Record<string, string | null>;
}

const STAGE_LABELS: Record<string, { name: string; icon: string }> = {
  "1-direction": { name: "定方向", icon: "🎯" },
  "2-literature": { name: "读论文", icon: "📚" },
  "3-reproduction": { name: "复现", icon: "🔬" },
  "4-improvement": { name: "改进", icon: "⚡" },
  "5-paper": { name: "写论文", icon: "📝" },
  "6-submission": { name: "投稿", icon: "📮" },
  "7-distillation": { name: "沉淀", icon: "💎" },
};

const STATUS_COLORS: Record<string, string> = {
  pending: "#888780",
  in_progress: "#f59e0b",
  completed: "#10b981",
  partial: "#3b82f6",
};

const STATUS_LABELS: Record<string, string> = {
  pending: "待开始",
  in_progress: "进行中",
  completed: "已完成",
  partial: "部分完成",
};

export function ProjectDashboard({ project }: { project: ProjectDetails | null }) {
  if (!project) {
    return (
      <div className="project-dashboard project-dashboard--empty">
        <div className="project-dashboard__placeholder">
          未选择项目或项目数据加载中...
        </div>
      </div>
    );
  }

  const stages = Object.entries(project.stages || {});
  const completedCount = stages.filter(([, s]) => s.status === "completed").length;
  const totalCount = stages.length;
  const progress = totalCount > 0 ? (completedCount / totalCount) * 100 : 0;

  return (
    <div className="project-dashboard">
      {/* 项目概览 */}
      <div className="project-dashboard__header">
        <h3 className="project-dashboard__title">{project.display_name}</h3>
        <div className="project-dashboard__meta">
          <span className="project-dashboard__domain">{project.domain}</span>
          <span className="project-dashboard__progress">
            {completedCount}/{totalCount} 阶段完成
          </span>
        </div>
      </div>

      {/* 研究问题 */}
      {project.research_question && (
        <div className="project-dashboard__section">
          <h4 className="project-dashboard__section-title">研究问题</h4>
          <p className="project-dashboard__question">{project.research_question}</p>
        </div>
      )}

      {/* 七阶段进度 */}
      <div className="project-dashboard__section">
        <h4 className="project-dashboard__section-title">七阶段进度</h4>
        <div className="project-dashboard__stages">
          {stages.map(([stageKey, stage]) => {
            const label = STAGE_LABELS[stageKey] || { name: stageKey, icon: "📋" };
            const color = STATUS_COLORS[stage.status] || STATUS_COLORS.pending;
            return (
              <div key={stageKey} className="project-dashboard__stage">
                <div className="project-dashboard__stage-icon">{label.icon}</div>
                <div className="project-dashboard__stage-info">
                  <div className="project-dashboard__stage-name">{label.name}</div>
                  <div
                    className="project-dashboard__stage-status"
                    style={{ color }}
                  >
                    {STATUS_LABELS[stage.status] || stage.status}
                  </div>
                </div>
                {stage.note && (
                  <div className="project-dashboard__stage-note">{stage.note}</div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* 核心指标 */}
      {project.metrics && Object.keys(project.metrics).length > 0 && (
        <div className="project-dashboard__section">
          <h4 className="project-dashboard__section-title">核心指标</h4>
          <div className="project-dashboard__metrics">
            {Object.entries(project.metrics).map(([key, metric]) => (
              <div key={key} className="project-dashboard__metric">
                <div className="project-dashboard__metric-label">
                  {metric.name || key}
                </div>
                <div className="project-dashboard__metric-value">
                  {typeof metric.value === "number"
                    ? metric.value.toFixed(2)
                    : metric.value || "—"}
                  {metric.unit && (
                    <span className="project-dashboard__metric-unit">
                      {" "}{metric.unit}
                    </span>
                  )}
                </div>
                {metric.std && (
                  <div className="project-dashboard__metric-std">
                    ± {metric.std.toFixed(2)}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 关键产出 */}
      {project.outputs && Object.keys(project.outputs).length > 0 && (
        <div className="project-dashboard__section">
          <h4 className="project-dashboard__section-title">关键产出</h4>
          <div className="project-dashboard__outputs">
            {Object.entries(project.outputs).map(([key, path]) => (
              <div key={key} className="project-dashboard__output">
                <span className="project-dashboard__output-label">{key}:</span>
                <span className="project-dashboard__output-path">
                  {path || "未生成"}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 进度条 */}
      <div className="project-dashboard__progress-bar">
        <div
          className="project-dashboard__progress-fill"
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  );
}
