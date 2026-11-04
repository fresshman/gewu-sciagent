# 开箱可复现演练（Clean-unpack Drill）· 2026-11-04

> 目的：验证**只看仓库里 git 跟踪的文件**能否把格物装起来、跑起来。
> 全部数字为本机实测，不来自文档复述。执行环境：Windows 10 19045 / Git Bash /
> 便携 Node 26.9.0 / WorkBuddy 托管 Python（default、paper-search、office-word 三个 venv）。

## 0. 结论先说

干净解包目录里，**配置生成 → schema 校验 → 10 个 MCP 服务真实起进程 → 两套件测试 →
依赖安装 → 前端构建 → 代理起服并出真实数据**全链路通过，无需修改任何一行代码。
演练过程中暴露并当场修掉的缺陷 6 个（见 §8），另有 3 项已知缺口没动（见 §9）。

## 1. 解包方式

```bash
mkdir -p "$DRILL" && git ls-files -z | xargs -0 -I{} cp --parents {} "$DRILL"/
```

- 只复制 git 跟踪的文件：**186 个**（演练时另补本次新增、尚未提交的 `requirements-coal.txt`
  与 `scripts/bootstrap_openclaw_config.py`，共 188 个文件、2.0 MB）；不含 `.git/`、
  `web/node_modules/`、`output/`、`.env`、`web/.local/case.json`、
  `openclaw/workspace/agents/*/MEMORY.md`——这些全是 gitignore 的本机状态，正是"换机器不该带走"的东西。
- 演练目录在工作区之外（`%LOCALAPPDATA%/Temp/gewu_drill*`），避免与仓库内文件互相串味。
- **共解包两次**：第一次跑 §2–§5（配置 / MCP / 构建 / 代理）；改完 §8 的 6 个缺陷后
  **重新解包一次**再跑 §4 与 `create_project.py`，确保记录里的数字来自"修完之后的干净解包"。

## 2. 配置生成（`scripts/bootstrap_openclaw_config.py`）

在解包目录里执行（不带任何路径改写参数，只让脚本自己探测）：

| 项 | 实测结果 |
|---|---|
| 仓库根替换 | 26 处 `F:/python-exercise/.../gewu-sciagent` → 演练目录（`%LOCALAPPDATA%/Temp/gewu_drill`） |
| 解释器替换 | `--python` 7 处、`--node` 1 处、`--paper-python` 1 处、`--office-python` 1 处 |
| `--check` 退出码 | **0**（全部 ok） |
| workspace 存在性 | 8 条（网关根 + 7 角色）全部在解包目录内真实存在 ✓ |
| Node 闸门 | v26.9.0 满足「24.16 ≤ v < 25 或 v ≥ 26.1」✓ |
| `openclaw config validate` | **Config valid**，2 条 warning：`agents.defaults.heartbeat.agentId` 未设（多智能体心跳默认关，不影响本轮链路）、`gateway.auth.token` 引用未设置的 `OPENCLAW_GATEWAY_TOKEN`（可选加固项） |

**负例也验过**（同一脚本，故意不给参数）：

- 只给 PATH 上的 Node 24.13 → `✗ Node v24.13.0 不满足 openclaw 闸门`，退出码 **1**。
- 不给 `--paper-python/--office-python` → `✗ 产物里仍有 2 处 MCP command 指向 <user> 占位，
  这些 server 起不来`，退出码 **1**。这是设计意图：**宁可拒绝生成，也不产出一份"看起来成功了"的配置**。

## 3. MCP 服务：从解包目录起真实进程

用 `OPENCLAW_HOME` 指到只装解包配置的临时 home，跑 `openclaw mcp probe`：

| server | tools | | server | tools |
|---|---|---|---|---|
| sci-compute | 4 | | report | 4 |
| sci-data | 5 | | sci-plot | 17 |
| sci-exp | 4 | | chart-cloud | 12 |
| sci-verify | 8 | | office-word | 54（外部包） |
| mil-model | 6 | | paper-search | 57（外部包） |

