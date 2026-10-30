// web/shared/trace_source.mjs 的行为测试：node --test "web/tests/**/*.test.mjs"
// 用 node:sqlite 现造一份和网关 transcript_events 同构的最小表，
// 验证「增量游标 + 按时间划界（续跑复用 key 不吃上一轮历史） + zstd 行解码 + 只读降级」。
import { test } from "node:test";
import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { zstdCompressSync } from "node:zlib";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { TraceReader, agentStateDb, summarizeToolCall, summarizeToolResult } from "../shared/trace_source.mjs";

const KEY = "agent:gewu-director:regress-1";
const SID = "sess-1";
const T0 = 1_793_331_600_000;

const toolCall = (name, id = "c", args = {}) => ({ type: "message", message: { role: "assistant", content: [{ type: "toolCall", id, name, arguments: args }] } });
const assistant = (text) => ({ type: "message", message: { role: "assistant", content: [{ type: "text", text }] } });
const toolResult = (isError, id = "c", name = "exec", content = "ok") => ({ type: "message", message: { role: "toolResult", toolCallId: id, toolName: name, isError, content } });
const meta = (type) => ({ type });

/**
 * @param {Array<{at:number, ev:object, zstd?:boolean}>} rows  at 是相对 T0 的毫秒偏移
 * @param {{sessionKey?:string|null, sid?:string}} opts        sessionKey 传 null 造「会话不存在」
 */
function fixture(rows, { sessionKey = KEY, sid = SID } = {}) {
  const dir = mkdtempSync(path.join(tmpdir(), "gewu-trace-"));
  const dbPath = path.join(dir, "openclaw-agent.sqlite");
  const db = new DatabaseSync(dbPath);
  db.exec(
    "create table session_nodes (session_key text primary key, current_session_id text not null);" +
    "create table transcript_events (" +
    "  session_id text not null, seq integer not null, event_json text, created_at integer not null," +
    "  event_zstd blob, event_utf8_bytes integer, primary key (session_id, seq));"
  );
  if (sessionKey) db.prepare("insert into session_nodes values (?, ?)").run(sessionKey, sid);
  const ins = db.prepare(
    "insert into transcript_events (session_id, seq, event_json, created_at, event_zstd, event_utf8_bytes)" +
    " values (?, ?, ?, ?, ?, ?)"
  );
  rows.forEach((r, i) => {
    const json = JSON.stringify(r.ev);
    ins.run(sid, i, r.zstd ? null : json, T0 + r.at,
      r.zstd ? new Uint8Array(zstdCompressSync(Buffer.from(json))) : null, json.length);
  });
  db.close();
  const append = (more) => {
    const d = new DatabaseSync(dbPath);
    const q = d.prepare("insert into transcript_events values (?, ?, ?, ?, ?, ?)");
    more.forEach((r, i) => {
      const json = JSON.stringify(r.ev);
      const seq = rows.length + i;
      q.run(SID, seq, r.zstd ? null : json, T0 + r.at,
        r.zstd ? new Uint8Array(zstdCompressSync(Buffer.from(json))) : null, json.length);
    });
    d.close();
    rows.push(...more);
  };
  return { dbPath, dir, append };
}

test("一轮的 toolCall 块 / toolResult / 错误 / 回合各自计数正确，非消息事件忽略", () => {
  const f = fixture([
    { at: 0, ev: meta("session") },
    { at: 10, ev: meta("model_change") },
    { at: 20, ev: meta("custom") },
    { at: 100, ev: toolCall("exec") },
    { at: 200, ev: toolResult(false) },
    { at: 300, ev: toolCall("write") },
    { at: 301, ev: toolCall("read") },   // 一次回合里并行两个调用
    { at: 400, ev: toolResult(true) },
    { at: 500, ev: assistant("阶段完成") },
  ]);
  const snap = new TraceReader({ sessionKey: KEY, dbPath: f.dbPath, startedAtMs: T0 }).poll();
  assert.equal(snap.ok, true, snap.reason);
  assert.deepEqual(
    [snap.toolCalls, snap.toolResults, snap.toolErrors, snap.turns],
    [3, 2, 1, 4]
  );
  assert.equal(snap.lastEventMs, T0 + 500);
  assert.equal(snap.cursor, 8);
  rmSync(f.dir, { recursive: true, force: true });
});

