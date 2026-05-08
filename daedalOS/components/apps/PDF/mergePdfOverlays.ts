import { type PDFDocument as PdfLibDocument } from "pdf-lib";

const OVERLAY_ALPHA_THRESHOLD = 12;

export const canvasHasDrawing = (canvas: HTMLCanvasElement): boolean => {
  const ctx = canvas.getContext("2d");

  if (!ctx) return false;

  const { height, width } = canvas;

  if (width === 0 || height === 0) return false;

  const { data } = ctx.getImageData(0, 0, width, height);

  for (let i = 3; i < data.length; i += 4) {
    if (data[i] > OVERLAY_ALPHA_THRESHOLD) return true;
  }

  return false;
};

const overlayPageOps = async (
  pdfDoc: PdfLibDocument,
  overlay: HTMLCanvasElement | null | undefined,
  pageIndex: number
): Promise<void> => {
  if (!overlay || !canvasHasDrawing(overlay)) return;

  const page = pdfDoc.getPage(pageIndex);
  const pageWidth = page.getWidth();
  const pageHeight = page.getHeight();
  const dataUrl = overlay.toDataURL("image/png");
  const pngBuffer = await fetch(dataUrl).then((response) =>
    response.arrayBuffer()
  );
  const png = await pdfDoc.embedPng(pngBuffer);

  page.drawImage(png, {
    height: pageHeight,
    width: pageWidth,
    x: 0,
    y: 0,
  });
};

export const mergeOverlaysIntoPdf = async (
  originalBytes: Uint8Array,
  overlays: (HTMLCanvasElement | null | undefined)[]
): Promise<Uint8Array> => {
  const { PDFDocument } = await import("pdf-lib");

  const pdfDoc = await PDFDocument.load(originalBytes);

  await Promise.all(
    overlays.map((overlay, index) =>
      overlayPageOps(pdfDoc, overlay, index)
    )
  );

  return pdfDoc.save();
};
