import { memo, useMemo, useState } from "react";

type PrintResponse = {
  error?: string;
  files_count?: number;
  order_by?: string;
  orientation?: string;
  page_size?: string;
  pages?: number;
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

const FleetMultiFilePrint: FC = () => {
  const [files, setFiles] = useState<File[]>([]);
  const [pageSize, setPageSize] = useState("original");
  const [orientation, setOrientation] = useState("portrait");
  const [orderBy, setOrderBy] = useState("as_uploaded");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [pdfUrl, setPdfUrl] = useState("");
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
    setPdfUrl("");

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

      if (!response.ok || !data.success || !data.pdf_url) {
        setError(data.error || "Print batch error");
        return;
      }

      const absolutePdfUrl = data.pdf_url.startsWith("http")
        ? data.pdf_url
        : `${window.location.origin}${data.pdf_url}`;
      setPdfUrl(absolutePdfUrl);
      setSummary(`${data.files_count || 0} files -> ${data.pages || 0} pages`);
    } catch {
      setError("Print service reach nahi ho saki. Dobara try karein.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div style={appStyle}>
      <div style={{ alignItems: "center", display: "flex", gap: 8, justifyContent: "space-between" }}>
        <strong style={{ color: "#0f172a" }}>Fleet Multi File Print</strong>
        <button
          type="button"
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
        >
          {isSubmitting ? "Preparing..." : "Combine & Print"}
        </button>
      </div>

      <input
        type="file"
        multiple
        accept=".pdf,.png,.jpg,.jpeg,.webp,.bmp,.gif,.tif,.tiff"
        onChange={(event) => setFiles(Array.from(event.target.files || []))}
      />

      <div style={{ display: "grid", gap: 8, gridTemplateColumns: "repeat(3, minmax(0, 1fr))" }}>
        <select value={pageSize} onChange={(event) => setPageSize(event.target.value)}>
          <option value="original">Original</option>
          <option value="a4">A4</option>
          <option value="letter">Letter</option>
        </select>
        <select value={orientation} onChange={(event) => setOrientation(event.target.value)}>
          <option value="portrait">Portrait</option>
          <option value="landscape">Landscape</option>
        </select>
        <select value={orderBy} onChange={(event) => setOrderBy(event.target.value)}>
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

      {pdfUrl && (
        <div style={{ border: "1px solid #dbe1ea", borderRadius: 8, flex: 1, minHeight: 260, overflow: "hidden" }}>
          <iframe
            src={pdfUrl}
            title="Combined PDF"
            style={{ border: 0, height: "100%", width: "100%" }}
          />
        </div>
      )}
    </div>
  );
};

export default memo(FleetMultiFilePrint);
