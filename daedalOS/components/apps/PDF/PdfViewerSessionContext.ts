import { createContext, useContext } from "react";

export type PdfViewerSessionValue = {
  overlayRefs: { current: (HTMLCanvasElement | null)[] };
  reloadDocument: () => void;
};

const PdfViewerSessionContext = createContext<
  PdfViewerSessionValue | undefined
>(undefined);

export const PdfViewerSessionProvider = PdfViewerSessionContext.Provider;

export const usePdfViewerSession = (): PdfViewerSessionValue => {
  const ctx = useContext(PdfViewerSessionContext);

  if (!ctx) {
    throw new Error("usePdfViewerSession must be used inside PDF app tree");
  }

  return ctx;
};
