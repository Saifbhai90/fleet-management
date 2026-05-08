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

const TOKEN_REGEX = /(\d+(?:\.\d+)?)|[+\-*/]/g;

const parseTokens = (expression: string): string[] => {
  const normalized = expression.replaceAll(" ", "");
  const matches = normalized.match(TOKEN_REGEX) || [];

  return matches.join("") === normalized ? matches : [];
};

const computeMulDiv = (tokens: string[]): number[] => {
  const reduced: number[] = [];
  let operator = "+";

  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index];
    if (token === "*" || token === "/" || token === "+" || token === "-") {
      operator = token;
      continue;
    }

    const value = Number(token);
    if (!Number.isFinite(value)) return [];

    if (operator === "*") {
      const last = reduced.pop();
      if (typeof last !== "number") return [];
      reduced.push(last * value);
    } else if (operator === "/") {
      const last = reduced.pop();
      if (typeof last !== "number" || value === 0) return [];
      reduced.push(last / value);
    } else if (operator === "-") {
      reduced.push(-value);
    } else {
      reduced.push(value);
    }
  }

  return reduced;
};

const evalExpression = (expression: string): string => {
  if (!expression) return "0";
  const tokens = parseTokens(expression);
  if (tokens.length === 0) return "Error";

  const phaseOne = computeMulDiv(tokens);
  if (phaseOne.length === 0) return "Error";

  const result = phaseOne.reduce((sum, current) => sum + current, 0);
  if (!Number.isFinite(result)) return "Error";

  return Number(result.toFixed(10)).toString();
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
            type="button"
          >
            {button}
          </button>
        ))}
        <button
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
          type="button"
        >
          =
        </button>
      </div>
    </div>
  );
};

export default memo(FleetCalculator);
