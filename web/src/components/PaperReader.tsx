// 论文阅读器：三栏布局（论文列表 | PDF 阅读器 | AI 问答面板）
import { useEffect, useState, useRef, useCallback } from "react";
import {
  getPapers,
  uploadPaper,
  getPaperMetadata,
  getPaperText,
  getPaperFileUrl,
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

export function PaperReader() {
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
  const [notes, setNotes] = useState("");

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
    setSelectedPaper(paper);
    setSummary("");
    setQaAnswer("");
    setNotes("");

    try {
      const meta = await getPaperMetadata(paper.id);
      setMetadata(meta);
    } catch {
      setMetadata(null);
    }
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

  // 生成摘要（调用 AI）
  const handleSummarize = useCallback(async () => {
    if (!selectedPaper) return;
    setSummaryLoading(true);
    setSummary("");
    try {
      const data = await getPaperText(selectedPaper.id, 5); // 前 5 页
      // TODO: 接入真实 AI，这里先用文本前 500 字模拟
      const text = data.text || "";
      setSummary(
        `【自动摘要】\n\n标题：${metadata?.title || selectedPaper.title}\n作者：${metadata?.authors || "未知"}\n页数：${metadata?.page_count || selectedPaper.page_count}\n\n` +
        `【摘要内容】\n${metadata?.abstract || text.slice(0, 500) + "..." || "暂无摘要"}`,
      );
    } catch (e) {
      setSummary("摘要生成失败：" + (e as Error).message);
    } finally {
      setSummaryLoading(false);
    }
  }, [selectedPaper, metadata]);

  // AI 问答
  const handleAsk = useCallback(async () => {
    if (!selectedPaper || !qaQuestion.trim()) return;
    setQaLoading(true);
    setQaAnswer("");
    try {
      const data = await getPaperText(selectedPaper.id, 10);
      const text = data.text || "";
      // TODO: 接入真实 AI，这里用关键词匹配模拟
      const q = qaQuestion.toLowerCase();
      let answer = "基于论文内容的分析：\n\n";
      if (q.includes("创新") || q.includes("贡献")) {
        answer += "本文的主要创新点需要结合摘要和引言部分分析。请查看论文前 2 页的 Introduction 部分。";
      } else if (q.includes("方法") || q.includes("model") || q.includes("approach")) {
        answer += "本文的方法部分通常在 Section 3 或 Method 章节。关键方法描述如下：\n" + text.slice(500, 1500);
      } else if (q.includes("结论") || q.includes("result")) {
        answer += "论文的结论部分通常在最后 1-2 页。主要结论需要查看 Conclusion 章节。";
      } else {
        answer += `关于"${qaQuestion}"，论文中的相关内容：\n${text.slice(0, 800)}...`;
      }
      setQaAnswer(answer);
    } catch (e) {
      setQaAnswer("问答失败：" + (e as Error).message);
    } finally {
      setQaLoading(false);
    }
  }, [selectedPaper, qaQuestion]);

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

      {/* 中栏：PDF 阅读器 */}
      <div className="paper-reader__main">
        {selectedPaper ? (
          <PDFViewer url={getPaperFileUrl(selectedPaper.id)} outline={metadata?.toc} />
        ) : (
          <div className="paper-reader__empty-main">
            <div className="paper-reader__empty-icon">📄</div>
            <div className="paper-reader__empty-text">选择或上传一篇论文开始阅读</div>
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
                  {summary ? (
                    <pre className="paper-reader__summary-text">{summary}</pre>
                  ) : (
                    <button
                      className="paper-reader__action-btn"
                      onClick={handleSummarize}
                      disabled={summaryLoading}
                    >
                      {summaryLoading ? "生成中…" : "生成 AI 摘要"}
                    </button>
                  )}
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
                </div>
              )}

              {aiTab === "notes" && (
                <div className="paper-reader__notes">
                  <textarea
                    className="paper-reader__notes-area"
                    placeholder="阅读笔记…（自动保存到项目 2-literature 阶段）"
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                  />
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
