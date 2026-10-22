# 格物 (Gewu) — 通用学术科学智能体

> 基于 **书生大模型（Intern-S1 / InternVL）** + **OpenClaw 原生编排** 的 AI4S 科学智能体。
> **不自己写控制流编排器**——OpenClaw 原生提供多智能体编排 / Skills / 长周期记忆 / A2A / Computer Use；
> Python 只保留"科学工具层"（MCP Server），通过 MCP 被 OpenClaw 调用。
> 以「大颗粒原煤 LIBS 光谱热值预测」作为首个**参考实现（Reference Implementation）**，用于跑通闭环、产出可复现指标。

## 赛道
第三期 Production AI Skills 大赛 · 方向 1：AI4S 科学智能体

## 项目定位
- **通用学术智能体（科研全生命周期，而非论文翻译/管理工具）**：覆盖
  **定方向 → 读论文找 idea → 复现 → 改进/梳理 → 写论文 → 发表追踪 → 沉淀**，
  且「沉淀」把方法固化为可复用 OpenClaw Skill 与长周期记忆，系统越用越强（复利闭环）。
- **不局限于光谱**：LIBS 煤热值只是"参考实现"，用来证明深度与可复现性；换领域只需替换 `gewu/domain_packs/` 下的领域包。
- **与普通论文工具的区别**：不止于读/整理，而是贯穿复现→改进→写→发表→沉淀的科研生产流。

## 架构要点（原生 OpenClaw）
| 层 | 角色 | 落地 |
|---|---|---|
| 书生大模型 (Intern-S1/InternVL) | 大脑 | OpenAI 兼容 `base_url` 接入 OpenClaw model profile |
| OpenClaw | 执行框架 | 原生多智能体编排、Skills、Memory、A2A、Computer Use |
| 格物层 | 科研能力 | 7 阶段 Agent（openclaw.json 的 `agents.entries`，各用独立工作区 `AGENTS.md` 承载角色）+ Python MCP 工具 + 领域包 + Skills |

详细设计与落地路线图见 [`docs/architecture.md`](docs/architecture.md)。

## 目录结构
```
gewu-sciagent/
├── README.md                  # 本文件
├── requirements.txt           # Python MCP 工具层依赖
├── .gitignore
├── docs/
│   └── architecture.md         # 架构设计文档（原生 OpenClaw 方案 + 落地路线图）
├── data/                       # 数据集（大文件建议放网盘，仅留索引）
├── openclaw/                   # OpenClaw 项目（提交层的"应用"）
│   ├── openclaw.json           # 网关配置（书生模型/agents.entries/mcp.servers，已验证 config valid + Gateway 运行）
│   ├── skills/                 # 3 个 Skill 源（已复制进各 Agent 工作区 skills/）
│   └── workspace/
│       ├── MEMORY.md           # 共享长周期记忆（初稿）
│       └── agents/<role>/      # 7 个 Agent 各自工作区，各含 AGENTS.md + skills/ + MEMORY.md
└── gewu/                       # Python 工具/技能/领域源码（被 OpenClaw 经 MCP 调用）
    ├── mcp/                    # 5 个 stdio MCP Server（已注册到 mcp.servers，probe 通过）
    ├── skills/                 # OpenClaw Skills 源（SKILL.md）
    └── domain_packs/           # 可插拔领域包：coal_libs（LIBS/煤热值参考实现）
```

## 快速开始（已部署基线）
```bash
# 1) 安装 OpenClaw（MIT 开源，无需克隆源码）
#    注意：要求 Node ≥24.16/<25 或 ≥26.1；本机用独立 Node 26.9.0 全局安装
#    npm i -g openclaw@2026.10.5
# 2) 将 openclaw/openclaw.json 合并进 ~/.openclaw/openclaw.json，并设置环境变量 INTERN_API_KEY
# 3) 启动网关（常驻）：openclaw gateway run --force
# 4) 提出科研目标，例如：
#    "调研并复现大颗粒原煤 LIBS 光谱热值预测的 MIL 方法，给出 5 折交叉验证指标"
```

> **当前状态（2026-10-22 已验证）**：OpenClaw 安装并常驻运行；书生模型 provider、5 个 MCP 服务、
> 7 个 Agent（`agents.ownership="explicit"`，各用 `AGENTS.md` 承载角色）均已配置并通过 `config validate`。
> 已配通：书生 API key 已写入 `~/.openclaw/openclaw.json`（项目模板 `openclaw/openclaw.json` 保留 `${INTERN_API_KEY}` 占位以免密钥进 Git）；
> `openclaw models status --json --agent gewu-director` 与真实对话（`intern-s2`）均验证通过。
> 待补：OpenVINO MIL 模型权重 + 真实 LIBS 数据（跑实参考实现）。

## 评分映射
| 评分项 | 本项目的应对 |
|---|---|
| 实用性 40% | 通用内核 = 广价值；全生命周期（含复现/发表/沉淀）= 真科研痛点；煤热值 = 可复现证据 |
| 技术难度 30% | 书生模型 + OpenClaw 原生多智能体 + 通用 MCP 工具层 + 多模态 + 本地 OpenVINO + Agent Skills + 长周期记忆 + A2A |
| 完整性 30% | 7 阶段在参考实现上跑通，文档 + 视频齐全 |

## 提交材料约定
- 技术文档（PDF）：含 5 分钟介绍视频网盘链接 + 应用体验链接。
- 关键代码与模型：模型过大时以网盘链接写入 `model_links.txt`。
- 提交包命名：`单位简称-作品名称-队长姓名-队长手机号-日期.zip`。
