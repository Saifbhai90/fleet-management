/** CamScanner-style cleanup: grayscale + contrast/brightness + threshold toward white paper / dark ink. */

const clampByte = (value: number): number =>
  Math.min(255, Math.max(0, Math.round(value)));

export const enhanceCanvasToDataUrl = (
  source: HTMLCanvasElement,
  quality = 0.92
): string => {
  const { height, width } = source;

  if (width === 0 || height === 0) return "";

  const work = document.createElement("canvas");

  work.width = width;
  work.height = height;

  const sctx = source.getContext("2d");
  const wctx = work.getContext("2d");

  if (!sctx || !wctx) return "";

  wctx.drawImage(source, 0, 0);

  const imageData = wctx.getImageData(0, 0, width, height);
  const { data } = imageData;

  const contrast = 1.48;
  const brightness = 14;
  const threshold = 186;

  let offset = 0;

  while (offset < data.length) {
    const gray = clampByte(
      data[offset] * 0.299 +
        data[offset + 1] * 0.587 +
        data[offset + 2] * 0.114
    );
    let value = (gray - 128) * contrast + 128 + brightness;

    value = clampByte(value);

    const binary = value >= threshold ? 255 : clampByte(value * 0.25);

    data[offset] = binary;
    data[offset + 1] = binary;
    data[offset + 2] = binary;
    data[offset + 3] = 255;
    offset += 4;
  }

  wctx.putImageData(imageData, 0, 0);

  return work.toDataURL("image/png", quality);
};
