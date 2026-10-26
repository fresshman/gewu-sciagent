#!/usr/bin/env bash
# =============================================================================
#  格物 (Gewu) 一键启动脚本 —— 同时拉起「后端网关」与「前端 Web」
#
#  用法（在 Git Bash 中，于仓库根目录执行）：
#      bash start-gewu.sh
#   或  chmod +x start-gewu.sh && ./start-gewu.sh
#
#  设计要点（专治本机坑）：
#  - 全部用「绝对路径」调用 Node 26，绕过 Git Bash 默认把 openclaw 解析到 Node 22 的 shim，
#    避免 `cannot import` / sqlite 告警 / 对话一发就失败。
#  - 给 web 代理显式设置 OPENCLAW_MJS，确保 CLI 桥接（openclaw agent）也用 Node 26 + 正确 openclaw。
#  - 日志写到 .aris/logs/（已在 .gitignore 中，不会入库）。
#  - Ctrl+C 会按进程树杀掉网关与前端（含 vite / proxy 子进程）。
# =============================================================================

set -uo pipefail

# ── 绝对路径（本机实测有效）──────────────────────────────────────────────
NODE26="/c/Users/SHJ/tools/node26/node-v26.9.0-win-x64/node.exe"
OPENCLAW_MJS="/c/Users/SHJ/.npm-global/node_modules/openclaw/openclaw.mjs"
NPM26="/c/Users/SHJ/tools/node26/node-v26.9.0-win-x64/node_modules/npm/bin/npm-cli.js"
NODE26_BIN="/c/Users/SHJ/tools/node26/node-v26.9.0-win-x64"

# ── 仓库根目录（无论在哪里执行脚本都正确）────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB_DIR="$SCRIPT_DIR/web"
LOG_DIR="$SCRIPT_DIR/.aris/logs"
mkdir -p "$LOG_DIR"

# 让 web 代理内部调用的 `npm root -g` 也解析到 Node 26 的全局目录（双保险）
export PATH="$NODE26_BIN:$PATH"
# 直接告诉代理用哪个 openclaw（web/proxy/server.mjs 读取此变量，优先级最高）
export OPENCLAW_MJS

GATEWAY_URL="http://127.0.0.1:18789"
GATEWAY_LOG="$LOG_DIR/gateway.log"
WEB_LOG="$LOG_DIR/web.log"
NPM_LOG="$LOG_DIR/npm-install.log"

GW_PID=""
WEB_PID=""

# ── 清理：按进程树杀掉子进程 ─────────────────────────────────────────────
cleanup() {
  echo
  echo "[start-gewu] 收到停止信号，正在关闭子进程..."
  for pid in "$GW_PID" "$WEB_PID"; do
    [ -n "$pid" ] || continue
    # taskkill /T 杀整棵树（含 vite / proxy 子进程）；失败则退回 kill -9
    taskkill //PID "$pid" //T //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null
  done
  echo "[start-gewu] 已停止。日志见 $LOG_DIR"
  exit 0
}
trap cleanup INT TERM EXIT

# ── 网关健康检查 ─────────────────────────────────────────────────────────
gateway_up() {
  "$NODE26" -e "fetch('$GATEWAY_URL/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))" >/dev/null 2>&1
}

# ── 1) 启动后端：OpenClaw 网关 ────────────────────────────────────────────
if gateway_up; then
  echo "[start-gewu] 网关已在运行 ($GATEWAY_URL)，跳过启动。"
else
  echo "[start-gewu] 启动后端网关 (OpenClaw Gateway) → 日志 $GATEWAY_LOG"
  "$NODE26" "$OPENCLAW_MJS" gateway run --force > "$GATEWAY_LOG" 2>&1 &
  GW_PID=$!

  echo -n "[start-gewu] 等待网关自检完成（最多约 120s）"
  ready=0
  for _ in $(seq 1 60); do
    if gateway_up; then ready=1; echo " 就绪 ✓"; break; fi
    sleep 2; echo -n "."
  done
  if [ "$ready" -eq 0 ]; then
    echo
    echo "[start-gewu] ⚠️ 网关未在预期时间内就绪，继续启动前端；可用以下命令排查："
    echo "    tail -n 50 $GATEWAY_LOG"
    echo "    $NODE26 $OPENCLAW_MJS gateway probe"
  fi
fi

# ── 2) 首次/依赖缺失时安装前端依赖 ───────────────────────────────────────
if [ ! -d "$WEB_DIR/node_modules" ]; then
  echo "[start-gewu] 未检测到 web/node_modules，执行 npm install → 日志 $NPM_LOG"
  ( cd "$WEB_DIR" && "$NODE26" "$NPM26" install ) > "$NPM_LOG" 2>&1 \
    && echo "[start-gewu] 前端依赖安装完成 ✓" \
    || echo "[start-gewu] ⚠️ npm install 失败，详见 $NPM_LOG（node_modules 可能已部分就绪，仍尝试启动）"
fi

# ── 3) 启动前端：Vite(:5173) + 本地代理(:3000) ───────────────────────────
echo "[start-gewu] 启动前端 (web/scripts/dev.mjs) → 日志 $WEB_LOG"
( cd "$WEB_DIR" && "$NODE26" "$WEB_DIR/scripts/dev.mjs" ) > "$WEB_LOG" 2>&1 &
WEB_PID=$!

# ── 完成提示 ─────────────────────────────────────────────────────────────
echo
echo "============================================================"
echo "  格物 (Gewu) 已启动"
echo "  后端网关 : $GATEWAY_URL"
echo "  前端地址 : http://localhost:5173   (开发态 Vite)"
echo "             http://localhost:3000   (生产态代理 / 同源 API)"
echo "  日志目录 : $LOG_DIR"
echo "  停止方式 : 在此窗口按 Ctrl+C（会一并关闭前后端）"
echo "============================================================"
echo "[start-gewu] 按 Ctrl+C 停止；脚本保持前台运行以接收停止信号..."

# 保持前台，等待任一子进程结束或信号
wait 2>/dev/null