**10 个 server 全部握手成功**，与仓库内跑的清单逐项一致。业务工具合计 **171**
（FastMCP 给每个 server 另加的 `resources_list/resources_read/prompts_list/prompts_get`
4 个模板工具不计入）。其中**本仓自研 48 个**＝7 个 Python server（4+5+8+4+6+17+4），
与 `gewu/mcp/*.py` 里 `@mcp.tool()` 装饰器总数（48）逐一对齐；
`chart-cloud` 的 12 个是对 AntV 外部包做白名单放行后的子集，`paper-search` 57、
`office-word` 54 均为外部包自带。

## 4. Python 套件

```bash
python -m pytest tests -q
```

| 场景 | 结果 | 用时 |
|---|---|---|
| 仓库内（有 gitignore 的 `.coal_project_root`） | **68 passed / 0 skipped** | 9.91s |
| 干净解包 · 第一次 | **67 passed / 1 skipped** | 16.60s |
| 干净解包 · 第二次（同一目录连跑两次） | 第一次 **66 passed / 2 skipped**（25.31s），紧接着重跑 **67 passed / 1 skipped**（12.41s） | — |

固定的那一条 skip 来自 `tests/test_mcp_timeout_hierarchy.py:99`：`本机未配置煤热值项目，
subprocess 分支不可达`——解包目录里必然没有 gitignore 的 `.coal_project_root`，属**外部条件，
不是代码失败**。会飘的那一条是 `test_verify_papers_fallback`（CrossRef 限流/断网时返回
`verify_pending` 而跳过），同一份解包两次跑出 66/2 与 67/1 就是它。
所以 README 把 68/0、67/1、66/2 三种合法结果与各自成因写死，而不是承诺单一数字。

## 5. Web 套件与构建

| 步骤 | 结果 |
|---|---|
| `node --test "tests/**/*.test.mjs"`（**未装任何依赖时**） | **48 pass / 0 fail**，337.86ms |
| `npm install` | added 71 packages in 40s（提示 esbuild postinstall 未被 allowScripts 覆盖，属 npm 侧策略告警，不阻断构建） |
| `npm run build` | ✓ built in 825ms；产物 `dist/assets/index-*.js` 668.34 kB、`pdf.worker.min-*.mjs` 1264.34 kB、css 31.79 kB |
| `node proxy/server.mjs`（PORT=3100，接本机已运行网关） | 起服成功，下列端点全 200 |

代理端点实测返回（解包目录起的进程）：

```
/api/health   {"ok":true,"proxy":"live","gateway":{"reachable":true,"status":"live"},...}
/api/agents   7 个 gewu-* 角色（id/name/role/color/desc）
/api/models   intern-s2 / intern-s1-pro / intern-s1 / internvl3.5-241b-a28b
/api/stages   七阶段清单
/api/projects {"active_project":"coal-thermal", ...}
/api/runs     {"runs":[]}
/api/case     {"available":false,"reason":"本机尚未生成案例数据（运行 scripts/export_case_bundle.py）"}
```

`/api/case` 这条是刻意的**降级口径**：新机器没有 `web/.local/case.json` 时返回
`available:false` + 生成提示，前端显示占位，**不拿假数据顶替**。

## 6. 启动脚本（`start-gewu.sh`）

| 场景 | 实测 |
|---|---|
| `--check`（正向） | Node 26.9.0 ✓ / openclaw 2026.10.5 (1b58cb9) / 配置里 10 个 MCP server / 前端依赖已装，退出码 0 |
| `--check`（`GEWU_NODE` 指向非 Node 程序） | 0.28s 内报 `非 Node 程序（文件名不是 node）`，退出码 1，**不弹窗、不挂死** |
| `--help` / 未知参数 | 打印用法 / `未知参数：--bogus（可用 --check / --gateway）`，退出码 2 |
| 运行态 `bash start-gewu.sh` | 网关约 14s 内就绪，前端代理起服；`/health` 与代理 `/api/health` 均 `ok:true` |

