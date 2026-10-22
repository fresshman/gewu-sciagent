// 开发启动器：用同一个 Node(26) 同时拉起 Vite(:5173) 与本地轻代理(:3000)
// 用法：在 web/ 目录下 `npm run dev`
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");
const node = process.execPath; // 当前 Node（托管版 26）

// 代理先起，保证 /api 就绪
const proxy = spawn(node, [join(ROOT, "proxy/server.mjs")], {
  stdio: "inherit",
  env: process.env,
});

const viteBin = join(ROOT, "node_modules/vite/bin/vite.js");
const vite = spawn(node, [viteBin], {
  stdio: "inherit",
  env: { ...process.env, PORT: "5173" },
});

function cleanup() {
  try { proxy.kill(); } catch {}
  try { vite.kill(); } catch {}
  process.exit(0);
}
process.on("SIGINT", cleanup);
process.on("SIGTERM", cleanup);

setTimeout(() => {
  if (!existsSync(viteBin)) {
    console.warn("\n[dev] 未检测到 vite，请先在 web/ 下运行 `npm install`。\n");
  }
}, 1500);
