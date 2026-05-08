import { memo, useMemo, useState } from "react";
import { type ComponentProcessProps } from "components/system/Apps/RenderComponent";

const BUTTONS = [
  "7",
  "8",
  "9",
  "/",
  "4",
  "5",
  "6",
  "*",
  "1",
  "2",
  "3",
  "-",
  "0",
  ".",
  "C",
  "+",
] as const;

const calcContainerStyle: React.CSSProperties = {
  background: "#f7f8fa",
  color: "#1f2937",
  display: "flex",
  flexDirection: "column",
  height: "100%",
  padding: 12,
};

const displayStyle: React.CSSProperties = {
  background: "#0f172a",
  borderRadius: 10,
  color: "#f8fafc",
  fontFamily: "Consolas, Menlo, Monaco, monospace",
  fontSize: 28,
  marginBottom: 10,
  minHeight: 62,
  overflow: "hidden",
  padding: "12px 14px",
  textAlign: "right",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};

const gridStyle: React.CSSProperties = {
  display: "grid",
  flex: 1,
  gap: 8,
  gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
};

const evalExpression = (expression: string): string => {
  if (!expression) return "0";
  const safe = expression.replace(/[^0-9+\-*/.() ]/g, "");
  if (!safe.trim()) return "0";

  try {
    const result = Function(`"use strict"; return (${safe});`)();
    if (typeof result !== "number" || Number.isNaN(result) || !Number.isFinite(result)) {
      return "Error";
    }
    return Number(result.toFixed(10)).toString();
  } catch {
    return "Error";
  }
};

const FleetCalculator: FC<ComponentProcessProps> = () => {
  const [expression, setExpression] = useState("");
  const [result, setResult] = useState("0");

  const displayText = useMemo(
    () => (result === "Error" || expression.length === 0 ? result : expression),
    [expression, result]
  );

  const handleButton = (value: (typeof BUTTONS)[number]): void => {
    if (value === "C") {
      setExpression("");
      setResult("0");
      return;
    }

    const next = `${expression}${value}`;
    setExpression(next);
    setResult(evalExpression(next));
  };

  const handleEquals = (): void => {
    if (!expression) return;
    setExpression(result === "Error" ? "" : result);
  };

  return (
    <div style={calcContainerStyle}>
      <div style={displayStyle}>{displayText}</div>
      <div style={gridStyle}>
        {BUTTONS.map((button) => (
          <button
            key={button}
            type="button"
            onClick={() => handleButton(button)}
            style={{
              background: button === "C" ? "#fee2e2" : "#ffffff",
              border: "1px solid #d1d5db",
              borderRadius: 8,
              color: "#111827",
              cursor: "pointer",
              fontSize: 18,
              fontWeight: 600,
              minHeight: 44,
            }}
          >
            {button}
          </button>
        ))}
        <button
          type="button"
          onClick={handleEquals}
          style={{
            background: "#16a34a",
            border: "1px solid #15803d",
            borderRadius: 8,
            color: "#ffffff",
            cursor: "pointer",
            fontSize: 20,
            fontWeight: 700,
            gridColumn: "span 4",
            minHeight: 44,
          }}
        >
          =
        </button>
      </div>
    </div>
  );
};

export default memo(FleetCalculator);