test("大行只落 event_zstd（实测 72 行里 10 行如此）：解压后照样计数", () => {
  const f = fixture([
    { at: 100, ev: toolCall("exec") },
    { at: 200, ev: toolResult(false), zstd: true },
    { at: 300, ev: toolCall("read"), zstd: true },
    { at: 400, ev: { bad: "json" } },
  ]);
  const snap = new TraceReader({ sessionKey: KEY, dbPath: f.dbPath, startedAtMs: T0 }).poll();
  assert.deepEqual([snap.toolCalls, snap.toolResults, snap.turns], [2, 1, 2]);
  assert.equal(snap.rowsSeen, 4);
  rmSync(f.dir, { recursive: true, force: true });
});

test("续跑复用同一 session key：本轮开始前的历史行一律不计数（否则第二轮瞬间被闸门打死）", () => {
  const prev = Array.from({ length: 60 }, (_, i) => ({ at: 100 + i, ev: toolCall("exec") }));
  const cur = [{ at: 9000, ev: toolCall("read") }, { at: 9100, ev: toolResult(false) }];
  const f = fixture([...prev, ...cur]);
  // 第二轮的 reader 在上一轮结束后才建立：startedAtMs 落在两轮之间
  const second = new TraceReader({ sessionKey: KEY, dbPath: f.dbPath, startedAtMs: T0 + 8000 }).poll();
  assert.equal(second.ok, true, second.reason);
  assert.equal(second.toolCalls, 1);
  assert.equal(second.cursor, 61); // 游标从历史最后一行（59）起算，跳过旧行后才推进
  // 本轮还没开始的 reader：只能报 0，绝不能把上一轮的 60 次算进来
  const early = new TraceReader({ sessionKey: KEY, dbPath: f.dbPath, startedAtMs: T0 + 20000 }).poll();
  assert.equal(early.toolCalls, 0);
  assert.equal(early.rowsSeen, 0);
  rmSync(f.dir, { recursive: true, force: true });
});

test("增量游标：第二次 poll 只解析新行，累计值单调增长", () => {
  const rows = [{ at: 100, ev: toolCall("exec") }];
  const f = fixture(rows);
  const r = new TraceReader({ sessionKey: KEY, dbPath: f.dbPath, startedAtMs: T0 });
  assert.equal(r.poll().toolCalls, 1);
  f.append([{ at: 2000, ev: toolCall("write") }]);
  const snap = r.poll();
  assert.equal(snap.toolCalls, 2);
  assert.equal(snap.cursor, 1);
  assert.equal(r.poll().toolCalls, 2); // 没有新行就不动
  rmSync(f.dir, { recursive: true, force: true });
});

test("会话还没建 / 库文件不在 → 降级为 ok:false，不抛（轨迹不可用不能拖垮轮次）", () => {
  const f = fixture([{ at: 100, ev: toolCall("exec") }]);
  assert.equal(
    new TraceReader({ sessionKey: "agent:x:nope", dbPath: f.dbPath, startedAtMs: T0 }).poll().reason,
    "no-session");
  const missing = path.join(f.dir, "does-not-exist.sqlite");
  assert.equal(new TraceReader({ sessionKey: KEY, dbPath: missing, startedAtMs: T0 }).poll().reason, "no-db");
  rmSync(f.dir, { recursive: true, force: true });
});

test("session_nodes 里查不到 key（裸 key 走 tail 的那类命名错配）→ no-session，而不是静默 0 次", () => {
  const f = fixture([{ at: 100, ev: toolCall("exec") }], { sessionKey: null });
  const snap = new TraceReader({ sessionKey: KEY, dbPath: f.dbPath, startedAtMs: T0 }).poll();
  assert.equal(snap.ok, false);
  assert.equal(snap.reason, "no-session");
  rmSync(f.dir, { recursive: true, force: true });
});

test("dbPath 由 agent 名推导，OPENCLAW_HOME 可覆盖（换机器/换实例不用改代码）", () => {
  const p = agentStateDb("gewu-director", { OPENCLAW_HOME: "C:/claw" });
  assert.match(p, /C:\\?claw[/\\]agents[/\\]gewu-director[/\\]agent[/\\]openclaw-agent\.sqlite$/);
});

