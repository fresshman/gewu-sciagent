#!/usr/bin/env bash
# =============================================================================
#  格物 (Gewu) 一键启动脚本 —— 同时拉起「后端网关」与「前端 Web」
#
#  用法（在 Git Bash / WSL / macOS 终端里，于任意目录执行）：
#      bash start-gewu.sh              # 启动网关 + 前端
#      bash start-gewu.sh --check      # 只自检环境与端口，不启动任何东西
#      bash start-gewu.sh --gateway    # 只起网关（前端自己跑 npm run dev）
#
#  为什么不写死路径：本机 Node 常是 20/22/24.13 这类被 openclaw 版本闸门拒绝的版本，
#  旧脚本因此硬编码了一个便携 Node——换机器照抄即失效。现在的解析顺序：
#      $GEWU_NODE  →  PATH 上第一个满足闸门的 node  →  明确报错并给出修法
#  openclaw 入口同理：$OPENCLAW_MJS → PATH 上的 openclaw 邻接目录 → 全局/便携 node_modules
#
#  版本闸门（实测来自 openclaw 2026.10.5）：24.16 ≤ v < 25，或 v ≥ 26.1。
#  不满足时网关拒绝启动，且报错落在网关日志里而不是本脚本，所以这里先判掉。
#
#  日志写到 .aris/logs/（已在 .gitignore，不入库）。Ctrl+C 按进程树关闭子进程。
# =============================================================================

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB_DIR="$SCRIPT_DIR/web"
LOG_DIR="$SCRIPT_DIR/.aris/logs"

GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:18789}"
WEB_PORT="${PORT:-3000}"
GATEWAY_LOG="$LOG_DIR/gateway.log"
WEB_LOG="$LOG_DIR/web.log"
NPM_LOG="$LOG_DIR/npm-install.log"

MODE="run"
for arg in "$@"; do
  case "$arg" in
    --check) MODE="check" ;;
    --gateway) MODE="gateway" ;;
    -h|--help) sed -n '2,21p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "[start-gewu] 未知参数：$arg（可用 --check / --gateway）"; exit 2 ;;
  esac
done

# ── 仓库 .env（若存在）：只补父 shell 没设过的变量，显式 export 的值优先 ──────
if [ -f "$SCRIPT_DIR/.env" ]; then
  while IFS= read -r line; do
    case "$line" in ''|\#*|=*) continue ;; esac
    key="${line%%=*}"
    val="${line#*=}"
    key="$(printf '%s' "$key" | tr -d ' \t\r')"
    val="${val%$'\r'}"
    val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
    case "$key" in ''|[0-9]*|*[!A-Za-z0-9_]*) continue ;; esac
    [ -n "${!key:-}" ] || export "$key=$val"
  done < "$SCRIPT_DIR/.env"
fi

# ── Node 解析 + 版本闸门 ───────────────────────────────────────────────────
node_ok() {  # $1 = 候选 node 路径；满足 openclaw 闸门返回 0
  # 先按文件名过滤再执行：GEWU_NODE 指错到 GUI 程序时（本机实测踩到 notepad.exe），
  # 任何一次执行都会弹窗并永久占住脚本，所以连 timeout 包住的探测也要省掉。
  case "$(basename "$1")" in node|node.exe) ;; *) return 1 ;; esac
  local v major minor
  v="$(timeout 10 "$1" -v 2>/dev/null)" || return 1
  case "$v" in v[0-9]*) ;; *) return 1 ;; esac
  v="${v#v}"; major="${v%%.*}"; minor="${v#*.}"; minor="${minor%%.*}"
  case "$major" in ''|*[!0-9]*) return 1 ;; esac
  case "$minor" in ''|*[!0-9]*) minor=0 ;; esac
  [ "$major" -eq 24 ] && [ "$minor" -ge 16 ] && return 0
  [ "$major" -gt 26 ] && return 0
  [ "$major" -eq 26 ] && [ "$minor" -ge 1 ] && return 0
  return 1
}

NODE=""
NODE_WHY=""
node_v() {  # 只在文件名确实是 node 时探测版本，否则给固定提示
  local o
  case "$(basename "$1")" in
    node|node.exe) ;;
    *) printf '非 Node 程序（文件名不是 node）'; return 0 ;;
  esac
  o="$(timeout 10 "$1" -v 2>/dev/null | head -1)"
  case "$o" in v[0-9]*) printf '%s' "$o" ;; *) printf '无版本输出（不是 Node）' ;; esac
}
if [ -n "${GEWU_NODE:-}" ]; then
  if [ -x "$GEWU_NODE" ] || command -v "$GEWU_NODE" >/dev/null 2>&1; then
    if node_ok "$GEWU_NODE"; then
      NODE="$GEWU_NODE"
    else
      NODE_WHY="GEWU_NODE 指向的 $(node_v "$GEWU_NODE") 不满足闸门"
    fi
  else
    NODE_WHY="GEWU_NODE=$GEWU_NODE 不可执行"
  fi
