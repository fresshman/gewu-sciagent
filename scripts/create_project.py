#!/usr/bin/env python3
"""创建格物科研项目（以项目为中心的科研生产力系统）。

用法：
  python scripts/create_project.py <project-name> [options]

示例：
  python scripts/create_project.py llm-finetune \
    --domain nlp \
    --display-name "LLM 微调实验" \
    --research-question "如何利用 LoRA 高效微调书生大模型？" \
    --gpu-required

项目结构：
  ~/.gewu/projects/<project-name>/
  ├── project.json          # 项目元数据
  ├── config.json           # 项目配置（环境、服务器、数据集、七阶段状态）
  ├── README.md             # 项目说明
  ├── stages/               # 七阶段工作区
  │   ├── 1-direction/      # 定方向
  │   ├── 2-literature/     # 读论文
  │   ├── 3-reproduction/   # 复现（可多次）
  │   ├── 4-improvement/    # 改进
  │   ├── 5-paper/          # 写论文
  │   ├── 6-submission/     # 投稿
  │   └── 7-distillation/   # 沉淀
  ├── data/                 # 数据集
  ├── models/               # 模型权重
  └── logs/                 # 运行日志
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

GEWU_ROOT = Path.home() / ".gewu"
PROJECTS_DIR = GEWU_ROOT / "projects"
CONFIG_FILE = GEWU_ROOT / "config.json"

DOMAINS = {
    "spectroscopy": "光谱学（LIBS/Raman/IR 等）",
    "nlp": "自然语言处理（LLM 微调/RAG/文本分类等）",
    "cv": "计算机视觉（目标检测/图像分割/分类等）",
    "ml": "通用机器学习（表格数据/回归/分类等）",
    "other": "其他领域",
}

STAGES = [
    ("1-direction", "定方向"),
    ("2-literature", "读论文"),
    ("3-reproduction", "复现"),
    ("4-improvement", "改进"),
    ("5-paper", "写论文"),
    ("6-submission", "投稿"),
    ("7-distillation", "沉淀"),
]


def load_config() -> dict:
    """加载全局配置。"""
    if not CONFIG_FILE.exists():
        return {
            "version": "2.0.0",
            "gewu_root": str(GEWU_ROOT),
            "projects_dir": str(PROJECTS_DIR),
            "global_dir": str(GEWU_ROOT / "global"),
            "projects": {},
            "defaults": {
                "python_version": "3.13.12",
                "shared_venv": "C:/Users/SHJ/.workbuddy/binaries/python/envs/gewu",
            },
            "features": {
                "multi_project_isolation": True,
                "project_templates": False,
                "computer_use": False,
                "auto_dependency_install": False,
            },
        }
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_config(config: dict) -> None:
    """保存全局配置。"""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def create_project_structure(project_dir: Path) -> None:
    """创建项目目录结构（七阶段隔离）。"""
    dirs = [
        project_dir / "data",
        project_dir / "models",
        project_dir / "logs",
    ]
    # 七阶段目录
    for stage_dir, _ in STAGES:
        stage_path = project_dir / "stages" / stage_dir
        dirs.append(stage_path)
        # 子目录
        if stage_dir == "2-literature":
            dirs.append(stage_path / "papers")
            dirs.append(stage_path / "notes")
        elif stage_dir == "3-reproduction":
            pass  # 复现目录按需创建（repro-001, repro-002, ...）
        elif stage_dir == "4-improvement":
            dirs.append(stage_path / "experiments")
        elif stage_dir == "5-paper":
            dirs.append(stage_path / "draft")
            dirs.append(stage_path / "figures")
            dirs.append(stage_path / "references")
        elif stage_dir == "6-submission":
            dirs.append(stage_path / "versions")
        elif stage_dir == "7-distillation":
            dirs.append(stage_path / "skills")
    
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    print(f"  [OK] 创建七阶段目录结构")


def create_project_json(
    project_dir: Path,
    name: str,
    display_name: str,
    domain: str,
    description: str,
    research_question: str,
) -> dict:
    """创建 project.json（简化版，指向 config.json）。"""
    now = datetime.now().astimezone().isoformat()
    project_json = {
        "name": name,
        "display_name": display_name,
        "created_at": now,
        "domain": domain,
        "description": description,
        "research_question": research_question,
        "status": "active",
        "config_file": str(project_dir / "config.json"),
        "readme_file": str(project_dir / "README.md"),
    }
    project_file = project_dir / "project.json"
    with open(project_file, "w", encoding="utf-8") as f:
        json.dump(project_json, f, ensure_ascii=False, indent=2)
    print(f"  [OK] 创建 project.json")
    return project_json


def create_config_json(
    project_dir: Path,
    name: str,
    display_name: str,
    domain: str,
    description: str,
    research_question: str,
    gpu_required: bool,
) -> dict:
    """创建 config.json（项目配置，包含七阶段状态）。"""
    now = datetime.now().astimezone().isoformat()
    
    # 初始化七阶段状态
    stages = {}
    for stage_dir, stage_name in STAGES:
        stages[stage_dir] = {
            "status": "pending",
            "started_at": None,
            "completed_at": None,
        }
    
    config_json = {
        "project_name": name,
        "display_name": display_name,
        "created_at": now,
        "domain": domain,
        "description": description,
        "research_question": research_question,
        "hypothesis": "",
        
        "environment": {
            "python_version": "3.13.14",
            "venv_path": "C:/Users/SHJ/.workbuddy/binaries/python/envs/gewu",
            "key_dependencies": {},
            "cuda_required": gpu_required,
            "gpu_required": gpu_required,
        },
        
        "servers": [
            {
                "name": "local",
                "type": "local",
                "description": "本地开发环境",
                "host": "localhost",
                "status": "active",
            }
        ],
        
        "datasets": [],
        "papers": [],
        "stages": stages,
        
        "outputs": {
            "paper_draft": None,
            "paper_pdf": None,
            "figures": None,
            "journal_report": None,
        },
        
        "metrics": {},
        "tags": [domain],
        "status": "active",
    }
    
    config_file = project_dir / "config.json"
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config_json, f, ensure_ascii=False, indent=2)
    print(f"  [OK] 创建 config.json（含七阶段状态）")
    return config_json


def create_readme(
    project_dir: Path,
    display_name: str,
    research_question: str,
    domain: str,
) -> None:
    """创建 README.md。"""
    readme = f"""# {display_name}

