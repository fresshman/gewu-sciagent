// 会话结束原因的中文标签。
//
// 之前三处（任务圆环 / 消息内执行行 / 执行面板）各自把 session.ended 的
// disposition 原样铺出来，界面上直接出现 `success`、`error` 这种内部枚举。
// 一个中文界面里露出协议字段，用户既看不懂，也分不清「成功结束」和「被中止」。
//
// 认不出来的值原样返回：宁可显示一个陌生词，也不假装认识它而翻译成「成功」。

const RULES: Array<[string, string]> = [
  ["success", "成功"],
  ["complete", "完成"],
  ["timeout", "超时"],
  ["abort", "中止"],
  ["cancel", "取消"],
  ["fail", "失败"],
  ["error", "出错"],
];

export function dispositionText(d?: string | null): string {
  const raw = String(d ?? "").trim();
  if (!raw) return "—";
  const s = raw.toLowerCase();
  for (const [k, label] of RULES) {
    if (s.includes(k)) return label;
  }
  return raw;
}

/** 结束原因对应的观感色：成功 / 出错 / 非正常但非报错（超时、中止、取消） */
export function dispositionTone(d?: string | null): "ok" | "err" | "warn" {
  const s = String(d ?? "").toLowerCase();
  if (!s) return "warn";
  if (s.includes("success") || s.includes("complete")) return "ok";
  if (s.includes("error") || s.includes("fail")) return "err";
  return "warn";
}
