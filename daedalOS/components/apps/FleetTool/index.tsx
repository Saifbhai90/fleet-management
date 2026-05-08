import { memo, useMemo } from "react";
import { type ComponentProcessProps } from "components/system/Apps/RenderComponent";
import { useProcesses } from "contexts/process";
import { IFRAME_CONFIG } from "utils/constants";

const FleetTool: FC<ComponentProcessProps> = ({ id }) => {
  const {
    processes: { [id]: process },
  } = useProcesses();
  const processUrl = process?.url || "";
  const src = useMemo(() => {
    if (!processUrl) return "";
    if (processUrl.startsWith("http://") || processUrl.startsWith("https://")) {
      return processUrl;
    }

    return `${window.location.origin}${processUrl}`;
  }, [processUrl]);

  return (
    <iframe
      src={src || undefined}
      title={id}
      {...IFRAME_CONFIG}
      style={{ border: 0, height: "100%", width: "100%" }}
    />
  );
};

export default memo(FleetTool);
