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
import { existsSync, mkdirSync, writeFileSync, readdirSync, readFileSync, unlinkSync, openSync, closeSync, fstatSync, readSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { tmpdir } from "node:os";
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

// ============================================================================
// 长任务 RunManager —— ①后台化 + ③服务端预算闸门
//
// ① 后台化：agent CLI 以 detached 方式 spawn、stdout 落 <key>.out 文件，
//    SSE 只是「观察窗」：客户端断开/关页不再杀任务；回复文本增量持久化进
//    run 记录（此前 reply 从不落盘，超时=全丢）。重连走 GET /api/run-stream。
// ③ 预算闸门：工具调用数 + 墙钟时间双阈值。软阈值打「预警」步骤；硬阈值
//    触发时——OpenClaw 2026.10.5 实测**无中断网关进行中会话的 CLI 动词**
//    （sessions 只有 archive/compact/delete），杀 CLI 杀不掉网关轮次、只会
//    丢失回复，因此硬触发不杀进程，而是：标记 budget.exceeded + 服务端强制
//    回写 repro_request handoff 为 over_budget（复现类指令可从 message 抽出
//    落盘路径）。真正的终局兜底仍是网关 timeoutSeconds=1800。
// 已知边界：代理重启会丢失内存态（detached 子进程仍在跑、.out 仍在写，但
//    tail/回复不再被采集）→ 启动时把 status=running 的落盘记录标为
//    interrupted_by_restart，杜绝「永久 running」假象。
// ============================================================================
const activeRuns = new Map(); // runKey -> entry
// 阈值默认值来自实测：一轮 397B 长任务常见 15–25 分钟 / 20–30 次工具调用。
// 注意：工具计数依赖 `sessions tail`，而它只在会话结束时一次性吐出（实测），
// 所以**墙钟是主闸门**，工具数只在轨迹到达时才起作用。
const BUDGET = {
  warnTools: Number(process.env.GEWU_RUN_BUDGET_WARN_TOOLS) || 20,
  hardTools: Number(process.env.GEWU_RUN_BUDGET_TOOLS) || 30,
  warnMs: (Number(process.env.GEWU_RUN_BUDGET_WARN_MINUTES) || 18) * 60_000,
  hardMs: (Number(process.env.GEWU_RUN_BUDGET_MINUTES) || 25) * 60_000,
  slowGapMs: Number(process.env.GEWU_RUN_SLOW_GAP_MS) || 120_000,
};
const nowZ = () => new Date().toISOString().slice(11, 20) + "Z";

// 预算硬触发时，服务端代写复现请求 handoff：从指令文本抽出落盘路径。
function guardReproHandoff(run, noteText) {
  try {
    const m = String(run.message || "").match(/复现请求】[\s\S]*?落盘于：\r?\n(.+\.json)/);
    if (!m) return null;
    const p = m[1].trim();
    if (!existsSync(p)) return null;
    const j = JSON.parse(readFileSync(p, "utf8"));
    if (j.type !== "repro_request" || !["queued", "running"].includes(j.status)) return null;
    j.status = "over_budget";
    j.updated_at = new Date().toISOString();
    j.note = (j.note ? j.note + "\n" : "") + noteText;
    writeFileSync(p, JSON.stringify(j, null, 2), "utf8");
    return p;
  } catch { return null; }
}

// Windows：openclaw CLI 会自我 re-exec（--stack-size=8192），只 kill 父 pid 会漏掉孙进程 → 树杀
function killTree(child) {
  if (!child || !child.pid) return;
  if (process.platform === "win32") {
    try { spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true, stdio: "ignore" }); return; } catch {}
  }
  try { child.kill(); } catch {}
}

// startRun 半途抛错时的兜底清理：不留孤儿 tail / 计时器
function cleanupEntry(entry) {
  if (!entry) return;
  for (const t of ["outTimer", "flushTimer", "watchdog", "endGrace"]) clearInterval(entry[t]);
  killTree(entry.tailChild);
  for (const fd of [entry.outFd, entry.errFd]) { try { if (fd !== undefined) closeSync(fd); } catch {} }
  try { if (entry.promptFile) unlinkSync(entry.promptFile); } catch {}
}

