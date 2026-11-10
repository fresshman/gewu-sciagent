# 静默降级：代理拿自己的 Node 22 去跑 openclaw，且健康检查恒为 ok

## 现象

打开 `http://localhost:3112`，界面一切正常（顶栏、阶段条、右栏都有数据），
但只要发一句话就失败，且**失败信息是英文技术栈警告**：

```
POST /api/chat →
  (node:21512) ExperimentalWarning: SQLite is an experimental feature…
  openclaw: Node 22.22.2: node:sqlite truncates TEXT at embedded NUL (nodejs/node#61954);
            use 24.16+/26.1+ or a build with the fix
  If you use nvm, run: nvm install 26
→ "type":"done","exitCode":1,"status":"error"
```

同时 `/api/health` 返回 `{"ok":true,...}` —— 前端因此不显示任何告警。
桌面上连"未连接网关"那行灰字都没有（它只在移动端 chat 页渲染）。

## 根因（两个独立缺陷叠加）

1. **入口解析成功，但运行时选错了。** `resolveOpenclawLaunch()` 找到 `openclaw.mjs` 后，
   一律用 `process.execPath`（**代理自己的 Node**）去跑它，从不校验版本。
   代理被 `node proxy/server.mjs` 起在 Node 22 上时，等于用 22 去跑一个要求 ≥24.16 的程序。
   `npm root -g` 那段是好的：入口路径本身能找到（`~/.npm-global/node_modules/openclaw/openclaw.mjs`），
   所以"找不到入口"的假设从头到尾是错的——**问题不在路径，在运行时**。

2. **健康检查的 `ok` 是写死的字面量。** `{ ok: true, ... }` 与网关实际可达性无关，
   评审看到的绿灯只代表"代理进程还活着"。

失败归因也被带偏过一次：`/api/health` 里 `openclawBin` 报的是环境变量 `OPENCLAW_BIN` 的原始值
（`"openclaw"`），**不是**最终解析出来的启动路径，于是看起来像"回落到了 PATH 垫片"。
改成上报 `LAUNCH.entryPath/nodePath` 之后才看清真相。

## 修法

- 新增 `web/shared/launch_guard.mjs`（零依赖纯函数）：`parseNodeVersion` / `nodeGateOk` /
  `pickRuntime` / `formatRefusal` / `formatDegradedWarning`。闸门边界与 openclaw 一致：
  `≥24.16 且 <25`，或 `≥26.1`；**25.x 整条线排除**；版本解析失败一律判不满足（默认拒绝）。
- `resolveOpenclawLaunch()` 改为两段解析：入口（`OPENCLAW_MJS` → `npm root -g` → 常见全局目录，
  只收真实存在的 `.mjs`）与运行时（`GEWU_NODE`/`OPENCLAW_NODE` → 当前进程 Node → PATH 上其它 node）。
  **当前 Node 不满足闸门时不再被当成默认值**。
- 启动硬闸：解析不出入口或找不到合规运行时 → 打印中文修法并 `exit 1`；
  显式 `GEWU_ALLOW_DEGRADED_PROXY=1` 才降级启动，且 `/api/chat` 直接回未就绪原因。
- `/api/health`：`ok = launch.ok && gateway.reachable`，新增 `ready` 与 `launch{node,nodePath,nodeFrom,entry,requirement,degraded}`。
- 前端：红条提到 `.app` 层（`grid-template-areas` 显式加 `alert` 行，不用自动放置），
  桌面/移动/论文库都可见；文案三态区分「Node 不合规」「网关没起」「代理连不上」。

## 验证（本机实测）

| 场景 | 命令 | 结果 |
|---|---|---|
| Node 22（不合格） | `PORT=3113 node web/proxy/server.mjs` | 退出码 1；中文报错点名 `v22.22.2`、列出已检查的两个 node（22.22.2 / 24.13.0）、给三条修法 |
| 降级 | `GEWU_ALLOW_DEGRADED_PROXY=1 PORT=3113 …` | 起服；`/api/health` → `ok:false, ready:false, launch.ok:false`；`/api/chat` → 「系统未就绪：当前 Node v22.22.2 不满足要求…」 |
| 合规 Node | `GEWU_NODE=<node26> PORT=3114 …` | `launch.ok:true, node:v26.13.0`；网关未起时 `ready:false`（正确），拉起网关后 `ok:true, ready:true` |
| 真对话 | 同上 + `POST /api/chat` | `delta:"格物就绪"` → `done exitCode:0`（38s，intern-s2 真实推理） |

Node 26.13.0（便携版）已放到 `~/.workbuddy/binaries/node/versions/26.13.0/`，
`start-gewu.sh` 与 `GEWU_NODE` 都指向它；3112 已用新代码重启并实测通过。

## 下次动到同一处时的约束

1. **任何"启动子进程"的解析，都要同时校验"入口存在"与"运行时合规"**。只校验前者
   会得到"进程起来了、每句话都失败"这种最难排查的形态。
2. **健康检查里的 `ok` 不许是字面量**。它必须是"能不能干活"的派生值；否则红灯永远不会亮。
3. **诊断字段要报最终解析结果，不报环境变量原值**。`openclawBin: "openclaw"` 掩盖了真相一整轮。
4. 可执行检查：`node --test web/tests/launch_guard.test.mjs`（9 项，锁定 24.15/24.16/25.x/26.0/26.1 边界）。

## 顺带发现（未修，另议）

拉起网关时日志暴露：`openclaw/workspace/**/scientific_plotting/SKILL.md` 共 5 份
**缺 `description` 字段**，被 OpenClaw 判为无效技能并静默跳过
（`error=description is required`），涉及 reproduction / improver / writer / publication 四个 Agent。
即"技能自动发现"里这个技能实际没被加载——与本次同类：*静默跳过比报错更贵*。
