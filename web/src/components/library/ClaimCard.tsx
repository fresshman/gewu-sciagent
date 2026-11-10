import type { ClaimRow, ClaimStatus } from "../../types";

// 一条声明一张卡。要回答的是三个问题，顺序就是卡片从上到下的顺序：
//   ① 这句话断言了什么数字
//   ② 它跟真值对不对得上（写的是多少 / 注册表是多少 / 差多少 / 容忍多少）
//   ③ 对不上的话，是数字错了还是指针写错了
//
// 三态语义是「支持 / 矛盾 / 证据不足」，从引擎判定直接推出来，不是另打分：
//   grounded / paper_grounded          → 支持
//   drift                              → 矛盾
//   其余（指针坏、指标没登记、越界…）  → 证据不足
// 不做 supports/contradicts/mixed 那套文献论证立场：那需要读原文抽论证关系，
// 现在没有这一步，凭空给个「mixed」等于编。

type Tone = "ok" | "err" | "warn";

export const TONE: Record<ClaimStatus, Tone> = {
  grounded: "ok",
  paper_grounded: "ok",
  drift: "err",
  paper_unverified: "warn",
  unknown_experiment: "warn",
  metric_required: "warn",
  metric_not_in_registry: "warn",
  metric_not_scalar: "warn",
  metric_not_list: "warn",
  metric_index_out_of_range: "warn",
  metric_not_numeric: "warn",
  bad_value: "err",
  bad_source: "warn",
};

export const VERDICT: Record<Tone, string> = { ok: "支持", err: "矛盾", warn: "证据不足" };

export const ST_LABEL: Record<ClaimStatus, string> = {
  grounded: "数值一致",
  paper_grounded: "文献在已核集合",
  drift: "数值漂移",
  paper_unverified: "文献未核验",
  unknown_experiment: "注册表无此实验",
  metric_required: "缺 metric",
  metric_not_in_registry: "指标未登记",
  metric_not_scalar: "列表未写下标",
  metric_not_list: "标量误用下标",
  metric_index_out_of_range: "下标越界",
  metric_not_numeric: "登记值非数字",
  bad_value: "值不可解析",
  bad_source: "来源不可识别",
};

/** 每种失败各自怎么修 —— 这是这张卡比「状态：失败」多出来的全部价值。
 *
 * 故意不收 bad_source：那 7 条的原因和改法完全一样，卡片里重复 7 遍就是噪音，
 * 统一由核查台页头讲一次。卡片只留「跟这条具体数据有关」的建议。 */
const FIX: Partial<Record<ClaimStatus, string>> = {
  unknown_experiment:
    "注册表里没有这个 id。注意别把 domain 当 id 写（coal_mil 是领域，our_hybrid 才是实验）。",
  metric_not_in_registry:
    "实验登记了，但这个指标没登记。要么补进 registry 的 metrics 段，要么这条声明不该用 registry 溯源。",
  metric_not_scalar:
    "这是列表型指标，必须指到某一折，例如 per_fold_rmse_kcal[0]。不写下标引擎不会替你猜「第一折」。",
  metric_not_list: "下标只能用在列表指标上，这个指标是标量。",
  metric_index_out_of_range: "下标超出了列表长度。",
  metric_required: "写了 registry: 但没给 metric，无从比对。",
  bad_value: "value 里没有可解析的数字（比如整句自然语言）。",
  drift: "成稿里的数字与注册表记录值超出容忍度：先确认抄的是不是同一次实验，再确认单位。",
  paper_unverified: "这篇文献不在 D1 已核验集合里，它支撑的数字不可采信。",
  metric_not_numeric: "注册表里这个位置存的不是数字（可能是字符串或对象），引擎不比。",
};

