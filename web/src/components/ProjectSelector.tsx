// 项目选择器：显示项目列表、切换活跃项目
import { useEffect, useState, useRef } from "react";
import { getProjects, switchProject } from "../api/client";

interface Project {
  path: string;
  display_name: string;
  domain: string;
  status: string;
  created_at: string;
}

interface ProjectsResponse {
  active_project: string | null;
  projects: Record<string, Project>;
}

const DOMAIN_LABELS: Record<string, string> = {
  spectroscopy: "光谱学",
  nlp: "NLP",
  cv: "计算机视觉",
  ml: "机器学习",
  other: "其他",
};

const DOMAIN_COLORS: Record<string, string> = {
  spectroscopy: "#8b5cf6",
  nlp: "#3b82f6",
  cv: "#10b981",
  ml: "#f59e0b",
  other: "#6b7280",
};

export function ProjectSelector() {
  const [projects, setProjects] = useState<ProjectsResponse | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    loadProjects();
  }, []);

  // 点击外部关闭下拉菜单
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }

    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [isOpen]);

  async function loadProjects() {
    try {
      const data = await getProjects();
      setProjects(data);
    } catch (e) {
      console.error("Failed to load projects:", e);
    }
  }

  async function handleSwitch(projectName: string) {
    setLoading(true);
    try {
      await switchProject(projectName);
      await loadProjects();
      setIsOpen(false);
      // 刷新页面以加载新项目数据
      window.location.reload();
    } catch (e) {
      console.error("Failed to switch project:", e);
    } finally {
      setLoading(false);
    }
  }

  if (!projects || Object.keys(projects.projects).length === 0) {
    return (
      <div className="project-selector project-selector--empty">
        <span className="project-selector__label">无项目</span>
      </div>
    );
  }

  const activeProject = projects.active_project;
  const activeInfo = activeProject ? projects.projects[activeProject] : null;

  return (
    <div className="project-selector" ref={containerRef}>
      <button
        className="project-selector__trigger"
        onClick={() => setIsOpen(!isOpen)}
        disabled={loading}
      >
        {activeInfo && (
          <span
            className="project-selector__domain-dot"
            style={{ backgroundColor: DOMAIN_COLORS[activeInfo.domain] || DOMAIN_COLORS.other }}
          />
        )}
        <span className="project-selector__label">
          {activeInfo ? activeInfo.display_name : "选择项目"}
        </span>
        <span className="project-selector__arrow">{isOpen ? "▲" : "▼"}</span>
      </button>

      {isOpen && (
        <div className="project-selector__dropdown">
          <div className="project-selector__header">科研项目</div>
          {Object.entries(projects.projects).map(([name, info]) => (
            <button
              key={name}
              className={`project-selector__item ${name === activeProject ? "project-selector__item--active" : ""}`}
              onClick={() => handleSwitch(name)}
              disabled={loading || name === activeProject}
            >
              <span
                className="project-selector__domain-dot"
                style={{ backgroundColor: DOMAIN_COLORS[info.domain] || DOMAIN_COLORS.other }}
              />
              <span className="project-selector__item-name">{info.display_name}</span>
              <span className="project-selector__item-domain">
                {DOMAIN_LABELS[info.domain] || info.domain}
              </span>
              {name === activeProject && <span className="project-selector__item-check">✓</span>}
            </button>
          ))}
          <div className="project-selector__footer">
            <a href="#" onClick={(e) => { e.preventDefault(); window.open("/projects", "_blank"); }}>
              管理项目 →
            </a>
          </div>
        </div>
      )}
    </div>
  );
}
