import { useEffect, useMemo, useState } from "react";
import type { ClaimReport } from "../../types";
import { ClaimCard } from "./ClaimCard";

type Filter = "all" | "ok" | "bad" | "weak" | "badptr";

function queryFromHash(): string {
  if (typeof location === "undefined") return "";
  const i = location.hash.indexOf("?");
  if (i < 0) return "";
  try {
    return new URLSearchParams(location.hash.slice(i + 1)).get("q") || "";
  } catch {
    return "";
  }
}

// 声明核查：一份稿子里每个「对外断言过的数字」，逐条问它从哪来、对不对。
//
// 这一页存在的理由，不是「有个漂亮的清单」，而是：稿子自己说 12 条声明全部
// 带来源指针，实际能核上的只有 4 条。不把这件事摆在台面上，它就会一直
// 以绿色徽章的形式撒谎。所以页头那行数字必须是真实判定，不能是「有 source 就算过」。
export function ClaimBoard({ data }: { data: ClaimReport | null }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState(queryFromHash);

  // 聊天里的引用指针点了会带 ?q=<id> 过来，这里跟着高亮
  useEffect(() => {
    const onHash = () => setQ(queryFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const rows = data?.claims || [];

  const buckets = useMemo(() => {
    const ok: typeof rows = [];
    const bad: typeof rows = [];
    const weak: typeof rows = [];
    for (const r of rows) {
      const tone = r.status;
      if (tone === "grounded" || tone === "paper_grounded") ok.push(r);
      else if (tone === "drift" || tone === "bad_value") bad.push(r);
      else weak.push(r);
    }
    return { ok, bad, weak };
  }, [rows]);

  const badptr = useMemo(
    () => rows.filter((r) => r.status === "bad_source" || r.status === "unknown_experiment"),
    [rows]
  );

  const list = useMemo(() => {
    let out = rows;
    if (filter === "ok") out = buckets.ok;
    else if (filter === "bad") out = buckets.bad;
    else if (filter === "weak") out = buckets.weak;
    else if (filter === "badptr") out = badptr;
    if (!q) return out;
    // 命中项置顶，其余保持原序：高亮而不隐藏，免得用户以为「只剩这一条」
    const hit = (s: string) => s.includes(q);
    return [...out].sort((a, b) => {
      const ha = hit(a.source) || a.experiment_id === q ? 0 : 1;
      const hb = hit(b.source) || b.experiment_id === q ? 0 : 1;
      return ha - hb;
    });
  }, [rows, filter, buckets, badptr, q]);

  if (!data) {
    return <div className="pw-view"><div className="pw-empty">正在跑溯源引擎…</div></div>;
  }
  if (!data.available) {
    return (
      <div className="pw-view">
        <div className="pw-empty">
          <p>{data.reason || "没有可核查的声明"}</p>
          {data.hint && <p><code>{data.hint}</code></p>}
        </div>
      </div>
    );
  }

  const n = data.n_claims ?? rows.length;
  const okN = data.n_grounded ?? 0;
  const driftN = data.n_drift ?? 0;
  const weakN = data.n_unverifiable ?? 0;

  return (
    <div className="pw-view pw-view--claims">
      <div className="fx-bar">
        <div className="fx-sum">
          <b>{n}</b> 条声明
          <span className="fx-arrow">→</span>
          <b className={okN ? "cl-ok" : ""}>{okN}</b> 条支持
          <span className="fx-sub">
            · {driftN} 条矛盾 · {weakN} 条证据不足
          </span>
        </div>
        <div className="fx-chips" role="tablist" aria-label="声明筛选">
          <button className="fx-chip" aria-selected={filter === "all"} onClick={() => setFilter("all")}>
            全部 {n}
          </button>
          <button className="fx-chip" aria-selected={filter === "ok"} onClick={() => setFilter("ok")}>
            支持 {okN}
          </button>
          <button className="fx-chip" aria-selected={filter === "bad"} onClick={() => setFilter("bad")}>
            矛盾 {driftN}
          </button>
          <button className="fx-chip" aria-selected={filter === "weak"} onClick={() => setFilter("weak")}>
            证据不足 {weakN}
          </button>
          <button className="fx-chip" aria-selected={filter === "badptr"} onClick={() => setFilter("badptr")}>
            指针有问题 {badptr.length}
          </button>
        </div>
      </div>

      {!data.all_grounded && (
        <div className="pw-bar-note pw-bar-note--warn">
          全部声明没有通过核验。这 {n} 条里有 {weakN} 条不是「数字算错」，而是
          <b>溯源指针写错或无对应机制</b>：引擎只认{" "}
          <code>registry:&lt;实验id&gt;</code>（指标写在 <code>metric</code> 字段）与{" "}
          <code>paper:&lt;文献id&gt;</code>，而稿子里用的是 <code>recompute:…</code>、
          <code>scripts/…</code> 这类自由文本。改法只有两条：把 source 换成注册表指针，
          或先把这条实验登记进 registry。→ 这类问题{" "}
          {data.counts?.bad_source ?? badptr.length} 条完全同因，下面不再逐卡重复。
        </div>
      )}

      {!!data.n_legacy_source && (
        <div className="pw-bar-note">
          {data.n_legacy_source} 条用了 <code>#</code> 锚点写法
          （<code>registry:&lt;domain&gt;#&lt;实验&gt;.metrics.&lt;指标&gt;</code>）。
          引擎已兼容解析并计入结果，但这不属于规范写法，建议统一成
          <code>registry:&lt;实验id&gt;</code> 并在 metric 字段写明指标。
        </div>
      )}

      {q && (
        <div className="pw-bar-note">
          正在看与 <code>{q}</code> 相关的声明（命中项已置顶）
          <button
            className="pw-ghost"
            style={{ marginLeft: 8 }}
            onClick={() => {
              history.replaceState(null, "", "#claims");
              setQ("");
            }}
          >
            清除
          </button>
        </div>
      )}

      {list.length === 0 ? (
        <div className="pw-empty">这个筛选下没有声明</div>
      ) : (
        <div className="cl-grid">
          {list.map((r, i) => (
            <ClaimCard
              key={`${i}-${r.source}-${r.text.slice(0, 12)}`}
              row={r}
              index={rows.indexOf(r)}
              highlight={!!q && (r.source.includes(q) || r.experiment_id === q)}
            />
          ))}
        </div>
      )}

      <div className="fx-foot">
        判定引擎：<code>gewu/mcp/claim_provenance.py</code> · 容忍度 1% 相对 + 0.01 绝对
        {data.verified_papers?.length ? ` · 已核文献 ${data.verified_papers.length} 篇` : " · 无已核文献集合"}
        {data.path ? ` · ${data.path}` : ""}
      </div>
    </div>
  );
}
