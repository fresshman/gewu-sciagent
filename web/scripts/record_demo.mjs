/**
 * 真自主七阶段演练 + 全程录屏。
 *
 * 用法：
 *   node scripts/record_demo.mjs --prompt scripts/demo_prompt.txt \
 *        --out "F:/.../output/scratch/demo_video" --max-minutes 100
 *
 * 产物：
 *   <out>/raw_<时间戳>.webm   1920×1080 全程录屏（后期 ffmpeg 加速）
 *   <out>/console.log         脚本日志
 *
 * 判定结束：SSE done 后前端 isStreaming 变 false，发送按钮恢复可点。
 * 诚实原则：director 中途失败/超时也照常落盘视频与日志，不重试造假。
 */
import { chromium } from "playwright-core";
import fs from "node:fs";
import path from "node:path";

const args = process.argv.slice(2);
function argOf(name, def) {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? args[i + 1] : def;
}
const PROMPT_FILE = argOf("--prompt", new URL("./demo_prompt.txt", import.meta.url).pathname.replace(/^\/([A-Z]:)/, "$1"));
const OUT_DIR = argOf("--out", path.resolve("..", "output", "scratch", "demo_video"));
const MAX_MINUTES = Number(argOf("--max-minutes", "100"));
const BASE_URL = argOf("--base-url", "http://127.0.0.1:3112");

const prompt = fs.readFileSync(PROMPT_FILE, "utf-8").trim();
fs.mkdirSync(OUT_DIR, { recursive: true });
const logLines = [];
function log(msg) {
  const line = `[${new Date().toISOString()}] ${msg}`;
  console.log(line);
  logLines.push(line);
}

async function main() {
  const startedAt = new Date();
  log(`启动录制：prompt=${PROMPT_FILE} out=${OUT_DIR} 上限=${MAX_MINUTES}min`);

  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const videoDir = fs.mkdtempSync(path.join(process.env.TEMP, "gewu_rec_"));
  const ctx = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    recordVideo: { dir: videoDir, size: { width: 1920, height: 1080 } },
    locale: "zh-CN",
  });
  const page = await ctx.newPage();
  page.setDefaultTimeout(30000);

  await page.goto(BASE_URL + "/", { waitUntil: "domcontentloaded" });
  await page.waitForSelector(".app", { timeout: 20000 });
  await page.waitForTimeout(2500); // 等数据加载与首屏动画

  // 确认当前 agent 是 director（格物·主编）；不是就点顶栏切换。
  const agentBadge = await page.textContent(".topbar").catch(() => null);
  log(`顶栏内容片段：${String(agentBadge).slice(0, 120)}`);
  if (!String(agentBadge).includes("主编")) {
    await page.click(".topbar [class*=agent]");
    await page.waitForTimeout(600);
    const item = page.locator("text=格物·主编").first();
    await item.click();
    await page.waitForTimeout(800);
  }

  // 发送指令
  await page.fill(".composer__input", prompt);
  await page.waitForTimeout(400);
  await page.click(".composer__send");
  log("指令已发送，等待一轮完成（判据：/api/runs 最新一条出现 endedAt+status）…");

  // 发送后最新 run 应该就是本轮；每 15s 轮询后端确认结束。
  // 注意：不能拿发送按钮当判据——发送后输入框清空，按钮因空文本恒为 disabled。
  const deadline = Date.now() + MAX_MINUTES * 60_000;
  let finished = false;
  let finalStatus = "";
  let lastSteps = -1;
  while (Date.now() < deadline) {
    await page.waitForTimeout(15_000);
    let top = null;
    try {
      const res = await fetch(BASE_URL + "/api/runs");
      const data = await res.json();
      top = (data.runs || [])[0] || null;
    } catch {
      /* 轮询失败不致命，下轮再试 */
    }
    const mins = ((Date.now() - startedAt.getTime()) / 60000).toFixed(1);
    if (top && top.message && top.message.slice(0, 24) === prompt.slice(0, 24)
        && top.status && top.status !== "running" && top.endedAt) {
      finished = true;
      finalStatus = String(top.status);
      log(`本轮结束：status=${finalStatus} steps=${top.stepCount} 用时 ${mins}min`);
      break;
    }
    const steps = top ? top.stepCount : -1;
    if (steps !== lastSteps) log(`进行中 ${mins}min：步骤数=${steps}`);
    lastSteps = steps;
  }

  if (!finished) log(`警告：达到 ${MAX_MINUTES} 分钟上限，按超时落盘（如实记录，不造假）`);
  else log(`完成状态：${finalStatus}`);

  await page.waitForTimeout(3000); // 收尾帧入片
  await ctx.close(); // 关闭 context 才落盘视频文件
  await browser.close();

  // 移动并重命名视频（临时目录与输出可能跨盘，rename 会抛 EXDEV，用 copy 兜底）
  const videos = fs.readdirSync(videoDir).filter((f) => f.endsWith(".webm"));
  const stamp = startedAt.toISOString().replace(/[:.]/g, "-").slice(0, 19);
  const outVideo = path.join(OUT_DIR, `raw_${stamp}.webm`);
  if (videos.length) {
    const src = path.join(videoDir, videos[0]);
    try {
      fs.renameSync(src, outVideo);
    } catch {
      fs.copyFileSync(src, outVideo);
      fs.rmSync(videoDir, { recursive: true, force: true });
    }
    const sz = fs.statSync(outVideo).size;
    log(`视频已落盘：${outVideo}（${(sz / 1024 / 1024).toFixed(1)} MB）`);
  } else {
    log("错误：未找到视频文件");
  }
  fs.writeFileSync(path.join(OUT_DIR, "console.log"), logLines.join("\n"), "utf-8");
  const wall = ((Date.now() - startedAt.getTime()) / 60000).toFixed(1);
  log(`总耗时 ${wall} 分钟，finished=${finished} status=${finalStatus || "timeout"}`);
  process.exit(finished && finalStatus === "success" ? 0 : 2);
}

main().catch((e) => {
  log(`脚本崩溃：${e.message}`);
  fs.writeFileSync(path.join(OUT_DIR, "console.log"), logLines.join("\n"), "utf-8");
  process.exit(1);
});
