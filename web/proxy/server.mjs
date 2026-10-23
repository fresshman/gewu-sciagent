// 格物 Web · 本地轻代理 (Node, 零依赖)
// 职责：① 托管静态前端(dist)；② 暴露 /api/* 给浏览器（同源，无 CORS）；
//       ③ /api/chat 通过官方 CLI `openclaw agent` 桥接 OpenClaw Gateway，
//          把 Agent 回复以 SSE 流透传给前端。
//
// 为什么走 CLI 而不是直接连 Gateway WS：Gateway 是 loopback + 同源鉴权 +
// 设备鉴权，浏览器直连会被 CORS/鉴权双重拦截；而 `openclaw agent` 本身就是
// Gateway 的官方客户端（已验证可跑通 intern-s2）。M1 用 CLI 桥接即可稳定打通，
// 后续可平滑替换为直连 Gateway WS（升级路径见 docs/architecture.md）。

import http from "node:http";
import { spawn, execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { dirname, join } from "node:path";
import { AGENTS, STAGES, MODELS, RESEARCH_TOPIC } from "../shared/seed.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");
const DIST = join(ROOT, "dist");

const PORT = Number(process.env.PORT) || 3000;
const GATEWAY = process.env.GATEWAY_URL || "http://127.0.0.1:18789";
// OpenClaw CLI：优先用环境变量 OPENCLAW_BIN，否则假定已在 PATH（跨平台）。
// 本机开发时若不在 PATH，可设 OPENCLAW_BIN 指向 openclaw.cmd 的绝对路径。
const OPENCLAW_BIN = process.env.OPENCLAW_BIN || "openclaw";

// OpenClaw 要求 Node ≥24.16/<25 或 ≥26.1。若直接用 `openclaw` 这个 shell shim，
// 它会被解析到系统里更老的 Node 上并以 code 1 退出（实测：对话一发就失败）。
// 因此优先用**当前运行代理的这个 Node** 直跑 openclaw.mjs（路径由 `npm root -g` 动态解析）。
function resolveOpenclawLaunch() {
  const explicit = process.env.OPENCLAW_MJS;
  if (explicit && existsSync(explicit))
    return { cmd: process.execPath, prefix: [explicit], shell: false };
  // Windows 上 npm 是 npm.cmd，必须经 shell 才能解析（否则 execFileSync 直接抛错）
  const npmBin = process.platform === "win32" ? "npm.cmd" : "npm";
  try {
    const root = execFileSync(npmBin, ["root", "-g"], {
      encoding: "utf8",
      windowsHide: true,
      shell: true,
      timeout: 15000,
    }).trim();
    const cand = join(root, "openclaw", "openclaw.mjs");
    if (existsSync(cand)) return { cmd: process.execPath, prefix: [cand], shell: false };
  } catch {
    /* 回落到 PATH 里的 openclaw */
  }
  return { cmd: OPENCLAW_BIN, prefix: [], shell: true };
}
const OPENCLAW = resolveOpenclawLaunch();

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".png": "image/png",
  ".woff2": "font/woff2",
};

function sendJSON(res, code, obj) {
  res.writeHead(code, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(obj));
}

async function gatewayHealth() {
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 1500);
    const r = await fetch(GATEWAY + "/health", { signal: ctrl.signal });
    clearTimeout(t);
    const body = await r.json().catch(() => ({}));
    return { reachable: r.ok, status: body.status || (r.ok ? "live" : "down") };
  } catch {
    return { reachable: false, status: "unreachable" };
  }
}

