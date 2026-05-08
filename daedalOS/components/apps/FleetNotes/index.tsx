import { memo, useEffect, useState } from "react";
import { type ComponentProcessProps } from "components/system/Apps/RenderComponent";

const NOTES_STORAGE_KEY = "fleet-personal-notes-v1";

const wrapperStyle: React.CSSProperties = {
  background: "#f8fafc",
  display: "flex",
  flexDirection: "column",
  gap: 10,
  height: "100%",
  padding: 12,
};

const toolbarStyle: React.CSSProperties = {
  alignItems: "center",
  display: "flex",
  gap: 8,
  justifyContent: "space-between",
};

const FleetNotes: FC<ComponentProcessProps> = () => {
  const [value, setValue] = useState("");
  const [savedAt, setSavedAt] = useState("");

  useEffect(() => {
    const saved = localStorage.getItem(NOTES_STORAGE_KEY);
    if (saved !== null) {
      setValue(saved);
    }
  }, []);

  useEffect(() => {
    localStorage.setItem(NOTES_STORAGE_KEY, value);
    if (value.trim()) {
      setSavedAt(new Date().toLocaleString());
    }
  }, [value]);

  return (
    <div style={wrapperStyle}>
      <div style={toolbarStyle}>
        <strong style={{ color: "#0f172a" }}>Fleet Notes</strong>
        <button
          type="button"
          onClick={() => setValue("")}
          style={{
            background: "#ef4444",
            border: "1px solid #dc2626",
            borderRadius: 6,
            color: "#fff",
            cursor: "pointer",
            padding: "5px 10px",
          }}
        >
          Clear
        </button>
      </div>

      <textarea
        aria-label="Fleet Notes Editor"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="Yahan notes likhein..."
        style={{
          background: "#ffffff",
          border: "1px solid #cbd5e1",
          borderRadius: 8,
          color: "#111827",
          flex: 1,
          fontFamily: "Consolas, Menlo, Monaco, monospace",
          fontSize: 14,
          lineHeight: 1.4,
          outline: "none",
          padding: 12,
          resize: "none",
          width: "100%",
        }}
      />

      <small style={{ color: "#475569" }}>
        {savedAt ? `Auto-saved: ${savedAt}` : "Auto-save enabled"}
      </small>
    </div>
  );
};

export default memo(FleetNotes);
