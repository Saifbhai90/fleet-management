import { basename, dirname, isAbsolute } from "path";
import { memo, useMemo, useState } from "react";
import { type ComponentProcessProps } from "components/system/Apps/RenderComponent";
import { useFileSystem } from "contexts/fileSystem";
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
  const { mkdirRecursive, updateFolder, writeFile } = useFileSystem();
  const [files, setFiles] = useState<File[]>([]);
  const [pageSize, setPageSize] = useState("original");
  const [orientation, setOrientation] = useState("portrait");
  const [orderBy, setOrderBy] = useState("as_uploaded");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState("");
  const [pendingPdfBytes, setPendingPdfBytes] = useState<Buffer>();
  const [pendingPdfName, setPendingPdfName] = useState("");
  const [savePath, setSavePath] = useState("");
  const [savedPath, setSavedPath] = useState("");
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
    setSavedPath("");
    setPendingPdfBytes(undefined);
    setPendingPdfName("");
    setSavePath("");

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
      setPendingPdfBytes(pdfBuffer);
      setPendingPdfName(data.pdf_name);
      setSavePath(`${DESKTOP_PATH}/${data.pdf_name}`);
      setSummary(`${data.files_count || 0} files -> ${data.pages || 0} pages`);
    } catch {
      setError("Print service reach nahi ho saki. Dobara try karein.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const saveCombinedPdf = async (): Promise<void> => {
    setError("");
    if (!pendingPdfBytes || !pendingPdfName) {
      setError("Pehle Combine & Print karein.");
      return;
    }

    const targetPath = (savePath || "").trim();
    if (!targetPath || !isAbsolute(targetPath)) {
      setError("Valid absolute path dein. Example: /Users/Public/Desktop/my-print.pdf");
      return;
    }
    if (!targetPath.toLowerCase().endsWith(".pdf")) {
      setError("Save path ka extension .pdf hona chahiye.");
      return;
    }

    setIsSaving(true);
    try {
      const targetDir = dirname(targetPath);
      await mkdirRecursive(targetDir);
      await writeFile(targetPath, pendingPdfBytes, true);
      await updateFolder(targetDir, basename(targetPath));
      setSavedPath(targetPath);
    } catch {
      setError("File save nahi ho saki. Path check karke dobara try karein.");
    } finally {
      setIsSaving(false);
    }
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

      {pendingPdfBytes && (
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
          <strong>PDF combined successfully</strong>
          <span style={{ fontSize: 13 }}>
            Ab save path choose karein. File auto-open nahi hogi; aap baad me khud open karein.
          </span>
          <code style={{ background: "#e2e8f0", borderRadius: 6, padding: "4px 8px" }}>{pendingPdfName}</code>
          <input
            onChange={(event) => setSavePath(event.target.value)}
            style={{
              border: "1px solid #cbd5e1",
              borderRadius: 8,
              fontFamily: "Consolas, Menlo, Monaco, monospace",
              fontSize: 13,
              maxWidth: 620,
              padding: "8px 10px",
              width: "100%",
            }}
            value={savePath}
          />
          <button
            disabled={isSaving}
            onClick={saveCombinedPdf}
            style={{
              background: "#0f766e",
              border: "1px solid #0f766e",
              borderRadius: 7,
              color: "#fff",
              cursor: isSaving ? "default" : "pointer",
              opacity: isSaving ? 0.75 : 1,
              padding: "6px 12px",
            }}
            type="button"
          >
            {isSaving ? "Saving..." : "Save Combined PDF"}
          </button>
          {savedPath && (
            <div style={{ color: "#166534", fontWeight: 600 }}>
              Saved: <code>{savedPath}</code>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default memo(FleetMultiFilePrint);
