// 轨迹真值来源：直接读网关写在磁盘上的会话事件表 transcript_events，
// 而不是解析它打印给人看的 `sessions tail` 日志行。
//
// 为什么不用 tail：实测 `sessions tail --follow` 不流式，整段轨迹在轮次结束时一次性吐出，
// 计数曲线是 0→N 的阶跃，「是否 ≥ 阈值」这类判定永远读不到中间态。
// 为什么不是 trajectory_runtime_events：同一批事件的结构化孪生表看着更对口，但它也是
// 轮次结束才批量落盘（实测一轮 134s：整轮 traj=0，结束后 +150s 一口气出 33 行）；
// transcript_events 才是边跑边写的那一个（同轮 5→44 行持续增长），
// 计数口径与孪生表一致（13 个 toolCall 块 = 13 行 tool.call）。
//
// 一个必须防住的坑：session key 可续跑复用，一个 session_id 下堆着多轮的事件，
// 而这张表没有 run_id 列 → 只能按时间划界：游标从 created_at < startedAtMs 的最大 seq 起算，
// 本轮开始之前的历史行既不计数，也不参与任何判定。

import { existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { zstdDecompressSync } from "node:zlib";

export function agentStateDb(agent, env = process.env) {
  const home = env.OPENCLAW_HOME || path.join(os.homedir(), ".openclaw");
  return path.join(home, "agents", agent, "agent", "openclaw-agent.sqlite");
}

// Node < 22.5 没有 node:sqlite；老 Node 上跑代理不能因为读轨迹而整体起不来。
let sqliteCtor;
function databaseSync() {
  if (sqliteCtor === undefined) {
    try {
      sqliteCtor = createRequire(import.meta.url)("node:sqlite").DatabaseSync;
    } catch {
      sqliteCtor = null;
    }
  }
  return sqliteCtor;
}

// 大事件的 event_json 会置空、只留 event_zstd（实测 72 行里 10 行如此），必须解压后才计数。
function parseEvent(row) {
  if (row.eventJson) {
    try {
      return JSON.parse(row.eventJson);
    } catch {
      return null;
    }
  }
  if (row.eventZstd) {
    try {
      return JSON.parse(zstdDecompressSync(Buffer.from(row.eventZstd)).toString("utf8"));
    } catch {
      return null;
    }
  }
  return null;
}

// 参数摘要只留「哪条线索能认出这次调用」，不铺原文：表里存的是完整 arguments JSON
// （命令行原文、绝对路径都在里面），tail 打印时是 {...redacted...}。原文一直在网关会话库内，要回取随时能取。
// 返回的是参数线索本身（工具名单独在 block.name 里，调用方别重复拼）。
const SUMMARY_CAP = 140;
const PRIMARY_ARG_KEYS = ["command", "path", "file_path", "url", "pattern", "query",
  "tool_name", "toolName", "session_key", "prompt", "message"];

function clip(text) {
  const s = String(text ?? "").replace(/\s+/g, " ").trim();
  return s.length > SUMMARY_CAP ? s.slice(0, SUMMARY_CAP) + "…" : s;
}

export function summarizeToolCall(block) {
  const args = block.arguments && typeof block.arguments === "object" ? block.arguments : {};
  // 截断作用在「整条线索」上，不是只作用在值上，否则 key 会把长度顶出上限
  for (const k of PRIMARY_ARG_KEYS) {
    if (typeof args[k] === "string" && args[k].trim()) return clip(`${k}=${args[k].trim()}`);
  }
  const [key, value] = Object.entries(args).find(([, v]) => typeof v === "string" && v.trim()) || [];
  return value ? clip(`${key}=${value.trim()}`) : clip(JSON.stringify(args));
}

export function summarizeToolResult(message) {
  const c = message.content;
  const text = typeof c === "string" ? c
    : Array.isArray(c) ? c.map((b) => (typeof b === "string" ? b : b?.text ?? "")).join(" ") : "";
  return clip(text) || (message.isError ? "失败" : "ok");
}

export class TraceReader {
  /**
   * @param {{sessionKey:string, dbPath:string, startedAtMs?:number, backdateMs?:number}} opts
   *        sessionKey 必须是 canonicalSessionKey() 出来的带 agent 前缀的名字；
   *        startedAtMs 是本轮开始时刻，早于它的事件一律视为上一轮的历史。
   */
  constructor({ sessionKey, dbPath, startedAtMs = 0, backdateMs = 2_000 } = {}) {
    if (!sessionKey) throw new Error("TraceReader: sessionKey 不能为空");
    if (!dbPath) throw new Error("TraceReader: dbPath 不能为空");
    this.sessionKey = sessionKey;
    this.dbPath = dbPath;
    this.startedAtMs = startedAtMs;
    // 网关写入可能比代理记下本轮开始早几毫秒到一两秒；留一点回溯容忍，
    // 但上一轮通常是分钟级之前结束的，不会被这点容差误纳。
    this.boundaryMs = Math.max(0, startedAtMs - backdateMs);
    this.cursor = null;
    this.toolCalls = 0;
    this.toolResults = 0;
    this.toolErrors = 0;
    this.turns = 0;
    this.rowsSeen = 0;
    this.lastEventMs = null;
    this.ok = false;
    this.reason = "not-polled";
  }

  /** 增量读：只解析本轮游标之后的新行，返回累计快照。任何失败都降级为 ok:false，不抛。 */
  poll() {
    const Database = databaseSync();
    if (!Database) return this._fail("no-node-sqlite");
    if (!existsSync(this.dbPath)) return this._fail("no-db");
    let db;
    try {
      db = new Database(this.dbPath, { readOnly: true });
    } catch (e) {
      return this._fail("open-failed: " + (e?.message || e));
    }
    try {
      const node = db.prepare(
        "select current_session_id sid from session_nodes where session_key = ?"
      ).get(this.sessionKey);
      if (!node) return this._fail("no-session");

      if (this.cursor === null) {
        this.cursor = db.prepare(
          "select coalesce(max(seq), -1) c from transcript_events" +
          " where session_id = ? and created_at < ?"
        ).get(node.sid, this.boundaryMs).c;
      }

      const rows = db.prepare(
        "select seq, created_at createdMs, event_json eventJson, event_zstd eventZstd" +
        " from transcript_events where session_id = ? and seq > ? order by seq"
      ).all(node.sid, this.cursor);

      // 本次 poll 新增的步骤级事件（游标保证只发一次，供调用方直接铺到时间线上）
      const events = [];
      for (const row of rows) {
        const ev = parseEvent(row);
        const msg = ev && (ev.message || null);
        if (msg && msg.role === "assistant") {
          this.turns++;
          const blocks = Array.isArray(msg.content) ? msg.content : [];
          for (const b of blocks) {
            if (!b || b.type !== "toolCall") continue;
            this.toolCalls++;
            events.push({
              kind: "tool.call", id: b.id || null, name: b.name || "?",
              detail: summarizeToolCall(b), ms: row.createdMs,
            });
          }
        } else if (msg && msg.role === "toolResult") {
          this.toolResults++;
          if (msg.isError === true) this.toolErrors++;
          events.push({
            kind: "tool.result", id: msg.toolCallId || null, name: msg.toolName || "?",
            detail: summarizeToolResult(msg), isError: msg.isError === true, ms: row.createdMs,
          });
        }
        this.rowsSeen++;
        this.cursor = row.seq;
        this.lastEventMs = row.createdMs;
      }
      this.ok = true;
      this.reason = "ok";
      return Object.assign(this.snapshot(), { events });
    } catch (e) {
      return this._fail("query-failed: " + (e?.message || e));
    } finally {
      try {
        db.close();
      } catch { /* 只读连接，关不掉也不影响已取到的计数 */ }
    }
  }

  _fail(reason) {
    this.reason = reason;
    return this.snapshot();
  }

  snapshot() {
    return {
      ok: this.ok,
      reason: this.reason,
      toolCalls: this.toolCalls,
      toolResults: this.toolResults,
      toolErrors: this.toolErrors,
      turns: this.turns,
      rowsSeen: this.rowsSeen,
      events: [],
      lastEventMs: this.lastEventMs,
      cursor: this.cursor,
    };
  }
}
