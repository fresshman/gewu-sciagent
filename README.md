# 格物 (Gewu) — 通用学术科学智能体

> 基于 **书生大模型（Intern-S2 系列）** + **OpenClaw 原生编排** 的科研全生命周期智能体。
> 覆盖 **定方向 → 读论文找 idea → 复现 → 改进 → 写论文 → 发表追踪 → 沉淀** 七个阶段，
> 并把沉淀下的方法固化为可复用 Skill 与长周期记忆，让系统越用越强。

---

## 项目定位

格物不是一个"论文阅读 / 翻译 / 管理"工具，而是一条**科研生产流**：

| 维度 | 说明 |
|---|---|
| **全生命周期** | 从选题到沉淀串联科研的每个环节，而非单点辅助 |
| **通用内核 + 可插拔领域包** | 「大颗粒原煤 LIBS 光谱热值预测」只是首个**参考实现**；换领域只需替换 `gewu/domain_packs/` 下的领域包 |
| **沉淀复利闭环** | 第 ⑦ 阶段把方法与踩坑固化为 OpenClaw Skill + 长周期记忆，系统随使用不断变强 |
| **可见的编排** | Web 界面能看见 Director 派发给谁、调用了哪个工具、当前处于哪一阶段 |
| **质量护栏** | 7-mode 失败自检、PRISMA 式文献筛选、引用与声明审计，主动抑制幻觉与自欺 |

---

## 架构

| 层 | 角色 | 落地 |
|---|---|---|
| 书生大模型（Intern-S2 / Intern-S1 / InternVL） | 大脑 | OpenAI 兼容接口接入 OpenClaw model provider |
| OpenClaw | 执行框架 | 原生多智能体编排、Skills、长周期记忆、A2A |
| 格物层 | 科研能力 | 7 个阶段 Agent + 5 个 Python MCP 工具服务 + 领域包 + Skills |

**不自己写控制流编排器**：7 阶段流程交由 OpenClaw 原生多智能体编排，
Python 侧只保留"科学工具层"（MCP Server），通过 MCP 被 OpenClaw 调用。

---

## 七阶段与 Agent 分工

| # | 阶段 | Agent | 主要工作 |
|---|---|---|---|
| ① | 定方向 | `gewu-director` | 主编：澄清研究问题、拆解目标、派发子任务并收敛结果 |
| ② | 读论文找 idea | `gewu-ideation` | 多源检索、PRISMA 式筛选、按 FINER 给选题打分 |
| ③ | 复现 | `gewu-reproduction` | 复现基线、复现门控与 `repro_lock`、真值隔离 |
| ④ | 改进 | `gewu-improver` | 多视角评分、消融实验与迭代改进 |
| ⑤ | 写论文 | `gewu-writer` | 成稿，并执行引用与声明审计（claim-audit） |
| ⑥ | 发表追踪 | `gewu-publication` | 投稿策略、期刊匹配、进度追踪 |
| ⑦ | 沉淀 | `gewu-distillation` | 固化为 Skill + 长周期记忆，形成复利闭环 |

各阶段产出写入 `handoff_<stage>.json`，下游按 schema 消费，避免上下文丢失。

---

## MCP 工具服务（Python 侧）

| 服务 | 能力 |
|---|---|
| `sci-compute` | PCA / PLS / 曲线拟合 / 交叉验证 等科学计算 |
| `sci-data` | 光谱等科学数据的读取与预处理 |
| `mil-model` | MIL 模型推理（支持 OpenVINO 本地推理） |
| `report` | 报告与图表产出 |
| `paper-search` | 多源论文检索（arXiv / Semantic Scholar / Crossref / OpenAlex / PubMed） |

---

## 目录结构

```
gewu-sciagent/
├── README.md                  # 本文件
├── LICENSE                    # Apache-2.0
├── NOTICE                     # 第三方方法论借鉴署名
├── requirements.txt           # Python MCP 工具层依赖
├── .env.example               # 环境变量示例（真实值填 .env，已被 Git 忽略）
├── .gitignore
├── docs/
│   ├── architecture.md        # 架构设计与落地路线图
│   ├── ui-design-plan.md      # Web 前端界面设计规格
│   └── borrowed-patterns.md   # 外部方法论借鉴分析（含合规声明）
├── data/                      # 数据集（大文件建议放网盘，仅留索引）
├── web/                       # 自研轻量 Web 前端 + 本地代理
│   ├── src/                   # React + Vite + TypeScript 前端
│   └── proxy/server.mjs       # 零依赖 Node 代理（托管前端 + 反代 Gateway + SSE 透传）
├── openclaw/                  # OpenClaw 配置与 Agent 工作区
│   ├── openclaw.json          # 网关配置（模型 / Agents / MCP；凭据用占位符）
│   ├── skills/                # Skill 源（research_lifecycle 等）
│   └── workspace/
│       ├── MEMORY.md          # 共享长周期记忆
│       └── agents/<role>/     # 7 个 Agent 工作区（AGENTS.md + skills/ + MEMORY.md）
└── gewu/                      # Python 工具层（经 MCP 被 OpenClaw 调用）
    ├── mcp/                   # 5 个 stdio MCP Server
    ├── skills/                # OpenClaw Skills 源（SKILL.md）
    └── domain_packs/          # 可插拔领域包：coal_libs（LIBS 煤热值参考实现）
```