function fmtNum(v: unknown): string {
  if (v == null || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return String(v);
  if (n !== 0 && Math.abs(n) < 1e-3) return n.toExponential(2);
  const s = String(n);
  // 230.9521*0.01 会算出 2.1861080000000004 这种二进制尾巴，原样显示像 bug。
  // 只有「数字位数明显超过有效信息」时才截，别把 214.5699 也四舍五入掉。
  if (s.replace(/[-.]/g, "").length > 8) {
    return String(Number(n.toPrecision(6)));
  }
  return s;
}

/** 把 source 拆成「指针类型 / 主体 / 路径」，让一眼能看出它到底指向哪 */
function splitSource(src: string): { kind: string; head: string; tail: string } {
  const s = (src || "").trim();
  const hashAt = s.indexOf("#");
  const rawHead = hashAt >= 0 ? s.slice(0, hashAt) : s.split(/\s/)[0];
  const tail = hashAt >= 0 ? s.slice(hashAt + 1) : "";
  const kind = s.split(":")[0] || "—";
  // 左边已经有 kind 徽章了，主体里再带一次 "registry:" 就是重复
  const head = rawHead.replace(/^[a-z_]+:/i, "");
  return { kind, head, tail };
}

export function ClaimCard({ row, index, highlight }: { row: ClaimRow; index: number; highlight?: boolean }) {
  const tone = TONE[row.status] || "warn";
  const src = splitSource(row.source);
  const hasTruth = row.truth != null;
  const fix = FIX[row.status];

  return (
    <article className={`cl-card cl-card--${tone} ${highlight ? "is-hit" : ""}`}>
      <header className="cl-head">
        <span className={`cl-verdict cl-verdict--${tone}`}>{VERDICT[tone]}</span>
        <span className="cl-status">{ST_LABEL[row.status] || row.status}</span>
        {/* 非规范写法只在卡片上打个标记：原因和改法页头统一讲一次，
            每张卡再抄一遍长文案就成噪音了 */}
        {row.source_style === "legacy-anchor" && (
          <span
            className="cl-flag"
            title="用了 # 锚点写法（registry:<domain>#<实验>.metrics.<指标>）。引擎能解析，但不属于规范写法，换个工具读可能读不出来。"
          >
            #锚点
          </span>
        )}
        <span className="cl-idx">#{index + 1}</span>
      </header>

      <p className="cl-text">{row.text || "（这条声明没有正文）"}</p>

      <div className="cl-nums">
        <span className="cl-num">
          <i>写的</i>
          <b>{fmtNum(row.value)}</b>
        </span>
        {hasTruth ? (
          <>
            <span className="cl-num">
              <i>注册表</i>
              <b>{fmtNum(row.truth)}</b>
            </span>
            <span className="cl-num">
              <i>差</i>
              <b className={row.status === "drift" ? "is-bad" : ""}>{fmtNum(row.abs_diff)}</b>
            </span>
            <span className="cl-num">
              <i>容忍</i>
              <b className="is-mut">{fmtNum(row.tolerance)}</b>
            </span>
          </>
        ) : (
          // 没有对照值就别摆四格：空格子会让人以为「比过了但都是空」
          <span className="cl-num cl-num--wide">
            <i>对照</i>
            <b className="is-mut">没比过 —— 来源不可解析或指标取不到标量</b>
          </span>
        )}
      </div>

      <div className="cl-src">
        <span className={`cl-kind ${src.kind === "registry" ? "is-reg" : src.kind === "paper" ? "is-paper" : "is-raw"}`}>
          {src.kind}
        </span>
        <code className="cl-srcbody" title={row.source}>{src.head}</code>
        {src.tail && <code className="cl-srctail">#{src.tail}</code>}
      </div>

      <div className="cl-meta">
        {row.experiment_id && (
          <span className="cl-kv"><i>实验</i><b>{row.experiment_id}</b></span>
        )}
        {row.metric && (
          <span className="cl-kv"><i>指标</i><b className="mono">{row.metric}</b></span>
        )}
        {row.domain && <span className="cl-kv"><i>领域</i><b>{row.domain}</b></span>}
        {row.reproducibility && (
          <span className="cl-kv"><i>可复现性</i><b>{row.reproducibility}</b></span>
        )}
        {row.claim_metric && (
          <span className="cl-kv cl-kv--warn" title="claim.metric 在注册表里没找到，改用 source 锚点路径里的指标">
            <i>claim.metric</i>
            <b className="mono">{row.claim_metric}</b>
            <em>已回退</em>
          </span>
        )}
      </div>

      {row.reason && (
        <div className={`cl-note ${tone === "ok" ? "" : "cl-note--warn"}`}>
          {row.reason}
          {row.available_metrics?.length ? (
            <div className="cl-avail">
              已登记指标：{row.available_metrics.map((m) => <code key={m}>{m}</code>)}
            </div>
          ) : null}
          {row.length != null && (
            <div className="cl-avail">列表长度：<code>{row.length}</code></div>
          )}
        </div>
      )}

      {row.note && <div className="cl-note cl-note--quiet">{row.note}</div>}

      {fix && <div className="cl-fix"><b>怎么修</b>{fix}</div>}
    </article>
  );
}
