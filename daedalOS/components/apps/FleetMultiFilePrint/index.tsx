import { memo, useMemo, useState } from "react";
import { type ComponentProcessProps } from "components/system/Apps/RenderComponent";
import { useFileSystem } from "contexts/fileSystem";
import { useProcesses } from "contexts/process";
import { DESKTOP_PATH } from "utils/constants";

type PrintResponse = {
  error?: string;
  files_count?: number;
  order_by?: string;
  orientation?: string;
  page_size?: string;
  pages?: number;
  pdf_base64?: string;
  pdf_name?: string;
  pdf_url?: string;
  success?: boolean;
};

const appStyle: React.CSSProperties = {
  background: "#f8fafc",
  display: "flex",
  flexDirection: "column",
  gap: 10,
  height: "100%",
  padding: 12,
};

const decodeBase64ToBuffer = (content: string): Buffer => {
  const binary = window.atob(content);
  const bytes = Uint8Array.from(binary, (character) => {
    const code = character.codePointAt(0);
    return typeof code === "number" ? code : 0;
  });

  return Buffer.from(bytes);
};

const FleetMultiFilePrint: FC<ComponentProcessProps> = () => {
  const { createPath } = useFileSystem();
  const { open } = useProcesses();
  const [files, setFiles] = useState<File[]>([]);
  const [pageSize, setPageSize] = useState("original");
  const [orientation, setOrientation] = useState("portrait");
  const [orderBy, setOrderBy] = useState("as_uploaded");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [pdfPath, setPdfPath] = useState("");
  const [summary, setSummary] = useState("");

  const orderedFiles = useMemo(() => {
    const next = [...files];
    if (orderBy === "name_asc" || orderBy === "name_desc") {
      next.sort((a, b) => a.name.localeCompare(b.name));
      if (orderBy === "name_desc") next.reverse();
    }
    return next;
  }, [files, orderBy]);

  const submit = async (): Promise<void> => {
    setError("");
    setSummary("");
    setPdfPath("");

    if (orderedFiles.length === 0) {
      setError("Kam az kam 1 PDF/Image file select karein.");
      return;
    }

    const formData = new FormData();
    orderedFiles.forEach((file) => formData.append("print_files", file));
    formData.append("page_size", pageSize);
    formData.append("orientation", orientation);
    formData.append("order_by", orderBy);

    setIsSubmitting(true);
    try {
      const response = await fetch("/api/personal-tools/quick-print", {
        body: formData,
        credentials: "include",
        method: "POST",
      });
      const data = (await response.json()) as PrintResponse;

      if (!response.ok || !data.success || !data.pdf_base64 || !data.pdf_name) {
        setError(data.error || "Print batch error");
        return;
      }
      const pdfBuffer = decodeBase64ToBuffer(data.pdf_base64);
      const savedName = await createPath(data.pdf_name, DESKTOP_PATH, pdfBuffer);
      if (!savedName) {
        setError("Combined PDF Desktop par save nahi ho saki.");
        return;
      }

      const savedPath = `${DESKTOP_PATH}/${savedName}`;
      setPdfPath(savedPath);
      setSummary(`${data.files_count || 0} files -> ${data.pages || 0} pages`);
      open("PDF", { url: savedPath });
    } catch {
      setError("Print service reach nahi ho saki. Dobara try karein.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const openPdfInViewer = (): void => {
    if (!pdfPath) return;
    open("PDF", { url: pdfPath });
  };

  const printPdfFromViewer = (): void => {
    if (!pdfPath) return;
    open("PDF", { url: pdfPath });
  };

  return (
    <div style={appStyle}>
      <div style={{ alignItems: "center", display: "flex", gap: 8, justifyContent: "space-between" }}>
        <strong style={{ color: "#0f172a" }}>Fleet Multi File Print</strong>
        <button
          disabled={isSubmitting}
          onClick={submit}
          style={{
            background: "#16a34a",
            border: "1px solid #15803d",
            borderRadius: 7,
            color: "#fff",
            cursor: isSubmitting ? "default" : "pointer",
            fontWeight: 600,
            opacity: isSubmitting ? 0.75 : 1,
            padding: "6px 12px",
          }}
          type="button"
        >
          {isSubmitting ? "Preparing..." : "Combine & Print"}
        </button>
      </div>

      <input
        accept=".pdf,.png,.jpg,.jpeg,.webp,.bmp,.gif,.tif,.tiff"
        onChange={(event) => setFiles([...(event.target.files || [])])}
        type="file"
        multiple
      />

      <div style={{ display: "grid", gap: 8, gridTemplateColumns: "repeat(3, minmax(0, 1fr))" }}>
        <select onChange={(event) => setPageSize(event.target.value)} value={pageSize}>
          <option value="original">Original</option>
          <option value="a4">A4</option>
          <option value="letter">Letter</option>
        </select>
        <select onChange={(event) => setOrientation(event.target.value)} value={orientation}>
          <option value="portrait">Portrait</option>
          <option value="landscape">Landscape</option>
        </select>
        <select onChange={(event) => setOrderBy(event.target.value)} value={orderBy}>
          <option value="as_uploaded">As Uploaded</option>
          <option value="name_asc">A to Z</option>
          <option value="name_desc">Z to A</option>
        </select>
      </div>

      <div
        style={{
          background: "#ffffff",
          border: "1px solid #dbe1ea",
          borderRadius: 8,
          color: "#0f172a",
          minHeight: 50,
          padding: 8,
        }}
      >
        {orderedFiles.length === 0
          ? "No files selected."
          : `${orderedFiles.length} file(s): ${orderedFiles
              .slice(0, 8)
              .map((file) => file.name)
              .join(", ")}${orderedFiles.length > 8 ? " ..." : ""}`}
      </div>

      {error && <div style={{ color: "#b91c1c", fontWeight: 600 }}>{error}</div>}
      {summary && <div style={{ color: "#166534", fontWeight: 600 }}>{summary}</div>}

      {pdfPath && (
        <div
          style={{
            alignItems: "center",
            background: "#f1f5f9",
            border: "1px solid #dbe1ea",
            borderRadius: 8,
            color: "#0f172a",
            display: "flex",
            flex: 1,
            flexDirection: "column",
            gap: 10,
            justifyContent: "center",
            minHeight: 220,
            padding: 16,
            textAlign: "center",
          }}
        >
          <strong>PDF ready inside DaedalOS</strong>
          <span style={{ fontSize: 13 }}>
            File Desktop me save ho chuki hai aur internal PDF viewer me open ho gayi hai.
          </span>
          <code style={{ background: "#e2e8f0", borderRadius: 6, padding: "4px 8px" }}>{pdfPath}</code>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              onClick={openPdfInViewer}
              style={{
                background: "#2563eb",
                border: "1px solid #1d4ed8",
                borderRadius: 7,
                color: "#fff",
                cursor: "pointer",
                padding: "6px 12px",
              }}
              type="button"
            >
              Open in PDF Viewer
            </button>
            <button
              onClick={printPdfFromViewer}
              style={{
                background: "#0f766e",
                border: "1px solid #0f766e",
                borderRadius: 7,
                color: "#fff",
                cursor: "pointer",
                padding: "6px 12px",
              }}
              type="button"
            >
              Print via PDF Viewer
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default memo(FleetMultiFilePrint);
