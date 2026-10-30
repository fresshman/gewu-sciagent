// `sessions tail` 打印的行首时间戳只有时分秒（实测形如 `04:52:36Z`），没有日期。
// 复用同一个 session key 续跑时，tail 会把上一轮（甚至上几轮）的历史一起回放进来。
// 这些历史行如果照单全收，会造成两类污染（都实测踩过）：
//   1) 计数污染：上一轮的 4 次工具调用在本轮开始 4 秒就把预算闸门打炸；
//   2) 生命周期污染：上一轮的 session.ended 让代理以为本轮结束，
//      于是宽限期一到就 finalize —— 本轮还在跑，回复被丢掉、终态被提前写死。
// 所以先把时分秒还原成绝对毫秒，再判断它属不属于本轮。
//
// 跨天处理：本轮从 00:00:30 开始时，昨天 23:59 的历史行按「今天 23:59」还原会落在未来，
// 而网关不可能打印未来的时间 → 落未来就回退一天。秒级截断只会让时间偏早，
// 因此判定给一个 >=1s 的回溯容忍（与轨迹读侧同一个口径）。

const DAY_MS = 86_400_000;

/**
 * 把 tail 行首的 `HH:MM:SSZ` 还原成绝对毫秒。
 * @param {string} tsField 行首时间字段；解析不出（老格式/别的行）返回 null
 * @param {number} nowMs   当前时刻，用来挑「最近的过去」那一天
 * @returns {number|null}
 */
export function tailLineMs(tsField, nowMs) {
  const m = /^(\d{2}):(\d{2}):(\d{2})Z$/.exec(String(tsField || "").trim());
  if (!m) return null;
  const [h, mi, s] = [Number(m[1]), Number(m[2]), Number(m[3])];
  if (h > 23 || mi > 59 || s > 59) return null;
  const midnight = Math.floor(nowMs / DAY_MS) * DAY_MS; // tail 的 Z 即 UTC，天界按 UTC 取
  let ms = midnight + ((h * 60 + mi) * 60 + s) * 1000;
  if (ms > nowMs) ms -= DAY_MS; // 今天的这个点还在未来 → 是昨天的行
  return ms;
}

/**
 * 这行轨迹属不属于本轮？
 * @param {string|null} tsField   tail 行首时间字段
 * @param {number} startedAtMs    本轮开始时刻
 * @param {number} nowMs          当前时刻
 * @param {number} backdateMs     秒级截断回溯容忍，默认 1500
 * @returns {boolean}             true=本轮的行；false=历史回放或无法判定
 */
export function isCurrentRoundLine(tsField, startedAtMs, nowMs, backdateMs = 1_500) {
  const ms = tailLineMs(tsField, nowMs);
  return ms !== null && ms >= startedAtMs - backdateMs;
}