> {research_question}

## 研究问题

{research_question}

## 假设

（待填写）

## 项目状态

| 阶段 | 状态 | 说明 |
|---|---|---|
| ① 定方向 | ⏳ 待开始 | |
| ② 读论文 | ⏳ 待开始 | |
| ③ 复现 | ⏳ 待开始 | |
| ④ 改进 | ⏳ 待开始 | |
| ⑤ 写论文 | ⏳ 待开始 | |
| ⑥ 投稿 | ⏳ 待开始 | |
| ⑦ 沉淀 | ⏳ 待开始 | |

## 关键产出

（待生成）

## 核心指标

（待测量）

## 技术栈

- **领域**：{DOMAINS.get(domain, domain)}
- **环境**：Python 3.13 + PyTorch（待配置）

## 快速开始

```bash
# 进入项目目录
cd ~/.gewu/projects/{project_dir.name}

# 查看七阶段状态
cat config.json | jq .stages

# 开始定方向（阶段 1）
# 使用格物 Web 界面或 OpenClaw CLI
```

## 项目日志

- **{datetime.now().strftime('%Y-%m-%d')}**：项目创建
"""
    
    readme_file = project_dir / "README.md"
    with open(readme_file, "w", encoding="utf-8") as f:
        f.write(readme)
    print(f"  [OK] 创建 README.md")


def update_config(config: dict, name: str, project_dir: Path, display_name: str, domain: str) -> None:
    """更新全局配置。"""
    now = datetime.now().astimezone().isoformat()
    config["projects"][name] = {
        "path": str(project_dir),
        "display_name": display_name,
        "domain": domain,
        "status": "active",
        "created_at": now,
    }
    # 如果是第一个项目，设为活跃项目
    if len(config["projects"]) == 1:
        config["active_project"] = name
    save_config(config)
    print(f"  [OK] 更新全局配置（活跃项目: {config.get('active_project', name)}）")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="创建格物科研项目（以项目为中心的科研生产力系统）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("name", help="项目名称（英文，如 llm-finetune）")
    parser.add_argument(
        "--domain",
        choices=list(DOMAINS.keys()),
        default="other",
        help="项目领域（默认: other）",
    )
    parser.add_argument(
        "--display-name",
        help="项目显示名称（中文，如 'LLM 微调实验'）",
    )
    parser.add_argument(
        "--research-question",
        default="",
        help="研究问题（如 '如何利用 LoRA 高效微调书生大模型？'）",
    )
    parser.add_argument(
        "--description",
        default="",
        help="项目描述",
    )
    parser.add_argument(
        "--gpu-required",
        action="store_true",
        help="项目需要 GPU（默认 False）",
    )

    args = parser.parse_args()

    name = args.name
    domain = args.domain
    display_name = args.display_name or name
    description = args.description or f"{display_name}（{DOMAINS[domain]}）"
    research_question = args.research_question or f"（待填写研究问题）"

    project_dir = PROJECTS_DIR / name

    print(f"=" * 60)
    print(f"创建格物科研项目: {display_name}")
    print(f"=" * 60)
    print(f"  名称: {name}")
    print(f"  领域: {domain} ({DOMAINS[domain]})")
    print(f"  研究问题: {research_question}")
    print(f"  GPU 需求: {'是' if args.gpu_required else '否'}")
    print(f"  路径: {project_dir}")
    print()

    # 检查项目是否已存在
    if project_dir.exists():
        print(f"[ERROR] 项目已存在: {project_dir}")
        return 1

    # 创建目录结构
    print("[1/4] 创建七阶段目录结构...")
    create_project_structure(project_dir)
    print()

    # 创建 project.json
    print("[2/4] 创建项目元数据...")
    create_project_json(project_dir, name, display_name, domain, description, research_question)
    print()

    # 创建 config.json
    print("[3/4] 创建项目配置...")
    create_config_json(project_dir, name, display_name, domain, description, research_question, args.gpu_required)
    create_readme(project_dir, display_name, research_question, domain)
    print()

    # 更新全局配置
    print("[4/4] 更新全局配置...")
    config = load_config()
    update_config(config, name, project_dir, display_name, domain)
    print()

    print("=" * 60)
    print(f"[PASS] 项目创建成功: {display_name}")
    print("=" * 60)
    print()
    print("下一步:")
    print(f"  1. 进入项目目录: cd {project_dir}")
    print(f"  2. 编辑 README.md: 填写研究问题、假设、目标")
    print(f"  3. 开始阶段 1（定方向）: 使用格物 Web 界面或 OpenClaw CLI")
    print()
    print("提示:")
    print(f"  - 七阶段工作区: {project_dir / 'stages'}")
    print(f"  - 项目配置: {project_dir / 'config.json'}")
    print(f"  - 切换活跃项目: 编辑 {CONFIG_FILE} 的 active_project 字段")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