function startRun({ agent, message, runKey }) {
  const run = {
    key: runKey, agent, message,
    startedAt: Date.now(), endedAt: null,
    status: "running", steps: [], raw: [], reply: "", budget: null,
  };
  mkdirSync(RUNS_DIR, { recursive: true });
  const entry = {
    run, listeners: new Set(), toolCalls: 0,
    warnFired: false, hardFired: false, slowWarned: true,
    lastEventTs: Date.now(), finalized: false,
    replyDirty: false, outPos: 0, seenRaw: new Set(),
  };
  activeRuns.set(runKey, entry);
  writeRun(runKey, run);

  const fanout = (obj) => {
    for (const l of entry.listeners) {
      try { if (!l.writableEnded) l.write(`data: ${JSON.stringify(obj)}\n\n`); } catch {}
    }
  };
  const touch = () => { entry.lastEventTs = Date.now(); entry.slowWarned = false; };

  // 步骤入册（含 tool.result 回填合并）+ 广播
  const addStep = (step) => {
    if (step.raw && entry.seenRaw.has(step.raw)) return; // tail 重连回放去重
    if (step.raw) entry.seenRaw.add(step.raw);
    let sent = step;
    if (step.kind === "tool" && step.phase === "result") {
      let idx = -1;
      for (let i = run.steps.length - 1; i >= 0; i--) {
        const s = run.steps[i];
        if (s.kind === "tool" && s.tool === step.tool && s.status === "running") { idx = i; break; }
      }
      if (idx >= 0) {
        run.steps[idx].status = step.status;
        run.steps[idx].result = step.result;
        run.steps[idx].endedTs = step.ts;
        sent = run.steps[idx];
      } else {
        run.steps.push({ ...step, startedTs: step.ts });
      }
    } else {
      run.steps.push(step);
    }
    if (step.kind === "tool" && step.phase === "call") entry.toolCalls++;
    if (step.kind === "ended") {
      run.status = step.disposition || run.status;
      finishAfterTurn(run.status === "success" ? 0 : 1);
    }
    run.raw.push(step.raw);
    touch();
    writeRun(runKey, run);
    fanout({ type: "step", step: sent });
  };

  // fd 尾读（.out 回复 / .err 报错）：detached 子进程没有 stdio 流，只能按位置读文件
  entry.errPos = 0;
  const readTail = (fd, posKey) => {
    try {
      const size = fstatSync(fd).size;
      if (size <= entry[posKey]) return "";
      const buf = Buffer.alloc(size - entry[posKey]);
      const rd = readSync(fd, buf, 0, buf.length, entry[posKey]);
      entry[posKey] += rd;
      return rd > 0 ? buf.toString("utf8", 0, rd) : "";
    } catch { return ""; }
  };

  const stopTail = () => { killTree(entry.tailChild); };

  // 回复尾巴捞取：agent CLI 是在轮次结束时一次性打印回复的，最后一次捞取必须
  // 同时广播给观察窗，否则前端气泡只剩空白（落盘有、屏幕没有）。
  const sweepOutIntoReply = () => {
    const rest = readTail(entry.outFd, "outPos");
    if (!rest) return;
    run.reply += rest;
    entry.replyDirty = true;
    touch();
    fanout({ type: "delta", text: rest });
  };

  const cleanup = () => {
    if (entry.cleaned) return;
    entry.cleaned = true;
    clearInterval(entry.outTimer); clearInterval(entry.flushTimer); clearTimeout(entry.cleanupTimer);
    sweepOutIntoReply();
    const restErr = readTail(entry.errFd, "errPos");
    if (restErr.trim()) run.raw.push("[stderr] " + restErr.trim());
    writeRun(runKey, run);
    try { closeSync(entry.outFd); closeSync(entry.errFd); } catch {}
    try { unlinkSync(entry.promptFile); } catch {}
    stopTail();
  };

  const finalize = (code) => {
    if (entry.finalized) return;
    entry.finalized = true;
    clearInterval(entry.watchdog); clearInterval(entry.endGrace);
    // OpenClaw 2026.10.5 实测：`sessions tail --follow` 并不流式，整段轨迹是在会话结束时
    // 一次性吐出的，而 agent CLI 退出几乎同时发生 —— 立刻杀 tail 会把刚拿到的步骤丢掉。
    // 所以先落终态 + 通知观察窗，再给 tail 3s 宽限读完 burst，之后才做资源清理。
    sweepOutIntoReply();
    if (run.status === "running") run.status = code === 0 ? "success" : "error";
    run.endedAt = Date.now();
    writeRun(runKey, run);
    fanout({ type: "done", exitCode: code, status: run.status, ts: run.endedAt });
    for (const l of entry.listeners) { try { l.end(); } catch {} }
    entry.listeners.clear();
    activeRuns.delete(runKey);
    entry.cleanupTimer = setTimeout(cleanup, 3_000);
  };

  // 网关轮次已结束（tail 报 session.ended）：正常情况 CLI 随即自行退出、由 close 收口；
  // 若它挂住或 exit 事件丢失，这里探测退出码，最长 20s 后由服务端收口，
  // 保证 endedAt / tail 清理 / 计时器清理一定发生（否则预算看门狗会在成功 run 上误触发）。
  const finishAfterTurn = (fallbackCode) => {
    if (entry.finalized || entry.endGrace) return;
    const probeAt = Date.now();
    entry.endGrace = setInterval(() => {
      if (entry.finalized) { clearInterval(entry.endGrace); return; }
      const code = entry.agentChild && entry.agentChild.exitCode;
      if (code !== null && code !== undefined) { finalize(code); return; }
      if (Date.now() - probeAt > 20_000) finalize(fallbackCode);
    }, 2_000);
  };

  // tail 子进程：轨迹事件 → 步骤。
  // 坑：`sessions tail` 对还不存在的 session key 会立即 exit 1（Session not found），
  // 而 key 是 agent CLI 起来之后才创建的 → 首次 attach 是一场竞速。失败就重试，
  // 重连时 --tail 200 会回放历史，配合 seenRaw 去重：既不丢步骤也不重复。
  const tailArgs = ["sessions", "tail", "--session-key", runKey, "--follow", "--tail", "200"];
  const onTailData = (d) => {
    for (const ln of d.toString().split("\n")) {
      const t = ln.trim();
      if (t && !/Session not found/i.test(t)) addStep(parseTailLine(t));
    }
  };
  const startTail = (attempt) => {
    if (entry.finalized) return;
    const child = spawn(OPENCLAW.cmd, [...OPENCLAW.prefix, ...tailArgs], { shell: OPENCLAW.shell, env: { ...process.env } });
    entry.tailChild = child;
    child.stdout.on("data", onTailData);
    child.stderr.on("data", onTailData);
    let settled = false; // 同一个 child 的 error/exit 只重试一次
    const retry = (why, info) => {
      if (settled) return;
      settled = true;
      if (entry.finalized) return; // finalize 主动杀 tail，退出是预期行为
      const msg = `tail attempt#${attempt} ${why}${info ? ": " + info : ""}`;
      run.raw.push(msg);
      console.error("[gewu-proxy]", runKey, msg);
      if (attempt >= 20) {
        addStep({ kind: "info", type: "trace.unavailable", ts: nowZ(),
          detail: "轨迹采集没连上会话（只保留最终回复，中间步骤不可见）",
          raw: `tail give-up after ${attempt + 1} attempts` });
        return;
      }
      setTimeout(() => startTail(attempt + 1), 1_200);
    };
    child.on("error", (e) => retry("spawn-error", e?.message || String(e)));
    child.on("exit", (code, sig) => retry("exit", `code=${code} sig=${sig}`));
  };
  startTail(0);

  // agent 轮次：detached + 输出落文件，脱离 HTTP 生命周期；长中文走 --message-file
  entry.outFd = openSync(join(RUNS_DIR, safeName(runKey) + ".out"), "w+");
  entry.errFd = openSync(join(RUNS_DIR, safeName(runKey) + ".err"), "w+");
  entry.promptFile = join(tmpdir(), `gewu-chat-${randomUUID()}.txt`);
  writeFileSync(entry.promptFile, message, "utf8");
  const timeoutSec = String(Number(process.env.GEWU_AGENT_TIMEOUT) || 3600);
  const agentArgs = ["agent", "--agent", agent, "--session-key", runKey, "--message-file", entry.promptFile, "--timeout", timeoutSec];
  entry.agentChild = spawn(OPENCLAW.cmd, [...OPENCLAW.prefix, ...agentArgs], {
    shell: OPENCLAW.shell, env: { ...process.env },
    detached: true, stdio: ["ignore", entry.outFd, entry.errFd],
  });
  // 收口订阅紧跟 spawn：fd-stdio 下 child.stderr 是 null，任何在其上挂监听的代码
  // 都会同步抛错并跳过这里的订阅，导致 finalize 永不执行（tail/计时器泄漏）。
  entry.agentChild.on("close", (code) => finalize(code ?? 1));
  entry.agentChild.on("error", (e) => {
    fanout({ type: "error", text: "桥接失败：" + (e?.message || e) });
    finalize(1);
  });

  // .out 尾读：回复持久化 + delta 广播；.err 尾读：网关侧报错翻译成人话推给观察窗
  entry.outTimer = setInterval(() => {
    sweepOutIntoReply();
    const errText = readTail(entry.errFd, "errPos");
    if (errText) {
      for (const ln of errText.split("\n")) {
        if (/error|拒绝|fail|denied|exception/i.test(ln)) fanout({ type: "error", text: friendly(ln) });
      }
    }
  }, 700);
  entry.flushTimer = setInterval(() => {
    if (entry.replyDirty) { entry.replyDirty = false; writeRun(runKey, run); }
  }, 2000);

  // 预算/慢轮次看门狗
  entry.watchdog = setInterval(() => {
    if (entry.finalized) return;
    const elapsed = Date.now() - run.startedAt;
    const mins = (elapsed / 60_000).toFixed(1);
    if (!entry.warnFired && (entry.toolCalls >= BUDGET.warnTools || elapsed >= BUDGET.warnMs)) {
      entry.warnFired = true;
      addStep({ kind: "info", type: "budget.warn", ts: nowZ(),
        detail: `预算预警：工具 ${entry.toolCalls} 次 / 用时 ${mins} 分钟（硬阈值 ${BUDGET.hardTools} 次 / ${(BUDGET.hardMs / 60_000).toFixed(1)} 分钟）`,
        raw: `budget.warn tools=${entry.toolCalls} elapsed=${mins}m` });
    }
    if (!entry.hardFired && (entry.toolCalls >= BUDGET.hardTools || elapsed >= BUDGET.hardMs)) {
      entry.hardFired = true;
      run.budget = { exceeded: true, toolCalls: entry.toolCalls, elapsedMs: elapsed, at: new Date().toISOString() };
      const note = `[gewu-proxy 预算闸门] ${new Date().toISOString()} 触发：工具调用 ${entry.toolCalls} 次、用时 ${mins} 分钟。网关轮次不支持外部中断（OpenClaw 2026.10.5 实测），此为服务端强制落盘的终态标记，可据 note 决策续跑或止损。`;
      const hp = guardReproHandoff(run, note);
      addStep({ kind: "info", type: "budget.hard", ts: nowZ(),
        detail: `预算闸门触发：${hp ? "已回写 handoff → over_budget" : "已记录 budget.exceeded（无关联 handoff）"}`,
        raw: note });
      writeRun(runKey, run);
    }
    if (!entry.slowWarned && Date.now() - entry.lastEventTs >= BUDGET.slowGapMs) {
      entry.slowWarned = true;
      const gapS = Math.round((Date.now() - entry.lastEventTs) / 1000);
      addStep({ kind: "info", type: "turn.slow", ts: nowZ(),
        detail: `慢轮次：${gapS}s 无轨迹事件（上下文膨胀或网关排队，后续轮次会更快触顶预算）`,
        raw: `turn.slow gap=${gapS}s` });
    }
  }, 10_000);

  return entry;
}

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".png": "image/png",
  ".pdf": "application/pdf",
  ".woff2": "font/woff2",
  ".map": "application/json",
};

