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
import { existsSync, mkdirSync, writeFileSync, readdirSync, readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
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

// ── A3: 中间结果落盘 ──────────────────────────────────────────────
// 长任务（多步工具调用）可能跑十几分钟；此前 agent stdout 只在结束才吐最终回复，
// 超时则用户一无所获。这里并发 `openclaw sessions tail --follow` 跟会话轨迹，把每一步
// 工具调用/结果实时落盘到 web/.local/runs/<key>.json，前端即使超时/关页也能看到
// 「已完成步骤」，并可断点续跑（复用同一 session-key 让 agent 承接上下文）。
const RUNS_DIR = join(ROOT, ".local", "runs");
function safeName(key) { return String(key).replace(/[^a-zA-Z0-9._-]/g, "_"); }
function runPath(key) { return join(RUNS_DIR, safeName(key) + ".json"); }

// 把 `sessions tail` 的一行解析成结构化步骤。
// 行格式： `<ts>Z <eventType> <sessionKey> <detail>`
//   tool.call   mil-model__list_val_bags {...redacted...}
//   tool.result mil-model__list_val_bags ok
//   model.completed sheng/intern-s2 done
//   session.ended   success
function parseTailLine(line) {
  const m = line.match(/^(\S+Z)\s+(\S+)\s+(\S+)\s?(.*)$/);
  if (!m) return { kind: "raw", raw: line };
  const [, ts, type, , detailRaw] = m;
  const detail = (detailRaw || "").trim();
  const step = { ts, type, detail, raw: line };
  if (type === "tool.call") {
    step.kind = "tool"; step.tool = detail.split(/\s+/)[0]; step.phase = "call"; step.status = "running";
  } else if (type === "tool.result") {
    const tool = detail.split(/\s+/)[0];
    const rest = detail.slice(tool.length).trim();
    step.kind = "tool"; step.tool = tool; step.phase = "result";
    step.status = /error|fail|失败|拒绝|denied|exception/i.test(rest) ? "error" : "ok";
    step.result = rest;
  } else if (type === "model.completed") {
    step.kind = "model";
  } else if (type === "session.ended") {
    step.kind = "ended"; step.disposition = detail;
  } else {
    step.kind = "info";
  }
  return step;
}

function writeRun(key, data) {
  try {
    mkdirSync(RUNS_DIR, { recursive: true });
    writeFileSync(runPath(key), JSON.stringify(data, null, 2));
  } catch (e) {
    console.error("[gewu-proxy] writeRun failed:", e?.message);
  }
}

function readRun(key) {
  try { return JSON.parse(readFileSync(runPath(key), "utf8")); } catch { return null; }
}

function listRuns() {
  try {
    return readdirSync(RUNS_DIR)
      .filter((f) => f.endsWith(".json"))
      .map((f) => {
        try {
          const d = JSON.parse(readFileSync(join(RUNS_DIR, f), "utf8"));
          return {
            key: d.key, agent: d.agent, message: d.message,
            startedAt: d.startedAt, endedAt: d.endedAt, status: d.status,
            stepCount: Array.isArray(d.steps) ? d.steps.length : 0,
          };
        } catch { return null; }
      })
      .filter(Boolean)
      .sort((a, b) => (b.startedAt || 0) - (a.startedAt || 0));
  } catch { return []; }
}

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

  if (p === "/api/runs" && req.method === "GET") {
    return sendJSON(res, 200, { runs: listRuns() });
  }
  if (p === "/api/run" && req.method === "GET") {
    const key = url.searchParams.get("key");
    if (!key) return sendJSON(res, 400, { error: "missing key" });
    const data = readRun(key);
    if (!data) return sendJSON(res, 404, { error: "run not found" });
    return sendJSON(res, 200, data);
  }

  if (p === "/api/chat" && req.method === "POST") {
    let raw = "";
    for await (const chunk of req) raw += chunk;
    let payload;
    try { payload = JSON.parse(raw); } catch { return sendJSON(res, 400, { error: "invalid json" }); }
    const agent = String(payload.agent || "gewu-director");
    const message = String(payload.message || "");
    if (!message.trim()) return sendJSON(res, 400, { error: "empty message" });

    // 会话 key：续跑时复用前端传来的 sessionKey，否则新生成。
    const runKey = String(payload.sessionKey || `agent:${agent}:${randomUUID()}`);

    res.writeHead(200, {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    });
    const send = (obj) => res.write(`data: ${JSON.stringify(obj)}\n\n`);

    // 内存中的本次运行记录，逐步写盘（A3 落盘核心：超时/关页也能复盘已完成步骤）
    const run = {
      key: runKey, agent, message, startedAt: Date.now(), endedAt: null,
      status: "running", steps: [], raw: [],
    };
    writeRun(runKey, run);
    send({ type: "start", agent, runKey, ts: run.startedAt });

    // 通过官方 CLI 桥接 Gateway；单次 agent 轮次超时默认 1500s。
    const timeoutSec = String(Number(process.env.GEWU_AGENT_TIMEOUT) || 1500);
    const agentArgs = ["agent", "--agent", agent, "--session-key", runKey, "-m", message, "--timeout", timeoutSec];
    const tailArgs = ["sessions", "tail", "--session-key", runKey, "--follow", "--tail", "200"];

    let agentChild, tailChild;

    // 把一条轨迹事件落盘并实时推给前端
    const finishStep = (step) => {
      let sent;
      if (step.kind === "tool" && step.phase === "result") {
        // 回填到最近一个同工具、仍在运行的步骤
        let realIdx = -1;
        for (let i = run.steps.length - 1; i >= 0; i--) {
          const s = run.steps[i];
          if (s.kind === "tool" && s.tool === step.tool && s.status === "running") { realIdx = i; break; }
        }
        if (realIdx >= 0) {
          run.steps[realIdx].status = step.status;
          run.steps[realIdx].result = step.result;
          run.steps[realIdx].endedTs = step.ts;
          sent = run.steps[realIdx];
        } else {
          const merged = { ...step, startedTs: step.ts };
          run.steps.push(merged);
          sent = merged;
        }
      } else {
        run.steps.push(step);
        sent = step;
      }
      if (step.kind === "ended") run.status = step.disposition || run.status;
      run.raw.push(step.raw);
      writeRun(runKey, run);
      send({ type: "step", step: sent });
    };

    const stopTail = () => { try { tailChild && !tailChild.killed && tailChild.kill(); } catch {} };

    // 把网关侧的低层错误翻译成人话：这些是"系统状态"，不是"任务失败"。
    function friendly(t) {
      const s = String(t || "");
      if (/has not completed startup inspection/i.test(s))
        return "⏳ 格物正在做启动自检（网关重启后约 1–2 分钟），请稍后重试。";
      if (/Request timed out|timeout/i.test(s))
        return "⏱ 本轮超时未返回结果。已完成步骤已保留在「执行进度」，可缩小任务范围后点「续跑」。";
      if (/failed to acquire gateway state ownership|gateway is not running|ECONNREFUSED/i.test(s))
        return "🔌 未连上 OpenClaw Gateway。请先在终端启动：openclaw gateway run --force";
      return s.slice(0, 500);
    }

    try {
      // 先起 tail（follow），再起 agent，避免漏掉 session.started 等早期事件。
      // 注意：sessions tail 的轨迹可能写到 stdout 或 stderr，两者都解析。
      tailChild = spawn(OPENCLAW.cmd, [...OPENCLAW.prefix, ...tailArgs], {
        shell: OPENCLAW.shell, env: { ...process.env },
      });
      const onTailData = (d) => {
        for (const ln of d.toString().split("\n")) {
          const t = ln.trim();
          if (t) finishStep(parseTailLine(t));
        }
      };
      tailChild.stdout.on("data", onTailData);
      tailChild.stderr.on("data", onTailData);
      tailChild.on("error", () => {});

      agentChild = spawn(OPENCLAW.cmd, [...OPENCLAW.prefix, ...agentArgs], {
        shell: OPENCLAW.shell, env: { ...process.env },
      });
    } catch (e) {
      send({ type: "error", text: "无法启动 openclaw：" + (e?.message || e) });
      return res.end();
    }

    let errored = false;
    agentChild.stdout.on("data", (d) => send({ type: "delta", text: d.toString() }));
    agentChild.stderr.on("data", (d) => {
      const t = d.toString();
      if (/error|拒绝|fail|denied|exception/i.test(t)) {
        errored = true;
        send({ type: "error", text: friendly(t) });
      }
    });
    agentChild.on("close", (code) => {
      stopTail();
      if (run.status === "running") run.status = code === 0 ? "success" : "error";
      run.endedAt = Date.now();
      writeRun(runKey, run);
      if (!errored && code !== 0)
        send({ type: "error", text: `智能体异常退出（code ${code}）。可稍后重试或缩小任务范围。` });
      send({ type: "done", exitCode: code, status: run.status, ts: run.endedAt });
      res.end();
    });
    agentChild.on("error", (e) => {
      stopTail();
      send({ type: "error", text: "桥接失败：" + (e?.message || e) });
      res.end();
    });
    req.on("close", () => {
      try { agentChild.kill(); } catch {}
      stopTail();
      try { run.status = "aborted"; run.endedAt = Date.now(); writeRun(runKey, run); } catch {}
    });
    return;
  }

  return serveStatic(req, res);
});

server.listen(PORT, () => {
  console.log(`[gewu-proxy] listening on http://localhost:${PORT}`);
  console.log(`[gewu-proxy] gateway=${GATEWAY}  openclaw=${OPENCLAW.cmd} ${OPENCLAW.prefix.join(" ")}`);
  console.log(`[gewu-proxy] agent timeout=${process.env.GEWU_AGENT_TIMEOUT || 1500}s`);
});
