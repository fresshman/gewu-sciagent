// 论文阅读器：三栏布局（论文列表 | PDF 阅读器 | AI 问答面板）
import { useEffect, useState, useRef, useCallback } from "react";
import {
  getPapers,
  uploadPaper,
  getPaperMetadata,
  getPaperFileUrl,
  getPaperNotes,
  savePaperNotes,
  askPaperAi,
  translateText,
  createReproduceHandoff,
} from "../api/client";
import { PDFViewer } from "./PDFViewer";

interface Paper {
  id: string;
  filename: string;
  title: string;
  authors: string;
  doi: string;
  page_count: number;
  added_at: string;
}

export function PaperReader({
  onReproduce,
  isStreaming,
}: {
  onReproduce: (instruction: string) => void;
  isStreaming: boolean;
}) {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null);
  const [metadata, setMetadata] = useState<any>(null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // AI 面板状态
  const [aiTab, setAiTab] = useState<"summary" | "qa" | "notes">("summary");
  const [summary, setSummary] = useState("");
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [qaQuestion, setQaQuestion] = useState("");
  const [qaAnswer, setQaAnswer] = useState("");
  const [qaLoading, setQaLoading] = useState(false);
  const [aiError, setAiError] = useState("");
  const [notes, setNotes] = useState("");
  const [notesStatus, setNotesStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const notesSaveTimer = useRef<number | null>(null);
  const selectedIdRef = useRef<string | null>(null);

  // 划词翻译状态
  const mainRef = useRef<HTMLDivElement>(null);
  const [selBubble, setSelBubble] = useState<{ text: string; x: number; y: number } | null>(null);
  const [trans, setTrans] = useState<{ source: string; result: string } | null>(null);
  const [transLoading, setTransLoading] = useState(false);

  // 送复现状态
  const [reproBusy, setReproBusy] = useState(false);
  const [reproMsg, setReproMsg] = useState("");

  // 选区被取消（点击别处/清空）时收起翻译气泡。
  // 注意：selectionchange 是异步派发的，可能在 mouseup 设置气泡之后才到达，
  // 因此只在选区真正塌缩时清除，否则会把刚弹的气泡误关。
  useEffect(() => {
    const onSelChange = () => {
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed || !sel.toString().trim()) setSelBubble(null);
    };
    document.addEventListener("selectionchange", onSelChange);
    return () => document.removeEventListener("selectionchange", onSelChange);
  }, []);

  const handleTextSelect = useCallback((text: string, rect: { x: number; y: number }) => {
    const box = mainRef.current?.getBoundingClientRect();
    if (!box) return;
    if (text.length > 2000) {
      setSelBubble(null);
      return;
    }
    const x = Math.min(Math.max(rect.x - box.left, 60), box.width - 60);
    const y = Math.min(Math.max(rect.y - box.top, 8), box.height - 44);
    setSelBubble({ text, x, y });
  }, []);

  const handleTranslate = useCallback(() => {
    if (!selBubble || transLoading) return;
    const source = selBubble.text;
    setSelBubble(null);
    setTrans({ source, result: "" });
    setTransLoading(true);
    translateText(source, {
      onDelta: (t) => setTrans((s) => (s ? { ...s, result: s.result + t } : s)),
      onError: (t) => {
        setTrans((s) => (s ? { ...s, result: s.result + (s.result ? "\n" : "") + "⚠ " + t } : s));
        setTransLoading(false);
      },
      onDone: () => setTransLoading(false),
    });
  }, [selBubble, transLoading]);

  // 加载论文列表
  useEffect(() => {
    loadPapers();
  }, []);

  async function loadPapers() {
    try {
      const data = await getPapers();
      setPapers(data.papers || []);
    } catch (e) {
      console.error("Failed to load papers:", e);
    }
  }

  // 选择论文
  async function handleSelect(paper: Paper) {
    selectedIdRef.current = paper.id;
    setSelectedPaper(paper);
    setSummary("");
    setQaAnswer("");
    setNotes("");
    setNotesStatus("idle");
    setSelBubble(null);
    setTrans(null);

    try {
      const meta = await getPaperMetadata(paper.id);
      if (selectedIdRef.current === paper.id) setMetadata(meta);
    } catch {
      if (selectedIdRef.current === paper.id) setMetadata(null);
    }
    // 载入该项目下这篇论文已保存的阅读笔记
    try {
      const d = await getPaperNotes(paper.id);
      if (selectedIdRef.current === paper.id && d.notes) {
        setNotes(d.notes);
        setNotesStatus("saved");
      }
    } catch { /* 无笔记视为空，不打扰用户 */ }
  }

  // 笔记编辑：800ms 防抖后自动落盘（按论文 id 关闭闭包，切走也会保存旧论文的最后编辑）
  function handleNotesChange(v: string) {
    setNotes(v);
    if (!selectedPaper) return;
    const pid = selectedPaper.id;
    setNotesStatus("saving");
    if (notesSaveTimer.current) window.clearTimeout(notesSaveTimer.current);
    notesSaveTimer.current = window.setTimeout(async () => {
      try {
        await savePaperNotes(pid, v);
        if (selectedIdRef.current === pid) setNotesStatus("saved");
      } catch {
        if (selectedIdRef.current === pid) setNotesStatus("error");
      }
    }, 800);
  }

  // 上传 PDF
  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    try {
      const buffer = await file.arrayBuffer();
      const base64 = btoa(
        new Uint8Array(buffer).reduce((data, byte) => data + String.fromCharCode(byte), ""),
      );
      await uploadPaper(base64, file.name);
      await loadPapers();
    } catch (e) {
      console.error("Upload failed:", e);
      alert("上传失败：" + (e as Error).message);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  // 生成摘要（书生大模型，流式）
  const handleSummarize = useCallback(() => {
    if (!selectedPaper || summaryLoading) return;
    setSummaryLoading(true);
    setSummary("");
    setAiError("");
    askPaperAi(selectedPaper.id, "summary", "", {
      onDelta: (t) => setSummary((s) => s + t),
      onError: (t) => setAiError(t),
      onDone: () => setSummaryLoading(false),
    });
  }, [selectedPaper, summaryLoading]);

  // AI 问答（书生大模型，流式）
  const handleAsk = useCallback(() => {
    if (!selectedPaper || qaLoading || !qaQuestion.trim()) return;
    setQaLoading(true);
    setQaAnswer("");
    setAiError("");
    askPaperAi(selectedPaper.id, "qa", qaQuestion, {
      onDelta: (t) => setQaAnswer((s) => s + t),
      onError: (t) => setAiError(t),
      onDone: () => setQaLoading(false),
    });
  }, [selectedPaper, qaLoading, qaQuestion]);

  // 送复现：落盘 repro_request handoff，拿到指令后交给 App 唤起复现员（走 /api/chat 长任务通道）
  const handleReproduce = useCallback(async () => {
    if (!selectedPaper || reproBusy) return;
    setReproBusy(true);
    setReproMsg("");
    try {
      const r = await createReproduceHandoff(selectedPaper.id, summary);
      setReproMsg(r.stageActivated ? "✓ 已激活「复现」阶段，复现员开跑中" : "✓ 已送复现，复现员开跑中");
      onReproduce(r.instruction);
    } catch (e) {
      setReproMsg("⚠ 送复现失败：" + (e as Error).message);
    } finally {
      setReproBusy(false);
    }
  }, [selectedPaper, reproBusy, summary, onReproduce]);

  return (
    <div className="paper-reader">
      {/* 左栏：论文列表 */}
      <div className="paper-reader__sidebar">
        <div className="paper-reader__sidebar-header">
          <h3 className="paper-reader__sidebar-title">论文库</h3>
          <button
            className="paper-reader__upload-btn"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            title="上传 PDF"
          >
            {uploading ? "…" : "+"}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf"
            style={{ display: "none" }}
            onChange={handleUpload}
          />
        </div>
        <div className="paper-reader__paper-list">
          {papers.length === 0 ? (
            <div className="paper-reader__empty">
              点击 + 上传第一篇 PDF 论文
            </div>
          ) : (
            papers.map((p) => (
              <button
                key={p.id}
                className={`paper-reader__paper-item ${selectedPaper?.id === p.id ? "paper-reader__paper-item--active" : ""}`}
                onClick={() => handleSelect(p)}
              >
                <div className="paper-reader__paper-title">{p.title}</div>
                <div className="paper-reader__paper-meta">
                  {p.authors ? p.authors.slice(0, 30) : ""}
                  {p.page_count ? ` · ${p.page_count}p` : ""}
                </div>
              </button>
            ))
          )}
        </div>
      </div>

      {/* 中栏：PDF 阅读器 + 划词翻译浮层 */}
      <div className="paper-reader__main" ref={mainRef}>
        {selectedPaper ? (
          <PDFViewer url={getPaperFileUrl(selectedPaper.id)} outline={metadata?.toc} onTextSelect={handleTextSelect} />
        ) : (
          <div className="paper-reader__empty-main">
            <div className="paper-reader__empty-icon">📄</div>
            <div className="paper-reader__empty-text">选择或上传一篇论文开始阅读</div>
          </div>
        )}

        {selBubble && (
          <button
            className="paper-reader__trans-bubble"
            style={{ left: selBubble.x, top: selBubble.y }}
            onMouseDown={(e) => e.preventDefault() /* 防止点气泡时清空选区 */}
            onClick={handleTranslate}
            title={selBubble.text.length > 60 ? selBubble.text.slice(0, 60) + "…" : selBubble.text}
          >
            🌐 翻译
          </button>
        )}

        {trans && (
          <div className="paper-reader__trans-card">
            <div className="paper-reader__trans-head">
              <span className="paper-reader__trans-label">译文{transLoading ? "（生成中…）" : ""}</span>
              <button className="paper-reader__trans-close" onClick={() => setTrans(null)}>✕</button>
            </div>
            <div className="paper-reader__trans-result">{trans.result || "…"}</div>
            <div className="paper-reader__trans-source">
              {trans.source.length > 160 ? trans.source.slice(0, 160) + "…" : trans.source}
            </div>
          </div>
        )}
      </div>

      {/* 右栏：AI 面板 */}
      <div className="paper-reader__ai-panel">
        {selectedPaper ? (
          <>
            {/* 论文元信息 */}
            <div className="paper-reader__meta">
              <h4 className="paper-reader__meta-title">{metadata?.title || selectedPaper.title}</h4>
              {metadata?.authors && (
                <div className="paper-reader__meta-authors">{metadata.authors}</div>
              )}
              {metadata?.doi && (
                <div className="paper-reader__meta-doi">DOI: {metadata.doi}</div>
              )}
              {/* 跨阶段衔接：一键把论文+笔记打包成 handoff 并唤起复现员 */}
              <div className="paper-reader__repro-row">
                <button
                  className="paper-reader__repro-btn"
                  onClick={handleReproduce}
                  disabled={reproBusy || isStreaming}
                  title={isStreaming ? "有任务正在运行，稍后再送复现" : "把论文连同阅读笔记送到「复现」阶段，唤起复现员"}
                >
                  {reproBusy ? "打包中…" : "🔁 送复现"}
                </button>
                {reproMsg && <span className="paper-reader__repro-msg">{reproMsg}</span>}
              </div>
            </div>

            {/* AI 功能 Tab */}
            <div className="paper-reader__ai-tabs">
              <button
                className={`paper-reader__ai-tab ${aiTab === "summary" ? "paper-reader__ai-tab--active" : ""}`}
                onClick={() => setAiTab("summary")}
              >
                摘要
              </button>
              <button
                className={`paper-reader__ai-tab ${aiTab === "qa" ? "paper-reader__ai-tab--active" : ""}`}
                onClick={() => setAiTab("qa")}
              >
                问答
              </button>
              <button
                className={`paper-reader__ai-tab ${aiTab === "notes" ? "paper-reader__ai-tab--active" : ""}`}
                onClick={() => setAiTab("notes")}
              >
                笔记
              </button>
            </div>

            {/* Tab 内容 */}
            <div className="paper-reader__ai-content">
              {aiTab === "summary" && (
                <div className="paper-reader__summary">
                  {summary && <pre className="paper-reader__summary-text">{summary}</pre>}
                  {aiError && <div className="paper-reader__ai-error">{aiError}</div>}
                  {!summary && !summaryLoading && !aiError && (
                    <div className="paper-reader__ai-hint">由书生大模型基于论文全文生成结构化摘要</div>
                  )}
                  <button
                    className="paper-reader__action-btn"
                    onClick={handleSummarize}
                    disabled={summaryLoading}
                  >
                    {summaryLoading ? "生成中…（首次约 10-60 秒）" : summary ? "重新生成" : "生成 AI 摘要"}
                  </button>
                </div>
              )}

              {aiTab === "qa" && (
                <div className="paper-reader__qa">
                  <div className="paper-reader__qa-input-wrap">
                    <input
                      className="paper-reader__qa-input"
                      placeholder="问关于这篇论文的问题…"
                      value={qaQuestion}
                      onChange={(e) => setQaQuestion(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && handleAsk()}
                    />
                    <button
                      className="paper-reader__qa-send"
                      onClick={handleAsk}
                      disabled={qaLoading || !qaQuestion.trim()}
                    >
                      {qaLoading ? "…" : "→"}
                    </button>
                  </div>
                  {qaAnswer && (
                    <pre className="paper-reader__qa-answer">{qaAnswer}</pre>
                  )}
                  {aiError && <div className="paper-reader__ai-error">{aiError}</div>}
                  {qaLoading && !qaAnswer && (
                    <div className="paper-reader__ai-hint">书生大模型思考中…</div>
                  )}
                </div>
              )}

              {aiTab === "notes" && (
                <div className="paper-reader__notes">
                  <textarea
                    className="paper-reader__notes-area"
                    placeholder="阅读笔记…（停止输入 1 秒后自动保存到项目「读论文」阶段）"
                    value={notes}
                    onChange={(e) => handleNotesChange(e.target.value)}
                  />
                  <div className="paper-reader__notes-status">
                    {notesStatus === "saving" && "保存中…"}
                    {notesStatus === "saved" && "✓ 已保存到 stages/2-literature/notes/"}
                    {notesStatus === "error" && "⚠ 保存失败，继续编辑会自动重试"}
                    {notesStatus === "idle" && "笔记按论文归档到当前项目，可随七阶段产出沉淀"}
                  </div>
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="paper-reader__ai-empty">
            选择论文后，此处显示 AI 辅助功能
          </div>
        )}
      </div>
    </div>
  );
}
