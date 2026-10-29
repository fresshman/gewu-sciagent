// PDF 阅读器组件：基于 pdf.js 渲染，支持翻页、缩放、大纲导航
import { useEffect, useRef, useState, useCallback } from "react";
import * as pdfjsLib from "pdfjs-dist";

// 使用 bundled worker（Vite 会自动处理）
pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

interface PDFViewerProps {
  url: string;
  outline?: { level: number; title: string; page: number }[];
}

export function PDFViewer({ url, outline }: PDFViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [pdfDoc, setPdfDoc] = useState<any>(null);
  const [pageNum, setPageNum] = useState(1);
  const [pageCount, setPageCount] = useState(0);
  const [scale, setScale] = useState(1.2);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const renderingRef = useRef(false);

  // 加载 PDF
  useEffect(() => {
    if (!url) return;
    setLoading(true);
    setError(null);
    setPageNum(1);

    const loadingTask = pdfjsLib.getDocument({ url });
    loadingTask.promise
      .then((doc) => {
        setPdfDoc(doc);
        setPageCount(doc.numPages);
        setLoading(false);
      })
      .catch((e) => {
        setError(`PDF 加载失败：${e.message}`);
        setLoading(false);
      });

    return () => {
      loadingTask.destroy?.();
    };
  }, [url]);

  // 渲染当前页
  const renderPage = useCallback(
    async (num: number) => {
      if (!pdfDoc || !canvasRef.current || renderingRef.current) return;
      renderingRef.current = true;

      try {
        const page = await pdfDoc.getPage(num);
        const viewport = page.getViewport({ scale });
        const canvas = canvasRef.current;
        const context = canvas.getContext("2d")!;
        canvas.height = viewport.height;
        canvas.width = viewport.width;

        await page.render({ canvasContext: context, viewport }).promise;
      } catch (e) {
        // 忽略渲染错误（通常是页面切换时的竞态）
      } finally {
        renderingRef.current = false;
      }
    },
    [pdfDoc, scale],
  );

  useEffect(() => {
    renderPage(pageNum);
  }, [pageNum, scale, renderPage]);

  const goToPage = (n: number) => {
    if (n >= 1 && n <= pageCount) setPageNum(n);
  };

  const zoomIn = () => setScale((s) => Math.min(s + 0.2, 3));
  const zoomOut = () => setScale((s) => Math.max(s - 0.2, 0.5));

  if (loading) {
    return (
      <div className="pdf-viewer pdf-viewer--loading">
        <div className="pdf-viewer__placeholder">PDF 加载中…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="pdf-viewer pdf-viewer--error">
        <div className="pdf-viewer__placeholder">{error}</div>
      </div>
    );
  }

  return (
    <div className="pdf-viewer" ref={containerRef}>
      {/* 工具栏 */}
      <div className="pdf-viewer__toolbar">
        <button className="pdf-viewer__btn" onClick={() => goToPage(pageNum - 1)} disabled={pageNum <= 1}>
          ◀
        </button>
        <span className="pdf-viewer__page-info">
          {pageNum} / {pageCount}
        </span>
        <button className="pdf-viewer__btn" onClick={() => goToPage(pageNum + 1)} disabled={pageNum >= pageCount}>
          ▶
        </button>
        <div className="pdf-viewer__spacer" />
        <button className="pdf-viewer__btn" onClick={zoomOut} disabled={scale <= 0.5}>
          −
        </button>
        <span className="pdf-viewer__scale">{Math.round(scale * 100)}%</span>
        <button className="pdf-viewer__btn" onClick={zoomIn} disabled={scale >= 3}>
          +
        </button>
      </div>

      {/* PDF 画布 */}
      <div className="pdf-viewer__canvas-wrap">
        <canvas ref={canvasRef} />
      </div>

      {/* 大纲侧栏（如果有） */}
      {outline && outline.length > 0 && (
        <div className="pdf-viewer__outline">
          <div className="pdf-viewer__outline-title">大纲</div>
          <ul className="pdf-viewer__outline-list">
            {outline.map((item, i) => (
              <li
                key={i}
                className="pdf-viewer__outline-item"
                style={{ paddingLeft: `${(item.level - 1) * 12 + 8}px` }}
                onClick={() => goToPage(item.page)}
              >
                {item.title}
                <span className="pdf-viewer__outline-page">{item.page}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
