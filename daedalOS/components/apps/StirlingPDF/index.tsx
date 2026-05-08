import { memo, useMemo, type FC } from "react";
import { type ComponentProcessProps } from "components/system/Apps/RenderComponent";
import {
  IFRAME_CONFIG,
  STIRLING_PDF_APP_URL,
} from "utils/constants";

const StirlingPDF: FC<ComponentProcessProps> = ({ id }) => {
  const src = useMemo(() => STIRLING_PDF_APP_URL.replace(/\/$/, ""), []);

  if (!src) {
    return (
      <div
        style={{
          boxSizing: "border-box",
          color: "#ddd",
          fontFamily: "system-ui, sans-serif",
          fontSize: "14px",
          lineHeight: 1.5,
          padding: "24px",
        }}
      >
        <p style={{ margin: "0 0 12px" }}>
          Stirling-PDF is not configured for this build.
        </p>
        <p style={{ margin: 0 }}>
          Set{" "}
          <code style={{ color: "#fff" }}>NEXT_PUBLIC_STIRLING_PDF_URL</code>{" "}
          when building daedalOS (for example{" "}
          <code style={{ color: "#fff" }}>http://localhost:8080</code>), then
          redeploy. Use &quot;Open with&quot; → PDF to open the built-in viewer.
        </p>
      </div>
    );
  }

  return (
    <iframe
      referrerPolicy={IFRAME_CONFIG.referrerPolicy}
      sandbox={IFRAME_CONFIG.sandbox}
      src={src}
      style={{ border: 0, height: "100%", width: "100%" }}
      title={id}
    />
  );
};

export default memo(StirlingPDF);
