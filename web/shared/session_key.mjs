// runKey → OpenClaw session key 的归一化。
//
// 为什么要单独一层：`openclaw sessions tail --session-key <key>` 没有 --agent 参数，
// 裸 key（如 "gewu-seven-1030"）会被 CLI 用**默认 agent** 解析成 agent:<默认>:<key>，
// 而 `agent --agent <id> --session-key <key>` 把会话建在 agent:<id>:<key> 下。
// 两者不同名 → tail 永远 Session not found，轨迹采集 give-up，
// 依赖工具计数的预算闸门全程失明（实测一轮 50 次调用、阈值 30，budget 恒 null）。
export function canonicalSessionKey(agent, runKey) {
  const key = String(runKey || "");
  if (!key) throw new Error("canonicalSessionKey: runKey 不能为空");
  if (!agent) throw new Error("canonicalSessionKey: agent 不能为空");
  return key.startsWith("agent:") ? key : `agent:${agent}:${key}`;
}