// paperId 直接拼进文件路径，只允许安全字符白名单（且不含 ".."），防路径穿越。
function isSafePaperId(id) {
  return typeof id === "string" && !id.includes("..") && /^[a-zA-Z0-9_\-\u4e00-\u9fff.]+$/.test(id);
}

// 把网关侧的低层错误翻译成人话：这些是"系统状态"，不是"任务失败"。
function friendly(t) {
  const s = String(t || "");
  if (/has not completed startup inspection/i.test(s))
    return "⏳ 格物正在做启动自检（网关重启后约 1–2 分钟），请稍后重试。";
  if (/Request timed out|timeout/i.test(s))
    return "⏱ 本轮超时未返回结果。可缩小任务范围后重试。";
  if (/failed to acquire gateway state ownership|gateway is not running|ECONNREFUSED/i.test(s))
    return "🔌 未连上 OpenClaw Gateway。请先在终端启动：openclaw gateway run --force";
  return s.slice(0, 500);
}

// 一次性 agent 桥接：prompt 写入 UTF-8 临时文件（--message-file），spawn openclaw agent --json，
// 解析 result.payloads 纯文本后以 {type:"delta"} + {type:"done"} 推给 send 并收尾 res。
// 论文问答与划词翻译共用；区别于 /api/chat 的长任务通道（无 tail、无落盘）。
// 用 --json 而非 plain stdout：plain 模式回复尾部会混入「运行时(Runtime)…」元信息，污染展示；
// 且 CLI 本就是结束时一次性打印全文，改 JSON 并不损失实际流式粒度。
function bridgeOneShot({ req, res, send, agent, prompt, runKey, timeoutSec, failLabel }) {
  // argv 传参在 Windows 上有编码/长度双重风险（实测中文偶发 mojibake），必须走文件。
  const promptFile = join(tmpdir(), `gewu-prompt-${randomUUID()}.txt`);
  try {
    writeFileSync(promptFile, prompt, "utf8");
  } catch (e) {
    send({ type: "error", text: "写入临时 prompt 文件失败：" + (e?.message || e) });
    return res.end();
  }
  const dropPrompt = () => { try { unlinkSync(promptFile); } catch {} };

  const agentArgs = ["agent", "--agent", agent, "--session-key", runKey, "--message-file", promptFile, "--timeout", timeoutSec, "--json"];
  let child;
  try {
    child = spawn(OPENCLAW.cmd, [...OPENCLAW.prefix, ...agentArgs], {
      shell: OPENCLAW.shell, env: { ...process.env },
    });
  } catch (e) {
    dropPrompt();
    send({ type: "error", text: "无法启动 openclaw：" + (e?.message || e) });
    return res.end();
  }

  let errored = false;
  let out = "";
  child.stdout.on("data", (d) => { out += d.toString(); });
  child.stderr.on("data", (d) => {
    const t = d.toString();
    if (/error|拒绝|fail|denied|exception/i.test(t)) {
      errored = true;
      send({ type: "error", text: friendly(t) });
    }
  });
  child.on("close", (code) => {
    dropPrompt();
    let parsed = null;
    try { parsed = JSON.parse(out); } catch { /* 输出格式漂移时走下方兜底 */ }
    const payloads = parsed?.result?.payloads;
    if (Array.isArray(payloads)) {
      const text = payloads.map((pp) => pp?.text || "").filter(Boolean).join("\n");
      if (text) send({ type: "delta", text });
    } else if (out.trim() && !errored) {
      send({ type: "delta", text: out }); // 兜底：JSON 解析失败时原样透传
    }
    const status = parsed?.status;
    if (!errored && (code !== 0 || (status && status !== "ok"))) {
      send({ type: "error", text: `${failLabel}失败（${status || "exit " + code}），Gateway 可能未完全启动或自检未完成，请稍后重试。` });
    }
    send({ type: "done", exitCode: code });
    res.end();
  });
  child.on("error", (e) => {
    dropPrompt();
    send({ type: "error", text: friendly(e?.message || e) });
    res.end();
  });
  req.on("close", () => { try { child.kill(); } catch {} });
}

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

  // ── 多项目隔离：项目列表与切换 ──────────────────────────────────────
  const GEWU_CONFIG = join(process.env.HOME || process.env.USERPROFILE, ".gewu", "config.json");

  if (p === "/api/projects" && req.method === "GET") {
    try {
      const txt = await readFile(GEWU_CONFIG, "utf8");
      const config = JSON.parse(txt);
      return sendJSON(res, 200, {
        active_project: config.active_project,
        projects: config.projects || {},
      });
    } catch {
      return sendJSON(res, 200, {
        active_project: null,
        projects: {},
        error: "无法读取 ~/.gewu/config.json",
      });
    }
  }

  if (p === "/api/projects/active" && req.method === "GET") {
    try {
      const txt = await readFile(GEWU_CONFIG, "utf8");
      const config = JSON.parse(txt);
      const activeName = config.active_project;
      const project = config.projects?.[activeName];
      if (!project) {
        return sendJSON(res, 404, { error: "无活跃项目" });
      }
      // 读取 config.json（包含七阶段状态）
      const projectConfigPath = join(project.path, "config.json");
      let projectConfig = {};
      try {
        const configTxt = await readFile(projectConfigPath, "utf8");
        projectConfig = JSON.parse(configTxt);
      } catch {
        // config.json 可能不存在（旧项目）
      }
      return sendJSON(res, 200, {
        project_name: activeName,
        ...project,
        research_question: projectConfig.research_question || "",
        hypothesis: projectConfig.hypothesis || "",
        stages: projectConfig.stages || {},
        metrics: projectConfig.metrics || {},
        outputs: projectConfig.outputs || {},
      });
    } catch (e) {
      return sendJSON(res, 500, { error: "读取活跃项目失败", detail: e.message });
    }
  }

  if (p.startsWith("/api/projects/") && p.endsWith("/switch") && req.method === "POST") {
    const projectName = p.split("/")[3];
    try {
      const txt = await readFile(GEWU_CONFIG, "utf8");
      const config = JSON.parse(txt);
      if (!config.projects[projectName]) {
        return sendJSON(res, 404, { error: `项目 ${projectName} 不存在` });
      }
      config.active_project = projectName;
      writeFileSync(GEWU_CONFIG, JSON.stringify(config, null, 2), "utf8");
      return sendJSON(res, 200, {
        success: true,
        active_project: projectName,
        message: `已切换到项目: ${config.projects[projectName].display_name}`,
      });
    } catch (e) {
      return sendJSON(res, 500, { error: "切换项目失败", detail: e.message });
    }
  }

  // ---- 论文管理 API ----
  // 获取活跃项目的论文列表
  if (p === "/api/papers" && req.method === "GET") {
    try {
      const txt = await readFile(GEWU_CONFIG, "utf8");
      const config = JSON.parse(txt);
      const activeName = config.active_project;
      const project = config.projects?.[activeName];
      if (!project) return sendJSON(res, 404, { error: "无活跃项目" });

      const papersDir = join(project.path, "papers");
      if (!existsSync(papersDir)) {
        return sendJSON(res, 200, { papers: [] });
      }

      const files = readdirSync(papersDir).filter(f => f.endsWith(".pdf"));
      const papers = files.map(f => {
        const metaPath = join(papersDir, f.replace(/\.pdf$/, ".meta.json"));
        let meta = {};
        try { meta = JSON.parse(readFileSync(metaPath, "utf8")); } catch {}
        return {
          id: f.replace(/\.pdf$/, ""),
          filename: f,
          title: meta.title || f.replace(/\.pdf$/, ""),
          authors: meta.authors || "",
          doi: meta.doi || "",
          page_count: meta.page_count || 0,
          added_at: meta.added_at || "",
        };
      });
      return sendJSON(res, 200, { papers });
    } catch (e) {
      return sendJSON(res, 500, { error: "读取论文列表失败", detail: e.message });
    }
  }

  // 上传 PDF
  if (p === "/api/papers/upload" && req.method === "POST") {
    let raw = "";
    for await (const chunk of req) raw += chunk;
    let payload;
    try { payload = JSON.parse(raw); } catch { return sendJSON(res, 400, { error: "invalid json" }); }

    const pdfBase64 = payload.pdf;
    const filename = payload.filename || "unknown.pdf";
    if (!pdfBase64) return sendJSON(res, 400, { error: "missing pdf data" });

    try {
      const txt = await readFile(GEWU_CONFIG, "utf8");
      const config = JSON.parse(txt);
      const project = config.projects?.[config.active_project];
      if (!project) return sendJSON(res, 404, { error: "无活跃项目" });

      const papersDir = join(project.path, "papers");
      mkdirSync(papersDir, { recursive: true });

      // 清理文件名
      const safeName = filename.replace(/[^a-zA-Z0-9_\-\.\u4e00-\u9fff]/g, "_").replace(/_+/g, "_");
      const pdfPath = join(papersDir, safeName);
      const pdfBuffer = Buffer.from(pdfBase64, "base64");
      writeFileSync(pdfPath, pdfBuffer);

      // 提取元信息
      const pdfTool = join(ROOT, "..", "scripts", "pdf_tool.py");
      let meta = {};
      try {
        const out = execFileSync("python", [pdfTool, "metadata", pdfPath], { encoding: "utf8", timeout: 30000 });
        meta = JSON.parse(out);
      } catch { /* 元信息提取失败不阻断上传 */ }

      meta.added_at = new Date().toISOString();
      const metaPath = join(papersDir, safeName.replace(/\.pdf$/, ".meta.json"));
      writeFileSync(metaPath, JSON.stringify(meta, null, 2), "utf8");

      return sendJSON(res, 200, {
        success: true,
        id: safeName.replace(/\.pdf$/, ""),
        filename: safeName,
        ...meta,
      });
    } catch (e) {
      return sendJSON(res, 500, { error: "上传失败", detail: e.message });
    }
  }

  // 获取论文元信息
  if (p.startsWith("/api/papers/") && p.endsWith("/metadata") && req.method === "GET") {
    const paperId = p.split("/")[3];
    if (!isSafePaperId(paperId)) return sendJSON(res, 400, { error: "invalid paperId" });
    try {
      const txt = await readFile(GEWU_CONFIG, "utf8");
      const config = JSON.parse(txt);
      const project = config.projects?.[config.active_project];
      if (!project) return sendJSON(res, 404, { error: "无活跃项目" });

      const metaPath = join(project.path, "papers", `${paperId}.meta.json`);
      if (!existsSync(metaPath)) return sendJSON(res, 404, { error: "论文元信息不存在" });

      const meta = JSON.parse(readFileSync(metaPath, "utf8"));
      return sendJSON(res, 200, meta);
    } catch (e) {
      return sendJSON(res, 500, { error: "读取元信息失败", detail: e.message });
    }
  }

  // 获取论文文本（用于 AI 问答）
  if (p.startsWith("/api/papers/") && p.endsWith("/text") && req.method === "GET") {
    const paperId = p.split("/")[3];
    if (!isSafePaperId(paperId)) return sendJSON(res, 400, { error: "invalid paperId" });
    const maxPages = url.searchParams.get("max_pages") || "0";
    try {
      const txt = await readFile(GEWU_CONFIG, "utf8");
      const config = JSON.parse(txt);
      const project = config.projects?.[config.active_project];
      if (!project) return sendJSON(res, 404, { error: "无活跃项目" });

      const pdfPath = join(project.path, "papers", `${paperId}.pdf`);
      if (!existsSync(pdfPath)) return sendJSON(res, 404, { error: "PDF 文件不存在" });

      const pdfTool = join(ROOT, "..", "scripts", "pdf_tool.py");
      const out = execFileSync("python", [pdfTool, "text", pdfPath, maxPages], { encoding: "utf8", timeout: 60000 });
      const result = JSON.parse(out);
      return sendJSON(res, 200, result);
    } catch (e) {
      return sendJSON(res, 500, { error: "提取文本失败", detail: e.message });
    }
  }

  // 提供 PDF 文件下载/预览
  if (p.startsWith("/api/papers/") && p.endsWith("/file") && req.method === "GET") {
    const paperId = p.split("/")[3];
    if (!isSafePaperId(paperId)) return sendJSON(res, 400, { error: "invalid paperId" });
    try {
      const txt = await readFile(GEWU_CONFIG, "utf8");
      const config = JSON.parse(txt);
      const project = config.projects?.[config.active_project];
      if (!project) return sendJSON(res, 404, { error: "无活跃项目" });

      const pdfPath = join(project.path, "papers", `${paperId}.pdf`);
      if (!existsSync(pdfPath)) return sendJSON(res, 404, { error: "PDF 文件不存在" });

      const pdfBuffer = readFileSync(pdfPath);
      res.writeHead(200, {
        "Content-Type": "application/pdf",
        "Content-Length": pdfBuffer.length,
        "Cache-Control": "public, max-age=3600",
      });
      res.end(pdfBuffer);
      return;
    } catch (e) {
      return sendJSON(res, 500, { error: "读取 PDF 失败", detail: e.message });
    }
  }

  // 阅读笔记：持久化为 <project>/stages/2-literature/notes/<paperId>.md（front-matter + 正文），
  // 与阶段产出同目录，七阶段归档时笔记天然沉淀进「读论文」阶段。
  if (p.startsWith("/api/papers/") && p.endsWith("/notes") && (req.method === "GET" || req.method === "PUT")) {
    const paperId = p.split("/")[3];
    if (!isSafePaperId(paperId)) return sendJSON(res, 400, { error: "invalid paperId" });
    let notesPath;
    try {
      const txt = await readFile(GEWU_CONFIG, "utf8");
      const config = JSON.parse(txt);
      const project = config.projects?.[config.active_project];
      if (!project) return sendJSON(res, 404, { error: "无活跃项目" });
      notesPath = join(project.path, "stages", "2-literature", "notes", `${paperId}.md`);
    } catch (e) {
      return sendJSON(res, 500, { error: "读取项目配置失败", detail: e?.message });
    }

    if (req.method === "GET") {
      if (!existsSync(notesPath)) return sendJSON(res, 200, { notes: "", path: notesPath });
      const raw = readFileSync(notesPath, "utf8");
      let notes = raw;
      let updated = "";
      const m = raw.match(/^---\n([\s\S]*?)\n---\n\n?([\s\S]*)$/);
      if (m) {
        notes = m[2];
        updated = (m[1].match(/updated: (\S+)/) || [])[1] || "";
      }
      return sendJSON(res, 200, { notes, path: notesPath, updated });
    }

    let body = "";
    for await (const chunk of req) body += chunk;
    let payload;
    try { payload = JSON.parse(body); } catch { return sendJSON(res, 400, { error: "invalid json" }); }
    const notes = String(payload.notes ?? "");
    try {
      mkdirSync(dirname(notesPath), { recursive: true });
      const front = `---\npaper: ${paperId}\nupdated: ${new Date().toISOString()}\n---\n\n`;
      writeFileSync(notesPath, front + notes, "utf8");
      return sendJSON(res, 200, { success: true, path: notesPath });
    } catch (e) {
      return sendJSON(res, 500, { error: "保存笔记失败", detail: e?.message });
    }
  }

  // 送复现（跨阶段衔接）：把论文元信息 + 阅读笔记 + 阅读器摘要打包成 handoff 请求，
  // 落盘到 <project>/handoffs/repro_request_*.json，并返回给复现员的指令文本。
  // 阶段激活是守卫式的：只把 pending/todo/缺失的 3-reproduction 置为 active，绝不回退已完成阶段。
  if (p.startsWith("/api/papers/") && p.endsWith("/reproduce") && req.method === "POST") {
    const paperId = p.split("/")[3];
    if (!isSafePaperId(paperId)) return sendJSON(res, 400, { error: "invalid paperId" });
    let body = "";
    for await (const chunk of req) body += chunk;
    let payload;
    try { payload = JSON.parse(body); } catch { return sendJSON(res, 400, { error: "invalid json" }); }
    const readerSummary = String(payload.summary || "").trim();

    let project, projectPath;
    try {
      const txt = await readFile(GEWU_CONFIG, "utf8");
      const config = JSON.parse(txt);
      project = config.projects?.[config.active_project];
      if (!project) return sendJSON(res, 404, { error: "无活跃项目" });
      projectPath = project.path;
    } catch (e) {
      return sendJSON(res, 500, { error: "读取项目配置失败", detail: e?.message });
    }

    const pdfPath = join(projectPath, "papers", `${paperId}.pdf`);
    if (!existsSync(pdfPath)) return sendJSON(res, 404, { error: "PDF 文件不存在" });

    // 论文元信息（缺失不阻断）
    let meta = {};
    try { meta = JSON.parse(readFileSync(join(projectPath, "papers", `${paperId}.meta.json`), "utf8")); } catch {}

    // 阅读笔记（front-matter 剥离后截 4000 字符进 handoff）
    const notesPath = join(projectPath, "stages", "2-literature", "notes", `${paperId}.md`);
    let notesFull = "";
    if (existsSync(notesPath)) {
      const raw = readFileSync(notesPath, "utf8");
      const m = raw.match(/^---\n([\s\S]*?)\n---\n\n?([\s\S]*)$/);
      notesFull = m ? m[2] : raw;
    }
    const notesExcerpt = notesFull.trim().slice(0, 4000);

    // 项目级信息（研究问题等，缺失不阻断）
    let projMeta = {};
    try { projMeta = JSON.parse(readFileSync(join(projectPath, "config.json"), "utf8")); } catch {}

    const now = new Date();
    const ts = now.toISOString().replace(/[:.]/g, "-");
    const handoffDir = join(projectPath, "handoffs");
    const handoffPath = join(handoffDir, `repro_request_${paperId}_${ts}.json`);

    const instruction =
      `【来自文献阅读器的复现请求】\n` +
      `论文《${meta.title || paperId}》已由阅读阶段送来的复现请求，落盘于：\n${handoffPath}\n` +
      `请先读取该 handoff（含论文元信息、PDF 路径、阅读笔记摘录、阅读器摘要），然后：\n` +
      `1) 检查论文代码与数据是否可获取，说明可得性；\n` +
      `2) 制定复现方案并与研究问题对齐（研究问题：${projMeta.research_question || "见项目配置"}）；\n` +
      `3) 执行复现，把**真实跑出的指标**（含数据路径与日志位置）写入 ${join(projectPath, "stages", "3-reproduction")}/ 下；\n` +
      `4) 更新 handoff 文件中的 status 字段（queued → running → done/failed），并在 note 中记录结论。\n` +
      `禁止编造指标；无法复现的部分要明确说明原因。`;

    const handoff = {
      stage: 3,
      stage_name: "复现",
      type: "repro_request",
      status: "queued",
      created_by: "paper-reader",
      created_at: now.toISOString(),
      paper: {
        id: paperId,
        title: meta.title || paperId,
        authors: meta.authors || "",
        doi: meta.doi || "",
        pdf_path: pdfPath,
      },
      notes_path: existsSync(notesPath) ? notesPath : null,
      notes_excerpt: notesExcerpt,
      reader_summary: readerSummary,
      project: {
        name: projMeta.project_name || config.active_project,
        research_question: projMeta.research_question || "",
      },
      outputs: { stage_dir: join(projectPath, "stages", "3-reproduction") },
      instruction,
      next: "复现员（gewu-reproduction）",
      next_input: handoffPath,
    };

    try {
      mkdirSync(handoffDir, { recursive: true });
      writeFileSync(handoffPath, JSON.stringify(handoff, null, 2), "utf8");
    } catch (e) {
      return sendJSON(res, 500, { error: "写入复现 handoff 失败", detail: e?.message });
    }

    // 守卫式阶段激活：仅当 3-reproduction 处于未开始状态时才置 active。
    let stageActivated = false;
    try {
      const projCfgPath = join(projectPath, "config.json");
      const projCfg = JSON.parse(readFileSync(projCfgPath, "utf8"));
      const st = projCfg.stages?.["3-reproduction"];
      if (!st || st.status === "pending" || st.status === "todo" || !st.status) {
        projCfg.stages = projCfg.stages || {};
        projCfg.stages["3-reproduction"] = {
          ...(st || {}),
          status: "active",
          started_at: now.toISOString(),
        };
        writeFileSync(projCfgPath, JSON.stringify(projCfg, null, 2), "utf8");
        stageActivated = true;
      }
    } catch { /* 项目配置缺失/损坏不阻断送复现 */ }

    return sendJSON(res, 200, { success: true, handoffPath, instruction, stageActivated });
  }

  // 论文 AI 问答：提取 PDF 全文 → 组装 prompt → openclaw agent 桥接 Gateway（书生）→ SSE 流式回传。
  // 一次性问答：不开 sessions tail、不落盘，stdout 增量直接透传。
  if (p === "/api/papers/ai" && req.method === "POST") {
    let raw = "";
    for await (const chunk of req) raw += chunk;
    let payload;
    try { payload = JSON.parse(raw); } catch { return sendJSON(res, 400, { error: "invalid json" }); }
    const paperId = String(payload.paperId || "");
    const mode = payload.mode === "summary" ? "summary" : "qa";
    const question = String(payload.question || "").trim();
    if (!isSafePaperId(paperId)) return sendJSON(res, 400, { error: "invalid paperId" });
    if (mode === "qa" && !question) return sendJSON(res, 400, { error: "empty question" });

    // 全文提取在 SSE 之前同步完成：此处失败走普通 JSON，前端能明确区分"提取失败"与"AI 失败"。
    let paperText = "";
    let paperTitle = "";
    try {
      const txt = await readFile(GEWU_CONFIG, "utf8");
      const config = JSON.parse(txt);
      const project = config.projects?.[config.active_project];
      if (!project) return sendJSON(res, 404, { error: "无活跃项目" });
      const pdfPath = join(project.path, "papers", `${paperId}.pdf`);
      if (!existsSync(pdfPath)) return sendJSON(res, 404, { error: "PDF 文件不存在" });
      try {
        const metaRaw = JSON.parse(readFileSync(join(project.path, "papers", `${paperId}.meta.json`), "utf8"));
        paperTitle = metaRaw.title || "";
      } catch { /* 元信息缺失不阻断问答 */ }
      const pdfTool = join(ROOT, "..", "scripts", "pdf_tool.py");
      const out = execFileSync("python", [pdfTool, "text", pdfPath, "0"], { encoding: "utf8", timeout: 60000 });
      paperText = JSON.parse(out).text || "";
    } catch (e) {
      return sendJSON(res, 500, { error: "提取论文文本失败", detail: e?.message });
    }
    if (!paperText.trim()) return sendJSON(res, 422, { error: "该 PDF 无可提取文本（可能是扫描版）" });

    // 截断后进上下文：论文全文可能很长，超长论文取前段已足够回答概览类问题。
    const MAX_CHARS = Number(process.env.GEWU_PAPER_MAX_CHARS) || 24000;
    if (paperText.length > MAX_CHARS) paperText = paperText.slice(0, MAX_CHARS) + "\n…(后文省略)";

    const title = paperTitle || paperId;
    const prompt = mode === "summary"
      ? `请基于以下论文《${title}》的内容，生成结构化中文摘要，分「研究问题 / 方法 / 主要结果 / 结论 / 局限」五部分，各部分 1-3 句话。只使用论文中的信息，论文未提及的不要编造。\n\n【论文内容】\n${paperText}`
      : `你是论文阅读助手。请仅基于以下论文《${title}》的内容回答用户问题；论文中找不到答案时明确说「论文中未提及」，不要编造。\n\n【问题】\n${question}\n\n【论文内容】\n${paperText}`;

    res.writeHead(200, {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    });
    const send = (obj) => res.write(`data: ${JSON.stringify(obj)}\n\n`);
    send({ type: "start", paperId, mode, chars: paperText.length });

    const agent = String(payload.agent || "gewu-ideation");
    const timeoutSec = String(Number(process.env.GEWU_PAPER_TIMEOUT) || 300);
    bridgeOneShot({
      req, res, send,
      agent,
      prompt,
      runKey: `paper:${paperId}:${randomUUID()}`,
      timeoutSec,
      failLabel: "问答",
    });
    return;
  }

  // 划词/段落翻译：把选中片段交书生翻译，SSE 流式回传（不依赖论文全文，秒级启动）。
  if (p === "/api/translate" && req.method === "POST") {
    let raw = "";
    for await (const chunk of req) raw += chunk;
    let payload;
    try { payload = JSON.parse(raw); } catch { return sendJSON(res, 400, { error: "invalid json" }); }
    const text = String(payload.text || "").trim();
    if (!text) return sendJSON(res, 400, { error: "empty text" });
    if (text.length > 2000) return sendJSON(res, 413, { error: "选中文本过长（>2000 字符），请缩小选择范围" });

    const prompt =
      `你是学术文献翻译引擎。请把下面这段论文原文翻译成流畅、准确的中文。\n` +
      `要求：专业术语首次出现时用「中文（English）」形式括注；保持句式简洁；只输出译文本身，不要解释、不要加引号。\n\n【原文】\n${text}`;

    res.writeHead(200, {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    });
    const send = (obj) => res.write(`data: ${JSON.stringify(obj)}\n\n`);
    send({ type: "start", chars: text.length });
    bridgeOneShot({
      req, res, send,
      agent: "gewu-ideation",
      prompt,
      runKey: `translate:${randomUUID()}`,
      timeoutSec: String(Number(process.env.GEWU_TRANSLATE_TIMEOUT) || 120),
      failLabel: "翻译",
    });
    return;
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
    const send = (obj) => { try { res.write(`data: ${JSON.stringify(obj)}\n\n`); } catch {} };

    // 同一 key 已有在跑的 run：不重复开轮次，直接接入回放 + 实时轨迹。
    const existing = activeRuns.get(runKey);
    if (existing) {
      send({ type: "start", agent: existing.run.agent, runKey, ts: existing.run.startedAt, attached: true });
      for (const s of existing.run.steps) send({ type: "step", step: s });
      if (existing.run.reply) send({ type: "delta", text: existing.run.reply });
      send({ type: "error", text: "该会话仍在运行，已接入实时轨迹；请等本轮结束（或看磁盘产出）后再发新指令。" });
      existing.listeners.add(res);
      req.on("close", () => existing.listeners.delete(res));
      return;
    }

    send({ type: "start", agent, runKey, ts: Date.now() });
    let entry;
    try {
      entry = startRun({ agent, message, runKey });
    } catch (e) {
      console.error("[gewu-proxy] startRun failed:", e);
      cleanupEntry(activeRuns.get(runKey));
      activeRuns.delete(runKey);
      const partial = readRun(runKey) || { key: runKey, agent, message, startedAt: Date.now(), steps: [], raw: [], reply: "", budget: null };
      partial.status = "error";
      partial.endedAt = Date.now();
      partial.raw = [...(partial.raw || []), "startRun failed: " + (e?.message || e)];
      writeRun(runKey, partial);
      send({ type: "error", text: "无法启动 openclaw：" + (e?.message || e) });
      return res.end();
    }
    entry.listeners.add(res);
    // 关键差异：客户端断开只是关掉「观察窗」，不再 kill 子进程。
    req.on("close", () => { const en = activeRuns.get(runKey); if (en) en.listeners.delete(res); });
    return;
  }

  // 重连接口：对活跃 run 接实时轨迹；对已结束 run 回放落盘记录（含 reply）。
  if (p === "/api/run-stream" && req.method === "GET") {
    const key = url.searchParams.get("key");
    if (!key) return sendJSON(res, 400, { error: "missing key" });
    const live = activeRuns.get(key);
    const d = live ? live.run : readRun(key);
    if (!d) return sendJSON(res, 404, { error: "run not found" });
    res.writeHead(200, {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    });
    const send = (obj) => { try { res.write(`data: ${JSON.stringify(obj)}\n\n`); } catch {} };
    send({ type: "start", agent: d.agent, runKey: d.key, ts: d.startedAt, replay: true });
    for (const s of d.steps) send({ type: "step", step: s });
    if (d.reply) send({ type: "delta", text: d.reply });
    if (live && !live.finalized) {
      live.listeners.add(res);
      req.on("close", () => live.listeners.delete(res));
    } else {
      send({ type: "done", status: d.status, ts: d.endedAt });
      res.end();
    }
    return;
  }

  return serveStatic(req, res);
});