test("构造参数缺失直接抛：空 sessionKey 会让所有降级伪装成 no-session", () => {
  assert.throws(() => new TraceReader({ sessionKey: "", dbPath: "x" }), /sessionKey 不能为空/);
  assert.throws(() => new TraceReader({ sessionKey: KEY }), /dbPath 不能为空/);
});

test("poll 带出步骤级事件：call/result 各一条，带 id 供精确配对", () => {
  const f = fixture([
    { at: 100, ev: toolCall("exec", "id-1", { command: "powershell -Command Get-Date", timeoutSeconds: 30 }) },
    { at: 900, ev: toolResult(false, "id-1", "exec", "2026年10月30日 14:20:00") },
  ]);
  const r = new TraceReader({ sessionKey: KEY, dbPath: f.dbPath, startedAtMs: T0 });
  const snap = r.poll();
  assert.deepEqual(snap.events.map((e) => [e.kind, e.id, e.name]),
    [["tool.call", "id-1", "exec"], ["tool.result", "id-1", "exec"]]);
  assert.equal(snap.events[0].detail, "command=powershell -Command Get-Date");
  assert.equal(snap.events[0].ms, T0 + 100);
  assert.equal(snap.events[1].isError, false);
  assert.equal(snap.events[1].detail, "2026年10月30日 14:20:00");
  // 同一个 reader 再 poll 一次不重发（游标已推进）：否则时间线会把同一批调用铺两遍
  assert.deepEqual(r.poll().events, []);
  rmSync(f.dir, { recursive: true, force: true });
});

test("同一 reader 第二次 poll 只发新增行的事件", () => {
  const rows = [{ at: 100, ev: toolCall("exec", "id-1", { command: "Get-Date" }) }];
  const f = fixture(rows);
  const r = new TraceReader({ sessionKey: KEY, dbPath: f.dbPath, startedAtMs: T0 });
  assert.equal(r.poll().events.length, 1);
  f.append([{ at: 5000, ev: toolCall("write", "id-2", { path: "C:/tmp/a.json" }) }]);
  const snap = r.poll();
  assert.deepEqual(snap.events.map((e) => [e.kind, e.name]), [["tool.call", "write"]]);
  assert.equal(snap.toolCalls, 2);
  rmSync(f.dir, { recursive: true, force: true });
});

test("降级路径也带 events:[]，调用方可以无条件遍历", () => {
  const f = fixture([{ at: 100, ev: toolCall("exec", "id-1") }]);
  const missing = new TraceReader({ sessionKey: KEY, dbPath: path.join(f.dir, "nope.sqlite"), startedAtMs: T0 }).poll();
  assert.deepEqual(missing.events, []);
  assert.equal(missing.ok, false);
  rmSync(f.dir, { recursive: true, force: true });
});

test("参数摘要只挑可读线索，超长截断：表里存的是完整 arguments JSON，不能原样铺上屏", () => {
  const long = "powershell -Command " + "x".repeat(400);
  const d = summarizeToolCall({ name: "exec", arguments: { command: long, timeoutSeconds: 60 } });
  assert.ok(d.startsWith("command=powershell -Command "), d);
  assert.ok(d.length <= 141, `长度 ${d.length}`);
  assert.ok(d.endsWith("…"), "超长必须截断");
  assert.ok(!d.includes("timeoutSeconds"), "次要参数不进摘要");
  // 主键都不在时退到第一个字符串值，再退到紧凑 JSON；都不会整段照抄
  assert.equal(summarizeToolCall({ name: "read", arguments: { offset: 1 } }), JSON.stringify({ offset: 1 }));
  assert.equal(summarizeToolCall({ name: "grep", arguments: { other: "  P ATTERN  " } }), "other=P ATTERN");
});

test("结果摘要：字符串/块数组/错误三种形态都能读，且不铺原文", () => {
  assert.equal(summarizeToolResult({ content: "  a   b  " }), "a b");
  assert.equal(summarizeToolResult({ content: [{ type: "text", text: "第一段" }, { text: "第二段" }] }), "第一段 第二段");
  assert.equal(summarizeToolResult({ content: [], isError: true }), "失败");
  assert.equal(summarizeToolResult({ content: "x".repeat(500) }).length, 141);
});
