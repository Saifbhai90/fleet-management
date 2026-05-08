export const replacePdfPageWithPng = async (
  pdfBytes: Uint8Array,
  pageIndex: number,
  pngBuffer: ArrayBuffer | Uint8Array
): Promise<Uint8Array> => {
  const { PDFDocument } = await import("pdf-lib");

  const doc = await PDFDocument.load(pdfBytes);
  const embedded = await doc.embedPng(pngBuffer);

  const oldPage = doc.getPage(pageIndex);
  const { height, width } = oldPage.getSize();

  doc.removePage(pageIndex);

  const page = doc.insertPage(pageIndex, [width, height]);

  page.drawImage(embedded, {
    height,
    width,
    x: 0,
    y: 0,
  });

  return doc.save();
};