旧版脚本把便携 Node 与 openclaw 入口写死成本机绝对路径（换机即失效），现在按
`$GEWU_NODE → PATH` 与 `$OPENCLAW_MJS → openclaw shim → 全局 node_modules` 顺序解析。

## 7. 密钥扫描

```bash
git ls-files -z | xargs -0 grep -IlE "sk-[A-Za-z0-9]{16,}|api[_-]?key\s*[:=]\s*['\"]?[A-Za-z0-9]{20,}"
```

解包目录（= 将要公开的全部内容）扫描结果：**0 命中**。模板里 API Key 一律是
`${INTERN_API_KEY}`，真实 Key 只存在于仓库外的 `~/.openclaw/openclaw.json`。

## 8. 演练过程中发现并当场修掉的缺陷

1. **`openclaw/openclaw.json` 模板不可一键生成**：26 处仓库根 + 10 处 `<user>` 解释器路径
   要手工改，且改完无法验证 → 新增 `scripts/bootstrap_openclaw_config.py`（本文 §2）。
2. **`start-gewu.sh` 写死本机便携 Node 路径** → 改为环境变量优先 + PATH 探测 + 版本闸门 +
   `--check` 自检模式（§6）。
3. **`scripts/create_project.py` 把 `C:/Users/<user>/...` 写死进生成的项目配置**（两处），
   且 `python_version` 一个写 3.13.12、一个写 3.13.14 → 改为取 `GEWU_SHARED_VENV`，
   缺省回落到当前解释器 `sys.prefix`；版本取 `platform.python_version()`。
   干净解包内实测（把 `USERPROFILE` 指到临时 home 跑）：生成的
   `config.json` 里 `venv_path` / `shared_venv` = 运行脚本的那个解释器、
   `python_version` = 3.13.14（真实值），不再出现写死的用户名路径。
4. **`requirements.txt` 虚报依赖**：列了 9 个仓库内**零导入**的包（pandas/optuna/requests/
   pyyaml/arxiv/pdfplumber/pillow/openvino/torch），其中 torch+openvino 白拉 1–2 GB →
   精简为实际导入的 8 项；torch 单独移到可选的 `requirements-coal.txt`。
5. **`research_lifecycle` 技能指向未配置模型 `intern-s1-mini`**：providers 里只注册了
   intern-s2 / intern-s1-pro / intern-s1 / internvl3.5，按该纪律路由会直接解析失败 →
   10 个跟踪副本（9 份 SKILL.md + architecture.md）统一改为 `intern-s1`。
6. **文档不实**：README 把 A2A 协议层与 Computer Use 列为落地能力、MCP 表漏 2 个服务、
   目录结构里 per-agent `MEMORY.md` 的入库口径写反、测试步骤整条缺失、外链指向无法验证的
   GitHub 地址 → 全部按实测改写，能力口径明确标注"框架具备 / 本项目未使用"。

## 9. 已知缺口（本次没动，如实记录）

1. **`sci_data.parse_figure` 仍是占位实现**（返回 `modality:"unknown"`），却被
   `spectrum_preprocess` 技能声明为工具。赛题把「多模态科学数据解析」列为方向 1 必备要素，
   这一条要么接 internvl3.5 要么从技能声明里摘掉，**是当前最刺眼的自相矛盾点**。
2. **含未发表数值/本机路径的文件仍在仓库里**：`e2e_*.md`（5 个文件里出现真实的交叉验证
   RMSE 数值，本文不复述）、`.workbuddy/memory/2026-10-28.md`（含 `C:/Users/<user>` 与同一 RMSE）、
   `openclaw/workspace/agents/gewu-director/make_figures.py`（硬编码输出路径 + 逐 bag 真实预测值）。
   按「未发表数据与本机路径不入库」的既定纪律，这三类应当移出仓库；涉及改写已推送历史，
   留待决策。
3. **两处代码待办**：一键送复现不预检目标项目可达性（`web/proxy/server.mjs:1030`）；
   论文全文抽取仍是前缀硬截断（`web/proxy/server.mjs:1146`），长论文后文取不到。