async function serveStatic(req, res) {
  let urlPath = decodeURIComponent((req.url || "/").split("?")[0]);
  if (urlPath === "/") urlPath = "/index.html";
  const filePath = join(DIST, urlPath);
  if (!filePath.startsWith(DIST)) {
    res.writeHead(403); res.end("forbidden"); return;
  }
  if (existsSync(filePath) && (await readFile(filePath).then(() => true).catch(() => false))) {
    const ext = path.extname(filePath);
    res.writeHead(200, { "Content-Type": MIME[ext] || "application/octet-stream" });
    res.end(await readFile(filePath));
    return;
  }
  // SPA 回退
  const idx = join(DIST, "index.html");
  if (existsSync(idx)) {
    res.writeHead(200, { "Content-Type": MIME[".html"] });
    res.end(await readFile(idx));
    return;
  }
  res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
  res.end("Gewu web 尚未构建。请先 `npm run build`，或使用开发服务器 :5173。");
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  const p = url.pathname;

  if (p === "/api/health") {
    const gw = await gatewayHealth();
    return sendJSON(res, 200, { ok: true, proxy: "live", gateway: gw, openclawBin: OPENCLAW_BIN });
  }
  if (p === "/api/agents") return sendJSON(res, 200, { agents: AGENTS });
  if (p === "/api/stages") return sendJSON(res, 200, { stages: STAGES });
  if (p === "/api/models") return sendJSON(res, 200, { models: MODELS });
  if (p === "/api/topic") return sendJSON(res, 200, { topic: RESEARCH_TOPIC });

  // 真实案例数据：来自 scripts/export_case_bundle.py 生成的本机私有文件。
  // 该文件在 .gitignore 中（含未发表实验数值），缺失时返回 available:false，
  // 前端降级为占位提示，绝不用假数据顶替。
  if (p === "/api/case") {
    const caseFile = process.env.GEWU_CASE_FILE
      ? path.resolve(process.env.GEWU_CASE_FILE)
      : join(ROOT, ".local", "case.json");
    try {
      const txt = await readFile(caseFile, "utf8");
      const data = JSON.parse(txt);
      return sendJSON(res, 200, data);
    } catch {
      return sendJSON(res, 200, {
        available: false,
        reason: "本机尚未生成案例数据（运行 scripts/export_case_bundle.py）",
        hint: "python scripts/export_case_bundle.py",
      });
    }
  }

  if (p === "/api/chat" && req.method === "POST") {
    let raw = "";
    for await (const chunk of req) raw += chunk;
    let payload;
    try { payload = JSON.parse(raw); } catch { return sendJSON(res, 400, { error: "invalid json" }); }
    const agent = String(payload.agent || "gewu-director");
    const message = String(payload.message || "");
    if (!message.trim()) return sendJSON(res, 400, { error: "empty message" });

    res.writeHead(200, {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    });
    const send = (obj) => res.write(`data: ${JSON.stringify(obj)}\n\n`);

    send({ type: "start", agent, ts: Date.now() });

    // 通过官方 CLI 桥接 Gateway（CLI 是 Gateway 的官方客户端）
    // 单次 agent 轮次超时：默认 1500s（与 agents.defaults.timeoutSeconds=1800 对齐，
    // 留出网关侧余量）。领域模型推理/绘图都远超早先写死的 240s。
    const timeoutSec = String(Number(process.env.GEWU_AGENT_TIMEOUT) || 1500);
    const args = ["agent", "--agent", agent, "-m", message, "--timeout", timeoutSec];
    let child;
    try {
      child = spawn(OPENCLAW.cmd, [...OPENCLAW.prefix, ...args], {
        shell: OPENCLAW.shell,
        env: { ...process.env },
      });
    } catch (e) {
      send({ type: "error", text: "无法启动 openclaw：" + (e?.message || e) });
      return res.end();
    }

    // 把网关侧的低层错误翻译成人话：这些是"系统状态"，不是"任务失败"。
    function friendly(raw) {
      const t = String(raw || "");
      if (/has not completed startup inspection/i.test(t))
        return "⏳ 格物正在做启动自检（网关重启后约 1–2 分钟），请稍后重试。";
      if (/Request timed out|timeout/i.test(t))
        return "⏱ 本轮超时未返回结果。建议把任务拆小（一次只让智能体做一件事）后重试。";
      if (/failed to acquire gateway state ownership|gateway is not running|ECONNREFUSED/i.test(t))
        return "🔌 未连上 OpenClaw Gateway。请先在终端启动：openclaw gateway run --force";
      return t.slice(0, 500);
    }

    let errored = false;
    child.stdout.on("data", (d) => send({ type: "delta", text: d.toString() }));
    child.stderr.on("data", (d) => {
      const t = d.toString();
      if (/error|拒绝|fail|denied|exception/i.test(t)) {
        errored = true;
        send({ type: "error", text: friendly(t) });
      }
    });
    child.on("close", (code) => {
      if (!errored && code !== 0)
        send({ type: "error", text: `智能体异常退出（code ${code}）。可稍后重试或缩小任务范围。` });
      send({ type: "done", exitCode: code, ts: Date.now() });
      res.end();
    });
    child.on("error", (e) => {
      send({ type: "error", text: "桥接失败：" + (e?.message || e) });
      res.end();
    });
    req.on("close", () => { try { child.kill(); } catch {} });
    return;
  }

  return serveStatic(req, res);
});

server.listen(PORT, () => {
  console.log(`[gewu-proxy] listening on http://localhost:${PORT}`);
  console.log(`[gewu-proxy] gateway=${GATEWAY}  openclaw=${OPENCLAW.cmd} ${OPENCLAW.prefix.join(" ")}`);
  console.log(`[gewu-proxy] agent timeout=${process.env.GEWU_AGENT_TIMEOUT || 1500}s`);
});