---

## 快速开始

### 前置要求

- **Node.js** ≥ 24.16（且 < 25）或 ≥ 26.1 —— OpenClaw 的硬性要求
- **Python** 3.10+ —— MCP 工具层（注意需 `mcp` **1.x**，2.x 会重命名 `FastMCP` 导致导入失败）
- **书生大模型 API Key** —— 见下方「配置与隐私」

### 1. 安装 OpenClaw

```bash
npm i -g openclaw@2026.10.5
```

### 2. 安装 Python 依赖

```bash
pip install -r requirements.txt
```

### 3. 配置模型与凭据

```bash
cp .env.example .env      # 填入你的 INTERN_API_KEY
export INTERN_API_KEY=... # 或直接写入 ~/.openclaw/openclaw.json
```

将 `openclaw/openclaw.json` 的内容合并进 `~/.openclaw/openclaw.json`
（该模板中的 API Key 为 `${INTERN_API_KEY}` 占位符，不会泄露密钥）。

### 4. 启动网关

```bash
openclaw gateway run --force     # 常驻，默认 127.0.0.1:18789
openclaw gateway probe           # 验证连通
openclaw config validate         # 校验配置
openclaw mcp probe               # 验证 5 个 MCP 服务
```

### 5. 发起科研目标

```bash
openclaw agent --agent gewu-director \
  -m "调研并复现大颗粒原煤 LIBS 光谱热值预测的 MIL 方法，给出 5 折交叉验证指标"
```

---

## Web 界面（可选）

自研轻量前端，统一体验入口：移动优先（概览面）+ PC 三区驾驶舱（全量面）。

```bash
cd web
npm install
npm run dev        # 开发：前端 :5173 （/api 反代到本机代理 :3000）
npm run build && npm start   # 生产：单端口 :3000 同时提供前端与 API
```

---

## 配置与隐私

本项目对凭据处理遵循以下原则，**仓库中不含任何真实密钥或个人身份信息**：

| 措施 | 说明 |
|---|---|
| **环境变量注入** | API Key 通过 `INTERN_API_KEY` 环境变量提供 |
| **配置模板占位** | `openclaw/openclaw.json` 中写作 `${INTERN_API_KEY}`，提交到仓库的只是占位符 |
| **真实凭据不入库** | 真实 Key 只写入 `~/.openclaw/openclaw.json`（位于用户目录，不进 Git） |
| **`.env` 已忽略** | `.gitignore` 忽略 `.env` 与 `.env.*`，仅提交 `.env.example` 占位示例 |
| **无个人信息** | 仓库不含姓名、手机号、邮箱等个人身份信息 |

提交前建议自查：

```bash
grep -rInE "sk-[A-Za-z0-9]{16,}|1[3-9][0-9]{9}" --exclude-dir=node_modules --exclude-dir=.git .
```

> ⚠️ `openclaw/openclaw.json` 中的 MCP `command` 路径为 `<user>` 占位符，
> **换机部署时**需替换为本机的 Python venv 绝对路径。

---

## 文档

| 文档 | 内容 |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | 架构设计、配置要点与分阶段落地路线图 |
| [`docs/ui-design-plan.md`](docs/ui-design-plan.md) | Web 前端界面设计规格（移动优先 + PC 驾驶舱） |
| [`docs/borrowed-patterns.md`](docs/borrowed-patterns.md) | 外部方法论借鉴分析与合规声明 |

---

## 许可证

本项目采用 **Apache-2.0** 许可证，详见 [`LICENSE`](LICENSE)。

第三方署名与方法论借鉴说明见 [`NOTICE`](NOTICE)。

## 致谢

- **书生大模型**（Intern-S2 / Intern-S1 / InternVL）—— 提供模型能力
- **OpenClaw** —— 多智能体编排与运行时框架
- **paper-search-mcp**（MIT）—— 多源论文检索 MCP 服务
- **academic-research-skills** —— 借鉴其科研质量护栏的方法论思想
  （该仓库为 CC-BY-NC 4.0，本项目**仅借鉴方法论、未复制其代码与文本**，署名见 `NOTICE`）
