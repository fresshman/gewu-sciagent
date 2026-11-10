import { useCallback, useEffect, useRef, useState } from "react";
import { getFigures, getLibrary, getWriting } from "../../api/client";
import type { FigureIndexResponse, LibraryResponse, WritingResponse } from "../../types";
import { FigureBoard } from "./FigureBoard";
import { PaperLibrary } from "./PaperLibrary";
import { WritingDesk } from "./WritingDesk";

type Tab = "lib" | "write" | "fig";

// hash ↔ tab。写作台与图纸都挂在 #writing 之外单独给个锚，刷新不丢位置。
const HASH: Record<Tab, string> = { lib: "#library", write: "#writing", fig: "#figures" };
function tabFromHash(): Tab {
  const h = typeof location !== "undefined" ? location.hash : "";
  if (h === "#writing") return "write";
  if (h === "#figures") return "fig";
  return "lib";
}

// 论文视图容器：一次拉两份只读投影，tab 之间切换不重复请求。
// 两条横幅都只在「真有问题」时出现，不写常驻装饰文案。
export function PaperWorkspace({ onOpenPaper }: { onOpenPaper?: (paperId: string) => void }) {
  const [tab, setTab] = useState<Tab>(tabFromHash);
  const [lib, setLib] = useState<LibraryResponse | null>(null);
  const [wri, setWri] = useState<WritingResponse | null>(null);
  const [fig, setFig] = useState<FigureIndexResponse | null>(null);
  const [err, setErr] = useState("");
  const [toast, setToast] = useState("");
  const toastTimer = useRef<number | undefined>(undefined);

  const notify = useCallback((msg: string) => {
    setToast(msg);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(""), 1300);
  }, []);

  const go = useCallback((t: Tab) => {
    setTab(t);
    if (typeof location !== "undefined") history.replaceState(null, "", HASH[t]);
  }, []);

  const load = useCallback(() => {
    setErr("");
    Promise.all([getLibrary(), getWriting(), getFigures()])
      .then(([a, b, c]) => {
        setLib(a);
        setWri(b);
        setFig(c);
      })
      .catch((e) => setErr(String(e?.message || e)));
  }, []);

  useEffect(() => {
    load();
    return () => window.clearTimeout(toastTimer.current);
  }, [load]);

  // hash 是唯一真相源：刷新、手改地址、浏览器后退都走这里，不再各存一份 tab 状态
  useEffect(() => {
    const onHash = () => setTab(tabFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const project = lib?.project || wri?.project || "";
  const own = lib?.items.find((x) => x.kind === "own");
  const assets = wri?.assets;
  const brokenDup = wri?.duplicates?.filter((d) => !d.same) || [];

  return (
    <div className="pw">
      <div className="pw-top">
        <div className="pw-proj">
          <span className="pw-dot" />
          <b>{project || "—"}</b>
          <span>{own?.title || "论文管理"}</span>
        </div>
        <div className="pw-tabs" role="tablist" aria-label="论文视图">
          <button
            className="pw-tab"
            role="tab"
            aria-selected={tab === "lib"}
            onClick={() => go("lib")}
          >
            论文库{lib ? ` ${lib.summary.total}` : ""}
          </button>
          <button
            className="pw-tab"
            role="tab"
            aria-selected={tab === "write"}
            onClick={() => go("write")}
          >
            写作台
          </button>
          <button
            className="pw-tab"
            role="tab"
            aria-selected={tab === "fig"}
            onClick={() => go("fig")}
            title="图纸：按内容 sha256 合并散落各目录的副本，一张图一个 id"
          >
            图纸{fig?.summary ? ` ${fig.summary.total}` : ""}
          </button>
        </div>
        <div className="pw-spacer" />
        <button className="pw-ghost" onClick={load} title="重新读取磁盘上的索引">
          重新索引
        </button>
      </div>

      {err && <div className="pw-bar-note pw-bar-note--warn">读取失败：{err}</div>}

      {!err && lib?.available && assets && (
        <div className="pw-bar-note">
          数据取自 {project} 真实产物：{lib.summary.total} 篇 · {assets.tables} 表{" "}
          {fig?.summary ? `${fig.summary.total} 图（${fig.summary.files} 个文件合并）` : `${assets.figures} 图`} ·{" "}
          {assets.claims.n} 条声明 · {assets.equations.n} 条编号公式 · {assets.refs.n} 条参考文献
          {wri?.tex ? ` · 源 ${wri.tex.path}` : ""}
        </div>
      )}

      {/* 同一稿子两份内容不同的副本 —— 必须让人看见，不能静默取一份 */}
      {brokenDup.length > 0 && (
        <div className="pw-bar-note pw-bar-note--warn">
          稿子有两份内容不同的副本：本页显示的是 {wri?.tex?.path}（{wri?.tex?.bytes} B）；
          {brokenDup.map((d) => ` ${d.path}（${d.bytes} B · ${d.lines} 行 · 表 ${d.tables} 张）`).join("；")}
          　sha256 不一致，改动只会落在其中一份上。
        </div>
      )}

      {tab === "lib" && (
        <PaperLibrary data={lib} onToast={notify} onOpenPaper={onOpenPaper} onRetry={load} />
      )}
      {tab === "write" && <WritingDesk data={wri} figures={fig?.figures || []} onToast={notify} />}
      {tab === "fig" && <FigureBoard data={fig} onToast={notify} />}

      <div className={`pw-toast ${toast ? "on" : ""}`}>{toast}</div>
    </div>
  );
}