server.listen(PORT, () => {
  // 代理重启会丢内存态（detached 子进程可能仍在跑，但轨迹/回复无人采集）：
  // 把落盘里仍是 running 的记录标为 interrupted_by_restart，杜绝「永久 running」。
  try {
    for (const r of listRuns()) {
      if (r.status === "running") {
        const d = readRun(r.key);
        if (d) {
          d.status = "interrupted_by_restart";
          d.endedAt = d.endedAt || Date.now();
          d.raw = [...(d.raw || []), `proxy.restart ${new Date().toISOString()}：未完成 run 标记为 interrupted_by_restart（detached 轮次可能仍在网关侧进行）`];
          writeRun(r.key, d);
        }
      }
    }
  } catch {}
  console.log(`[gewu-proxy] listening on http://localhost:${PORT}`);
  console.log(`[gewu-proxy] gateway=${GATEWAY}  openclaw=${OPENCLAW.cmd} ${OPENCLAW.prefix.join(" ")}`);
  console.log(`[gewu-proxy] agent CLI wait timeout=${process.env.GEWU_AGENT_TIMEOUT || 3600}s | budget: tools ${BUDGET.warnTools}/${BUDGET.hardTools} | wall ${(BUDGET.warnMs / 60000).toFixed(1)}/${(BUDGET.hardMs / 60000).toFixed(1)} min | slow gap ${BUDGET.slowGapMs / 1000}s`);
});
