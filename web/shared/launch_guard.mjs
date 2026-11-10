// 启动闸门：判断"这台机器现在能不能真的把 openclaw 跑起来"。
//
// 为什么单独抽一个模块：原实现把判断藏在 server.mjs 里，且**判断错了方向**——
// 它只管"能不能找到 openclaw.mjs"，找到就用 `process.execPath`（当前代理的 Node）去跑。
// 于是出现实测过的坏局面：代理跑在 Node 22.22.2 上 → 找到入口、照跑 → openclaw 打印
// 「Node 22.22.2: node:sqlite truncates TEXT ... use 24.16+/26.1+」→ exit 1 →
// 用户只看到一串英文警告，聊天框里什么都没有。
//
// 正确判据是两件事同时成立：
//   ① 入口：真的存在一个 openclaw.mjs（不是 shell shim、不是目录）；
//   ② 运行时：拿来跑它的那个 node 必须满足 openclaw 的版本闸门。
// 任一不成立就**拒绝启动**并给中文修法——"起不来"要比"起来了但每句话都失败"诚实。
//
// 本文件零依赖、纯函数，便于 node --test 直接测边界（24.15/24.16/25/26.0/26.1）。

import { join } from "node:path";

/// openclaw 自 2026.10 起要求：Node ≥24.16 且 <25；或 ≥26.1（25.x 被明确排除）。
export const NODE_GATE_TEXT = "Node ≥24.16 且 <25，或 ≥26.1";

/** "v24.16.0" / "24.16.0" → [24,16,0]；解析不了返回 null（绝不猜成 0,0,0）。 */
export function parseNodeVersion(raw) {
  if (typeof raw !== "string") return null;
  const m = raw.trim().match(/^v?(\d+)\.(\d+)\.(\d+)/);
  if (!m) return null;
  return [Number(m[1]), Number(m[2]), Number(m[3])];
}

/** 版本是否满足 openclaw 闸门。解析失败一律判不满足（宁可拒绝，也不放行）。 */
export function nodeGateOk(raw) {
  const v = parseNodeVersion(raw);
  if (!v) return false;
  const [major, minor] = v;
  if (major > 26) return true;
  if (major === 26) return minor >= 1;
  if (major === 25) return false; // 25.x 整条线被 openclaw 排除
  if (major === 24) return minor >= 16;
  return false;
}

/** 从 `npm root -g` 的输出取全局 node_modules（去空白，保留原分隔符）。 */
export function parseNpmRootG(stdout) {
  if (typeof stdout !== "string") return null;
  const line = stdout
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean)
    .pop();
  if (!line) return null;
  return line.replace(/[\\/]+$/, "");
}

/** 全局 node_modules → openclaw 入口路径（只算路径，不检查存在性）。 */
export function openclawEntryFromRoot(root) {
  if (!root) return null;
  return join(root, "openclaw", "openclaw.mjs");
}

/**
 * 在候选运行时里挑第一个满足闸门的。
 * candidates: [{ path, version }]，按调用方给的优先级排列（前面的更优先）。
 * 当前进程的 Node 也作为候选传进来——它不满足时**不能**被当成默认值。
 * 返回 { picked, rejected }：rejected 保留理由，供拒绝启动时原样讲给用户听。
 */
export function pickRuntime(candidates) {
  const list = Array.isArray(candidates) ? candidates : [];
  const rejected = [];
  for (const c of list) {
    if (!c || !c.path) continue;
    if (!c.version) {
      rejected.push({ path: c.path, reason: "取不到版本号（文件不存在或不是 node）" });
      continue;
    }
    if (!nodeGateOk(c.version)) {
      rejected.push({ path: c.path, reason: `${c.version} 不满足闸门` });
      continue;
    }
    return { picked: c, rejected };
  }
  return { picked: null, rejected };
}

/**
 * 拒绝启动时打印的中文说明。刻意给"三条修法 + 一条临时降级"，
 * 不含英文堆栈——用户不需要知道 node:sqlite 的 NUL 截断细节。
 */
export function formatRefusal({ nodeVersion, entryPath, port, rejected = [] }) {
  const lines = [];
  lines.push("");
  lines.push("✗ 格物 Web 代理拒绝启动：当前环境跑不了 OpenClaw。");
  lines.push("");
  if (!entryPath) {
    lines.push("  原因：找不到 openclaw 入口（openclaw.mjs）。");
    lines.push("  说明：`openclaw` 这个 shell 垫片会落到系统里更老的 Node 上并以 code 1 退出，");
    lines.push("        所以这里不接受垫片，只要真实的 .mjs 文件。");
  } else if (!nodeGateOk(nodeVersion)) {
    lines.push(`  原因：当前 Node 是 ${String(nodeVersion || "未知").replace(/^v/, "v")}，OpenClaw 要求 ${NODE_GATE_TEXT}。`);
    lines.push("        版本不够时 openclaw 会在启动阶段直接退出，界面上表现为「每句话都失败」。");
  } else {
    lines.push("  原因：启动自检未通过。");
  }
  if (rejected.length) {
    lines.push("");
    lines.push("  已检查过的运行时：");
    for (const r of rejected.slice(0, 5)) lines.push(`    · ${r.path} → ${r.reason}`);
  }
  lines.push("");
  lines.push("  修法（任选其一）：");
  lines.push("    1) 装一个合规的 Node 26，再用它启动代理：");
  lines.push("         node -v                                 # 先确认 ≥26.1");
  lines.push(`         node web/proxy/server.mjs               # 端口默认 ${port || 3000}`);
  lines.push("    2) 已有合规 Node，直接指给它（不改 PATH）：");
  lines.push("         GEWU_NODE=/path/to/node26/node.exe node web/proxy/server.mjs");
  lines.push("    3) openclaw 不在全局目录时，显式给入口：");
  lines.push("         OPENCLAW_MJS=/path/to/openclaw/openclaw.mjs node web/proxy/server.mjs");
  lines.push("    —— 或者直接跑仓库脚本，它自带 Node/入口双重探测：bash start-gewu.sh");
  lines.push("");
  lines.push("  只想看前端静态页（不做对话）可以降级启动，但会明确标注未就绪：");
  lines.push("         GEWU_ALLOW_DEGRADED_PROXY=1 node web/proxy/server.mjs");
  lines.push("");
  return lines.join("\n");
}

/** 降级启动时的警告（用户显式要求忽略闸门）。 */
export function formatDegradedWarning({ nodeVersion, entryPath }) {
  return [
    "",
    "⚠ 已按 GEWU_ALLOW_DEGRADED_PROXY=1 降级启动：只提供静态前端与只读接口。",
    `  Node=${nodeVersion || "未知"}  入口=${entryPath || "未找到"}  要求=${NODE_GATE_TEXT}`,
    "  /api/chat 会直接返回未就绪错误，不再尝试拉起 openclaw。",
    "",
  ].join("\n");
}
