// 格物 Web · 本地轻代理 (Node, 零依赖)
// 职责：① 托管静态前端(dist)；② 暴露 /api/* 给浏览器（同源，无 CORS）；
//       ③ /api/chat 通过官方 CLI `openclaw agent` 桥接 OpenClaw Gateway，
//          把 Agent 回复以 SSE 流透传给前端。
//
// 为什么走 CLI 而不是直接连 Gateway WS：Gateway 是 loopback + 同源鉴权 +
// 设备鉴权，浏览器直连会被 CORS/鉴权双重拦截；而 `openclaw agent` 本身就是
// Gateway 的官方客户端（已验证可跑通 intern-s2）。M1 用 CLI 桥接即可稳定打通，
// 后续可平滑替换为直连 Gateway WS（升级路径见 docs/ui-design-plan.md §2）。

import http from "node:http";
import { spawn } from "node:child_process";
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
    const args = ["agent", "--agent", agent, "-m", message, "--timeout", "240"];
    let child;
    try {
      child = spawn(OPENCLAW_BIN, args, { shell: true, env: { ...process.env } });
    } catch (e) {
      send({ type: "error", text: "无法启动 openclaw：" + (e?.message || e) });
      return res.end();
    }

    let errored = false;
    child.stdout.on("data", (d) => send({ type: "delta", text: d.toString() }));
    child.stderr.on("data", (d) => {
      const t = d.toString();
      if (/error|拒绝|fail|denied|exception/i.test(t)) {
        errored = true;
        send({ type: "error", text: t });
      }
    });
    child.on("close", (code) => {
      if (!errored && code !== 0) send({ type: "error", text: `agent 异常退出 (code ${code})` });
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
  console.log(`[gewu-proxy] gateway=${GATEWAY}  openclaw=${OPENCLAW_BIN}`);
});
