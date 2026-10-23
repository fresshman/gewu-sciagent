# 编排层与 Web 层实测记录（2026-10-23）

动机：上一轮「端到端走查」是在 bash 里直接 `import` MCP 模块调函数，**绕开了 OpenClaw
编排与 Web UI**。本轮补齐这两层，记录真实结论与暴露的缺陷。

载荷：用户未发表的 MIL+LIBS 煤热值课题（仅路径引用，仓库零数据副本）。

---

## 一、编排层：OpenClaw Gateway + 7 Agent + MCP（实测结论：**通**）

### 1.1 打通过程踩到的三个坑

1. **Gateway 起不来：陈旧 owner 租约**
   `openclaw gateway run --force` 连续失败：

   ```
   failed to acquire gateway state ownership | Another Gateway owner lease is
   still active for this state directory: holder 24672 at SJY04-0299,
   last renewed 85629 s ago. The holder 24672 is alive on this host
   ```

   实际 pid 24672 早已不存在（`tasklist` 查无此进程），但 `--force` **只抢端口、不清租约**，
   `gateway stop` 也无效（服务是 Scheduled Task 且已 missing）。
   **解决办法**：备份 `~/.openclaw/state/openclaw.sqlite` 后删掉 `state_leases` 中
   `scope='gateway-owner'` 那一行。这是每台机器上都会再遇到的运维坑，建议写进部署文档。

2. **冷启动 inspection 窗口内 agent 全部不可用**
   重启 Gateway 后立刻调 agent 会返回：

   ```
   Agent gewu-director has not completed startup inspection and preparation.
   Sessions remain unavailable until background inspection and preparation finish.
   ```

   实测该窗口约 1–2 分钟。Web 端若不区分这类错误，会把「系统还没热」当成「任务失败」弹给用户。

3. **默认超时不够，且超时后用户侧零输出**
   首轮任务（复现 fold0 + 列验证袋）在 300s 被斩断：`toolSummary.calls=27 / failures=8`、
   `assistantTurns=14`、`terminalReply.disposition=empty`，用户什么都没拿到。
   **已修**：`agents.defaults.timeoutSeconds` 由默认 600 提到 **1800**。

4. **MCP 请求级超时把重活工具判死**（比上面那条更隐蔽）
   即使 agent 超时放宽到 900s，`reproduce_fold` 仍报 `MCP 错误 -32001 请求超时`——
   卡住的是 **MCP 单请求超时**（默认远小于一次 MIL 前向推理耗时），而不是 agent 超时。
   **已修**：`openclaw mcp configure <server> --timeout <s>` 给重活服务单独放宽
   （mil-model `requestTimeoutMs=900000`、sci-plot/sci-data/report `600000`），
   已同步写进项目模板 `openclaw/openclaw.json`。修复后同一任务 1m18s 成功返回。

### 1.2 成功的两次真实调用

**最小化任务**（`list_val_bags`）——3 次工具调用、0 失败、2m14s：

```
验证袋数量：14（总袋数 70，第 0 折）
1. 中马矿中煤矿11月14日（12 条光谱，y_true = 2931.0 kcal/kg）
2. 煤场混煤11月22日（12 条光谱，y_true = 4138.0 kcal/kg）
3. 赵固二矿中煤矿1月12日（12 条光谱，y_true = 4231.0 kcal/kg）
```

与 `best_solution/fold0/predictions.json` 逐字一致（首条 `y_true=2931.0`）——**编排层拿到的是
真实工具返回值，不是模型编造**。

**MIL 真实推理任务**（`reproduce_fold`，修复 MCP 请求超时后）——2 次调用、0 失败、1m18s：

```
reproduce_fold(fold=0) 实际返回：
- RMSE：218.6113 kcal/kg
- MAE：173.9017 kcal/kg
- R²：0.8786
（状态：real-inference，真实推理，14 个验证袋，光谱长度 7305）
```

与直接调用 `mil_model.reproduce_fold` 的结果**逐位一致**（218.6113 / 173.9017 / 0.8786），
说明编排层拿到的是真实工具返回值，不是模型编造。

### 1.3 仍然存在的编排层问题

| # | 问题 | 证据 | 状态 |
|---|---|---|---|
| A1 | MCP 工具不在 Agent 直连工具表，需 `tool_search → tool_describe → tool_call` 三步桥接 | 成功轮次也要 3 次调用才完成 1 次真实取数；失败轮次 27 次调用 | **已修**：`tools.toolSearch.enabled=false`，实测同类任务降到 **1 次调用 / 0 失败** |
| A2 | intern-s2 397B 每轮推理慢，多步任务极易撞超时 | 首轮 14 turn / 325s 超时 | 已缓解（超时 1800s）+ Director 侧纪律：单轮只派一件事 |
| A3 | 超时/失败时用户侧无部分结果 | `terminalReply.disposition: empty` | 已缓解：代理把超时翻译成人话并提示拆任务；Web 轮次超时 240s→1500s |
| A4 | 冷启动 inspection 窗口返回 cli_error | 见 1.1(2) | **已修**：代理识别该错误 → 提示"启动自检中，稍后重试" |

### 1.4 A1 的根因与修复

