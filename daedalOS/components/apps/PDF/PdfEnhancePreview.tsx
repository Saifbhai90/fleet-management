import { memo, useEffect, useRef, type FC } from "react";
import { usePdfViewerSession } from "components/apps/PDF/PdfViewerSessionContext";
import { replacePdfPageWithPng } from "components/apps/PDF/replacePdfPageWithImage";
import { useFileSystem } from "contexts/fileSystem";
import { useProcesses } from "contexts/process";

type PdfEnhancePreviewProps = {
  id: string;
};

const PREVIEW_MAX_W = 140;

const PdfEnhancePreview: FC<PdfEnhancePreviewProps> = ({ id }) => {
  const { processes: { [id]: process } = {} } = useProcesses();
  const url = process?.url ?? "";
  const {
    enhancePreviewDataUrl,
    enhancePreviewPage,
    pageCanvasRefs,
    reloadDocument,
    setEnhancePreview,
  } = usePdfViewerSession();
  const { readFile, writeFile } = useFileSystem();

  const beforeRef = useRef<HTMLCanvasElement>(null);

  const pageIndex =
    typeof enhancePreviewPage === "number" ? enhancePreviewPage - 1 : -1;

  const sourceCanvas = pageCanvasRefs.current[pageIndex];

  useEffect(() => {
    const canvas = beforeRef.current;

    if (
      !canvas ||
      enhancePreviewDataUrl === undefined ||
      !sourceCanvas ||
      typeof enhancePreviewPage !== "number"
    ) {
      return;
    }

    const ctx = canvas.getContext("2d");

    if (!ctx) return;

    const ratio = sourceCanvas.height / sourceCanvas.width;
    const width = PREVIEW_MAX_W;
    const height = Math.max(40, Math.round(PREVIEW_MAX_W * ratio));

    canvas.width = width;
    canvas.height = height;
    ctx.drawImage(sourceCanvas, 0, 0, width, height);
  }, [enhancePreviewDataUrl, enhancePreviewPage, sourceCanvas]);

  if (
    enhancePreviewDataUrl === undefined ||
    typeof enhancePreviewPage !== "number"
  ) {
    return false;
  }

  const dismiss = (): void => {
    setEnhancePreview(undefined, undefined);
  };

  const applyEnhance = async (): Promise<void> => {
    if (!url) return;

    try {
      const pngBuffer = await fetch(enhancePreviewDataUrl).then((response) =>
        response.arrayBuffer()
      );
      const pdfBytes = await readFile(url);
      const nextPdf = await replacePdfPageWithPng(
        new Uint8Array(pdfBytes),
        enhancePreviewPage - 1,
        pngBuffer
      );

      const wrote = await writeFile(url, Buffer.from(nextPdf), true);

      if (!wrote) throw new Error("writeFile returned false");

      reloadDocument();
      dismiss();
    } catch {
      // eslint-disable-next-line no-alert -- user-visible failure path
      window.alert("Could not apply enhancement to this page.");
    }
  };

  return (
    <div
      style={{
        backgroundColor: "rgb(38 41 45 / 96%)",
        borderRadius: "12px",
        bottom: "16px",
        boxShadow: "0 8px 28px hsl(0 0% 0% / 50%)",
        display: "flex",
        flexDirection: "column",
        gap: "10px",
        left: "50%",
        maxWidth: "min(560px, calc(100% - 24px))",
        padding: "14px 16px",
        position: "absolute",
        transform: "translateX(-50%)",
        zIndex: 22,
      }}
    >
      <div
        style={{
          color: "#e5e7eb",
          fontSize: "13px",
          fontWeight: 600,
          letterSpacing: "0.02em",
          textAlign: "center",
        }}
      >
        {`Enhanced preview (page ${String(enhancePreviewPage)})`}
      </div>
      <div
        style={{
          alignItems: "stretch",
          display: "flex",
          flexWrap: "wrap",
          gap: "12px",
          justifyContent: "center",
        }}
      >
        <div style={{ textAlign: "center" }}>
          <div
            style={{
              color: "#94a3b8",
              fontSize: "11px",
              marginBottom: "6px",
            }}
          >
            Original
          </div>
          <canvas
            ref={beforeRef}
            style={{
              borderRadius: "6px",
              boxShadow: "0 0 0 1px rgb(255 255 255 / 15%)",
              display: "block",
              height: "auto",
              maxWidth: `${String(PREVIEW_MAX_W)}px`,
            }}
          />
        </div>
        <div style={{ textAlign: "center" }}>
          <div
            style={{
              color: "#94a3b8",
              fontSize: "11px",
              marginBottom: "6px",
            }}
          >
            Cleaned
          </div>
          <img
            alt="Enhanced page preview"
            src={enhancePreviewDataUrl}
            style={{
              borderRadius: "6px",
              boxShadow: "0 0 0 1px rgb(255 255 255 / 15%)",
              display: "block",
              maxWidth: `${String(PREVIEW_MAX_W)}px`,
              objectFit: "contain",
            }}
          />
        </div>
      </div>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "8px",
          justifyContent: "center",
        }}
      >
        <button
          disabled={!url}
          onClick={() => {
            applyEnhance().catch(() => {
              // surfaced via alert inside applyEnhance
            });
          }}
          style={{
            background: "rgb(34 197 94)",
            border: "none",
            borderRadius: "8px",
            color: "#052e16",
            cursor: url ? "pointer" : "not-allowed",
            fontSize: "13px",
            fontWeight: 700,
            opacity: url ? 1 : 0.5,
            padding: "8px 18px",
          }}
          type="button"
        >
          Apply to PDF
        </button>
        <button
          onClick={dismiss}
          style={{
            background: "transparent",
            border: "1px solid rgb(148 163 184)",
            borderRadius: "8px",
            color: "#e2e8f0",
            cursor: "pointer",
            fontSize: "13px",
            padding: "8px 18px",
          }}
          type="button"
        >
          Cancel
        </button>
      </div>
    </div>
  );
};

export default memo(PdfEnhancePreview);