else
  for cand in node "$HOME"/tools/node*/node-*-*/node.exe "$HOME"/.nvm/versions/node/*/bin/node \
              /usr/local/bin/node /opt/homebrew/bin/node; do
    if [ -x "$cand" ] || command -v "$cand" >/dev/null 2>&1; then
      if node_ok "$cand"; then NODE="$cand"; break; fi
      [ -z "$NODE_WHY" ] && NODE_WHY="PATH 上的 node（$(node_v "$cand")）不满足闸门"
    fi
  done
fi

if [ -z "$NODE" ]; then
  echo "[start-gewu] ✗ 找不到满足 openclaw 闸门的 Node（24.16 ≤ v < 25，或 v ≥ 26.1）"
  echo "             ${NODE_WHY:-未探测到任何 node}"
  echo "             修法：export GEWU_NODE=/path/to/node"
  exit 1
fi

# ── openclaw 入口解析 ──────────────────────────────────────────────────────
NODE_DIR="$(cd "$(dirname "$(command -v "$NODE" 2>/dev/null || echo "$NODE")")" 2>/dev/null && pwd)"
OPENCLAW_JS="${OPENCLAW_MJS:-}"
OPENCLAW_WHY=""
if [ -n "$OPENCLAW_JS" ] && [ ! -f "$OPENCLAW_JS" ]; then
  OPENCLAW_WHY="显式 OPENCLAW_MJS=$OPENCLAW_JS 不存在，已改用自动发现"
  OPENCLAW_JS=""
fi
if [ -z "$OPENCLAW_JS" ] && command -v openclaw >/dev/null 2>&1; then
  oc_dir="$(dirname "$(command -v openclaw)")"
  for cand in "$oc_dir/openclaw/openclaw.mjs" "$oc_dir/../lib/node_modules/openclaw/openclaw.mjs" \
              "$oc_dir/../node_modules/openclaw/openclaw.mjs"; do
    [ -f "$cand" ] && OPENCLAW_JS="$(cd "$(dirname "$cand")" && pwd)/$(basename "$cand")" && break
  done
fi
if [ -z "$OPENCLAW_JS" ]; then
  for root in "$NODE_DIR/node_modules/openclaw/.." "$HOME/.npm-global/node_modules" \
              "$HOME/.npm-global/lib/node_modules" /usr/local/lib/node_modules \
              "$("$NODE_DIR/npm" root -g 2>/dev/null || true)"; do
    [ -n "$root" ] && [ -f "$root/openclaw/openclaw.mjs" ] && OPENCLAW_JS="$root/openclaw/openclaw.mjs" && break
  done
fi

CFG="${OPENCLAW_HOME:-$HOME/.openclaw}/openclaw.json"

# ══ --check：只报环境结论，不启动任何进程 ══════════════════════════════════
if [ "$MODE" = "check" ]; then
  echo "── 格物环境自检 ────────────────────────────"
  echo "Node          : $NODE（$("$NODE" -v)）满足 openclaw 闸门 ✓"
  if [ -n "$OPENCLAW_JS" ]; then
    echo "openclaw 入口 : $OPENCLAW_JS"
    [ -n "$OPENCLAW_WHY" ] && echo "                ⚠ $OPENCLAW_WHY"
    echo "openclaw 版本 : $(timeout 20 "$NODE" "$OPENCLAW_JS" --version 2>&1 | head -1)"
  else
    echo "openclaw 入口 : ✗ 未找到 openclaw.mjs → export OPENCLAW_MJS=/path/to/openclaw/openclaw.mjs"
  fi
  if [ -f "$CFG" ]; then
    n_srv="$("$NODE" -e 'const fs=require("fs");const t=fs.readFileSync(process.argv[1],"utf8");console.log((t.match(/"?(?:command)"?\s*:/g)||[]).length)' "$CFG" 2>/dev/null)"
    echo "网关配置      : $CFG（MCP server 条目约 $n_srv 个，应为 10）"
  else
    echo "网关配置      : ✗ $CFG 不存在 → python scripts/bootstrap_openclaw_config.py --write"
  fi
  probe() {  # $1=标签 $2=URL
    if timeout 6 "$NODE" -e "fetch('$2/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))" >/dev/null 2>&1; then
      printf '%s\t运行中\t%s\n' "$1" "$2"
    else
      printf '%s\t未响应（未启动属正常）\t%s\n' "$1" "$2"
    fi
  }
  probe "网关" "$GATEWAY_URL"
  probe "Web 代理" "http://127.0.0.1:$WEB_PORT"
  [ -d "$WEB_DIR/node_modules" ] && echo "前端依赖      : web/node_modules 已安装" \
                                || echo "前端依赖      : 缺失 → 启动时自动 npm install"
  echo "Python        : 本脚本不校验。需含 mcp>=1,<2 / numpy / scipy / pymupdf（requirements.txt）"
  echo "──────────────────────────────────────"
  [ -n "$OPENCLAW_JS" ] && [ -f "$CFG" ] || exit 1
  exit 0
fi

# ── 启动前置检查 ───────────────────────────────────────────────────────────
if [ -z "$OPENCLAW_JS" ]; then
  echo "[start-gewu] ✗ 找不到 openclaw 入口，无法启动网关。"
  echo "             修法：export OPENCLAW_MJS=/path/to/node_modules/openclaw/openclaw.mjs"
  echo "             或先跑 bash start-gewu.sh --check 看完整解析结论"
  exit 1
fi
if [ ! -f "$CFG" ]; then
  echo "[start-gewu] ✗ 网关配置不存在：$CFG"
  echo "             生成：python scripts/bootstrap_openclaw_config.py --write"
  exit 1
fi

GW_PID=""
WEB_PID=""

cleanup() {
  echo
  echo "[start-gewu] 收到停止信号，正在关闭子进程..."
  for pid in "$GW_PID" "$WEB_PID"; do
    [ -n "$pid" ] || continue
    # taskkill /T 杀整棵树（含 vite / proxy 子进程，仅 Windows 有）；失败退回 kill -9
    taskkill //PID "$pid" //T //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null
  done
  echo "[start-gewu] 已停止。日志见 $LOG_DIR"
  exit 0
}
trap cleanup INT TERM EXIT

gateway_up() {
  "$NODE" -e "fetch('$GATEWAY_URL/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))" >/dev/null 2>&1
}

mkdir -p "$LOG_DIR"
# 代理内部会调 `npm root -g` 定位 openclaw，把 node 目录放到 PATH 最前保证同一版本
export PATH="$NODE_DIR:$PATH"
export OPENCLAW_MJS="$OPENCLAW_JS"

# ── 1) 后端：OpenClaw 网关 ─────────────────────────────────────────────────
if gateway_up; then
  echo "[start-gewu] 网关已在运行 ($GATEWAY_URL)，跳过启动。"
else
  echo "[start-gewu] 启动后端网关 (OpenClaw Gateway) → 日志 $GATEWAY_LOG"
  "$NODE" "$OPENCLAW_JS" gateway run --force > "$GATEWAY_LOG" 2>&1 &
  GW_PID=$!

  echo -n "[start-gewu] 等待网关自检完成（最多约 120s）"
  ready=0
  for _ in $(seq 1 60); do
    if gateway_up; then ready=1; echo " 就绪 ✓"; break; fi
    sleep 2; echo -n "."
  done
  if [ "$ready" -eq 0 ]; then
    echo
    echo "[start-gewu] ⚠️ 网关未在预期时间内就绪，可用以下命令排查："
    echo "    tail -n 50 $GATEWAY_LOG"
    echo "    $NODE $OPENCLAW_JS gateway probe"
    [ "$MODE" = "gateway" ] && exit 1
  fi
fi

if [ "$MODE" = "gateway" ]; then
  echo "[start-gewu] 仅网关模式：保持前台，Ctrl+C 停止。"
  wait 2>/dev/null
  exit 0
fi

# ── 2) 首次/依赖缺失时安装前端依赖 ─────────────────────────────────────────
if [ ! -d "$WEB_DIR/node_modules" ]; then
  if command -v npm >/dev/null 2>&1; then
    npm_cmd=(npm)
  elif [ -f "$NODE_DIR/npm-cli.js" ]; then
    npm_cmd=("$NODE" "$NODE_DIR/npm-cli.js")
  elif [ -f "$NODE_DIR/node_modules/npm/bin/npm-cli.js" ]; then
    npm_cmd=("$NODE" "$NODE_DIR/node_modules/npm/bin/npm-cli.js")
  else
    npm_cmd=()
  fi
  if [ ${#npm_cmd[@]} -eq 0 ]; then
    echo "[start-gewu] ⚠️ 找不到 npm，无法自动装前端依赖。手动执行：cd web && npm install"
  else
    echo "[start-gewu] 未检测到 web/node_modules，执行 npm install → 日志 $NPM_LOG"
    ( cd "$WEB_DIR" && "${npm_cmd[@]}" install ) > "$NPM_LOG" 2>&1 \
      && echo "[start-gewu] 前端依赖安装完成 ✓" \
      || echo "[start-gewu] ⚠️ npm install 失败，详见 $NPM_LOG"
  fi
fi

# ── 3) 前端：Vite(:5173) + 本地代理(:$WEB_PORT) ────────────────────────────
echo "[start-gewu] 启动前端 (web/scripts/dev.mjs) → 日志 $WEB_LOG"
( cd "$WEB_DIR" && "$NODE" "$WEB_DIR/scripts/dev.mjs" ) > "$WEB_LOG" 2>&1 &
WEB_PID=$!

echo
echo "============================================================"
echo "  格物 (Gewu) 已启动"
echo "  后端网关 : $GATEWAY_URL"
echo "  前端地址 : http://localhost:5173   (开发态 Vite)"
echo "             http://localhost:$WEB_PORT   (生产态代理 / 同源 API)"
echo "  日志目录 : $LOG_DIR"
echo "  停止方式 : 在此窗口按 Ctrl+C（会一并关闭前后端）"
echo "============================================================"
echo "[start-gewu] 按 Ctrl+C 停止；脚本保持前台运行以接收停止信号..."

wait 2>/dev/null