`tools.toolSearch.enabled` 默认开启，schema 描述写得很清楚：

> Enables Tool Search. When on, OpenClaw hides large tool catalogs behind
> structured search/describe/call tools during embedded runtime runs.

格物挂了 8 个 MCP 服务（约 150+ 工具），正好命中"large tool catalog"，于是每个真实取数都要
先 search 再 describe 再 call。关闭后（代价：工具 schema 全量进 prompt，intern-s2 的 256K
上下文足够）：

```
toolSummary: { calls: 1, tools: ["mil-model__cv_summary"], failures: 0 }   // 74.8s
→ hybrid 均值 = 214.5699 kcal/kg，标准差 = 25.7094（与官方 214.5699 差 1.1e-05）
```

### 1.5 Web 代理自身的两个 bug（对话功能此前是坏的）

实测 Web 端发消息，SSE 立刻返回 `智能体异常退出（code 1）`：

1. **`openclaw` shell shim 解析到老 Node**。代理用 `spawn("openclaw")` → 命中系统 Node 22，
   而 OpenClaw 要求 Node ≥24.16/<25 或 ≥26.1，直接 code 1 退出。
   **已修**：改用**运行代理的当前 Node** 直跑 `openclaw.mjs`，路径由 `npm root -g` 动态解析
   （支持 `OPENCLAW_MJS` 显式覆盖）。坑：Windows 上 `npm` 是 `npm.cmd`，`execFileSync` 必须带
   `shell: true` 才解析得到。
2. **代理把 agent 轮次超时写死成 240s**，与配置里的 1800s 脱节——Web 端必然先超时。
   **已修**：默认 1500s，可用 `GEWU_AGENT_TIMEOUT` 覆盖。

同时把网关侧低层错误翻译成人话：启动自检中 / 超时建议拆任务 / 网关未连。

**冒烟**：`POST /api/chat {"agent":"gewu-director","message":"只回答四个字：格物就绪"}`
→ `delta: 格物就绪` → `done exitCode 0`。

---

## 二、Web 层：右栏三区块接入真实数据（已实现）

此前 `RightPanel.tsx` 三块全是 `right__placeholder`，注释写着「待接入测试案例」。
本轮用真实课题数据填实，同时**保证未发表数据不出本机**。

### 2.1 数据流

```
真实课题（本机，路径引用）
   └─ scripts/export_case_bundle.py   ← 只读，按路径读，不复制
        └─ web/.local/case.json       ← .gitignore，含未发表数值与本机路径
             └─ proxy /api/case
                  └─ RightPanel（零依赖内联 SVG 渲染）
```

* 未配置项目根时导出 `available:false`，前端降级为占位提示，**绝不用假数据顶替**。
* 仓库内新增文件只有 exporter 脚本与前端代码，无任何实验数值。

### 2.2 三个区块的真实内容

| 区块 | 数据来源 | 渲染 |
|---|---|---|
| 光谱查看器 | 真实 LIBS 单条击打 CSV（7305 点，抽样 366 点） | SVG 折线 + 峰位标注 + 波长轴 |
| 5 折 CV 指标 | `best_solution/fold*/predictions.json` 重算 | 4 张指标卡（RMSE/R²/MAE/相对基线）+ 逐折分组柱图 + 预测-真实散点（含 y=x） |
| 文献与产出物 | 3 条已核验 DOI（Talanta / SAB / JAAS）+ 阶段产物清单 | 列表 + verified 徽标 + 产物体积 |

指标口径在 UI 上明示：5 折折均 ± 总体标准差（ddof=0），并同时给出 ddof=1 的
`std_sample`，避免与 `summary.txt` 的 20.07 混淆。

### 2.3 验证

* `npm run typecheck` / `npm run build` 通过（48 modules）。
* `/api/health` → `gateway.reachable: true`；`/api/case` → `available: True`、
  RMSE 均值 214.568（与 `mil-model` 复现值 214.57 一致）、光谱 366 点、文献 3、产物 23。
* 未引入任何图表库（uPlot/Chart.js 均未安装），全部为零依赖内联 SVG，随主题切换。

---

## 三、本轮改动清单

| 文件 | 改动 |
|---|---|
| `scripts/export_case_bundle.py` | 新增：真实课题 → 案例 bundle 导出器 |
| `web/proxy/server.mjs` | 新增 `/api/case`（支持 `GEWU_CASE_FILE` 覆盖路径） |
| `web/src/types.ts` | 新增 `CaseBundle` 等类型 |
| `web/src/api/client.ts` | 新增 `getCase()` |
| `web/src/components/SpectrumChart.tsx` | 新增：光谱折线 |
| `web/src/components/FoldBars.tsx` | 新增：逐折分组柱图 |
| `web/src/components/PredScatter.tsx` | 新增：预测-真实散点 |
| `web/src/components/RightPanel.tsx` | 重写：三区块接入真实数据 |
| `web/src/styles/global.css` | 新增 `.case-*` 样式（随明暗主题） |
| `.gitignore` | 增加 `web/.local/` |
| `~/.openclaw/openclaw.json` | `agents.defaults.timeoutSeconds: 1800` |
