/**
 * 看护录制：接续一场进行中的多轮演练，录到全部七阶段收尾。
 * 结束判据（不靠单轮 run）：subagent_runs 全部 terminal 且静默 ≥ QUIET 分钟
 * 且 /api/runs 无 running 轮次。
 */
import { chromium } from "playwright-core";
import fs from "node:fs";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";

const args = process.argv.slice(2);
function argOf(name, def) {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? args[i + 1] : def;
}
const OUT_DIR = argOf("--out", path.resolve("..", "output", "scratch", "demo_video"));
const MAX_MINUTES = Number(argOf("--max-minutes", "60"));
const QUIET_MINUTES = Number(argOf("--quiet-minutes", "6"));
const BASE_URL = argOf("--base-url", "http://127.0.0.1:3112");
const DB_PATH = argOf(
  "--db",
  "C:/Users/SHJ/.openclaw/state/openclaw.sqlite"
);

fs.mkdirSync(OUT_DIR, { recursive: true });
const logLines = [];
function log(msg) {
  const line = `[${new Date().toISOString()}] ${msg}`;
  console.log(line);
  logLines.push(line);
}

function spawnStatus() {
  try {
    const db = new DatabaseSync(DB_PATH, { readOnly: true });
    const rows = db
      .prepare("select created_at, payload_json from subagent_runs where created_at > ? order by created_at")
      .all(Date.now() - 3 * 3600_000);
    db.close();
    const out = [];
    for (const r of rows) {
      const p = JSON.parse(r.payload_json);
      const ex = p.execution || {};
      out.push({
        label: String(p.label || "?"),
        status: String(ex.status || "?"),
        created: Number(r.created_at),
        ended: ex.endedAt ? Number(ex.endedAt) : null,
      });
    }
    return out;
  } catch (e) {
    log(`DB 轮询失败：${e.message.split("\n")[0]}`);
    return null;
  }
}

async function main() {
  const startedAt = new Date();
  log(`看护录制启动：out=${OUT_DIR} 上限=${MAX_MINUTES}min 静默判据=${QUIET_MINUTES}min`);

  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const videoDir = fs.mkdtempSync(path.join(process.env.TEMP, "gewu_watch_"));
  const ctx = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    recordVideo: { dir: videoDir, size: { width: 1920, height: 1080 } },
    locale: "zh-CN",
  });
  const page = await ctx.newPage();
  page.setDefaultTimeout(30000);
  await page.goto(BASE_URL + "/", { waitUntil: "domcontentloaded" });
  await page.waitForSelector(".app", { timeout: 20000 });
  await page.waitForTimeout(2500);
  log("页面已打开（director 会话历史 + 进行中轮次渲染中）");

  const deadline = Date.now() + MAX_MINUTES * 60_000;
  let finished = false;
  let lastSig = "";
  while (Date.now() < deadline) {
    await page.waitForTimeout(20_000);
    const sp = spawnStatus();
    const mins = ((Date.now() - startedAt.getTime()) / 60000).toFixed(1);
    if (!sp) continue;
    const running = sp.filter((x) => x.status === "running");
    const terminal = sp.filter((x) => x.status === "terminal");
    const lastEnd = Math.max(0, ...terminal.map((x) => x.ended || x.created));
    const quietMs = Date.now() - lastEnd;
    const sig = `${sp.length}:${running.length}`;
    if (sig !== lastSig) {
      log(`${mins}min spawns=${sp.length} running=${running.length} 静默=${(quietMs / 60000).toFixed(1)}min [${sp.map((x) => `${x.label.split(" ").pop()}:${x.status.slice(0, 4)}`).join(" ")}]`);
      lastSig = sig;
    }
    if (running.length === 0 && sp.length >= 7 && quietMs > QUIET_MINUTES * 60_000) {
      finished = true;
      log(`全部 spawn 已 terminal 且静默超 ${QUIET_MINUTES} 分钟——判定演练收尾。`);
      break;
    }
  }
  if (!finished) log(`警告：达 ${MAX_MINUTES} 分钟上限，按超时落盘（如实记录）。`);
  else log("看护录制完成。");

  await page.waitForTimeout(3000);
  await ctx.close();
  await browser.close();

  const videos = fs.readdirSync(videoDir).filter((f) => f.endsWith(".webm"));
  const stamp = startedAt.toISOString().replace(/[:.]/g, "-").slice(0, 19);
  const outVideo = path.join(OUT_DIR, `watch_${stamp}.webm`);
  if (videos.length) {
    const src = path.join(videoDir, videos[0]);
    try {
      fs.renameSync(src, outVideo);
    } catch {
      fs.copyFileSync(src, outVideo);
      fs.rmSync(videoDir, { recursive: true, force: true });
    }
    log(`视频已落盘：${outVideo}（${(fs.statSync(outVideo).size / 1024 / 1024).toFixed(1)} MB）`);
  }
  fs.writeFileSync(path.join(OUT_DIR, "watch_console.log"), logLines.join("\n"), "utf-8");
  process.exit(finished ? 0 : 2);
}

main().catch((e) => {
  log(`脚本崩溃：${e.message}`);
  fs.writeFileSync(path.join(OUT_DIR, "watch_console.log"), logLines.join("\n"), "utf-8");
  process.exit(1);
});
