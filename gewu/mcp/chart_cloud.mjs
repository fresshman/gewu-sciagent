#!/usr/bin/env node
/**
 * chart_cloud.mjs —— 包装 @antv/mcp-server-chart，只暴露「不含实验数据」的结构/概念图。
 *
 * 背景：@antv/mcp-server-chart 是云端出图 MCP（把图表数据 POST 到
 * antv-studio.alipay.com 公有云渲染，返回远程图片 URL）。格物本地优先、可能含
 * 未发表实验数据，不能让测量值出域。本包装在启动前注入 DISABLED_TOOLS，关掉所有
 * 「含数据的统计图」类型（共 15 个），只保留思维导图/桑基/鱼骨/组织架构/地图等
 * 12 种纯结构图，从源头强制隔离实验数据离开本机。
 *
 * 分工：
 *   - 含实验数据的统计图（line/area/scatter/bar/boxplot/violin/histogram/pie/
 *     radar/waterfall/dual_axes 等）→ 本地 matplotlib，见 gewu/mcp/sci_plot.py
 *   - 纯结构/概念图（mind_map/fishbone/sankey/org_chart/map/...）→ 本包装（云端）
 *
 * 路径处理：AntV 入口由 `npm root -g` 动态解析，不把机器用户名写死进仓库。
 * 换机操作：先 `npm install -g @antv/mcp-server-chart`，本包装会自动定位其入口。
 */
import { spawn, execFileSync } from "node:child_process";
import path from "node:path";
import { existsSync } from "node:fs";

// ── 解析 @antv/mcp-server-chart 入口（动态，避免硬编码机器路径）──────────────
function resolveAntvEntry() {
  const nodeDir = path.dirname(process.execPath); // 当前 node 安装目录
  const candidates = [
    path.join(nodeDir, "node_modules", "npm", "bin", "npm-cli.js"),
    "npm", // 退路：直接走 PATH 上的 npm
  ];
  let root = "";
  for (const npm of candidates) {
    try {
      root = execFileSync(process.execPath, [npm, "root", "-g"], {
        encoding: "utf-8",
        windowsHide: true,
      }).trim();
      if (root) break;
    } catch {
      // 尝试下一个候选
    }
  }
  if (!root) {
    console.error(
      "[chart_cloud] 无法解析 npm 全局根目录，请确认 node/npm 可用。"
    );
    process.exit(1);
  }
  const entry = path.join(root, "@antv", "mcp-server-chart", "build", "index.js");
  return entry;
}

const ANTV_ENTRY = resolveAntvEntry();
if (!existsSync(ANTV_ENTRY)) {
  console.error(
    "[chart_cloud] 未找到 @antv/mcp-server-chart，请先执行：\n" +
      "  npm install -g @antv/mcp-server-chart\n" +
      "期望入口：" +
      ANTV_ENTRY
  );
  process.exit(1);
}

// ── 必须本地出图的「含数据」类型，云端一律禁用（防实验数据出域）─────────────
const DISABLED_TOOLS = [
  // 纯统计图（测量值）
  "generate_line_chart",
  "generate_area_chart",
  "generate_scatter_chart",
  "generate_column_chart",
  "generate_bar_chart",
  "generate_dual_axes_chart",
  "generate_boxplot_chart",
  "generate_violin_chart",
  "generate_histogram_chart",
  "generate_pie_chart",
  "generate_radar_chart",
  "generate_waterfall_chart",
  // 以下三类偏结构，但可承载量化值/数据表，保守禁用以防泄漏：
  "generate_venn_chart",
  "generate_liquid_chart",
  "generate_spreadsheet",
].join(",");

process.env.DISABLED_TOOLS = DISABLED_TOOLS;

// 拉起 AntV server（stdio 透传，JSON-RPC 经本包装直通 OpenClaw）
const child = spawn(process.execPath, [ANTV_ENTRY], {
  stdio: "inherit",
  env: process.env,
  cwd: path.dirname(ANTV_ENTRY),
});

child.on("exit", (code) => process.exit(code ?? 0));
child.on("error", (err) => {
  console.error("[chart_cloud] 启动 @antv/mcp-server-chart 失败:", err.message);
  process.exit(1);
});
