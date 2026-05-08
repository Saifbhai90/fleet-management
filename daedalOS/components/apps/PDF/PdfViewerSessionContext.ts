import { createContext, useContext, type RefObject } from "react";

export type PdfViewerSessionValue = {
  enhancePreviewDataUrl?: string;
  enhancePreviewPage?: number;
  overlayRefs: { current: (HTMLCanvasElement | undefined)[] };
  pageCanvasRefs: { current: (HTMLCanvasElement | undefined)[] };
  penUndoHandlersRef: RefObject<((() => void) | undefined)[]>;
  reloadDocument: () => void;
  setEnhancePreview: (
    dataUrl?: string,
    pageOneBased?: number
  ) => void;
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
